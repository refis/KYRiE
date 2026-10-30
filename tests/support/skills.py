from dataclasses import replace
import struct
from events import PacketEvent
from tests.support.world import actor_packet

def mob(actor=42, class_id=1005, timestamp=0, connection='flow-a'):
    event = actor_packet(actor_id=actor, actor_type=5, timestamp=timestamp, connection=connection)
    raw = bytearray(event.raw)
    struct.pack_into('<H', raw, 23, class_id)
    return replace(event, raw=bytes(raw))

def damage(actor=42, skill=177, tick=1000, timestamp=1, target=99, level=65535, value=50, connection='flow-a'):
    raw = bytearray(33)
    struct.pack_into('<HHII', raw, 0, 0x1de, skill, actor, target)
    struct.pack_into('<IiiiHhB', raw, 12, tick, 100, 200, value, level, 1, 8)
    return PacketEvent(timestamp, 'RECV', 0x1de, bytes(raw), 'NPCAP', connection)

def cast(actor=42, skill=177, timestamp=0.5, duration=500, target=99, pid=0x13e):
    raw = bytearray(24 if pid == 0x13e else 25)
    struct.pack_into('<HIIHHH', raw, 0, pid, actor, target, 10, 20, skill)
    struct.pack_into('<I', raw, 20, duration)
    return PacketEvent(timestamp, 'RECV', pid, bytes(raw), 'NPCAP', 'flow-a')


def unit_appearance(unit_type=127,source_actor=42,unit_actor=4444,level=7):
    raw=struct.pack('<HHIIHHIBBB',0x9ca,23,unit_actor,source_actor,100,200,unit_type,0,1,level)
    return PacketEvent(1.25,'RECV',0x9ca,raw,'NPCAP','flow-a')
