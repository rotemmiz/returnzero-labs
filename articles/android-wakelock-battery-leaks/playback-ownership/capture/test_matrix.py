import unittest
from matrix import SCENARIOS, trial_order


class MatrixTest(unittest.TestCase):
    def test_three_rounds_rotate_and_cover_each_condition(self):
        order = trial_order(3)
        self.assertEqual(21, len(order))
        for round_number in range(1, 4):
            scenarios = [s for r, s in order if r == round_number]
            self.assertCountEqual(SCENARIOS, scenarios)
            self.assertEqual(SCENARIOS[round_number - 1], scenarios[0])
