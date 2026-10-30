import copy
import json
from pathlib import Path
import tempfile
import unittest
from reconstruction.client_names import load_client_names,item_name,map_label,quest_label,quest_reference
from tools.build_client_names import pairs,quests


class ClientNameTests(unittest.TestCase):
    def test_names_are_lookup_only_and_instance_lookup_does_not_replace_raw_map(self):
        catalog=load_client_names()
        self.assertNotIn('item_unidentified',catalog['tables'])
        self.assertEqual(item_name(catalog,501),'赤ポーション')
        self.assertTrue(map_label(catalog,'prontera.gat'))
        self.assertEqual(map_label(catalog,'prontera.rsw'),map_label(catalog,'prontera.gat'))
        copied=copy.deepcopy(catalog)
        copied['tables']['maps']['1@test.rsw']='参考MAP'
        raw='aB11@test.gat'
        self.assertEqual(map_label(copied,raw),'参考MAP')
        self.assertEqual(raw,'aB11@test.gat')
        self.assertEqual(map_label(copied,'aB1@test.gat'),'')
        self.assertEqual(item_name(catalog,0xffffffff),'未登録')
        self.assertEqual(quest_reference(catalog,0xffffffff),'ID=4294967295')

    def test_quest_duplicates_retain_distinct_candidates_and_not_execution_conditions(self):
        catalog=load_client_names()
        self.assertIn('運命のカラス',quest_label(catalog,2063))
        label=quest_label(catalog,12059)
        self.assertIn('名称候補',label)
        self.assertIn('時間移動の影響',label)
        self.assertIn('オークの記憶入場時間制限',label)
        data=b'1#A#ICON#IMAGE#body#objective#\n1#B#ICON#IMAGE#body#objective#'
        names,duplicates=quests(data)
        self.assertEqual(names,{'1':['A','B']})
        self.assertEqual(len(duplicates),1)
        for bad in (data+b'extra',b'1#truncated#',b'x#A#I#I#body#objective#'):
            with self.assertRaises(ValueError):quests(bad)

    def test_pair_records_keep_empty_name_evidence_and_reject_duplicates(self):
        rows,empty=pairs('1#全角　空白#\n2##'.encode('cp932'))
        self.assertEqual(rows,{'1':'全角　空白'})
        self.assertEqual(empty,[{'key':'2','line':2}])
        for bad in (b'1#A#\n1#B#',b'01#A#',b'1#truncated'):
            with self.assertRaises(ValueError):pairs(bad)

    def test_catalog_validation_checks_ids_labels_and_namespace_without_guessing(self):
        original=load_client_names()
        for defect in ('key','control','namespace','duplicate_quest'):
            with self.subTest(defect=defect),tempfile.TemporaryDirectory() as folder:
                document=copy.deepcopy(original)
                if defect=='key':document['tables']['item_identified']['01']='bad'
                elif defect=='control':document['tables']['item_identified']['501']='bad\nname'
                elif defect=='namespace':document['tables']['npc_names']={}
                else:document['tables']['quests']['2063']=['same','same']
                path=Path(folder)/'names.json';path.write_text(json.dumps(document,ensure_ascii=False),encoding='utf-8')
                with self.assertRaises(ValueError):load_client_names(path)
