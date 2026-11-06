import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from storage.user_settings import (DEFAULTS, UserSettingsError, load, save, validate,
                                   offline_replay_budget, DEFAULT_OFFLINE_MAX_PACKETS,
                                   DEFAULT_OFFLINE_MAX_PACKET_MIB)


class UserSettingsTests(unittest.TestCase):
    def test_missing_file_returns_defaults_and_roundtrip_persists(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'user_settings.json'
            self.assertEqual(load(path), DEFAULTS)
            document = dict(DEFAULTS, capture_send=False, display_timestamps=True,
                            merge_npc_paths=True, pipe_name='gpa-test', manual_server_port='6900',
                            offline_max_packets=50000, offline_max_packet_mib=64)
            save(document, path)
            loaded = load(path)
            self.assertFalse(loaded['capture_send'])
            self.assertTrue(loaded['display_timestamps'])
            self.assertTrue(loaded['merge_npc_paths'])
            self.assertEqual(loaded['pipe_name'], 'gpa-test')
            self.assertEqual(loaded['manual_server_port'], '6900')
            self.assertEqual(loaded['offline_max_packets'], 50000)
            self.assertEqual(loaded['offline_max_packet_mib'], 64)
            self.assertFalse(path.with_suffix('.json.tmp').exists())

    def test_failed_atomic_save_keeps_original_and_removes_temporary_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'user_settings.json'
            original = dict(DEFAULTS, record_stream=True)
            save(original, path)
            with patch('storage.user_settings.os.replace', side_effect=OSError('locked')):
                with self.assertRaises(OSError):
                    save(dict(DEFAULTS, record_stream=False), path)
            self.assertEqual(load(path)['record_stream'], True)
            self.assertEqual(list(Path(folder).iterdir()), [path])

    def test_invalid_documents_and_size_limit(self):
        with self.assertRaises(UserSettingsError):
            validate(dict(DEFAULTS, version=2))
        with self.assertRaises(UserSettingsError):
            validate(dict(DEFAULTS, capture_send=1))
        with self.assertRaises(UserSettingsError):
            validate(dict(DEFAULTS, emulator='hercules'))
        with self.assertRaises(UserSettingsError):
            validate(dict(DEFAULTS, script_indent='spaces2'))
        with self.assertRaises(UserSettingsError):
            validate(dict(DEFAULTS, manual_server_port='70000'))
        with self.assertRaises(UserSettingsError):
            validate(dict(DEFAULTS, pipe_name='bad name'))
        with self.assertRaises(UserSettingsError):
            validate(dict(DEFAULTS, unexpected=True))
        with self.assertRaises(UserSettingsError):
            validate(dict(DEFAULTS, offline_max_packets=999))
        with self.assertRaises(UserSettingsError):
            validate(dict(DEFAULTS, offline_max_packet_mib=7))
        with self.assertRaises(UserSettingsError):
            validate(dict(DEFAULTS, offline_max_packets=True))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'user_settings.json'
            path.write_text('{' + ('"x":1,' * 20000) + '"y":1}', encoding='utf-8')
            with self.assertRaises(UserSettingsError):
                load(path)
            path.write_text('{not-json', encoding='utf-8')
            with self.assertRaises(UserSettingsError):
                load(path)

    def test_partial_document_fills_defaults(self):
        result = validate(dict(version=1, display_unmapped=True))
        self.assertTrue(result['display_unmapped'])
        self.assertTrue(result['capture_send'])
        self.assertEqual(result['emulator'], 'auriga')
        self.assertEqual(result['script_indent'], 'spaces')
        self.assertEqual(result['offline_max_packets'], DEFAULT_OFFLINE_MAX_PACKETS)
        self.assertEqual(result['offline_max_packet_mib'], DEFAULT_OFFLINE_MAX_PACKET_MIB)
        self.assertFalse(result['startup_checklist_seen'])
        self.assertEqual(result['workspace_preset'], 'observe')

    def test_startup_checklist_seen_roundtrip_does_not_require_other_keys(self):
        result = validate(dict(version=1, startup_checklist_seen=True))
        self.assertTrue(result['startup_checklist_seen'])
        self.assertTrue(result['capture_send'])
        with self.assertRaises(UserSettingsError):
            validate(dict(DEFAULTS, startup_checklist_seen='yes'))

    def test_workspace_preset_defaults_and_rejects_unknown(self):
        self.assertEqual(DEFAULTS['workspace_preset'], 'observe')
        self.assertEqual(validate(dict(version=1))['workspace_preset'], 'observe')
        restored = validate(dict(version=1, workspace_preset='restore'))
        self.assertEqual(restored['workspace_preset'], 'restore')
        with self.assertRaises(UserSettingsError):
            validate(dict(DEFAULTS, workspace_preset='compact'))
        with self.assertRaises(UserSettingsError):
            validate(dict(DEFAULTS, workspace_preset=1))

    def test_offline_replay_budget_converts_mib_to_bytes(self):
        packets, nbytes = offline_replay_budget()
        self.assertEqual(packets, DEFAULT_OFFLINE_MAX_PACKETS)
        self.assertEqual(nbytes, DEFAULT_OFFLINE_MAX_PACKET_MIB * 1024 * 1024)
        packets, nbytes = offline_replay_budget(dict(version=1, offline_max_packets=30000,
                                                    offline_max_packet_mib=48))
        self.assertEqual((packets, nbytes), (30000, 48 * 1024 * 1024))

    def test_gitignore_lists_user_settings_profile(self):
        text = Path(__file__).resolve().parents[2].joinpath('.gitignore').read_text(encoding='utf-8')
        self.assertIn('config/user_settings.json', text)
