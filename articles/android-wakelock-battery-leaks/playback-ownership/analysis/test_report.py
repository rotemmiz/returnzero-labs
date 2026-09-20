import importlib.util
from pathlib import Path
import unittest

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location('report', HERE / 'report.py')
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)
spec = importlib.util.spec_from_file_location('capture', HERE.parent / 'capture/capture.py')
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


class EvidenceTests(unittest.TestCase):
    def test_filters_other_runs_and_reports_corrupt_lines(self):
        events, errors = report.read_events('{"run_id":"a","event":"x"}\nnope\n{"run_id":"b"}\n[]', 'a')
        self.assertEqual(len(events), 1)
        self.assertEqual(errors, [2, 4])

    def test_balanced_release_is_only_app_evidence(self):
        events = [{'event': event, 'player_id': 'one', 'pid': 1, 'seq': i, 'elapsed_ns': i * 1000000000}
                  for i, event in enumerate(['player_created', 'release_start', 'release_end'])]
        result = report.summarize_events(events)
        self.assertEqual(result['app_owner_evidence'], 'balanced_create_release_records')
        self.assertEqual(result['event_span_seconds'], 2)
        self.assertNotIn('device_cleanup', result)

    def test_process_restart_does_not_match_old_unreleased_player(self):
        result = report.summarize_events([
            {'event': 'player_created', 'player_id': 1, 'pid': 1, 'seq': 1},
            {'event': 'release_end', 'player_id': 1, 'pid': 2, 'seq': 1},
        ])
        self.assertEqual(result['unreleased_players'], 1)
        self.assertEqual(result['unmatched_releases'], 1)
        self.assertEqual(result['app_owner_evidence'], 'inconclusive')

    def test_missing_events_cannot_pass(self):
        self.assertEqual(report.summarize_events([])['app_owner_evidence'], 'inconclusive')

    def test_uid_selection_does_not_include_other_apps(self):
        text = '  u0a123:\n    Wake lock AudioMix: 2m 3s 100ms partial (2 times) realtime\n    private: secret\n  u0a124:\n    Wake lock AudioMix: 9h partial (1 times)\n'
        result = report.audiomix_summary(text, 10123)
        self.assertEqual(result['audiomix_entries'], [{'partial_duration_text': '2m 3s 100ms'}])
        self.assertNotIn('secret', str(result))
        self.assertNotIn('9h', str(result))
        self.assertFalse(report.audiomix_summary(text, 10500)['sample_uid_present'])

    def test_numeric_secondary_user_uid(self):
        text = '  110123:\n    Wake lock AudioMix: 5s partial (1 times)\n'
        self.assertTrue(report.audiomix_summary(text, 110123)['sample_uid_present'])

    def test_config_only_requests_available_atrace_categories(self):
        config = capture.make_config('name: linux.ftrace', '  audio - Audio\n  gfx - Graphics\n', 1000)
        self.assertIn('atrace_categories: "audio"', config)
        self.assertNotIn('atrace_categories: "power"', config)
        self.assertIn('duration_ms: 1000', config)
        self.assertIsNone(capture.make_config('unavailable', '', 1000))


if __name__ == '__main__':
    unittest.main()
