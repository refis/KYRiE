"""Measure DB-confirmed packet history eviction under a synthetic GUI load."""
import argparse
import gc
import os
import tempfile
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication

from events import PacketEvent
from gui.event_history import MEMORY_EVENT_LIMIT
from gui.main_window import MainWindow
from storage.database import PacketDatabase
from storage.observation_export import save_observations


def profile(app, *, limit, packets, confirm_db=True):
    folder = tempfile.TemporaryDirectory(prefix='kyrie-eviction-profile-')
    settings = tempfile.TemporaryDirectory(prefix='kyrie-eviction-settings-')
    db = PacketDatabase(':memory:')
    try:
        with patch('storage.user_settings.DEFAULT_PATH', Path(settings.name) / 'user_settings.json'), \
             patch('gui.main_window.PacketDatabase', return_value=db), \
             patch('gui.main_window.list_processes', return_value=[]):
            window = MainWindow(offline=True)
        window.log_root.setText(folder.name)
        window.memory_event_limit = limit
        started = perf_counter()
        for index in range(packets):
            if not confirm_db:
                window.database_failed = True
            window.add_packet(PacketEvent(index, 'RECV', 127, b'\x7f\0abcd', 'SYNTHETIC', 'synthetic'))
            app.processEvents()
        elapsed_ms = (perf_counter() - started) * 1000
        row = dict(
            memory_event_limit=limit,
            default_limit=MEMORY_EVENT_LIMIT,
            injected_packets=packets,
            confirm_db=confirm_db,
            retained=len(window.events),
            event_origin=window.event_origin,
            db_confirmed=window.packet_db_confirmed,
            evicted_rowid_map=len(window.evicted_rowids),
            add_packet_ms=round(elapsed_ms, 3),
            notes='Synthetic offline MainWindow; not live capture or peak RSS.',
        )
        window.close()
        app.processEvents()
        return row
    finally:
        folder.cleanup()
        settings.cleanup()
        gc.collect()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--limit', type=int, default=50)
    parser.add_argument('--packets', type=int, default=80)
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    rows = [
        profile(app, limit=args.limit, packets=args.packets, confirm_db=True),
        profile(app, limit=args.limit, packets=args.packets, confirm_db=False),
    ]
    save_observations(args.output, dict(
        kind='memory_event_eviction_profile',
        source='synthetic',
        includes_capture_database_decoding=False,
        scenarios=rows,
    ))
    for row in rows:
        print(row, flush=True)


if __name__ == '__main__':
    main()
