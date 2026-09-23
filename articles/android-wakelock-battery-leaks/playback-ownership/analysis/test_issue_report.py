import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('issue_report', Path(__file__).with_name('issue_report.py'))
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


class IssueEvidenceTests(unittest.TestCase):
    def test_duration_tokens(self):
        self.assertEqual(r.duration_ms('1m 2s 4ms'), 62004)
        self.assertIsNone(r.duration_ms('unavailable 2s'))

    def test_only_allowlisted_sample_timers(self):
        text = '  u0a123:\n    Wake lock AudioMix: 2s partial (1 times)\n    Wake lock DirectLockLab:direct-timed: 1m 2ms partial (1 times)\n    Wake lock PRIVATE: 1h partial\n  u0a124:\n    Wake lock AudioMix: 4h partial\n'
        result = r.battery(text, 10123)
        self.assertEqual(result['audiomix_partial_ms'], 2000)
        self.assertEqual(result['direct_partial_ms'], 60002)
        self.assertNotIn('PRIVATE', str(result))
        self.assertIsNone(r.battery(text, 10125)['audiomix_partial_ms'])
        self.assertIsNone(r.battery('  u0a123:\n    (nothing executed)\n', 10123)['audiomix_partial_ms'])

    def test_power_filters_attribution_and_preserves_disabled_unknown(self):
        text = "PARTIAL_WAKE_LOCK 'AudioMix' (uid=1041 ws=WorkSource{10123})\nPARTIAL_WAKE_LOCK 'DirectLockLab:direct-timed' DISABLED (uid=10123)\nPARTIAL_WAKE_LOCK 'PRIVATE' (uid=10124 disabled=false)\n"
        result = r.power(text, 10123)
        self.assertEqual(result['row_count'], 2)
        self.assertIsNone(result['sample_partial_rows'][0]['disabled'])
        self.assertTrue(result['sample_partial_rows'][1]['disabled'])
        self.assertNotIn('PRIVATE', str(result))
        self.assertEqual(r.power(text, 99999)['row_count'], 0)

    def test_audio_requires_uid_header(self):
        self.assertIsNone(r.audio_tracks('Track uid=10123 PRIVATE', 10123)['sample_track_rows'])
        text = 'Name Pid Uid Session\n42 501 10123 88\n43 502 10124 99\n\n'
        self.assertEqual(r.audio_tracks(text, 10123)['sample_track_rows'], 1)
        self.assertNotIn('501', str(r.audio_tracks(text, 10123)))

    def test_pixel_current_tracks_exclude_history(self):
        text = '  2 Tracks of which 1 are active\n Type Id Active Client(pid/uid) Session\n 12 yes 900/ 10123 1\n 13 no 901/ 10124 2\n Type Id Active Client(pid/uid) Session\n 09-20 removeTrack_l 11 yes 900/ 10123 1\n'
        result = r.audio_tracks(text, 10123)
        self.assertEqual(result['sample_track_rows'], 1)
        self.assertEqual(result['sample_active_track_rows'], 1)

    def test_process_state_unknown_without_column(self):
        self.assertEqual(r.process('UID PID NAME\nu0_a123 900 PRIVATE\n', 10123),
                         {'sample_processes': 1, 'process_states': None})

    def test_scenarios_do_not_require_players(self):
        self.assertEqual(r.app_summary([], 'idle')['evidence'], 'not_applicable_idle')
        self.assertEqual(r.app_summary([], 'direct-timed')['evidence'], 'inconclusive')
        summary = r.app_summary([{'event': 'wake_lock_acquired', 'is_held': True}], 'direct-untimed')
        self.assertEqual(summary['event_counts']['wake_lock_acquired'], 1)
        self.assertNotIn('players_created', summary)

    def test_capture_failure_and_counter_reset_stay_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'private').mkdir()
            (root / 'manifest.json').write_text(json.dumps({'run_id': 'synthetic', 'scenario': 'direct-timed', 'status': 'failed', 'app_uid': 10123}))
            for boundary, seconds in [('play-end', 10), ('observe-end', 2)]:
                (root / 'private' / (boundary + '-batterystats.txt')).write_text(f'  u0a123:\n    Wake lock AudioMix: {seconds}s partial\n')
            report = r.generate(root)
            self.assertEqual(report['classification'], 'inconclusive')
            self.assertEqual(report['capture_validity'], 'incomplete_or_corrupt')
            self.assertIsNone(report['batterystats_delta']['audiomix_partial_ms'])

    def test_measured_delta_is_not_total(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'private').mkdir()
            (root / 'manifest.json').write_text(json.dumps({'run_id': 'synthetic', 'scenario': 'foreground', 'status': 'completed', 'app_uid': 10123}))
            for boundary, seconds in [('play-end', 10), ('observe-end', 12)]:
                (root / 'private' / (boundary + '-batterystats.txt')).write_text(f'  u0a123:\n    Wake lock AudioMix: {seconds}s partial\n')
            report = r.generate(root)
            self.assertEqual(report['batterystats_delta']['audiomix_partial_ms'], 2000)
            self.assertEqual(report['classification'], 'inconclusive')


if __name__ == '__main__':
    unittest.main()
