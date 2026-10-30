"""Check suite coverage and selection without executing unrelated features."""
from pathlib import Path
import unittest

from tools.run_tests import GROUPS, cases, selected_names, selected_suite


class TestSelectionTests(unittest.TestCase):
    def test_groups_cover_existing_modules_without_stale_entries(self):
        root = Path(__file__).resolve().parents[2]
        actual = {'.'.join(path.relative_to(root).with_suffix('').parts)
                  for folder in ('unit', 'integration')
                  for path in (root / 'tests' / folder).glob('test_*.py')}
        configured = {name for names in GROUPS.values() for name in names}
        self.assertEqual(actual, configured)

    def test_selection_keeps_method_scope_and_deduplicates_overlapping_targets(self):
        method = __name__ + '.TestSelectionTests.test_groups_cover_existing_modules_without_stale_entries'
        suite = selected_suite(selected_names(['selection', method, 'selection']))
        self.assertEqual(suite.countTestCases(), 3)
        self.assertEqual(len({case.id() for case in cases(suite)}), 3)
        self.assertEqual(selected_suite([method]).countTestCases(), 1)

    def test_unknown_targets_are_rejected_without_broadening_scope(self):
        for target in ('all', 'shpo', 'tests', 'tools.run_tests'):
            with self.subTest(target=target), self.assertRaises(ValueError):
                selected_names([target])
