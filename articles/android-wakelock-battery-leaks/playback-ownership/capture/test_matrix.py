import json
from pathlib import Path
import tempfile
import unittest
from matrix import SCENARIOS, checkpoint_state, save_checkpoint, trial_order


class MatrixTest(unittest.TestCase):
    def test_three_rounds_rotate_and_cover_each_condition(self):
        order = trial_order(3)
        self.assertEqual(21, len(order))
        for round_number in range(1, 4):
            scenarios = [s for r, s in order if r == round_number]
            self.assertCountEqual(SCENARIOS, scenarios)
            self.assertEqual(SCENARIOS[round_number - 1], scenarios[0])

    def test_resume_preserves_failed_and_successful_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / 'matrix.json'
            identity = {'source_commit': 'revision', 'rounds': 3, 'serial': 'device',
                        'apk_sha256': {'playback': 'aaa', 'direct': 'bbb'}}
            state = checkpoint_state(checkpoint, identity)
            state['attempts'] = [{'index': 0, 'returncode': 1}, {'index': 0, 'returncode': 0}]
            save_checkpoint(checkpoint, state)
            self.assertEqual(checkpoint_state(checkpoint, identity), state)
            self.assertFalse(checkpoint.with_suffix('.tmp').exists())
            self.assertEqual(json.loads(checkpoint.read_text()), state)

    def test_resume_rejects_device_or_apk_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / 'matrix.json'
            identity = {'source_commit': 'revision', 'rounds': 3, 'serial': 'device',
                        'apk_sha256': {'playback': 'aaa', 'direct': 'bbb'}}
            save_checkpoint(checkpoint, checkpoint_state(checkpoint, identity))
            for change in ({'serial': 'other-device'}, {'apk_sha256': {'playback': 'aaa', 'direct': 'changed'}},
                           {'source_commit': 'other'}, {'rounds': 2}):
                with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'different'):
                    checkpoint_state(checkpoint, {**identity, **change})
