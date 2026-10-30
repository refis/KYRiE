import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from dataclasses import replace

from reconstruction.skill_units import load_unit_catalog, unit_labels
from tools.build_skill_unit_catalog import maria_units, auriga_units, build_catalog
from parser.display import DisplayProfile, ReceiveDisplay
from tests.support.skills import unit_appearance
from tests.support.display import event


class SkillUnitTests(unittest.TestCase):
    def test_reference_labels_keep_shared_units_and_disputed_ids_unresolved(self):
        catalog=load_unit_catalog()
        self.assertEqual(catalog['units']['126']['symbol'],'UNT_SAFETYWALL')
        self.assertEqual({row['id'] for row in catalog['units']['126']['skills']},{12,8033})
        self.assertIn('候補',unit_labels(catalog,126)['unit_name'])
        self.assertEqual(unit_labels(catalog,127)['unit_name'],'ファイアーウォール')
        self.assertFalse(unit_labels(catalog,264)['unit_known'])
        self.assertFalse(unit_labels(catalog,0xffffffff)['unit_known'])
        self.assertGreater(len(catalog['units']['134']['skills']),1)

    def test_static_sources_do_not_execute_and_reject_duplicate_or_computed_constants(self):
        self.assertEqual(maria_units(b'UNITID={126:"UNT_A"}\nraise RuntimeError("not executed")'),{126:'UNT_A'})
        for raw in (b'UNITID={126:"UNT_A",126:"UNT_B"}',b'UNITID={126:func()}',b'UNITID={**other}'):
            with self.assertRaises(ValueError):maria_units(raw)
        self.assertEqual(auriga_units(b'enum { UNT_SAFETYWALL=0x7e, UNT_B, UNT_C=0x90 };'),
                         {126:'UNT_SAFETYWALL',127:'UNT_B',144:'UNT_C'})
        with self.assertRaises(ValueError):auriga_units(b'enum { UNT_SAFETYWALL=foo() };')

    def test_builder_validates_skill_symbols_and_keeps_definition_conflicts(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'src/map').mkdir(parents=True);(root/'db').mkdir()
            maria=root/'const.py';maria.write_text('UNITID={126:"UNT_SAFETYWALL",127:"UNT_WRONG"}',encoding='utf-8')
            (root/'src/map/skill.h').write_text('enum { UNT_SAFETYWALL=0x7e, UNT_FIREWALL };')
            (root/'db/skill_unit_db.txt').write_text('12,0x7e,,0,0,0,0,0,MG_SAFE#name#\n18,0x7e,,0,0,0,0,0,MG_FIRE#name#\n19,0x7e,,0,0,0,0,0,WRONG#x#\n20,short\n')
            ids=root/'skillid.lua';ids.write_text('SKID={MG_SAFE=12,MG_FIRE=18}')
            names=root/'names.json';names.write_text(json.dumps(dict(version=1,skills={'12':'safe','18':'fire'})))
            document=build_catalog(maria,root,ids,names)
            self.assertEqual([row['id'] for row in document['units']['126']['skills']],[12,18])
            self.assertNotIn('127',document['units'])
            self.assertEqual(len(document['definition_conflicts']),1)
            self.assertEqual(len(document['unresolved_skill_links']),2)
            self.assertFalse(document['used_skill_inferred'])

    def test_catalog_validation_rejects_wrong_namespace_keys_and_duplicate_skill_links(self):
        original=load_unit_catalog()
        for defect in ('namespace','key','symbol','duplicate','name'):
            with self.subTest(defect=defect),tempfile.TemporaryDirectory() as folder:
                data=copy.deepcopy(original)
                if defect=='namespace':data['namespace']='skill_id'
                elif defect=='key':data['units']['0127']=data['units'].pop('127')
                elif defect=='symbol':data['units']['127']['symbol']='bad()'
                elif defect=='duplicate':data['units']['127']['skills']*=2
                else:data['units']['127']['skills'][0]['name']='x'*257
                path=Path(folder)/'catalog.json';path.write_text(json.dumps(data),encoding='utf-8')
                with self.assertRaises(ValueError):load_unit_catalog(path)

    def test_display_preserves_source_actor_unit_actor_type_and_unknown_values(self):
        profile=DisplayProfile.load();display=ReceiveDisplay(profile)
        packet=unit_appearance()
        before=packet.raw
        result=display.decode(packet)
        self.assertEqual(result.status,'decoded')
        self.assertEqual(result.fields['unit_actor_id'],4444)
        self.assertEqual(result.fields['actor_id'],42)
        self.assertEqual(result.fields['source_actor_id'],42)
        self.assertEqual(result.fields['unit_id'],127)
        self.assertEqual(result.fields['unit_skill_ids'],'18')
        self.assertEqual(result.fields['unit_mapping_basis'],'maria_auriga_agree')
        self.assertEqual(len(result.fields['unit_catalog_sha256']),64)
        self.assertIn('UNT_FIREWALL',result.text)
        self.assertIn('ファイアーウォール',result.text)
        self.assertEqual(packet.raw,before)
        for number in (264,265,0xffffffff):
            unknown=display.decode(unit_appearance(unit_type=number,level=255))
            self.assertEqual(unknown.status,'decoded')
            self.assertFalse(unknown.fields['unit_known'])
            self.assertEqual(unknown.fields['unit_id'],number)
            self.assertIn('未登録',unknown.text)
        with patch('pathlib.Path.read_bytes',side_effect=AssertionError('late catalog read')):
            self.assertEqual(display.decode(packet).text,result.text)
        self.assertNotEqual(profile.unit_catalog['namespace'],'skill_id')

    def test_invalid_packet_layout_does_not_guess_or_break_next_decode(self):
        display=ReceiveDisplay(DisplayProfile.load());packet=unit_appearance()
        for raw in (packet.raw[:-1],packet.raw+b'\0',packet.raw[:2]+b'\x16\0'+packet.raw[4:]):
            self.assertEqual(display.decode(replace(packet,raw=raw)).status,'error')
        self.assertEqual(display.decode(event(0xb5,(42).to_bytes(4,'little'))).text,'next;')
