"""Transport-independent packet contract shared by capture, IPC and storage."""
from dataclasses import dataclass


@dataclass(frozen=True)
class PacketEvent:
    timestamp: float
    direction: str
    packet_id: int
    raw: bytes
    source: str
    connection: str
    flow_id: str = ''

    def __post_init__(self):
        if self.direction not in ('SEND', 'RECV'):
            raise ValueError('Invalid packet direction')
        if not isinstance(self.raw, bytes) or len(self.raw) < 2:
            raise ValueError('Packet must contain an immutable ID header')
        if int.from_bytes(self.raw[:2], 'little') != self.packet_id:
            raise ValueError('Packet ID does not match raw header')
