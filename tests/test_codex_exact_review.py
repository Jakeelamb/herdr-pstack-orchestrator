"""Regressions for t-d7e156 and t-b8519c; no live worker transport."""
import base64
from contextlib import redirect_stdout
import copy
import hashlib
import io
import json
import os
import shutil
import time
import unittest
from unittest.mock import patch

import test_codex_completion as exact

c, h, PRODUCER = exact.c, exact.h, exact.PRODUCER
JSON_LOADS = json.loads


def deep_json():
    return '[' * 1500 + '0' + ']' * 1500


def decoder_recursion(raw, *args, **kwargs):
    # 3.14 accepts the review's 1500-level input. Exercise decoder failure on
    # both versions without masking failures in observation/validation logic.
    text = raw.decode() if isinstance(raw, bytes) else raw
    if '[' * 1500 in text:
        raise RecursionError('controlled JSON decoder depth failure')
    return JSON_LOADS(raw, *args, **kwargs)


class ExactReviewTests(unittest.TestCase):
    setUp = exact.ExactTests.setUp
    event = exact.ExactTests.event
    callback = exact.ExactTests.callback
    publish_result = exact.ExactTests.publish_result
    qualify_inputs = exact.ExactTests.qualify_inputs
    proof = exact.ExactTests.proof

    def invoke(self, argv):
        output = io.StringIO()
        code = 0
        with patch.object(h, "load_config", return_value=self.config), redirect_stdout(output):
            try:
                h.main(argv)
            except SystemExit as exc:
                code = exc.code
        return code, [json.loads(line) for line in output.getvalue().splitlines()]

    def second_task(self):
        task = copy.deepcopy(self.task)
        task_id = 't-bbccdd'
        directory = h.task_dir(task_id)
        directory.mkdir(mode=0o700)
        task.update(task_id=task_id, agent='horch-bbccdd', pane_id='w1:p3',
                    result_path=str(directory / 'result.json'))
        task['completion']['task_id'] = task_id
        task['completion'].pop('digest')
        task['completion']['digest'] = c.digest(task['completion'])
        h.write_json(directory / 'task.json', task)
        state = h.default_state()
        state['exact'] = {'kind': 'active', 'dispatch_intent': True, 'task_digest': c.digest(task)}
        h.write_json(directory / 'state.json', state)
        h.write_json(directory / 'result.json', {**self.result, 'task_id': task_id})
        c.accept_notify({'contract': task['completion'], 'directory': str(directory), 'notifier': []},
                        self.event())
        return task_id, directory

    def test_review_mixed_and_unsupported_check_batches_have_no_side_effects(self):
        # t-d7e156/batch_check_probe.py plus the nonempty-notifier t-b8519c controls.
        original = copy.deepcopy(self.config)
        tails = [['--unknown'], ['prompt'], ['--config=notify=[]'],
                 ['-c', 'notify=["/usr/bin/false"]'], ['-c', 'profile="x"'],
                 ['--profile', 'p', '--profile', 'q'], []]
        def transport(*args, **kwargs):
            if args[:2] == ('agent', 'start'):
                return {'result': {'type': 'agent_started'}}
            if args[:2] == ('agent', 'read'):
                return '\n› \n'
            if args[:2] == ('agent', 'prompt'):
                return {'result': {'agent': {'agent_status': 'working'}}}
            self.fail(f'unexpected controlled transport: {args[:2]}')
        for harness, tail in [('claude', []), ('pi', [])] + [('codex', t) for t in tails]:
            with self.subTest(harness=harness, tail=tail):
                self.config = copy.deepcopy(original)
                other = copy.deepcopy(original['workers']['solo'])
                other['harness'] = harness
                other['args'] = (['-c', 'notify=["/usr/bin/true"]'] + tail
                                 if tail else [])
                self.config['workers']['other'] = other
                store = self.root / ('batch-' + str(len(list(self.root.glob('batch-*')))))
                with patch.dict(os.environ, {'HORCH_EXACT_STORE': str(store)}), \
                        patch.object(h, 'require_caller_context', return_value={
                            'workspace_id': 'w1', 'tab_id': 't'}), \
                        patch.object(h, 'require_pi_integration') as pi, \
                        patch.object(c.shutil, 'which', return_value=str(self.binary)), \
                        patch.object(h, 'agent_index', return_value={}), \
                        patch.object(h, 'place_pane', return_value=('w1:p3', 'w1:t2')) as pane, \
                        patch.object(h, 'herdr', side_effect=transport) as rpc:
                    code, rows = self.invoke(['check', '--completion', c.MODE, '--max-seconds', '1',
                                              '--cwd', str(self.root)])
                    self.assertEqual(code, 1)
                    self.assertEqual(rows[0]['error'], 'exact_unverified')
                    pane.assert_not_called()
                    rpc.assert_not_called()
                    pi.assert_not_called()
                    self.assertFalse(store.exists(), 'rejected batch initialized its store')

    def test_review_symlink_tasks_rejected_before_any_store_write(self):
        # t-d7e156/review_probe.py, new AND already marked store, including dangling links.
        for marked in (False, True):
            for dangling in (False, True):
                with self.subTest(marked=marked, dangling=dangling):
                    store = self.root / f'alias-{marked}-{dangling}'
                    store.mkdir(mode=0o700)
                    outside = self.root / f'outside-{marked}-{dangling}'
                    if not dangling:
                        outside.mkdir(mode=0o700)
                    if marked:
                        c.atomic_record(store / 'exact-store.json', {'mode': c.MODE, 'schema': 1})
                    (store / 'tasks').symlink_to(outside, target_is_directory=True)
                    before = sorted(p.name for p in store.iterdir())
                    with patch.dict(os.environ, {'HORCH_EXACT_STORE': str(store)}), \
                            patch.object(h, 'require_caller_context', return_value={
                                'workspace_id': 'w1', 'tab_id': 't'}), \
                            patch.object(c.shutil, 'which', return_value=str(self.binary)), \
                            patch.object(h, 'place_pane') as pane, patch.object(h, 'herdr') as transport:
                        with self.assertRaisesRegex(c.Unverified, 'unsafe_directory'):
                            h.start_task(self.config, 'solo', 'brief', self.root, completion_mode=c.MODE)
                        with self.assertRaisesRegex(c.Unverified, 'unsafe_directory'):
                            with h.task_store_lock():
                                self.fail('unsafe startup lock admitted')
                    self.assertEqual(sorted(p.name for p in store.iterdir()), before)
                    self.assertEqual(list(outside.iterdir()) if outside.exists() else [], [])
                    pane.assert_not_called()
                    transport.assert_not_called()

    def test_canonical_private_tasks_directory_remains_admissible(self):
        store = self.root / 'private-store'
        (store / 'tasks').mkdir(parents=True, mode=0o700)
        store.chmod(0o700)
        with patch.dict(os.environ, {'HORCH_EXACT_STORE': str(store)}):
            h.require_exact_store()
            with h.task_store_lock():
                pass
            h.require_exact_store()
        self.assertEqual(c.read_record(store / 'exact-store.json'), {'mode': c.MODE, 'schema': 1})

    def test_review_invalid_exact_state_does_not_hide_healthy_wait_list_stats(self):
        # t-d7e156/reader_isolation_probe.py and t-b8519c/aggregate_readers.py.
        healthy_id, _ = self.second_task()
        h.write_json(self.directory / 'state.json', {'state': 'done', 'closed': True})
        with patch.object(h, 'herdr', side_effect=AssertionError('live transport forbidden')), \
                patch.object(h, 'close_pane', return_value='closed') as close:
            for argv in (['list'], ['wait', '--max-seconds', '2']):
                code, rows = self.invoke(argv)
                self.assertEqual(code, 0)
                indexed = {row['task_id']: row for row in rows}
                self.assertEqual(set(indexed), {self.task['task_id'], healthy_id})
                self.assertEqual(indexed[self.task['task_id']]['error'], 'exact_unverified')
                self.assertIn('exact_state_invalid', indexed[self.task['task_id']]['message'])
                if argv[0] == 'wait':
                    self.assertEqual(indexed[healthy_id]['result']['status'], 'completed')
            close.assert_called_once_with('w1:p3')
            code, rows = self.invoke(['stats'])
        self.assertEqual(code, 0)
        self.assertEqual(rows[0]['task_count'], 1)
        self.assertEqual(rows[0]['invalid_task_ids'], [self.task['task_id']])
        self.assertEqual(h.task_capacity('w1'), (1, [self.task['task_id']]))

    def test_named_invalid_exact_task_reports_its_id(self):
        healthy_id, _ = self.second_task()
        for control in (None, [], {}, {'kind': []}, {'kind': {}}, {'kind': 'future'}):
            h.write_json(self.directory / 'state.json', {'state': 'done', 'closed': True, 'exact': control})
            for argv in (['wait', self.task['task_id'], '--max-seconds', '0'],
                         ['close', self.task['task_id']]):
                with self.subTest(control=control, argv=argv), patch.object(h, 'close_pane') as close:
                    code, rows = self.invoke(argv)
                    self.assertEqual(code, 1)
                    self.assertEqual(rows[0]['error'], 'exact_unverified')
                    self.assertIn(self.task['task_id'], rows[0]['message'])
                    close.assert_not_called()
            for argv in (['list'], ['wait', '--max-seconds', '0'], ['stats']):
                with self.subTest(control=control, argv=argv):
                    code, rows = self.invoke(argv)
                    self.assertEqual(code, 0)
                    if argv[0] == 'stats':
                        self.assertEqual(rows[0]['invalid_task_ids'], [self.task['task_id']])
                    else:
                        self.assertEqual({row['task_id'] for row in rows}, {self.task['task_id'], healthy_id})
            self.assertEqual(h.task_capacity('w1'), (2, [self.task['task_id']]))

    def test_review_capacity_uses_exact_decision_before_raw_closed_bit(self):
        # t-d7e156/review_probe.py capacity-compatibility reproduction.
        for kind in ('active', 'cancel_requested'):
            state = h.read_json(self.directory / 'state.json')
            state['closed'] = True
            state['exact']['kind'] = kind
            h.write_json(self.directory / 'state.json', state)
            self.assertFalse(h.state_for_task(self.directory, self.task)['closed'])
            self.assertEqual(h.task_capacity('w1')[0], 1)
        # A damaged delivered decision cannot release capacity either.
        state['exact']['kind'] = 'delivered'
        h.write_json(self.directory / 'state.json', state)
        self.assertEqual(h.task_capacity('w1'), (1, [self.task['task_id']]))

    def test_deep_native_frame_first_does_not_abort_healthy_second(self):
        # t-b8519c/run_review.py deep_native_json, through real private JSONL pipes.
        self.qualify_inputs()
        healthy_id, healthy_dir = self.second_task()
        task = copy.deepcopy(self.task)
        task['completion']['reader']['argv'] = [str(PRODUCER), '--deep-json']
        task['completion'].pop('digest')
        task['completion']['digest'] = c.digest(task['completion'])
        h.write_json(self.directory / 'task.json', task)
        state = h.read_json(self.directory / 'state.json')
        state['exact']['task_digest'] = c.digest(task)
        h.write_json(self.directory / 'state.json', state)
        (self.directory / 'completion.json').unlink()
        c.accept_notify({**self.frozen, 'contract': task['completion']}, self.event())
        for force_recursion in (False, True):
            with self.subTest(force_recursion=force_recursion), \
                    patch.object(json, 'loads', side_effect=decoder_recursion if force_recursion else JSON_LOADS), \
                    patch.object(h, 'herdr', side_effect=AssertionError('no native worker')), \
                    patch.object(h, 'close_pane', return_value='closed') as close:
                code, rows = self.invoke(['wait', '--max-seconds', '2'])
                self.assertEqual(code, 0)
                indexed = {row['task_id']: row for row in rows}
                bad = indexed[self.task['task_id']]
                self.assertTrue(any(d in bad['message'] for d in
                                    ('native_malformed', 'native_ambiguous_turn')))
                if force_recursion:
                    self.assertIn('native_malformed', bad['message'])
                self.assertIsNone(bad['result'])
                self.assertFalse(bad['closed'])
                self.assertEqual(indexed[healthy_id]['result']['status'], 'completed')
                close.assert_called_once_with('w1:p3')
            shutil.rmtree(healthy_dir)
            if not force_recursion:
                healthy_id, healthy_dir = self.second_task()

    def test_deep_receipt_or_result_first_does_not_abort_healthy_second(self):
        for boundary, force_recursion in ((b, force) for b in ('completion.json', 'result.json')
                                          for force in (False, True)):
            with self.subTest(boundary=boundary, force_recursion=force_recursion):
                # Each subcase needs fresh decisions, not an already delivered second task.
                self.qualify_inputs()
                healthy_id, healthy_dir = self.second_task()
                (self.directory / boundary).write_text(deep_json())
                with patch.object(json, 'loads', side_effect=decoder_recursion if force_recursion else JSON_LOADS), \
                        patch.object(h, 'herdr', side_effect=AssertionError('no native worker')), \
                        patch.object(h, 'close_pane', return_value='closed') as close:
                    code, rows = self.invoke(['wait', '--max-seconds', '2'])
                self.assertEqual(code, 0)
                indexed = {row['task_id']: row for row in rows}
                bad = indexed[self.task['task_id']]
                self.assertIsNone(bad['result'])
                diagnostics = (('record_unavailable', 'binding_invalid') if boundary == 'completion.json'
                               else ('result_unavailable', 'result_invalid'))
                self.assertTrue(any(d in bad['message'] for d in diagnostics))
                if force_recursion:
                    self.assertIn(diagnostics[0], bad['message'])
                self.assertEqual(indexed[healthy_id]['state'], 'done')
                close.assert_called_once_with('w1:p3')
                shutil.rmtree(healthy_dir)
                (self.directory / 'completion.json').unlink(missing_ok=True)

    def test_exact_state_corrupted_during_poll_does_not_abort_healthy_second(self):
        self.qualify_inputs()
        healthy_id, _ = self.second_task()
        real_observe = c.observe
        def observe(contract, candidate, deadline):
            if contract['task_id'] == self.task['task_id']:
                h.write_json(self.directory / 'state.json', {'closed': True})
                return self.proof()
            return real_observe(contract, candidate, deadline)
        with patch.object(c, 'observe', side_effect=observe), \
                patch.object(h, 'herdr', side_effect=AssertionError('no native worker')), \
                patch.object(h, 'close_pane', return_value='closed') as close:
            code, rows = self.invoke(['wait', '--max-seconds', '2'])
        self.assertEqual(code, 0)
        indexed = {row['task_id']: row for row in rows}
        self.assertEqual(indexed[self.task['task_id']]['error'], 'exact_unverified')
        self.assertEqual(indexed[healthy_id]['state'], 'done')
        close.assert_called_once_with('w1:p3')

    def test_deep_persisted_task_and_state_are_contained_per_task(self):
        healthy_id, _ = self.second_task()
        for filename in ('task.json', 'state.json'):
            with self.subTest(filename=filename):
                path = self.directory / filename
                before = path.read_bytes()
                path.write_text(deep_json())
                with patch.object(h, 'herdr', side_effect=AssertionError('no transport')):
                    for argv in (['list'], ['wait', '--max-seconds', '0'], ['stats']):
                        code, rows = self.invoke(argv)
                        self.assertEqual(code, 0)
                        if argv[0] == 'stats':
                            self.assertEqual(rows[0]['invalid_task_ids'], [self.task['task_id']])
                        else:
                            indexed = {row['task_id']: row for row in rows}
                            self.assertIn(healthy_id, indexed)
                            if filename == 'state.json' or argv[0] == 'list':
                                self.assertIn(self.task['task_id'], indexed)
                self.assertEqual(h.task_capacity('w1'), (2, [self.task['task_id']]))
                path.write_bytes(before)

    def test_deep_callback_is_ignored_and_original_notifier_is_forwarded(self):
        with patch.object(c.os, 'execvp') as forward:
            frozen = {**self.frozen, 'notifier': ['original-notifier', 'literal']}
            self.assertEqual(c.notify_entry(c.encode(frozen), deep_json()), 0)
            forward.assert_called_once_with('original-notifier',
                                            ['original-notifier', 'literal', deep_json()])
        self.assertFalse((self.directory / 'completion.json').exists())
        with patch.object(json, 'loads', side_effect=decoder_recursion):
            with self.assertRaisesRegex(c.Unverified, 'native_malformed'):
                c.accept_notify(self.frozen, deep_json())
            encoded = base64.urlsafe_b64encode(deep_json().encode()).decode()
            with self.assertRaisesRegex(c.Unverified, 'record_unavailable'):
                c.decode(encoded)

    def test_deep_committed_result_is_invalid_without_mutable_result_fallback(self):
        self.qualify_inputs()
        with patch.object(h, 'close_pane', return_value='closed'):
            h.poll_exact(self.info, time.monotonic() + 2)
        state = h.read_json(self.directory / 'state.json')
        raw = deep_json().encode()
        state['exact']['result_bytes'] = base64.b64encode(raw).decode()
        state['exact']['result_sha256'] = hashlib.sha256(raw).hexdigest()
        h.write_json(self.directory / 'state.json', state)
        self.assertIsNone(h.snapshot_result(self.task, state['exact']))
        self.assertEqual(h.task_capacity('w1'), (1, [self.task['task_id']]))
        with patch.object(json, 'loads', side_effect=decoder_recursion):
            self.assertIsNone(h.snapshot_result(self.task, state['exact']))
            self.assertEqual(h.task_capacity('w1'), (1, [self.task['task_id']]))

    def test_non_json_recursion_errors_are_not_masked_by_native_observer(self):
        self.callback()
        with patch.object(c.Reader, '__enter__', side_effect=RecursionError('implementation defect')):
            with self.assertRaises(RecursionError):
                c.observe(self.contract, c.binding(self.directory, self.contract), time.monotonic() + 1)


if __name__ == '__main__':
    unittest.main()
