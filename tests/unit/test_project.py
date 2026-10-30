from pathlib import Path
import json
import tempfile
import unittest

from storage.project import (FILE_KEYS, fingerprint, load_project, save_project, verify_project, save_multiple_project,
                             project_references, relocate_project, save_relocated_project)


class ProjectTests(unittest.TestCase):
    def test_atomic_reference_roundtrip_and_input_overwrite_protection(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            files = {}
            for name in FILE_KEYS:
                path = root / (name + '.txt')
                path.write_text('content-' + name, encoding='utf-8')
                files[name] = path
            view = dict(filter='', timestamps=False, unmapped=False, tab=0, conversation=-1, merged=False)
            expected = fingerprint(files['log'], 1024)
            destination = root / 'work.gpa.json'
            save_project(destination, files, view, 'note', expected)
            loaded = load_project(destination)
            verify_project(loaded)
            self.assertEqual(loaded['view'], view)
            self.assertEqual(loaded['note'], 'note')
            second = root / 'second.jsonl'
            second.write_text('second-log', encoding='utf-8')
            multiple = root / 'multiple.gpa.json'
            sources = [dict(source_log=files['log'], source_sha256=expected,
                            definitions_path=files['definitions'], capture_session=1),
                       dict(source_log=second, source_sha256=fingerprint(second, 1024),
                            definitions_path=files['definitions'], capture_session=3)]
            common = {key: files[key] for key in ('recv', 'send', 'dialogue')}
            save_multiple_project(multiple, common, sources, view, 'multiple')
            multi = load_project(multiple)
            verify_project(multi)
            self.assertEqual([row['capture_session'] for row in multi['sources']], [1, 3])
            moved = root / 'moved-definitions.txt'
            moved.write_bytes(files['definitions'].read_bytes())
            index = next(i for i, (key, _) in enumerate(project_references(multi)) if key == 'definitions')
            relocated = relocate_project(multi, {index: moved})
            self.assertEqual([row['definitions']['path'] for row in relocated['sources']], [str(moved), str(moved)])
            self.assertEqual(multi['sources'][0]['definitions']['path'], str(files['definitions']))
            fixed = root / 'relocated.gpa.json'
            save_relocated_project(fixed, relocated)
            self.assertEqual(load_project(fixed), relocated)
            config_target = Path(__file__).resolve().parents[2] / 'config' / 'ignorepacket.json'
            original_config = config_target.read_bytes()
            for save in (lambda: save_project(config_target, files, view, 'note', expected),
                         lambda: save_multiple_project(config_target, common, sources, view, 'multiple'),
                         lambda: save_relocated_project(config_target, relocated)):
                with self.assertRaises(ValueError):
                    save()
                self.assertEqual(config_target.read_bytes(), original_config)
            with self.assertRaises(ValueError):
                relocate_project(multi, {index: second})
            with self.assertRaises(ValueError):
                save_relocated_project(second, relocated)
            with self.assertRaises(ValueError):
                save_multiple_project(second, common, sources, view, '')
            for defect in ('empty', 'duplicate_session', 'duplicate_hash', 'bad_hash'):
                document = json.loads(json.dumps(multi))
                if defect == 'empty':
                    document['sources'] = []
                elif defect == 'duplicate_session':
                    document['sources'][1]['capture_session'] = 1
                elif defect == 'duplicate_hash':
                    document['sources'][1]['log']['sha256'] = document['sources'][0]['log']['sha256']
                else:
                    document['sources'][1]['log']['sha256'] = 'bad'
                multiple.write_text(json.dumps(document), encoding='utf-8')
                with self.subTest(defect=defect), self.assertRaises(ValueError):
                    load_project(multiple)
            for name in FILE_KEYS:
                with self.subTest(name=name), self.assertRaises(ValueError):
                    save_project(files[name], files, view, '', expected)
            before = destination.read_bytes()
            files['log'].write_text('changed', encoding='utf-8')
            with self.assertRaises(ValueError):
                save_project(destination, files, view, '', expected)
            self.assertEqual(destination.read_bytes(), before)
            with self.assertRaises(ValueError):
                verify_project(loaded)
            files['recv'].unlink()
            with self.assertRaises(OSError):
                fingerprint(files['recv'], 1024)
            self.assertFalse(list(root.glob('*.tmp')))

    def test_untrusted_manifest_validation_is_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bad.gpa.json'
            for content in ('[]', '{"schema":1,"schema":1}',
                            '[' * 2000 + ']' * 2000, ' ' * (1024 * 1024 + 1)):
                with self.subTest(size=len(content)):
                    path.write_text(content, encoding='utf-8')
                    with self.assertRaises(ValueError):
                        load_project(path)


    def test_catalogs_roundtrip_both_schemas_and_relocation_without_changing_runtime_dictionary(self):
        from storage.project import CATALOG_PATHS
        for multiple in (False,True):
            with self.subTest(multiple=multiple),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);files={}
                for key in FILE_KEYS:
                    path=root/(key+'.txt');path.write_text(key);files[key]=path
                expected=fingerprint(files['log'],1024)
                view=dict(filter='',timestamps=False,unmapped=False,tab=0,conversation=-1,merged=False)
                catalogs={}
                for key,path in CATALOG_PATHS.items():
                    copy=root/(key+'.json');copy.write_bytes(path.read_bytes());catalogs[key]=copy
                destination=root/'work.gpa.json'
                if multiple:
                    sources=[dict(source_log=files['log'],source_sha256=expected,definitions_path=files['definitions'],capture_session=1)]
                    save_multiple_project(destination,{key:files[key] for key in ('recv','send','dialogue')},
                        sources,view,'note',catalogs=catalogs)
                else:save_project(destination,files,view,'note',expected,catalogs=catalogs)
                loaded=load_project(destination);verify_project(loaded)
                self.assertEqual(set(loaded['catalogs']),set(CATALOG_PATHS))
                self.assertTrue(set(CATALOG_PATHS)<=set(key for key,ref in project_references(loaded)))
                index=next(i for i,(key,ref) in enumerate(project_references(loaded)) if key=='skill_names')
                moved=root/'moved-names.json';catalogs['skill_names'].rename(moved)
                with self.assertRaises(OSError):verify_project(loaded)
                fixed=relocate_project(loaded,{index:moved});verify_project(fixed)
                repaired=root/'repaired.gpa.json';save_relocated_project(repaired,fixed)
                self.assertEqual(load_project(repaired),fixed)
                moved.write_bytes(moved.read_bytes()+b'\n')
                with self.assertRaises(ValueError):verify_project(fixed)

    def test_catalog_save_rejects_stale_loaded_hashes_and_runtime_mismatch_atomically(self):
        from unittest.mock import patch
        from storage.project import CATALOG_PATHS
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);files={}
            for key in FILE_KEYS:
                path=root/(key+'.txt');path.write_text(key);files[key]=path
            expected=fingerprint(files['log'],1024)
            view=dict(filter='',timestamps=False,unmapped=False,tab=0,conversation=-1,merged=False)
            target=root/'work.gpa.json';target.write_bytes(b'existing')
            catalogs={'skill_names':CATALOG_PATHS['skill_names']}
            with self.assertRaises(ValueError):save_project(target,files,view,'',expected,
                catalogs=catalogs,expected_catalog_hashes={'skill_names':'0'*64})
            self.assertEqual(target.read_bytes(),b'existing')
            save_project(target,files,view,'',expected,catalogs=catalogs)
            loaded=load_project(target)
            other=root/'different.json';other.write_text('{}')
            with patch.dict(CATALOG_PATHS,{'skill_names':other}):
                with self.assertRaises(ValueError):verify_project(loaded)
            old=target.read_bytes()
            with self.assertRaises(ValueError):save_project(target,files,view,'',expected,catalogs={'unknown':other})
            self.assertEqual(target.read_bytes(),old)
            for value in ({},{'unknown':{}},{'skill_names':{'path':'x','sha256':'bad'}}):
                doc=json.loads(old);doc['catalogs']=value
                invalid=root/'invalid.gpa.json';invalid.write_text(json.dumps(doc))
                with self.assertRaises(ValueError):load_project(invalid)
