import copy
import json
from pathlib import Path
import tempfile
import unittest
from reconstruction.navigation import load_navigation,validate_navigation,navigation_map_names,lookup_map
from reconstruction.client_names import empty_client_names,map_label
from tools.build_navigation import build_catalog,write_catalog,FILES


class NavigationTests(unittest.TestCase):
    def test_real_catalog_keeps_namespaces_raw_columns_and_lookup_only(self):
        catalog=load_navigation();before=copy.deepcopy(catalog)
        self.assertEqual({key:len(rows) for key,rows in catalog['tables'].items()},
                         dict(maps=4449,npcs=11897,mobs=14483,links=7852,scrolls=1,picknpcs=289))
        self.assertTrue(navigation_map_names(catalog,'prontera.gat'))
        self.assertEqual(lookup_map('aB11@test.gat'),'1@test')
        self.assertEqual(lookup_map('aB1@test.gat'),'aB1@test')
        names=empty_client_names()
        self.assertTrue(map_label(names,'prontera.gat',catalog))
        names['tables']['maps']['prontera.rsw']='TXT優先'
        self.assertEqual(map_label(names,'prontera.gat',catalog),'TXT優先')
        self.assertEqual(catalog,before)
        self.assertEqual(catalog['tables']['mobs'][0][3],1967947)

    def test_literal_import_rejects_code_bad_columns_and_stale_inputs(self):
        literals={'maps':'{"test","Name",1,20,20}', 'npcs':'{"test",1,2,3,"N","n",4,5}',
                  'mobs':'{"test",1,2,1967947,"M","m",4,5}',
                  'links':'{"test",1,2,3,"","n",4,5,"target",6,7}',
                  'scrolls':'{"NULL",0,0,"NULL",0,0}',
                  'picknpcs':'{"test",1,2,3,4,5,6,7,8,9,10,11}'}
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for key,(file,symbol) in FILES.items():
                (root/f'navi_{file}_jp.lua').write_text(symbol+'={'+literals[key]+'}',encoding='ascii')
            document=build_catalog(root);destination=root/'catalog.json'
            write_catalog(document,destination);original=destination.read_bytes()
            source=root/'navi_map_jp.lua'
            with self.assertRaises(ValueError):write_catalog(document,source)
            source.write_text('Navi_Map={} os.execute("bad")',encoding='ascii')
            with self.assertRaises(ValueError):build_catalog(root)
            with self.assertRaises(ValueError):write_catalog(document,destination)
            self.assertEqual(destination.read_bytes(),original)
            bad=copy.deepcopy(document);bad['tables']['mobs'][0][3]=True
            with self.assertRaises(ValueError):validate_navigation(bad)
            bad=copy.deepcopy(document);bad['tables']['links'][0].pop()
            with self.assertRaises(ValueError):validate_navigation(bad)
            destination.write_text('{"version":1,"version":1}',encoding='ascii')
            with self.assertRaises(ValueError):load_navigation(destination)
