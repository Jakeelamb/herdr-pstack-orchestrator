#!/usr/bin/env python3
"""Private, experimental Codex notification and read-only history adapter.

No Herdr calls, session discovery, config resolution, prompt submission or daemon.
All public errors are fixed codes: native/config/prompt contents are never errors.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
import ctypes
import fcntl
import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import tomllib

MODE = "codex-exact-v1"
MAX_FILE = 1024 * 1024
MAX_FRAME = 1024 * 1024
MAX_WIRE = 4 * MAX_FRAME
MAX_PAGES = 3
QUERY_SECONDS = 2.0


class Unverified(Exception):
    """A bounded diagnostic code, never a native error/payload."""


def packed(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value):
    return hashlib.sha256(packed(value)).hexdigest()


def encode(value):
    return base64.urlsafe_b64encode(packed(value)).decode()


def decode(value):
    return json.loads(base64.b64decode(value, altchars=b"-_", validate=True))


def read_bytes(path):
    """Read bounded regular canonical files without following a final symlink."""
    if Path(path).parent.resolve() != Path(path).parent:
        raise Unverified("unsafe_directory")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o022 or info.st_size > MAX_FILE):
            raise Unverified("unsafe_file")
        data = b""
        while len(data) <= MAX_FILE:
            chunk = os.read(fd, min(65536, MAX_FILE + 1 - len(data)))
            if not chunk:
                return data
            data += chunk
        raise Unverified("file_too_large")
    finally:
        os.close(fd)


def read_record(path):
    try:
        return json.loads(read_bytes(path))
    except (ValueError, UnicodeError, OSError) as exc:
        raise Unverified("record_unavailable") from exc


def atomic_record(path, value):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".exact-", delete=False) as out:
            temporary = Path(out.name)
            out.write(packed(value))
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def lock(directory, name=".state.lock", seconds=0.25):
    if directory.resolve() != directory:
        raise Unverified("unsafe_directory")
    fd = os.open(directory / name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise Unverified("unsafe_lock")
        deadline = time.monotonic() + seconds
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise Unverified("lifecycle_busy")
                time.sleep(0.005)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def environment_digest():
    # Only context selectors, never config/credential contents or arbitrary env.
    return digest({key: os.environ.get(key) for key in
                   ("HOME", "CODEX_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME")})


def executable_digest(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare(argv, directory, task_id, nonce, pointer, cwd, *, executable=None):
    """Replace one supported, already supplied root notify override in place.

    Deliberately small grammar: no subcommands, prompts, wrappers, provider or
    profile-changing config overlays. No inherited configuration is read.
    """
    if sys.platform != "linux":
        raise Unverified("linux_required")
    original = list(argv)
    reader = []
    slot, notifier = None, None
    i = 0
    value_flags = {"-m", "--model", "-s", "--sandbox", "-a", "--ask-for-approval",
                   "--add-dir", "-p", "--profile"}
    switches = {"--no-alt-screen", "--no-daemon"}
    profile_seen = False
    while i < len(argv):
        flag = argv[i]
        if flag in ("-c", "--config"):
            if i + 1 >= len(argv):
                raise Unverified("unsupported_argv")
            try:
                parsed = tomllib.loads(argv[i + 1])
            except (ValueError, tomllib.TOMLDecodeError) as exc:
                raise Unverified("unsupported_config") from exc
            # Parsing TOML determines the root key; constrain its lexical form too
            # so dotted/quoted/alternate encodings cannot become ambiguous slots.
            key = argv[i + 1].partition("=")[0].strip()
            if set(parsed) != {key} or key not in {"notify", "model_reasoning_effort"}:
                raise Unverified("unsupported_config")
            if key == "notify":
                value = parsed[key]
                if (slot is not None or not isinstance(value, list)
                        or not all(isinstance(v, str) and "\0" not in v for v in value)
                        or (value and not value[0])):
                    raise Unverified("ambiguous_notify")
                if not value:
                    raise Unverified("nonempty_explicit_notify_required")
                slot, notifier = i + 1, value
            else:
                if not isinstance(parsed[key], str):
                    raise Unverified("unsupported_config")
                reader += argv[i:i + 2]
            i += 2
        elif flag in value_flags:
            if i + 1 >= len(argv) or not argv[i + 1] or argv[i + 1].startswith("-"):
                raise Unverified("unsupported_argv")
            if flag in ("-p", "--profile"):
                if profile_seen:
                    raise Unverified("unsupported_argv")
                profile_seen = True
                reader += argv[i:i + 2]
            i += 2
        elif flag in switches:
            i += 1
        else:
            raise Unverified("unsupported_argv")
    if slot is None:
        raise Unverified("explicit_notify_required")
    binary = executable or shutil.which("codex")
    if not binary or Path(binary).name != "codex":
        raise Unverified("direct_codex_required")
    resolved = str(Path(binary).resolve(strict=True))
    # Reject scripts/custom command wrappers; record the actual ELF identity.
    with open(resolved, "rb") as stream:
        if stream.read(4) != b"\x7fELF":
            raise Unverified("direct_codex_required")
    contract = {"mode": MODE, "schema": 1, "task_id": task_id, "nonce": nonce,
                "expected_inputs": [pointer], "original_argv_sha256": digest(original),
                "reader": {"executable": resolved, "sha256": executable_digest(resolved),
                           "argv": reader, "cwd": str(cwd), "environment_sha256": environment_digest()}}
    contract["digest"] = digest(contract)
    frozen = {"contract": contract, "directory": str(directory), "notifier": notifier}
    wrapper = [sys.executable, str(Path(__file__).resolve()), "notify", encode(frozen)]
    argv = list(original)
    # JSON string arrays are valid TOML for these argv strings, including escapes.
    argv[slot] = "notify=" + json.dumps(wrapper, ensure_ascii=False)
    return argv, contract


def validate_contract(contract):
    if not isinstance(contract, dict) or contract.get("mode") != MODE or contract.get("schema") != 1:
        raise Unverified("unsupported_contract")
    plain = {key: value for key, value in contract.items() if key != "digest"}
    if (contract.get("digest") != digest(plain)
            or not isinstance(contract.get("nonce"), str) or len(contract["nonce"]) != 32
            or not isinstance(contract.get("expected_inputs"), list)
            or len(contract["expected_inputs"]) != 1
            or not isinstance(contract["expected_inputs"][0], str)
            or not isinstance(contract.get("reader"), dict)):
        raise Unverified("invalid_contract")


def binding(directory, contract):
    record = read_record(directory / "completion.json")
    if (not isinstance(record, dict) or record.get("contract_digest") != contract["digest"]
            or record.get("nonce") != contract["nonce"] or record.get("task_id") != contract["task_id"]):
        raise Unverified("binding_invalid")
    if record.get("conflict") is not False:
        raise Unverified("binding_conflict")
    for key in ("thread_id", "turn_id"):
        if not isinstance(record.get(key), str) or not 0 < len(record[key]) <= 256:
            raise Unverified("binding_invalid")
    return record


def accept_notify(frozen, raw):
    contract = frozen["contract"]
    validate_contract(contract)
    if len(raw.encode()) > MAX_FRAME:
        return
    event = json.loads(raw)
    if (not isinstance(event, dict) or event.get("type") != "agent-turn-complete"
            or event.get("input-messages") != contract["expected_inputs"]):
        return
    identity = [event.get("thread-id"), event.get("turn-id")]
    if not all(isinstance(v, str) and 0 < len(v) <= 256 for v in identity):
        return
    directory = Path(frozen["directory"])
    with lock(directory):
        task = read_record(directory / "task.json")
        if (task.get("completion") != contract or task.get("nonce") != contract["nonce"]
                or task.get("task_id") != contract["task_id"]):
            raise Unverified("launch_changed")
        path = directory / "completion.json"
        try:
            previous = read_record(path)
        except Unverified:
            if path.exists() or path.is_symlink():
                raise
            previous = None
        candidate = {"contract_digest": contract["digest"], "nonce": contract["nonce"],
                     "task_id": contract["task_id"], "thread_id": identity[0],
                     "turn_id": identity[1], "conflict": False}
        if previous is None:
            atomic_record(path, candidate)
        elif previous != candidate and previous.get("conflict") is not True:
            # Keep the first identity. A conflicting attempt never becomes latest-wins.
            previous["conflict"] = True
            atomic_record(path, previous)


def notify_entry(encoded, raw):
    frozen = decode(encoded)
    try:
        accept_notify(frozen, raw)
    except Exception:
        # Never print raw native errors/config/prompt; observer diagnoses missing proof.
        pass
    # Always forward the identical argument once, even for foreign/malformed events
    # or a receipt write failure. exec preserves original cwd/env/lifetime/status.
    if frozen["notifier"]:
        try:
            os.execvp(frozen["notifier"][0], frozen["notifier"] + [raw])
        except OSError:
            return 127
    return 0


def reader_guard(expected_parent, argv):
    """Linux owned group supervisor, including parent death during initialization."""
    def kill_group(*_):
        os.killpg(os.getpgrp(), signal.SIGKILL)
    signal.signal(signal.SIGTERM, kill_group)
    if os.getppid() != expected_parent or os.getpgrp() != os.getpid():
        return 125
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0:
        return 125
    if os.getppid() != expected_parent:
        return 125
    child = subprocess.Popen(argv, close_fds=True)
    child.wait()
    # Do not leave initialization descendants alive after the main reader exits.
    # The observer reaps this supervisor; on observer death the OS reaper owns it.
    kill_group()


class Reader:
    """One owned child, one query deadline, bounded private JSONL pipes."""
    def __init__(self, context, deadline):
        self.context, self.deadline = context, deadline
        self.process = None
        self.buffer = b""
        self.wire = self.frames = 0
        self.next_id = 0

    def __enter__(self):
        c = self.context
        if (environment_digest() != c["environment_sha256"]
                or executable_digest(c["executable"]) != c["sha256"]):
            raise Unverified("reader_context_changed")
        if time.monotonic() >= self.deadline:
            raise Unverified("observation_deferred")
        argv = [sys.executable, str(Path(__file__).resolve()), "reader-guard", str(os.getpid()),
                c["executable"], *c["argv"], "app-server", "--listen", "stdio://"]
        self.process = subprocess.Popen(argv, cwd=c["cwd"], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        start_new_session=True, close_fds=True)
        os.set_blocking(self.process.stdin.fileno(), False)
        os.set_blocking(self.process.stdout.fileno(), False)
        try:
            self.rpc("initialize", {"clientInfo": {"name": "horch-exact", "version": "1"}})
            self.send({"method": "initialized"})
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *_):
        if self.process is not None:
            # Kill only the group created for this reader. Handles a supervisor
            # that already exited while its same-group descendants kept pipes open.
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            for stream in (self.process.stdin, self.process.stdout):
                stream.close()
            self.process.wait(timeout=1.0)

    def remaining(self):
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise Unverified("native_timeout")
        return left

    def send(self, value):
        data = packed(value) + b"\n"
        while data:
            if not select.select([], [self.process.stdin], [], self.remaining())[1]:
                raise Unverified("native_timeout")
            count = os.write(self.process.stdin.fileno(), data)
            data = data[count:]

    def frame(self):
        while b"\n" not in self.buffer:
            if not select.select([self.process.stdout], [], [], self.remaining())[0]:
                raise Unverified("native_timeout")
            data = os.read(self.process.stdout.fileno(), 65536)
            if not data:
                raise Unverified("native_eof")
            self.wire += len(data)
            self.buffer += data
            if self.wire > MAX_WIRE or len(self.buffer.partition(b"\n")[0]) > MAX_FRAME:
                raise Unverified("native_limit")
        raw, self.buffer = self.buffer.split(b"\n", 1)
        self.frames += 1
        if len(raw) > MAX_FRAME or self.frames > 64:
            raise Unverified("native_limit")
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise Unverified("native_malformed") from exc
        if not isinstance(value, dict):
            raise Unverified("native_malformed")
        return value

    def rpc(self, method, params):
        self.next_id += 1
        expected = self.next_id
        self.send({"id": expected, "method": method, "params": params})
        while True:
            value = self.frame()
            if "method" in value:
                if "id" in value:
                    raise Unverified("native_unsolicited_request")
                continue
            if value.get("id") != expected or type(value.get("id")) is not int:
                raise Unverified("native_response_id")
            if "error" in value or not isinstance(value.get("result"), dict):
                raise Unverified("native_rpc_error")
            return value["result"]


def observe(contract, candidate, deadline):
    """Only exact completed history constructs proof. All other outcomes retry."""
    deadline = min(deadline, time.monotonic() + QUERY_SECONDS)
    try:
        with Reader(contract["reader"], deadline) as reader:
            cursor, seen, turns = None, set(), set()
            for _ in range(MAX_PAGES):
                params = {"threadId": candidate["thread_id"], "limit": 50,
                          "sortDirection": "desc", "itemsView": "notLoaded"}
                if cursor is not None:
                    params["cursor"] = cursor
                result = reader.rpc("thread/turns/list", params)
                data = result.get("data")
                if not isinstance(data, list) or len(data) > 50:
                    raise Unverified("native_malformed")
                match = None
                for turn in data:
                    if (not isinstance(turn, dict) or not isinstance(turn.get("id"), str)
                            or turn["id"] in turns):
                        raise Unverified("native_ambiguous_turn")
                    turns.add(turn["id"])
                    if turn["id"] == candidate["turn_id"]:
                        match = turn
                if match is not None:
                    if match.get("status") != "completed" or match.get("error") is not None:
                        raise Unverified("native_not_completed")
                    return {"contract_digest": contract["digest"], "binding_digest": digest(candidate),
                            "thread_id": candidate["thread_id"], "turn_id": candidate["turn_id"],
                            "status": "completed", "response_sha256": digest(result)}
                cursor = result.get("nextCursor")
                if cursor is None:
                    raise Unverified("native_turn_missing")
                if not isinstance(cursor, str) or not 0 < len(cursor) <= 4096 or cursor in seen:
                    raise Unverified("native_cursor_invalid")
                seen.add(cursor)
            raise Unverified("native_page_limit")
    except (OSError, ValueError, subprocess.SubprocessError, KeyError) as exc:
        raise Unverified("native_unavailable") from exc


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "notify":
        sys.exit(notify_entry(sys.argv[2], sys.argv[3]))
    if len(sys.argv) >= 4 and sys.argv[1] == "reader-guard":
        sys.exit(reader_guard(int(sys.argv[2]), sys.argv[3:]))
    sys.exit(2)
