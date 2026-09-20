import unittest
from audit_snapshots import parse_meminfo


class AuditTests(unittest.TestCase):
    def test_header_only_is_missing(self):
        record = parse_meminfo('** MEMINFO in pid 42 [com.test:isolated] **')
        self.assertEqual(record['pid'], 42)
        self.assertIsNone(record['reported_total_pss_kib'])

    def test_reported_pss_and_swap_stay_separate(self):
        record = parse_meminfo('Pss Private Private SwapPss Rss\n'
                               ' TOTAL 100 20 30 40 200\n'
                               'TOTAL PSS: 100 TOTAL RSS: 200 TOTAL SWAP PSS: 40')
        self.assertEqual(record['reported_total_pss_kib'], 100)
        self.assertEqual(record['reported_swap_pss_kib'], 40)
        self.assertEqual(record['private_dirty_plus_clean_kib'], 50)


if __name__ == '__main__':
    unittest.main()
