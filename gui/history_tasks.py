"""Cooperative GUI-thread jobs; stage results and commit only the latest job."""
from time import perf_counter
from PySide6.QtCore import QObject,QTimer,Signal


class HistoryTasks(QObject):
    changed=Signal()
    failed=Signal()
    def __init__(self,parent=None):
        super().__init__(parent)
        self.jobs={}
        self.timer=QTimer(self)
        self.timer.setInterval(1)
        self.timer.timeout.connect(self.advance)

    @property
    def busy(self):return bool(self.jobs)

    def running(self,name):return name in self.jobs

    def cancel(self,name=None):
        names=list(self.jobs) if name is None else [name]
        for key in names:
            job=self.jobs.pop(key,None)
            if job:
                job['iterator'].close()
                if job['abort']:job['abort']()
        if not self.jobs:self.timer.stop()
        self.changed.emit()

    def start(self,name,iterator,commit,*,asynchronous,abort=None):
        self.cancel(name)
        job=dict(iterator=iterator,commit=commit,abort=abort)
        self.jobs[name]=job
        self.changed.emit()
        if asynchronous:self.timer.start()
        else:
            while self.jobs.get(name) is job:self._step(name,job,None)

    def _step(self,name,job,deadline):
        finished=False
        try:
            for _ in range(1000):
                next(job['iterator'])
                if deadline is not None and perf_counter()>=deadline:return
        except StopIteration as result:
            value=result.value
            finished=True
        except Exception:
            if self.jobs.get(name) is job:self.cancel(name)
            self.failed.emit()
            return
        if finished and self.jobs.get(name) is job:
            del self.jobs[name]
            try:job['commit'](value)
            except Exception:self.failed.emit()
            finally:self.changed.emit()

    def advance(self):
        deadline=perf_counter()+.008
        for name,job in list(self.jobs.items()):
            if self.jobs.get(name) is job:self._step(name,job,deadline)
            if perf_counter()>=deadline:break
        if not self.jobs:self.timer.stop()
