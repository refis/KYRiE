import time
import unittest
import uuid
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtNetwork import QLocalSocket
from ipc.server import PipeServer
from ipc.protocol import encode
from events import PacketEvent


class PipeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_until(self, predicate):
        deadline = time.monotonic() + 3
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.001)
        self.assertTrue(predicate())

    def test_local_pipe_reconnect_and_fragmented_delivery(self):
        events, status = [], []
        server = PipeServer('gpa-test-' + uuid.uuid4().hex, {0x90: 4}, events.append, status.append)
        server.start()
        client = QLocalSocket()
        event = PacketEvent(1, 'SEND', 0x90, b'\x90\x00ab', 'HOOK', 'hook:1')
        wire = encode(event, 1)
        try:
            client.connectToServer(server.name)
            self.wait_until(lambda: bool(server.clients))
            client.write(wire[:3])
            client.flush()
            self.wait_until(lambda: any(d.buffer for d in server.clients.values()))
            client.abort()
            self.wait_until(lambda: not server.clients)
            self.assertTrue(status)
            client.connectToServer(server.name)
            self.wait_until(lambda: bool(server.clients))
            # More than one read buffer worth of records must fully drain.
            client.write(wire * 6000)
            client.flush()
            self.wait_until(lambda: len(events) == 6000)
            self.assertEqual(events[0], event)
        finally:
            client.abort()
            server.stop()
            client.deleteLater()
            server.server.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            self.app.processEvents()
