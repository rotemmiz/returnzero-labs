import contextlib
import io
import json
import pathlib
import tempfile
import unittest

from summarize_pilot import summarize


class SummaryTests(unittest.TestCase):
    def test_partial_totals_and_process_count(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            rows = [dict(stage='baseline', sweep_start_s=0, sweep_end_s=.2,
                         processes=[dict(pid=1, start_ticks=10, identity_verified=True,
                                         VmRSS=1024, VmSwap=0)]),
                    dict(stage='baseline', sweep_start_s=1, sweep_end_s=1.2,
                         processes=[dict(pid=1, start_ticks=10, identity_verified=True,
                                         VmRSS=None, VmSwap=0)])]
            (root / 'processes.jsonl').write_text('\n'.join(json.dumps(r) for r in rows))
            (root / 'actions.jsonl').write_text('')
            with contextlib.redirect_stdout(io.StringIO()):
                summarize(root)
            result = json.loads((root / 'derived/summary.json').read_text())
            self.assertEqual(result['stages']['baseline']['median_summed_rss_mib'], 1)
            self.assertEqual(result['stages']['baseline']['process_count_range'], [1, 1])
            self.assertTrue((root / 'derived/pilot-timeline.png').exists())


if __name__ == '__main__':
    unittest.main()
