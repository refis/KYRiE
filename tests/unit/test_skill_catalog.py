"""Targeted static catalog import and atomic replacement contracts."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reconstruction.skill_catalog import build_import, apply_import, parse_table, read_bounded
from reconstruction.skills import load_skill_names


def lua_string(text):
    return b'"' + text.encode('cp932').replace(b'\\',b'\\\\').replace(b'"',b'\\"') + b'"'


class SkillCatalogTests(unittest.TestCase):
    def inputs(self, folder, extra=b''):
        root=Path(folder)
        ids=root/'skillid.lua';info=root/'skillinfolist.lua';current=root/'names.json'
        ids.write_bytes(b'-- header\nSKID = { MG_SAFETYWALL=12, All_Mixed=383, Alias=12 }')
        info.write_bytes(b'--[=[ comment with { and " ]=]\nSKILL_INFO_LIST = {'
            b'[SKID.MG_SAFETYWALL]={"MG_SAFETYWALL"; SkillName='+lua_string('ソ表"テスト')+
            b', MaxLv=10, SpAmount={1,2}, bSeperateLv=true, Need={{SKID.All_Mixed,1}}},'
            b'[SKID.All_Mixed]={SkillName="Mixed"},'+extra+b'}')
        current.write_text(json.dumps(dict(version=1,skills={'12':'old','999':'retain'})),encoding='utf-8')
        return ids,info,current

    def test_byte_escapes_mixed_case_nested_tables_and_lua_priority_preserve_existing_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            paths=self.inputs(folder)
            before=paths[2].read_bytes()
            document,report=build_import(*paths)
            self.assertTrue(report['ready'])
            self.assertEqual(document['skills'],{'12':'ソ表"テスト','383':'Mixed','999':'retain'})
            self.assertEqual(report['retained_existing_ids'],[999])
            self.assertEqual(len(report['additions']),1)
            self.assertEqual(len(report['changes']),1)
            self.assertEqual(report['aliases'],[{'id':12,'symbols':['MG_SAFETYWALL','Alias']}])
            self.assertEqual(paths[2].read_bytes(),before)
            apply_import(document,report)
            self.assertEqual(load_skill_names(paths[2])[12],'ソ表"テスト')
            again,preview=build_import(*paths)
            self.assertFalse(preview['changes'] or preview['additions'])
            self.assertEqual(again,document)
            self.assertEqual(preview['result_sha256'],report['result_sha256'])

    def test_parser_rejects_execution_duplicate_keys_bad_escapes_and_truncation(self):
        invalid=[b'SKID={A=1} os.execute("bad")',b'SKID={A=1,A=2}',
                 b'SKID={A=function() return 1 end}',rb'SKID={A="\q"}',
                 rb'SKID={A="\256"}',b'SKID={A=1',b'SKID={A="unfinished}',
                 b'\x1bLua',b'--[[ unclosed',b'SKID='+b'{'*50+b'}'*50]
        for raw in invalid:
            with self.subTest(raw=raw[:40]),self.assertRaises(ValueError):parse_table(raw,'SKID')
        self.assertEqual(parse_table(rb'SKID={A="\065\066", B="os.execute()"}','SKID'),
                         {'A':'AB','B':'os.execute()'})
        self.assertEqual(parse_table('SKID={A="日本語"}'.encode('utf-8'),'SKID','utf-8')['A'],'日本語')

    def test_unresolved_or_conflicting_names_block_application_without_deleting_current_names(self):
        for extra in (b'[SKID.UNKNOWN]={SkillName="unknown"},',
                      b'[SKID.Alias]={SkillName="conflict"},',
                      b'[SKID.Alias]={SkillName=""},'):
            with self.subTest(extra=extra),tempfile.TemporaryDirectory() as folder:
                paths=self.inputs(folder,extra)
                before=paths[2].read_bytes()
                document,report=build_import(*paths)
                self.assertFalse(report['ready'])
                self.assertTrue(report['issues'])
                with self.assertRaises(ValueError):apply_import(document,report)
                self.assertEqual(paths[2].read_bytes(),before)

    def test_changed_inputs_or_document_and_replace_failure_preserve_dictionary(self):
        for change in ('source','dictionary','document','replace'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as folder:
                paths=self.inputs(folder)
                document,report=build_import(*paths)
                if change=='source':paths[0].write_bytes(paths[0].read_bytes()+b'\n')
                if change=='dictionary':paths[2].write_bytes(paths[2].read_bytes()+b'\n')
                if change=='document':document['skills']['12']='tampered'
                before=paths[2].read_bytes()
                if change=='replace':
                    with patch('reconstruction.skill_catalog.os.replace',side_effect=OSError('blocked')):
                        with self.assertRaises(OSError):apply_import(document,report)
                else:
                    with self.assertRaises(ValueError):apply_import(document,report)
                self.assertEqual(paths[2].read_bytes(),before)
                self.assertFalse(list(Path(folder).glob('*.tmp')))

    def test_limits_and_encoding_errors_are_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            paths=self.inputs(folder)
            with self.assertRaises(ValueError):read_bounded(paths[0],1)
            with patch('reconstruction.skill_catalog.MAX_TOKENS',1):
                with self.assertRaises(ValueError):parse_table(b'SKID={A=1}','SKID')
            with self.assertRaises(UnicodeDecodeError):parse_table(b'SKID={A="\x81"}','SKID')
            with self.assertRaises(ValueError):parse_table(b'SKID={A=1}','SKID','latin1')

    def test_cli_dry_run_apply_and_source_output_protection(self):
        from contextlib import redirect_stdout,redirect_stderr
        from io import StringIO
        from tools.import_skill_names import main
        with tempfile.TemporaryDirectory() as folder:
            ids,info,current=self.inputs(folder)
            args=['import_skill_names','--skillid',str(ids),'--info',str(info),
                  '--dictionary',str(current)]
            before=current.read_bytes()
            with patch('sys.argv',args),redirect_stdout(StringIO()):main()
            self.assertEqual(current.read_bytes(),before)
            original=ids.read_bytes()
            with patch('sys.argv',args+['--report',str(ids)]),redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit):main()
            self.assertEqual(ids.read_bytes(),original)
            with patch('sys.argv',args+['--apply']),redirect_stdout(StringIO()):main()
            self.assertEqual(len(load_skill_names(current)),3)
            current.write_text('{"version":1,"skills":{"12":"a","12":"b"}}',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'Duplicate dictionary'):
                build_import(ids,info,current)

    def test_input_change_after_temporary_creation_is_rechecked(self):
        with tempfile.TemporaryDirectory() as folder:
            paths=self.inputs(folder)
            document,report=build_import(*paths)
            before=paths[2].read_bytes()
            create=tempfile.NamedTemporaryFile
            def changed(*args,**kwargs):
                stream=create(*args,**kwargs)
                paths[0].write_bytes(paths[0].read_bytes()+b'\n')
                return stream
            with patch('reconstruction.skill_catalog.tempfile.NamedTemporaryFile',side_effect=changed):
                with self.assertRaisesRegex(ValueError,'input changed'):
                    apply_import(document,report)
            self.assertEqual(paths[2].read_bytes(),before)
            self.assertFalse(list(Path(folder).glob('*.tmp')))

    def test_reference_tree_is_protected_even_for_non_input_output_files(self):
        from contextlib import redirect_stderr
        from io import StringIO
        from tools.import_skill_names import main
        with tempfile.TemporaryDirectory() as folder:
            ids,info,current=self.inputs(folder)
            root=Path(folder)/'reference';root.mkdir()
            target=root/'other.txt';target.write_bytes(b'keep source')
            args=['import_skill_names','--skillid',str(ids),'--info',str(info),
                  '--dictionary',str(current),'--report',str(target)]
            with patch('sys.argv',args),patch('tools.import_skill_names.REFERENCE_ROOT',root),redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit):main()
            self.assertEqual(target.read_bytes(),b'keep source')
            document,report=build_import(ids,info,current)
            before=current.read_bytes()
            with patch('reconstruction.skill_catalog.REFERENCE_ROOT',Path(folder)):
                with self.assertRaisesRegex(ValueError,'read-only'):apply_import(document,report)
            self.assertEqual(current.read_bytes(),before)
