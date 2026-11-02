"""MapTypeProperty parsing and comment-only mapflag suggestions."""
import json
import tempfile
import unittest
from pathlib import Path

from reconstruction.maptype_property import (
    build_catalog, format_mapflag_comments, parse_maptype_property,
    suggest_mapflag_comments,
)


SAMPLE = """
//------------------------------------------------------------//
// [ Notes ]
//	1. A property that is not set is FALSE.
//------------------------------------------------------------//
MAPTYPE 0  // Town
{
	ADD_PROPERTY(TELEPORT, TRUE);
	ADD_PROPERTY(NOTREMEMBER, TRUE);
	ADD_PROPERTY(CALLMONSTER, FALSE);
	ADD_BLOCK_ITEM("Greed_Scroll");
	ADD_BLOCK_SKILL(SC_MANHOLE,PLAYER);
}
MAPTYPE 10 // Dungeon - no teleport
{
	ADD_PROPERTY(EXP, TRUE);
	ADD_PROPERTY(CALLMONSTER, TRUE);
	ADD_BLOCK_ITEM("N_Fly_Wing");
}
MAPTYPE 19 // Battleground
{
	ADD_PROPERTY (BATTLEFIELD, TRUE);
	ADD_PROPERTY(SIEGE, TRUE);
}
"""


class MapTypePropertyCatalogTests(unittest.TestCase):
    def test_parse_defaults_and_battlefield_spacing(self):
        parsed = parse_maptype_property(SAMPLE)
        self.assertEqual(set(parsed['types']), {'0', '10', '19'})
        self.assertEqual(parsed['types']['0']['label'], 'Town')
        self.assertTrue(parsed['types']['0']['properties']['TELEPORT'])
        self.assertFalse(parsed['types']['0']['properties']['CALLMONSTER'])
        self.assertEqual(parsed['types']['0']['block_items'], ['Greed_Scroll'])
        self.assertTrue(parsed['types']['19']['properties']['BATTLEFIELD'])
        self.assertEqual(parsed['parse_issues'], [])

    def test_mapflag_comments_require_catalog_type_and_stay_comments(self):
        parsed = parse_maptype_property(SAMPLE)
        comments = format_mapflag_comments(
            'icas_in.gat', 10, parsed['types']['10'], source_sha256='abc123def4567890')
        text = '\n'.join(comments)
        self.assertTrue(all(line.startswith('//') for line in comments))
        self.assertIn('noteleport', text)  # TELEPORT unset → FALSE
        self.assertNotIn('nobranch', text)  # CALLMONSTER TRUE → no nobranch
        self.assertNotIn('executable', text.lower())

        town = format_mapflag_comments(
            'prontera.gat', 0, parsed['types']['0'], source_sha256='abc123def4567890')
        town_text = '\n'.join(town)
        self.assertIn('nobranch', town_text)
        self.assertNotIn('noteleport', town_text)

    def test_unknown_wire_kind_is_unresolved(self):
        catalog = dict(types={}, sources=[dict(sha256='0' * 64)])
        result = suggest_mapflag_comments(catalog, 'paramk_.gat', 50)
        self.assertFalse(result['ok'])
        self.assertEqual(result['reason'], 'type_not_in_maptype_property_catalog')
        self.assertTrue(result['comments'][0].startswith('//'))

    def test_build_catalog_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'MapTypeProperty.txt'
            path.write_text(SAMPLE, encoding='utf-8')
            catalog = build_catalog(path)
            self.assertEqual(catalog['version'], 1)
            self.assertFalse(catalog['executable_mapflags'])
            self.assertEqual(catalog['map_name_binding'], 'not_in_file')
            self.assertEqual(catalog['type_count'], 3)
            suggestion = suggest_mapflag_comments(catalog, 'bat_c01.gat', 19)
            self.assertTrue(suggestion['ok'])
            joined = '\n'.join(suggestion['comments'])
            self.assertIn('battleground', joined)
            self.assertIn('gvg', joined)


if __name__ == '__main__':
    unittest.main()
