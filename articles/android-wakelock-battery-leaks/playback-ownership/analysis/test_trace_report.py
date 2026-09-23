import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('trace_report', Path(__file__).with_name('trace_report.py'))
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


class TraceTests(unittest.TestCase):
    def test_only_sanitized_processor_versions_are_recorded(self):
        with patch.object(r, 'processor_command', return_value=['processor']), patch.object(r.subprocess, 'run') as run:
            run.return_value = Mock(returncode=0, stdout='private path /somewhere\nPerfetto v58.2-add693d8b (add693d8b338ba9599dbcbc3e300b1ab8c000897)\n')
            version = r.processor_version(Path('unused'))
            self.assertTrue(r.validated_version(version))
            self.assertNotIn('private', version)
            run.return_value = Mock(returncode=0, stdout='Perfetto v58.2 private /path\n')
            self.assertIsNone(r.processor_version(Path('unused')))
            run.return_value = Mock(returncode=1, stdout='Perfetto v58.2\n')
            self.assertIsNone(r.processor_version(Path('unused')))

    def test_only_reviewed_runtime_semantics_are_accepted(self):
        self.assertTrue(r.validated_version('Perfetto v58.2'))
        for value in (None, 'Perfetto v58.20', 'Perfetto v59.0', 'Perfetto v57.2'):
            self.assertFalse(r.validated_version(value))

    def test_pid_and_sequence_required(self):
        events = [{'pid': 42, 'seq': 1, 'event': 'run_start', 'elapsed_ns': 100}]
        markers = [{'pid': '43', 'name': 'PL:1:run_start', 'ts': '102'}]
        self.assertEqual(r.match_markers(events, markers, 'PL')['matched_events'], 0)
        markers.append({'pid': '42', 'name': 'PL:1:run_start', 'ts': '105'})
        result = r.match_markers(events, markers, 'PL')
        self.assertEqual(result['matched_events'], 1)
        self.assertEqual(result['marker_minus_app_elapsed_ns_max'], 5)

    def test_duplicate_markers_are_ambiguous(self):
        event = {'pid': 42, 'seq': 2, 'event': 'wake_lock_acquired', 'elapsed_ns': 100}
        marker = {'pid': '42', 'name': 'DL:2:wake_lock_acquired', 'ts': '110'}
        result = r.match_markers([event], [marker, marker], 'DL')
        self.assertEqual(result['ambiguous_events'], 1)
        self.assertIsNone(result['marker_minus_app_elapsed_ns_min'])

class SuspendBoundsTests(unittest.TestCase):
    def fixture(self, directory, second='1.40'):
        root = Path(directory)
        (root / 'private').mkdir()
        (root / 'private/pre-clock.txt').write_text('private date\n1.00 10.00\n')
        (root / 'private/post-clock.txt').write_text(f'private date\n{second} 10.00\n')
        return {'boundaries': [{'boundary': n, 'host_monotonic_ns': t} for n, t in
                [('pre', 0), ('quiet-screen-off-start', 100000000), ('quiet-screen-off-end', 300000000), ('post', 390000000)]],
                'commands': [{'command': ['shell', 'sh', '-c', 'date +%s; cat /proc/uptime'],
                              'returncode': 0, 'start_host_ns': t, 'end_host_ns': t + 20000000} for t in [0, 400000000]]}

    def test_alignment_quantization_and_brackets(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            m = self.fixture(d)
            a = r.quiet_alignment(m, d)
            self.assertEqual(a['offset_lower_ns'], 980000000)
            self.assertEqual(a['offset_upper_ns'], 1010000000)
            evidence = r.suspend_evidence(m, d, {'snapshots': 2, 'maximum_offset_ns': 0}, [],
                [(1080000000, 1130000000)], 1, [{'start_ts': 0, 'end_ts': 2000000000}])
            self.assertEqual(evidence['suspended_ns_lower'], 20000000)
            self.assertEqual(evidence['suspended_ns_upper'], 50000000)

    def test_clock_discontinuity_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            m = self.fixture(d, second='4.00')
            self.assertIsNone(r.quiet_alignment(m, d))

    def test_no_source_or_data_loss_is_unknown(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            m = self.fixture(d)
            for stats, sources, reason in [([], 0, 'no_supported_suspend_source_slices'),
                    ([{'severity': 'data_loss', 'name': 'ftrace_cpu_overrun'}], 2, 'reported_trace_loss_or_error')]:
                evidence = r.suspend_evidence(m, d, {'snapshots': 2, 'maximum_offset_ns': 0}, stats, [], sources,
                                             [{'start_ts': 0, 'end_ts': 2000000000}])
                self.assertEqual(evidence['reason'], reason)
                self.assertNotIn('suspended_ns_lower', evidence)

    def test_overlap_unions_duplicate_slices(self):
        self.assertEqual(r.overlap_duration([(1, 5), (3, 9), (1, 5)], 2, 8), 6)


if __name__ == '__main__':
    unittest.main()
