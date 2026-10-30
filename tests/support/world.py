import struct
from events import PacketEvent

def packet(pid, body=b'', connection='flow-a', timestamp=1.0, direction='RECV'):
    return PacketEvent(timestamp, direction, pid, struct.pack('<H', pid) + body, 'NPCAP', connection)

def actor_packet(actor_id=42, actor_type=6, name='案内人', pid=0x9ff, connection='flow-a',
                 x=150, y=200, direction=3, destination=(300, 400), timestamp=1.0, raw_name=None):
    start = {0x9ff: 84, 0x9fe: 83, 0x9fd: 90}[pid]
    name_bytes = name.encode('cp932') if raw_name is None else raw_name
    raw = bytearray(start + len(name_bytes) + 1)
    struct.pack_into('<HHBI', raw, 0, pid, len(raw), actor_type, actor_id)
    struct.pack_into('<H', raw, 13, 150)
    struct.pack_into('<I', raw, 19, 0x12345678)
    struct.pack_into('<H', raw, 23, 1018 if actor_type == 5 else 45)
    if pid == 0x9fd:
        dx, dy = destination
        raw[67:73] = bytes([x >> 2, ((x & 3) << 6) | (y >> 4),
                           ((y & 15) << 4) | (dx >> 6), ((dx & 63) << 2) | (dy >> 8), dy & 255, 0])
    else:
        raw[63:66] = bytes([x >> 2, ((x & 3) << 6) | (y >> 4), ((y & 15) << 4) | direction])
    raw[start:] = name_bytes + b'\0'
    return PacketEvent(timestamp, 'RECV', pid, bytes(raw), 'NPCAP', connection)

def name_packet(actor_id=42, name='正式名', title='案内', connection='flow-a', timestamp=2.0, group_id=7):
    return packet(0xadf, struct.pack('<II', actor_id, group_id) + name.encode('cp932').ljust(24, b'\0')
                  + title.encode('cp932') + b'\0', connection, timestamp)

def map_packet(name='prontera.gat', connection='flow-a', timestamp=1.0):
    return packet(0x91, name.encode('cp932').ljust(16, b'\0') + struct.pack('<HH', 100, 120),
                  connection, timestamp)
