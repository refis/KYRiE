import sqlite3


class PacketDatabase:
    def __init__(self, path, *, wal=True):
        if type(wal) is not bool:
            raise ValueError('wal must be a boolean')
        self.db = sqlite3.connect(path)
        self.db.execute('''CREATE TABLE IF NOT EXISTS packets (
            id INTEGER PRIMARY KEY, timestamp REAL, direction TEXT,
            packet_id INTEGER, raw BLOB, source TEXT, connection TEXT)''')
        self.db.commit()
        self.wal_fallback = False
        try:
            if wal:
                try:
                    self.db.execute('PRAGMA journal_mode=WAL').fetchone()
                except sqlite3.OperationalError:
                    self.wal_fallback = True
            self.db.execute('PRAGMA synchronous=FULL')
            self.journal_mode = self.db.execute('PRAGMA journal_mode').fetchone()[0].lower()
            self.synchronous = self.db.execute('PRAGMA synchronous').fetchone()[0]
            self.wal_fallback |= wal and self.journal_mode not in ('wal','memory')
        except Exception:
            self.db.close()
            raise

    def add(self, event):
        try:
            self.db.execute('INSERT INTO packets(timestamp,direction,packet_id,raw,source,connection) VALUES(?,?,?,?,?,?)',
                            (event.timestamp, event.direction, event.packet_id, event.raw, event.source, event.connection))
            self.db.commit()
        except sqlite3.Error:
            try:
                self.db.rollback()
            except sqlite3.Error:
                pass  # Preserve the original failure; GUI marks the result as unconfirmed.
            raise

    def close(self):
        self.db.close()
