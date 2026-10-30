import copy
from dataclasses import replace
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
from parser.display import DisplayProfile,ReceiveDisplay
from reconstruction.reference_names import load_reference_names,reference_labels
from tools.build_reference_names import constants
from tests.support.display import event


class ReferenceNameTests(unittest.TestCase):
    def test_namespaces_do_not_convert_numeric_ids_or_claim_skill_use(self):
        catalog=load_reference_names()
        visual=reference_labels(catalog,'visual_effect',12)
        status=reference_labels(catalog,'status_icon',12)
        self.assertIn('EF_BEGINSPELL',visual['reference_symbols'])
        self.assertTrue(status['reference_symbols'].startswith('EFST_'))
        self.assertNotEqual(visual['reference_symbols'],status['reference_symbols'])
        self.assertEqual(len(catalog['identical_duplicates']),3)
        self.assertFalse(catalog['script_id_conversion'])
        self.assertFalse(reference_labels(catalog,'visual_effect',0xffffffff)['reference_known'])

    def test_constants_record_equal_duplicates_reject_conflicts_and_ignore_only_exact_guard(self):
        rows,duplicates,guard=constants(b'EFID={EF_A=12,EF_A=12,EF_B=12}','EFID','EF_')
        self.assertEqual(rows,{'12':['EF_A','EF_B']})
        self.assertEqual(len(duplicates),1)
        self.assertFalse(guard)
        raw=b'EFST_IDs={EFST_A=1,__newindex=function() error("unknown state") end}\nsetmetatable(EFST_IDs, EFST_IDs)'
        self.assertTrue(constants(raw,'EFST_IDs','EFST_')[2])
        for bad in (b'EFID={EF_A=1,EF_A=2}', b'EFID={EF_A=func()}',
                    b'EFID={EF_A=1} os.execute("bad")', b'EFID={EFST_A=1}',
                    raw.replace(b'unknown state',b'other function')):
            with self.subTest(raw=bad[:30]),self.assertRaises(ValueError):
                constants(bad,'EFST_IDs' if bad.startswith(b'EFST') else 'EFID',
                          'EFST_' if bad.startswith(b'EFST') else 'EF_')

    def test_loader_rejects_namespace_mixups_invalid_ids_and_duplicate_symbols(self):
        original=load_reference_names()
        for defect in ('namespace','id','symbol','duplicate'):
            with self.subTest(defect=defect),tempfile.TemporaryDirectory() as folder:
                data=copy.deepcopy(original)
                if defect=='namespace':data['catalogs']['skill_id']=data['catalogs'].pop('visual_effect')
                elif defect=='id':data['catalogs']['visual_effect']['012']=['EF_A']
                elif defect=='symbol':data['catalogs']['visual_effect']['12']=['EFST_A']
                else:data['catalogs']['visual_effect']['12']=['EF_A','EF_A']
                path=Path(folder)/'names.json';path.write_text(json.dumps(data),encoding='utf-8')
                with self.assertRaises(ValueError):load_reference_names(path)

    def test_all_supported_packets_preserve_actor_value_and_namespace(self):
        profile=DisplayProfile.load();display=ReceiveDisplay(profile)
        packets=[event(pid,struct.pack('<II',42,12)) for pid in (0x19b,0x1f3,0xb0d)]
        packets+=[event(0x284,struct.pack('<III',42,12,99)),
                  event(0x196,struct.pack('<HIB',12,42,1)),
                  event(0x43f,struct.pack('<HIBIIII',12,42,1,1000,10,20,30)),
                  event(0x983,struct.pack('<HIBIIIII',12,42,1,1000,1234,10,20,30))]
        for packet in packets:
            with self.subTest(pid=packet.packet_id):
                raw=packet.raw;result=display.decode(packet)
                self.assertEqual(result.status,'decoded')
                self.assertEqual(result.fields['effect_id'],12)
                self.assertEqual(result.fields['actor_id'],42)
                namespace='status_icon' if packet.packet_id in (0x196,0x43f,0x983) else 'visual_effect'
                self.assertEqual(result.fields['reference_namespace'],namespace)
                self.assertTrue(result.fields['reference_known'])
                self.assertEqual(len(result.fields['reference_catalog_sha256']),64)
                self.assertEqual(packet.raw,raw)
        with patch('pathlib.Path.read_bytes',side_effect=AssertionError('late reference read')):
            self.assertEqual(display.decode(packets[0]).status,'decoded')

    def test_unknown_and_invalid_layouts_do_not_guess_or_break_following_packets(self):
        display=ReceiveDisplay(DisplayProfile.load())
        packet=event(0x19b,struct.pack('<II',42,0xffffffff))
        result=display.decode(packet)
        self.assertEqual(result.status,'decoded')
        self.assertEqual(result.fields['effect_id'],0xffffffff)
        self.assertFalse(result.fields['reference_known'])
        for raw in (packet.raw[:-1],packet.raw+b'\0'):
            self.assertEqual(display.decode(replace(packet,raw=raw)).status,'error')
        self.assertEqual(display.decode(event(0xb5,struct.pack('<I',42))).text,'next;')
