import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from capture.process_monitor import discover, owned_pids


class ProcessTests(unittest.TestCase):
    def test_children_are_opt_in(self):
        process = Mock(pid=42)
        process.children.return_value = [Mock(pid=43)]
        with patch('capture.process_monitor.psutil.Process', return_value=process):
            self.assertEqual(owned_pids(42), {42})
            self.assertEqual(owned_pids(42, True), {42, 43})

    def test_discovery_excludes_unrelated_and_listening_sockets(self):
        local = SimpleNamespace(ip='127.0.0.1', port=1234)
        remote = SimpleNamespace(ip='127.0.0.2', port=6900)
        rows = [SimpleNamespace(pid=pid, laddr=local, raddr=addr, status='ESTABLISHED')
                for pid, addr in ((42, remote), (43, remote), (42, None))]
        with patch('capture.process_monitor.owned_pids', return_value={42}), \
             patch('capture.process_monitor.psutil.net_connections', return_value=rows):
            endpoints = discover(42)
        self.assertEqual(len(endpoints), 1)
        self.assertEqual(next(iter(endpoints)).key, ('127.0.0.2', 6900, '127.0.0.1', 1234))
