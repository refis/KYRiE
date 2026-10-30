import struct
from events import PacketEvent

def attack(pid=0x8c8, actor=42, target=99, tick=1000, timestamp=1, damage=10,
           left=0, action=0, sp=0, divisions=1, connection='flow-a'):
    legacy, modern = pid == 0x8a, pid == 0x8c8
    offset = 26 if legacy else 29 if modern else 28
    raw = bytearray(29 if legacy else 34 if modern else 33)
    struct.pack_into('<HIIIii', raw, 0, pid, actor, target, tick, 120, 80)
    struct.pack_into('<h' if legacy else '<i', raw, 22, damage)
    struct.pack_into('<hB', raw, offset - 2, divisions, action)
    struct.pack_into('<h' if legacy else '<i', raw, offset + 1, left)
    if modern:
        raw[26] = sp
    return PacketEvent(timestamp, 'RECV', pid, bytes(raw), 'NPCAP', connection)
