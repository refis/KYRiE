"""Discover TCP connections owned by a selected Windows process (and optional children)."""
from dataclasses import dataclass
import psutil

@dataclass(frozen=True)
class Endpoint:
    local_ip: str
    local_port: int
    remote_ip: str
    remote_port: int
    pid: int
    status: str

    @property
    def key(self):
        return (self.remote_ip, self.remote_port, self.local_ip, self.local_port)


def list_processes():
    rows = []
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            if proc.info['name']:
                rows.append((proc.info['pid'], proc.info['name']))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return sorted(rows, key=lambda x: (x[1].lower(), x[0]))


def owned_pids(pid, include_children=False):
    proc = psutil.Process(int(pid))
    result = {proc.pid}
    if include_children:
        result.update(p.pid for p in proc.children(recursive=True))
    return result


def discover(pid, include_children=False):
    pids = owned_pids(pid, include_children)
    result = set()
    # net_connections is system-wide and includes PID where accessible.
    for c in psutil.net_connections(kind='tcp'):
        if c.pid not in pids or not c.laddr or not c.raddr:
            continue
        result.add(Endpoint(c.laddr.ip, c.laddr.port, c.raddr.ip,
                            c.raddr.port, c.pid, c.status))
    return result
