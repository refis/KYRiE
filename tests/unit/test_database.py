from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from storage.database import PacketDatabase
from events import PacketEvent


class PacketDatabaseTests(unittest.TestCase):
    def test_wal_full_keeps_each_add_committed_visible_and_existing_schema(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'packets.sqlite3'
            db=PacketDatabase(path)
            self.assertEqual(db.journal_mode,'wal')
            self.assertEqual(db.synchronous,2)
            self.assertEqual([r[1] for r in db.db.execute('PRAGMA table_info(packets)')],
                ['id','timestamp','direction','packet_id','raw','source','connection'])
            try:
                with closing(sqlite3.connect(path)) as reader:
                    for index in range(3):
                        event=PacketEvent(index,'SEND' if index%2 else 'RECV',0x7f,b'\x7f\0abcd','TEST','flow')
                        db.add(event)
                        self.assertFalse(db.db.in_transaction)
                        self.assertEqual(reader.execute('SELECT COUNT(*) FROM packets').fetchone()[0],index+1)
                self.assertEqual(db.db.execute('SELECT raw,source,connection FROM packets ORDER BY id DESC LIMIT 1').fetchone(),
                    (b'\x7f\0abcd','TEST','flow'))
            finally:db.close()
            with closing(sqlite3.connect(path)) as reader:
                self.assertEqual(reader.execute('SELECT COUNT(*) FROM packets').fetchone()[0],3)

    def test_unavailable_wal_falls_back_without_losing_per_packet_commit(self):
        connect=sqlite3.connect
        class NoWal(sqlite3.Connection):
            def execute(self,sql,*args,**kwargs):
                if sql=='PRAGMA journal_mode=WAL':raise sqlite3.OperationalError('WAL unavailable')
                return super().execute(sql,*args,**kwargs)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'fallback.sqlite3'
            with patch('storage.database.sqlite3.connect',side_effect=lambda *args,**kwargs:connect(*args,factory=NoWal,**kwargs)):
                db=PacketDatabase(path)
            try:
                self.assertEqual(db.journal_mode,'delete')
                self.assertTrue(db.wal_fallback)
                self.assertEqual(db.synchronous,2)
                db.add(PacketEvent(1,'RECV',0x7f,b'\x7f\0abcd','TEST','flow'))
                with closing(connect(path)) as reader:
                    self.assertEqual(reader.execute('SELECT COUNT(*) FROM packets').fetchone()[0],1)
            finally:db.close()
        memory=PacketDatabase(':memory:')
        self.assertEqual(memory.journal_mode,'memory')
        self.assertFalse(memory.wal_fallback)
        memory.close()

    def test_commit_failure_rolls_back_only_pending_packet(self):
        connect=sqlite3.connect
        class FailingCommit(sqlite3.Connection):
            fail=False
            def commit(self):
                if self.fail:raise sqlite3.OperationalError('commit failed')
                return super().commit()
        with patch('storage.database.sqlite3.connect',side_effect=lambda *a,**k:connect(*a,factory=FailingCommit,**k)):
            db=PacketDatabase(':memory:')
        try:
            event=PacketEvent(1,'RECV',127,b'\x7f\0packet','TEST','flow')
            db.add(event)
            db.db.fail=True
            with self.assertRaisesRegex(sqlite3.OperationalError,'commit failed'):db.add(event)
            self.assertFalse(db.db.in_transaction)
            self.assertEqual(db.db.execute('SELECT COUNT(*) FROM packets').fetchone()[0],1)
        finally:db.close()
