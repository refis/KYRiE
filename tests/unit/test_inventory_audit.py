from dataclasses import replace
import unittest
from tests.support.player import listing,packet
from tools.audit_inventory import InventoryLayoutAudit


class InventoryAuditTests(unittest.TestCase):
    def test_unknown_flags_remain_unknown_and_evidence_retains_source_bytes(self):
        audit=InventoryLayoutAudit();event=listing(0xb38)
        raw=bytearray(event.raw);raw[-1]=5;event=replace(event,raw=bytes(raw))
        audit.observe(event,7)
        audit.observe(replace(event,direction='SEND'),8)
        row=audit.snapshot()['layouts']['0x0B38']
        self.assertEqual(row['packets'],1)
        sample=row['samples'][0]
        self.assertEqual(sample['packet_index'],7)
        self.assertEqual(sample['identification_layout'],'unconfirmed')
        self.assertIsNone(sample['rows'][0]['identified'])
        self.assertIsNone(sample['rows'][0]['inventory_flags'])
        self.assertEqual(sample['rows'][0]['raw_hex'],event.raw[5:].hex())
        sample['rows'].clear()
        self.assertTrue(audit.snapshot()['layouts']['0x0B38']['samples'][0]['rows'])

    def test_sample_and_row_limits_keep_counts_and_malformed_inventory_is_separate(self):
        audit=InventoryLayoutAudit()
        event=listing(0xb39,items=tuple((i,501,1) for i in range(1,13)))
        for i in range(35):audit.observe(event,i)
        row=audit.snapshot()['layouts']['0x0B39']
        self.assertEqual((row['packets'],row['entries'],len(row['samples']),row['samples_omitted']),(35,420,32,3))
        self.assertEqual(len(row['samples'][0]['rows']),8)
        self.assertEqual(row['samples'][0]['rows_omitted'],4)
        audit.observe(listing(0xb38,inventory_type=1),36)
        audit.observe(packet(0xb38,b'\0x'),37)
        row=audit.snapshot()['layouts']['0x0B38']
        self.assertEqual((row['valid_packets'],row['other_inventory_packets'],row['invalid_packets']),(0,1,1))
        self.assertEqual(row['samples'][-1]['status'],'invalid')
