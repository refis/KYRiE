import struct
from events import PacketEvent
from reconstruction.player import LIST_STRIDES

def packet(pid, body=b'', flow='game', direction='RECV'):
    raw = struct.pack('<H', pid)
    if pid in (*LIST_STRIDES, 0xb08, 0x99d, 0xb72):
        raw += struct.pack('<H', len(body) + 4)
    return PacketEvent(1, direction, pid, raw + body, 'NPCAP', flow, flow)


def character_list(pid=0xb72, character=123, name='hero', zeny=1000, base_exp=2**40, job_exp=2**41):
    stride, name_offset, slot_offset = (175, 108, 138) if pid == 0xb72 else (155, 88, 118)
    body = bytearray(stride)
    struct.pack_into('<IQIQ', body, 0, character, base_exp, zeny, job_exp)
    body[name_offset:name_offset + 24] = name.encode('cp932').ljust(24, b'\0')
    struct.pack_into('<H', body, slot_offset, 0)
    return packet(pid, bytes(body), flow='char')

def listing(pid=0xb09, items=((2, 501, 10),), inventory_type=0, item_type=0):
    body = bytearray([inventory_type])
    for index, item_id, amount in items:
        record = bytearray(LIST_STRIDES[pid])
        struct.pack_into('<HI', record, 0, index, item_id)
        record[6] = item_type
        if pid in (0xb09, 0xb38):
            struct.pack_into('<H', record, 7, amount)
        body += record
    return packet(pid, body)

def pickup(pid=0xb41, index=2, item_id=501, amount=3, result=0):
    raw = bytearray(70 if pid == 0xb41 else 69)
    struct.pack_into('<HHHI', raw, 0, pid, index, amount, item_id)
    raw[10] = 1
    raw[33 if pid == 0xb41 else 34] = result
    return PacketEvent(1, 'RECV', pid, bytes(raw), 'NPCAP', 'game', 'game')
