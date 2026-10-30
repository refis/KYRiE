# Passive in-order TCP payload delivery with retransmission/overlap suppression.
# Does not guess across gaps; holds out-of-order segments until contiguous.
# Initial sequence is assumed to be a stream boundary only if SYN is observed.

class TCPReassembler:
    def __init__(self, max_pending=2 * 1024 * 1024):
        self.next_seq = None
        self.pending = {}
        self.max_pending = max_pending
        self.failed = False

    def feed(self, seq, payload, syn=False):
        if self.failed:
            return []
        seq = (int(seq) + int(bool(syn))) & 0xffffffff
        if self.next_seq is None:
            if not syn:
                # Midstream capture is not guaranteed to start at a message boundary.
                return []
            self.next_seq = seq
        if not payload:
            return []
        # Unwrap into the epoch nearest the contiguous stream position.
        seq = self.next_seq + ((seq - self.next_seq + 0x80000000) % 0x100000000 - 0x80000000)
        end = seq + len(payload)
        if end <= self.next_seq:
            return []
        if seq < self.next_seq:
            payload = payload[self.next_seq - seq:]
            seq = self.next_seq
        # Conflicting buffered overlaps make the stream ambiguous: fail closed.
        for start, data in self.pending.items():
            left, right = max(start, seq), min(start + len(data), end)
            if left < right and data[left-start:right-start] != payload[left-seq:right-seq]:
                self.failed = True
                self.pending.clear()
                return []
        if seq in self.pending:
            if len(payload) > len(self.pending[seq]):
                self.pending[seq] = payload
        else:
            self.pending[seq] = payload
        if sum(map(len, self.pending.values())) > self.max_pending:
            self.failed = True
            self.pending.clear()
            return []
        chunks = []
        while True:
            candidates = [s for s in self.pending if s <= self.next_seq]
            if not candidates:
                break
            s = min(candidates)
            data = self.pending.pop(s)
            offset = self.next_seq - s
            if offset >= len(data):
                continue
            chunk = data[offset:]
            chunks.append(chunk)
            self.next_seq += len(chunk)
        return chunks

    def start_at(self, seq):
        """Explicit opt-in boundary assumption for attaching an existing socket."""
        if self.next_seq is not None or self.failed:
            raise ValueError('Cannot restart an initialized or failed TCP stream')
        self.next_seq = int(seq) & 0xffffffff
