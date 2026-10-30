"""Thread-safe admission accounting for packets queued to the GUI."""
from dataclasses import dataclass
from threading import Lock
from PySide6.QtCore import QObject, Signal


@dataclass(frozen=True)
class PacketDelivery:
    session: int
    event: object


class Bridge(QObject):
    packet = Signal(object)
    status = Signal(str)
    connections = Signal(object)
    overflow = Signal()

    def __init__(self,parent=None,*,max_pending=4096,max_pending_bytes=16*1024*1024):
        if type(max_pending) is not int or max_pending<1 or type(max_pending_bytes) is not int or max_pending_bytes<1:
            raise ValueError('Delivery limits must be positive integers')
        super().__init__(parent)
        self.max_pending=max_pending
        self.max_pending_bytes=max_pending_bytes
        self._pending_bytes=0
        self._rejected=0
        self._overflowed=False
        self._sealed=False
        self._shutdown_rejected=0
        self._lock=Lock()
        self._published,self._accepted=0,0

    def publish(self,session,event):
        notify=False
        size=len(event.raw)
        with self._lock:
            self._published+=1
            pending=self._published-self._accepted-self._rejected
            if self._sealed:
                self._rejected+=1
                self._shutdown_rejected+=1
                admitted=False
            elif self._overflowed or pending>self.max_pending or self._pending_bytes+size>self.max_pending_bytes:
                self._rejected+=1
                notify=not self._overflowed
                self._overflowed=True
                admitted=False
            else:
                self._pending_bytes+=size
                admitted=True
        if admitted:
            self.packet.emit(PacketDelivery(session,event))
        elif notify:
            self.overflow.emit()
        return admitted

    def seal(self):
        """Close admission; previously admitted notifications must still drain."""
        with self._lock:self._sealed=True

    def accept(self,delivery):
        with self._lock:
            self._accepted+=1
            self._pending_bytes-=len(delivery.event.raw)

    def snapshot(self):
        with self._lock:
            return dict(published=self._published,accepted=self._accepted,
                awaiting_gui=self._published-self._accepted-self._rejected,
                pending_bytes=self._pending_bytes,rejected=self._rejected,overflowed=self._overflowed,
                sealed=self._sealed,shutdown_rejected=self._shutdown_rejected,
                max_pending=self.max_pending,max_pending_bytes=self.max_pending_bytes)
