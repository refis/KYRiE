"""GPA1 stream: magic, body length, timestamp(us), connection ID, raw packet."""
import struct
from events import PacketEvent
from parser.framer import PacketFramer

HEADER = struct.Struct('<4sIQI')
MAX_PACKET = 65535


def encode(event, connection_id):
    if event.direction != 'SEND' or event.source != 'HOOK':
        raise ValueError('IPC accepts plaintext HOOK SEND events only')
    if not 2 <= len(event.raw) <= MAX_PACKET:
        raise ValueError('Invalid packet size')
    return HEADER.pack(b'GPA1', len(event.raw), round(event.timestamp * 1000000), connection_id) + event.raw


class Decoder:
    def __init__(self, definitions):
        self.definitions = definitions
        self.buffer = bytearray()
        self.failed = False

    def feed(self, data):
        if self.failed:
            raise ValueError('IPC decoder failed; reconnect required')
        events = []
        try:
            # Accept arbitrary transport fragmentation without unbounded accumulation.
            for offset in range(0, len(data), 4096):
                self.buffer.extend(data[offset:offset + 4096])
                while len(self.buffer) >= HEADER.size:
                    magic, length, micros, connection_id = HEADER.unpack_from(self.buffer)
                    if magic != b'GPA1' or not 2 <= length <= MAX_PACKET:
                        raise ValueError('Invalid IPC header')
                    end = HEADER.size + length
                    if len(self.buffer) < end:
                        break
                    raw = bytes(self.buffer[HEADER.size:end])
                    framer = PacketFramer(self.definitions)
                    packets = framer.feed(raw)
                    if len(packets) != 1 or framer.buffer:
                        raise ValueError('IPC record must contain exactly one complete game packet')
                    events.append(PacketEvent(micros / 1000000, 'SEND', packets[0][0], raw,
                                              'HOOK', f'hook:{connection_id}'))
                    del self.buffer[:end]
        except Exception:
            self.failed = True
            self.buffer.clear()
            raise
        return events
