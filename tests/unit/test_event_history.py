import unittest
from gui.event_history import MEMORY_EVENT_LIMIT, physical_index, trim_parallel


class EventHistoryTests(unittest.TestCase):
    def test_physical_index_and_trim_keep_parallel_lists(self):
        self.assertEqual(physical_index(12, 10), 2)
        with self.assertRaises(ValueError):
            physical_index(1, -1)
        left, right = [0, 1, 2, 3], ['a', 'b', 'c', 'd']
        trim_parallel((left, right), 2)
        self.assertEqual((left, right), ([2, 3], ['c', 'd']))
        with self.assertRaises(ValueError):
            trim_parallel((left,), 5)
        self.assertGreaterEqual(MEMORY_EVENT_LIMIT, 2105)
