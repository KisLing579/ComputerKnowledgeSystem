import unittest
from representation.coverage import implementation_status


class CoverageTests(unittest.TestCase):
    def test_distinguishes_specialized_simplified_and_fallback(self):
        self.assertEqual(implementation_status("EVENT_PROPAGATION"), "dedicated")
        self.assertEqual(implementation_status("METRIC_CHANGE"), "simplified")
        self.assertEqual(implementation_status("CACHE_LOOKUP_HIT_MISS"), "simplified")
        self.assertEqual(implementation_status("TLB_CACHE_PARALLEL"), "fallback")
        self.assertEqual(implementation_status("RELATION_LINK"), "fallback")
