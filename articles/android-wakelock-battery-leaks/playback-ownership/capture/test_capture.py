"""Host-only orchestration tests: never contact a device."""
import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('capture', Path(__file__).with_name('capture.py'))
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


class CaptureTests(unittest.TestCase):
    def make_capture(self, root, scenario='foreground', **options):
        args = dict(serial='fake', output=Path(root), scenario=scenario, package=None,
                    baseline_seconds=0, play_seconds=0, observe_seconds=0, cleanup_seconds=0,
                    screenrecord=False, bugreport=False, source_commit='test-commit', apk=None)
        args.update(options)
        return capture.Capture(argparse.Namespace(**args))

    def run_mock(self, runner, fail=False):
        calls = []

        def adb(*command, **kwargs):
            calls.append(command)
            if command[:5] == ('shell', 'cmd', 'package', 'list', 'packages'):
                return f'package:{runner.package} uid:10123'
            if command[0] == 'exec-out':
                active = {'event': 'wake_lock_acquired', 'is_held': True} if runner.args.scenario.startswith('direct-') else {'event': 'is_playing', 'is_playing': True}
                return '\n'.join(json.dumps(dict(event, run_id=runner.run_id)) for event in [{'event': 'run_start'}, active])
            if command[:3] == ('shell', 'am', 'start') and fail:
                raise RuntimeError('start failed')
            return ''

        with patch.object(runner, 'adb', side_effect=adb), patch.object(runner, 'start_trace'), \
                patch.object(runner, 'finish_trace', side_effect=lambda: calls.append(('finish-trace',))), \
                patch.object(runner, 'start_recording', side_effect=lambda: calls.append(('start-recording',))), \
                patch.object(runner, 'finish_recording', side_effect=lambda: calls.append(('finish-recording',))), \
                patch.object(capture.time, 'sleep'):
            if fail:
                with self.assertRaisesRegex(RuntimeError, 'start failed'):
                    runner.run()
            else:
                runner.run()
        return calls

    def test_package_routing_and_validation(self):
        self.assertEqual(capture.package_for('direct-timed'), capture.DIRECT_PACKAGE)
        self.assertEqual(capture.package_for('idle'), capture.PACKAGE)
        self.assertEqual(capture.package_for('retained'), capture.PACKAGE)
        with self.assertRaises(ValueError):
            capture.package_for('direct-untimed', capture.PACKAGE)

    def test_trace_uses_selected_package(self):
        config = capture.make_config('linux.ftrace', 'power - Power', 1000, capture.DIRECT_PACKAGE)
        self.assertIn('atrace_apps: "dev.returnzero.directlocklab"', config)

    def test_idle_isolates_both_apps_without_start_or_stop(self):
        with tempfile.TemporaryDirectory() as root:
            runner = self.make_capture(root, 'idle')
            calls = self.run_mock(runner)
            for package in (capture.PACKAGE, capture.DIRECT_PACKAGE):
                self.assertIn(('shell', 'am', 'force-stop', package), calls)
            self.assertFalse(any(cmd[:3] in [('shell', 'am', 'start'), ('shell', 'am', 'broadcast')] for cmd in calls))
            self.assertIn(('shell', 'input', 'keyevent', 'KEYCODE_SLEEP'), calls)
            self.assertEqual(runner.manifest['status'], 'completed')
            marks = [entry['boundary'] for entry in runner.manifest['boundaries']]
            self.assertLess(marks.index('quiet-screen-off-start'), marks.index('quiet-screen-off-end'))
            self.assertTrue((runner.directory / 'artifact-index.json').exists())

    def test_direct_routes_commands_and_preserves_pre_cleanup_events(self):
        with tempfile.TemporaryDirectory() as root:
            runner = self.make_capture(root, 'direct-untimed')
            calls = self.run_mock(runner)
            start = next(cmd for cmd in calls if cmd[:3] == ('shell', 'am', 'start'))
            self.assertIn(capture.DIRECT_PACKAGE + '/.MainActivity', start)
            stop = next(cmd for cmd in calls if cmd[:3] == ('shell', 'am', 'broadcast'))
            self.assertIn(capture.DIRECT_PACKAGE + '/.StopReceiver', stop)
            self.assertTrue((runner.directory / 'events-before-cleanup.jsonl').exists())
            self.assertTrue((runner.directory / 'events.jsonl').exists())

    def test_bugreport_follows_observation_and_trace_before_stop(self):
        with tempfile.TemporaryDirectory() as root:
            runner = self.make_capture(root, bugreport=True)
            calls = self.run_mock(runner)
            bug = next(i for i, cmd in enumerate(calls) if cmd[0] == 'bugreport')
            stop = next(i for i, cmd in enumerate(calls) if cmd[:3] == ('shell', 'am', 'broadcast'))
            events = next(i for i, cmd in enumerate(calls) if cmd[0] == 'exec-out')
            self.assertLess(events, calls.index(('finish-trace',)))
            self.assertLess(calls.index(('finish-trace',)), bug)
            self.assertLess(bug, stop)

    def test_failure_keeps_manifest_and_force_stops(self):
        with tempfile.TemporaryDirectory() as root:
            runner = self.make_capture(root)
            calls = self.run_mock(runner, fail=True)
            self.assertEqual(runner.manifest['status'], 'failed')
            self.assertIn('start failed', runner.manifest['error'])
            self.assertIn(('shell', 'am', 'force-stop', capture.PACKAGE), calls)
            self.assertIn(('finish-trace',), calls)
            self.assertTrue((runner.directory / 'manifest.json').exists())

    def test_missing_start_or_other_run_fails_validation(self):
        with tempfile.TemporaryDirectory() as root:
            runner = self.make_capture(root)
            with patch.object(runner, 'adb', return_value='{"run_id":"other","event":"run_start"}'):
                with self.assertRaisesRegex(RuntimeError, 'startup events missing'):
                    runner.validate_started()
            self.assertFalse(runner.manifest['start_verified'])

    def test_supplied_apk_must_match_installed_bytes(self):
        with tempfile.TemporaryDirectory() as root:
            apk = Path(root) / 'sample.apk'
            apk.write_bytes(b'sample')
            runner = self.make_capture(root, apk=apk)
            with patch.object(runner, 'adb', side_effect=['package:/data/app/base.apk', 'a' * 64 + ' /data/app/base.apk']):
                with self.assertRaisesRegex(RuntimeError, 'does not match'):
                    runner.provenance()


if __name__ == '__main__':
    unittest.main()
