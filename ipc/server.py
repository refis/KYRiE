"""Opt-in local pipe endpoint; all callbacks run in the GUI thread."""
from PySide6.QtNetwork import QLocalServer
from ipc.protocol import Decoder


class PipeServer:
    def __init__(self, name, definitions, on_packet, on_status):
        self.server = QLocalServer()
        self.server.setSocketOptions(QLocalServer.UserAccessOption)
        self.server.setMaxPendingConnections(1)
        self.name = name
        self.definitions = definitions
        self.on_packet = on_packet
        self.on_status = on_status
        self.clients = {}
        self.server.newConnection.connect(self._accept)

    def start(self):
        if not self.server.listen(self.name):
            raise RuntimeError(self.server.errorString())

    def _accept(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            if self.clients:
                socket.abort()
                socket.deleteLater()
                continue
            socket.setReadBufferSize(128 * 1024)
            self.clients[socket] = Decoder(self.definitions)
            socket.readyRead.connect(lambda s=socket: self._read(s))
            socket.disconnected.connect(lambda s=socket: self._disconnect(s))

    def _read(self, socket):
        try:
            while socket.bytesAvailable():
                for event in self.clients[socket].feed(bytes(socket.read(65536))):
                    self.on_packet(event)
        except Exception as exc:
            self.on_status(f'Pipe stream stopped: {exc}')
            socket.abort()

    def _disconnect(self, socket):
        decoder = self.clients.pop(socket, None)
        if decoder and decoder.buffer:
            self.on_status('Pipe disconnected with an incomplete record')
        socket.deleteLater()

    def stop(self):
        self.server.close()
        for socket in list(self.clients):
            socket.abort()
        self.clients.clear()
