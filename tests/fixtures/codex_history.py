#!/usr/bin/env python3
"""Controlled JSONL producer; never opens a Codex session or calls a model."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

scenario = json.loads(Path(os.environ["HORCH_TEST_SCENARIO"]).read_text())
if scenario.get("pids"):
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    Path(scenario["pids"]).write_text(json.dumps([os.getpid(), child.pid]))
page = 0
for raw in sys.stdin:
    request = json.loads(raw)
    method = request["method"]
    if scenario.get("requests"):
        with open(scenario["requests"], "a") as log:
            log.write(json.dumps(request) + "\n")
    if method == "initialized":
        continue
    if method == "initialize":
        result = {}
    else:
        if method != "thread/turns/list":
            sys.exit(7)
        if '--deep-json' in sys.argv:
            print('{"id":' + str(request['id']) + ',"result":{"data":'
                  + '[' * 1500 + '0' + ']' * 1500 + '}}', flush=True)
            continue
        if scenario.get("hang"):
            time.sleep(60)
        if scenario.get("malformed"):
            print("not json", flush=True)
            continue
        if scenario.get("flood"):
            print("x" * (1024 * 1024 + 1), flush=True)
            continue
        if scenario.get("eof"):
            sys.exit(0)
        if scenario.get("request"):
            print(json.dumps({"id": 99, "method": "approval/request"}), flush=True)
            continue
        if scenario.get("error"):
            print(json.dumps({"id": request["id"], "error": {"message": "PRIVATE ERROR"}}), flush=True)
            continue
        pages = scenario.get("pages", [{"data": [{"id": "turn", "status": "completed", "error": None}]}])
        result = pages[min(page, len(pages) - 1)]
        page += 1
    print(json.dumps({"id": request["id"] + scenario.get("id_offset", 0), "result": result}), flush=True)
