import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from storage.user_settings import DEFAULTS, UserSettingsError, load, save, validate


class UserSettingsTests(unittest.TestCase):
    def test_missing_file_returns_defaults_and_roundtrip_persists(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'user_settings.json'
            self.assertEqual(load(path), DEFAULTS)
            document = dict(DEFAULTS, capture_send=False, display_timestamps=True,
                            merge_npc_paths=True, pipe_name='gpa-test', manual_server_port='6900')
            save(document, path)
            loaded = load(path)
            self.assertFalse(loaded['capture_send'])
            self.assertTrue(loaded['display_timestamps'])
            self.assertTrue(loaded['merge_npc_paths'])
            self.assertEqual(loaded['pipe_name'], 'gpa-test')
            self.assertEqual(loaded['manual_server_port'], '6900')
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

    def test_gitignore_lists_user_settings_profile(self):
        text = Path(__file__).resolve().parents[2].joinpath('.gitignore').read_text(encoding='utf-8')
        self.assertIn('config/user_settings.json', text)
