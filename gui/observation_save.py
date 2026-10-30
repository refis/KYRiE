"""Stream frozen observation/report inputs without reading Qt widgets off-thread."""
from dataclasses import dataclass
from PySide6.QtCore import QThread
from storage.observation_export import save_observation_chunks,observation_json_chunks,ExportCancelled,ExportLimitError


@dataclass(frozen=True)
class ObservationTextSnapshot:
    # MainWindow only appends to these lists or replaces an entire result list.
    # Retaining their references plus count freezes the prefix without copying it.
    events: object
    results: object
    tags: object
    count: int
    query: str
    ignored: object
    unmapped: bool
    fallback: str=''

    @property
    def needs_worker(self):
        if self.count>2000:return True
        characters=sum(len(self.results[index].text) for index in range(self.count)) if self.count else len(self.fallback)
        return characters>262144

    def __iter__(self):
        if not self.count:
            yield self.fallback
            return
        first=True
        for index in range(self.count):
            event=self.events[index];result=self.results[index]
            if ((not self.query or self.query in f'{event.packet_id:04x}') and result.text
                    and not self.ignored.hides(event,self.tags[index])
                    and (result.status!='unmapped' or self.unmapped)):
                if not first:yield '\n'
                yield result.text
                first=False
            else:
                yield ''  # Also let cancellation run during long excluded ranges.


class ObservationSaveWorker(QThread):
    def __init__(self,path,snapshot,protected,parent=None,*,builder=None):
        super().__init__(parent)
        self.path=path
        self.snapshot=snapshot
        self.builder=builder
        self.protected=tuple(protected)
        self.result=None

    def run(self):
        try:
            summary=None
            if self.isInterruptionRequested():raise ExportCancelled()
            if self.builder is not None:
                report=self.builder.build()
                if self.isInterruptionRequested():raise ExportCancelled()
                if report.get('kind')=='npc_bundle':
                    summary=dict(entries=len(report['entries']),excluded=len(report['excluded']),
                        review_only_count=report['review_only_count'],merge=report['dialogue_merged'])
                self.snapshot=(report['auriga'],) if getattr(self.builder,'text_output',False) else observation_json_chunks(report)
            size=save_observation_chunks(self.path,self.snapshot,self.protected,
                cancelled=self.isInterruptionRequested)
            self.result=dict(status='saved',bytes=size,summary=summary)
        except ExportCancelled:self.result=dict(status='cancelled')
        except ExportLimitError:self.result=dict(status='failed',reason='limit')
        except ValueError:self.result=dict(status='failed',reason='destination')
        except OSError:self.result=dict(status='failed',reason='io')
        except Exception:self.result=dict(status='failed',reason='unexpected')
        finally:
            self.snapshot=None
            self.builder=None
