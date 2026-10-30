import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from storage.observation_export import save_observations, CONFIG_ROOT


class ObservationExportTests(unittest.TestCase):
    def test_atomic_export_preserves_sources_existing_files_and_cleans_failed_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'capture.jsonl'
            source.write_bytes(b'original capture')
            destination = root / 'observations.json'
            report = {'name': '観測', 'values': [1, 2]}
            save_observations(destination, report, [source])
            self.assertEqual(json.loads(destination.read_text(encoding='utf-8')), report)
            previous = destination.read_bytes()
            with patch('storage.observation_export.os.replace', side_effect=OSError('locked')):
                with self.assertRaises(OSError):
                    save_observations(destination, {'changed': True}, [source])
            self.assertEqual(destination.read_bytes(), previous)
            self.assertFalse(list(root.glob('*.tmp')))
            with self.assertRaises(ValueError):
                save_observations(source, report, [source])
            self.assertEqual(source.read_bytes(), b'original capture')
            with self.assertRaises(ValueError):
                save_observations(CONFIG_ROOT / 'blocked-observation-export.json', report)
            with patch('storage.observation_export.MAX_EXPORT_BYTES', 1):
                with self.assertRaises(ValueError):
                    save_observations(destination, report)
            with self.assertRaises(ValueError):
                save_observations(destination, {'value': float('nan')})
            self.assertEqual(destination.read_bytes(), previous)


    def test_streamed_utf8_matches_join_and_enforces_byte_limit_before_replace(self):
        from storage.observation_export import save_observation_chunks,ExportLimitError
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'output.txt'
            chunks=['観測😀'*20000,'\n','終端']
            count=save_observation_chunks(target,iter(chunks))
            expected=''.join(chunks).encode('utf-8')
            self.assertEqual(target.read_bytes(),expected)
            self.assertEqual(count,len(expected))
            with patch('storage.observation_export.MAX_EXPORT_BYTES',7):
                self.assertEqual(save_observation_chunks(target,['あ','\n','い']),7)
                previous=target.read_bytes()
                with self.assertRaises(ExportLimitError):save_observation_chunks(target,['あ','\n','いう'])
                self.assertEqual(target.read_bytes(),previous)
            with self.assertRaises(ValueError):save_observation_chunks(target,['changed'],[target])
            with patch('storage.observation_export.os.replace',side_effect=OSError('locked')):
                with self.assertRaises(OSError):save_observation_chunks(target,['changed'])
            self.assertEqual(target.read_bytes(),previous)
            self.assertFalse(list(Path(folder).glob('*.tmp')))

    def test_streamed_cancel_before_during_and_at_commit_keeps_original(self):
        from storage.observation_export import save_observation_chunks,ExportCancelled
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'output.txt'
            target.write_bytes(b'original')
            for cancel_at in (1,4,10):
                calls=0
                def cancelled():
                    nonlocal calls
                    calls+=1
                    return calls>=cancel_at
                with self.subTest(cancel_at=cancel_at):
                    with self.assertRaises(ExportCancelled):
                        save_observation_chunks(target,['あ'*200000],cancelled=cancelled)
                    self.assertEqual(target.read_bytes(),b'original')
                    self.assertFalse(list(Path(folder).glob('*.tmp')))
            import os
            replace=os.replace
            interrupted=False
            def final_replace(source,destination):
                nonlocal interrupted
                interrupted=True
                replace(source,destination)
            with patch('storage.observation_export.os.replace',side_effect=final_replace):
                self.assertEqual(save_observation_chunks(target,['saved'],cancelled=lambda:interrupted),5)
            self.assertEqual(target.read_bytes(),b'saved')


    def test_json_stream_keeps_exact_format_and_rejects_late_invalid_values(self):
        from storage.observation_export import report_needs_worker
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'report.json'
            report={'日本語😀':[(index,True,None,index/10) for index in range(2000)],7:'end'}
            save_observations(target,report)
            expected=(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')
            self.assertEqual(target.read_bytes(),expected)
            for invalid in (float('nan'),float('inf')):
                with self.assertRaises(ValueError):save_observations(target,{'prefix':['x']*5000,'bad':invalid})
                self.assertEqual(target.read_bytes(),expected)
                self.assertFalse(list(Path(folder).glob('*.tmp')))
            cycle=[];cycle.append(cycle)
            self.assertTrue(report_needs_worker(cycle))
            with self.assertRaises(ValueError):save_observations(target,cycle)
            self.assertEqual(target.read_bytes(),expected)
            shared={'small':'observed'}
            self.assertFalse(report_needs_worker([shared,shared]))
            self.assertTrue(report_needs_worker({'text':'x'*262145}))
