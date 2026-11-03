"""Shared MOB export freeze gate for skill/combat/spawn stores."""
import unittest
from unittest.mock import MagicMock, patch

from gui.report_export import prepare_mob_export


class ReportExportTests(unittest.TestCase):
    def test_prepare_mob_export_uses_records_when_store_has_no_events(self):
        owner = MagicMock()
        workspace = MagicMock()
        owner.window.return_value = workspace
        workspace.save_prepared_report = object()
        store = MagicMock(spec=['records', 'world'])
        store.records = [object()] * 1001
        store.world = object()
        with patch('reconstruction.report_snapshot.freeze_mob_report', return_value='frozen') as freeze:
            self.assertEqual(prepare_mob_export(owner, store, {0: 'a.jsonl'}), 'frozen')
        freeze.assert_called_once()
        store.records = [object()] * 10
        self.assertIsNone(prepare_mob_export(owner, store, {0: 'a.jsonl'}))
