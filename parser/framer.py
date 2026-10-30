import struct
from collections import deque


class FramingError(Exception):
    def __init__(self, message, completed_packets=()):
        super().__init__(message)
        self.completed_packets = list(completed_packets)


class PacketFramer:
    def __init__(self, definitions, max_buffer=2 * 1024 * 1024):
        self.definitions = definitions
        self.buffer = bytearray()
        self.max_buffer = max_buffer
        self.failed = False
        self.offset = 0
        self.received_bytes = 0
        self.history = deque(maxlen=16)

    def snapshot(self):
        return dict(stream_offset=self.offset, received_bytes=self.received_bytes,
                    buffered_bytes=len(self.buffer), previous_packets=list(self.history),
                    next_packet_id=(struct.unpack_from('<H', self.buffer)[0] if len(self.buffer) >= 2 else None))

    def feed(self, data):
        if self.failed:
            raise FramingError('Stream framing already failed; reset connection')
        self.buffer.extend(data)
        self.received_bytes += len(data)
        if len(self.buffer) > self.max_buffer:
            self.failed = True
            raise FramingError('Framing buffer limit exceeded')
        packets = []
        while len(self.buffer) >= 2:
            pid = struct.unpack_from('<H', self.buffer)[0]
            size = self.definitions.get(pid)
            if size is None:
                self.failed = True
                raise FramingError(f'Unknown PacketID 0x{pid:04X}; remaining={len(self.buffer)} bytes', packets)
            if size == -1:
                if len(self.buffer) < 4:
                    break
                size = struct.unpack_from('<H', self.buffer, 2)[0]
                if size < 4:
                    self.failed = True
                    raise FramingError(f'Invalid variable length {size} for 0x{pid:04X}', packets)
            if len(self.buffer) < size:
                break
            packets.append((pid, bytes(self.buffer[:size])))
            self.history.append(dict(packet_id=pid, offset=self.offset, definition_length=self.definitions[pid],
                                     applied_length=size))
            self.offset += size
            del self.buffer[:size]
        return packets
