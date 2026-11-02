import struct
from reconstruction.dialogue import DialogueStore
from tests.support.dialogue import packet

def conversation(choice=1, answer='one result', identifier=1, actor=42, nested=False, input_prompt=False):
    store = DialogueStore()
    def add(pid, data=b'', direction='RECV'):
        store.apply(packet(pid, data, direction))
    add(0x90, struct.pack('<IB', actor, 1), 'SEND')
    add(0xb4, struct.pack('<I', actor) + b'hello\0')
    add(0xb7, struct.pack('<I', actor) + b'one:two:three:\0')
    add(0xb8, struct.pack('<IB', actor, choice), 'SEND')
    if nested:
        add(0xb7, struct.pack('<I', actor) + b'inner one:inner two:\0')
        add(0xb8, struct.pack('<IB', actor, 2), 'SEND')
    if input_prompt:
        add(0x142, struct.pack('<I', actor))
        add(0x143, struct.pack('<Ii', actor, choice), 'SEND')
    add(0xb4, struct.pack('<I', actor) + answer.encode('cp932') + b'\0')
    add(0xb6, struct.pack('<I', actor))
    result = store.sessions[0]
    result.id = identifier
    result.npc = dict(NPC)
    return result

NPC = dict(name='案内人', map_name='test.gat', class_id=45, x=10, y=20, direction=0,
           connection='half', map_generation=0, appearance=1, actor_id=42)
