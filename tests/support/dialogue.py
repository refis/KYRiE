import struct
from events import PacketEvent

def packet(pid, data=b'', direction='RECV', flow='flow', timestamp=1, connection='half'):
    raw = struct.pack('<H', pid)
    if pid in (0xb4, 0xb7, 0x972, 0x1d5):
        raw += struct.pack('<H', len(data) + 4)
    return PacketEvent(timestamp, direction, pid, raw + data, 'NPCAP', connection, flow)


def music_event(name='theme.mp3', mode=None):
    encoded = name.encode('cp932')
    if mode is None:
        return packet(0x7fe, encoded.ljust(24, b'\0'))
    body = bytes([mode]) + encoded + b'\0'
    return packet(0xb8c, struct.pack('<H', len(body) + 4) + body)


def viewpoint_event(actor=42, kind=1, x=100, y=200, marker=7, color=0xff123456):
    return packet(0x144, struct.pack('<IIIIBI', actor, kind, x, y, marker, color))


def overhead_event(actor=42, text='頭上メッセージ'):
    body = struct.pack('<I', actor) + text.encode('cp932') + b'\0'
    return packet(0x8b3, struct.pack('<H', len(body) + 4) + body)


def layout_conversation(width=280, alignment=1, identifier=1):
    """Placed complete dialogue with each layout command, for export contracts."""
    from copy import deepcopy
    from reconstruction.dialogue import DialogueStore
    from tests.support.branches import NPC
    store=DialogueStore()
    for event in (packet(0x90,struct.pack('<IB',42,1),'SEND'),
                  packet(0xb4,struct.pack('<I',42)+b'hello\0'),
                  packet(0xba2,struct.pack('<II',180,width)),
                  packet(0xba3,struct.pack('<II',10,20)),packet(0xba1,bytes([alignment])),
                  packet(0xb6,struct.pack('<I',42)),packet(0x146,struct.pack('<I',42),'SEND')):
        store.apply(event)
    item=store.sessions[0]
    item.npc=deepcopy(NPC)
    item.id=identifier
    return item
