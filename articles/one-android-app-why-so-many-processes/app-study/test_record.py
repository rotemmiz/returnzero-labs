import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from record import Recorder, parse_control, parse_ps, parse_sections, parse_status, process_identity, sum_complete


class ParserTests(unittest.TestCase):
    def test_controls_preserve_unlimited_and_events(self):
        self.assertEqual(parse_control('memory.high', 'max'), 'max')
        self.assertEqual(parse_control('memory.events', 'high 2\noom 0'), {'high': 2, 'oom': 0})
        self.assertIsNone(parse_control('memory.high', 'Permission denied'))

    def test_status_missing_is_not_zero(self):
        result = parse_status('VmRSS: 123 kB\nVmSwap: 0 kB\n')
        self.assertEqual(result['VmRSS'], 123)
        self.assertEqual(result['VmSwap'], 0)
        self.assertIsNone(result['RssAnon'])

    def test_identity_handles_parentheses_in_process_name(self):
        line = '42 (a process (name)) S ' + ' '.join(['0'] * 18 + ['1234'])
        self.assertEqual(process_identity(line), 1234)
        self.assertNotEqual(process_identity(line), process_identity(line.replace('1234', '1235')))
        self.assertIsNone(process_identity('Permission denied'))

    def test_ps_preserves_isolated_uid_and_name(self):
        self.assertEqual(parse_ps('PID UID NAME\n22 90001 com.android.chrome:sandbox\n'),
                         [dict(pid=22, uid=90001, name='com.android.chrome:sandbox')])

    def test_aggregate_requires_complete_data(self):
        self.assertEqual(sum_complete([{'rss': 3}, {'rss': 4}], 'rss'), 7)
        self.assertIsNone(sum_complete([{'rss': 3}, {'rss': None}], 'rss'))
        self.assertIsNone(sum_complete([], 'rss'))

    def test_sections_retain_permission_error(self):
        self.assertEqual(parse_sections('@@ 2/stat\nPermission denied\n')['2/stat'],
                         'Permission denied\n')

    def test_disconnect_persists_raw_before_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = Recorder('test', 'com.test', pathlib.Path(directory) / 'run')
            with patch('record.subprocess.run', return_value=subprocess.CompletedProcess(
                    [], 1, '', 'device offline')):
                with self.assertRaises(RuntimeError):
                    recorder.adb('ps')
            recorder.raw.close()
            self.assertIn('device offline', (recorder.output / 'raw.jsonl').read_text())

    def test_pid_reuse_invalidates_entire_sample(self):
        stat = '42 (chrome) S ' + ' '.join(['0'] * 18 + ['1234'])
        sections = ('@@ 42/stat\n' + stat + '\n@@ 42/stat_end\n'
                    + stat.replace('1234', '1235')
                    + '\n@@ 42/status\nVmRSS: 123 kB\n@@ 42/memory.current\n1000\n')
        with tempfile.TemporaryDirectory() as directory:
            recorder = Recorder('test', 'com.test', pathlib.Path(directory) / 'run')
            with patch.object(recorder, 'adb', side_effect=['42 123 com.test\n', sections]):
                row = recorder.sample(123)[0]
            recorder.raw.close()
            self.assertFalse(row['identity_verified'])
            self.assertIsNone(row['VmRSS'])
            self.assertIsNone(row['memory.current'])

    def test_timeout_preserves_partial_output(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = Recorder('test', 'com.test', pathlib.Path(directory) / 'run')
            with patch('record.subprocess.run', side_effect=subprocess.TimeoutExpired(
                    'adb', 20, output=b'partial data')):
                with self.assertRaises(RuntimeError):
                    recorder.adb('ps')
            recorder.raw.close()
            self.assertIn('partial data', (recorder.output / 'raw.jsonl').read_text())


if __name__ == '__main__':
    unittest.main()
