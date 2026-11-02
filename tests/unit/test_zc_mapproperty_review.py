"""PACKET_ZC_MAPPROPERTY symbols and map_property manual-review memos."""
import json
import struct
import tempfile
import unittest
from pathlib import Path

from reconstruction.dialogue import DialogueStore, decode_dialogue
from reconstruction.zc_mapproperty import (
    build_map_property_manual_review, build_zc_symbols, decode_zc_mapproperty_table,
    flags_manual_review, parse_zc_mapproperty_document, reset_catalog_caches,
    summarize_review_rows,
)
from tests.support.dialogue import packet

SAMPLE = """
struct PACKET_ZC_MAPPROPERTY {
	/* this+0x0 */ short PacketType
	/* this+0x2 */ unsigned short PacketLength
	/* this+0x4 */ short type {
		MAPTYPE_VILLAGE = 0x0,					//E7 02 21 00 00 00 00 01 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 10 00
		MAPTYPE_VILLAGE_IN = 0x1,				//E7 02 21 00 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 10 00
		// moonfild.gat
		MAPTYPE_UNUSED = 0x1D,					//
		MAPTYPE_LAST = 0x1E,
	}
	/* this+0x6 */ char mapInfoTable[...] {
		MAPPROPERTY_PK = 0x0,
		MAPPROPERTY_TELEPORT = 0x1,
		MAPPROPERTY_PKSERVER = 0xA,
		MAPPROPERTY_SHOW_HP_BAR = 0x19,
		MAPPROPERTY_LAST = 0x1B;
	}
}
"""


class ZcMapPropertyReviewTests(unittest.TestCase):
    def setUp(self):
        reset_catalog_caches()

    def tearDown(self):
        reset_catalog_caches()

    def test_parse_symbols_and_prior_map_notes(self):
        parsed = parse_zc_mapproperty_document(SAMPLE)
        self.assertEqual(parsed['maptypes']['0']['symbol'], 'MAPTYPE_VILLAGE')
        self.assertEqual(parsed['maptypes']['29']['map_name_notes'], ['moonfild.gat'])
        self.assertEqual(parsed['maptype_last'], 0x1E)
        self.assertEqual(parsed['properties']['10']['symbol'], 'MAPPROPERTY_PKSERVER')
        self.assertIn('0', parsed['samples'])
        table = decode_zc_mapproperty_table(
            bytes.fromhex(parsed['samples']['0']['packet_hex']),
            dict(properties=parsed['properties']))
        self.assertEqual(table['type_id'], 0)
        self.assertEqual(table['nonzero_properties'][0]['symbol'], 'MAPPROPERTY_TELEPORT')

    def test_out_of_catalog_memo_includes_map_and_type(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'PACKET_ZC_MAPPROPERTY.txt'
            path.write_text(SAMPLE, encoding='cp932')
            symbols = build_zc_symbols(path)
        review = build_map_property_manual_review(
            {'kind': 50, 'flags': 0x400}, 'paramk_.gat',
            zc_symbols=symbols, maptype_catalog={'types': {'0': {'label': 'Town'}}})
        self.assertTrue(review['out_of_catalog'])
        self.assertEqual(review['map_name'], 'paramk_.gat')
        self.assertEqual(review['type_id'], 50)
        self.assertIn('OUT_OF_MAPTYPE_CATALOG', review['memo'])
        self.assertEqual(review['flags']['hex'], '0x00000400')
        self.assertEqual(review['flags']['bits_set'], [10])
        self.assertEqual(review['flags']['property_bit_guesses'][0]['symbol'], 'MAPPROPERTY_PKSERVER')
        self.assertFalse(review['flags']['layout_confirmed'])

    def test_dialogue_store_attaches_manual_review(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'PACKET_ZC_MAPPROPERTY.txt'
            path.write_text(SAMPLE, encoding='cp932')
            symbols = build_zc_symbols(path)
            catalog_path = Path(folder) / 'catalog.json'
            catalog_path.write_text(json.dumps({
                'types': {'1': {'label': 'Indoor', 'properties': {'TELEPORT': False}}}
            }), encoding='utf-8')
            # Point default loaders via monkeypatch of module caches
            import reconstruction.zc_mapproperty as mod
            mod._ZC_CACHE = symbols
            mod._MAPTYPE_CACHE = json.loads(catalog_path.read_text(encoding='utf-8'))
            store = DialogueStore()
            store.apply(packet(0x99b, struct.pack('<HI', 50, 0x400)))
            store.apply(packet(0x1d6, struct.pack('<H', 1)))
            rows = store.presentation_observations
            self.assertEqual(len(rows), 2)
            self.assertTrue(rows[0]['manual_review']['out_of_catalog'])
            self.assertEqual(rows[0]['manual_review']['type_id'], 50)
            self.assertIn('flags=', rows[0]['manual_review']['flags']['memo'])
            self.assertFalse(rows[1]['manual_review']['out_of_catalog'])
            self.assertEqual(rows[1]['manual_review']['type_catalog_label'], 'Indoor')
            summary = summarize_review_rows(rows)
            self.assertEqual(summary['out_of_catalog_count'], 1)
            self.assertEqual(summary['flag_memos'][0]['flags_hex'], '0x00000400')
            raw = bytes.fromhex(symbols['samples']['0']['packet_hex'])
            event = packet(0x2e7, raw[2:])
            self.assertEqual(event.packet_id, 0x2e7)
            kind, actor, fields = decode_dialogue(event)
            self.assertEqual(kind, 'map_property')
            self.assertIsNone(actor)
            self.assertEqual(fields['kind'], 0)
            self.assertEqual(fields['layout'], 'zc_mapproperty_table')
            self.assertEqual(fields['nonzero_properties'][0]['symbol'], 'MAPPROPERTY_TELEPORT')


if __name__ == '__main__':
    unittest.main()
