import struct
from events import PacketEvent

def event(pid, body=b'', connection='server-a', direction='RECV'):
    return PacketEvent(1.25, direction, pid, struct.pack('<H', pid) + body,
                       'NPCAP' if direction == 'RECV' else 'HOOK', connection)

def variable(pid, body, connection='server-a'):
    return event(pid, struct.pack('<H', len(body) + 4) + body, connection)
