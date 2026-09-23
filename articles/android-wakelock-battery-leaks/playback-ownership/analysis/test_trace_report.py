import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('trace_report', Path(__file__).with_name('trace_report.py'))
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


class TraceTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
