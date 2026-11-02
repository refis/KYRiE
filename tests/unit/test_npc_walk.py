import unittest

from reconstruction.npc_walk import chebyshev_distance, npc_walk_wait_ms


class NpcWalkWaitTests(unittest.TestCase):
    def test_chebyshev_and_axis_aligned_wait_match_auriga(self):
        self.assertEqual(chebyshev_distance(10, 20, 13, 24), 4)
        # Axis-aligned: speed * dist + max(extra, 50)
        self.assertEqual(npc_walk_wait_ms(0, 0, 5, 0, 200), 200 * 5 + 50)
        self.assertEqual(npc_walk_wait_ms(0, 0, 0, 3, 150, extra_ms=10), 150 * 3 + 50)

    def test_diagonal_wait_uses_cardinal_and_14_10_diagonal_costs(self):
        # dx=3, dy=4 -> cardinal 1, diagonal 3
        self.assertEqual(npc_walk_wait_ms(0, 0, 3, 4, 200), 200 * 1 + 200 * 3 * 14 // 10 + 50)

    def test_rejects_non_integer_inputs(self):
        with self.assertRaises(ValueError):
            npc_walk_wait_ms(0, 0, 1, 1, 1.5)
