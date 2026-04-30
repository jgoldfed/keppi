"""File watcher daemon using watchdog for incremental graph updates."""

from __future__ import annotations

import os
import signal
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

import networkx as nx

try:
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers import Observer
    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False

from rich.console import Console

from keppi.graph.storage import load_graph, open_db
from keppi.parser.config import Config

_PID_FILE = Path.home() / ".keppi" / "watcher.pid"


class _DebounceHandler:
    """Batches file events and fires callback after debounce_ms of silence."""

    def __init__(self, debounce_ms: int, callback):
        self._debounce_s = debounce_ms / 1000.0
        self._callback = callback
        self._pending: set[str] = set()
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

    def schedule(self, path: str) -> None:
        with self._lock:
            self._pending.add(path)
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(self._debounce_s, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def _fire(self) -> None:
        with self._lock:
            paths = set(self._pending)
            self._pending.clear()
        self._callback(paths)


class _VaultEventHandler:
    """Watchdog event handler that enqueues changes."""

    def __init__(
        self,
        vault_root: Path,
        extensions: list[str],
        exclude_dirs: list[str],
        debounce: _DebounceHandler,
    ):
        self._vault_root = vault_root
        self._extensions = [e.lower() for e in extensions]
        self._exclude_dirs_lower = {d.lower() for d in exclude_dirs}
        self._debounce = debounce

    def dispatch(self, event) -> None:
        path = getattr(event, "dest_path", None) or event.src_path
        p = Path(path)
        if p.suffix.lower() not in self._extensions:
            return
        parts_lower = {part.lower() for part in p.relative_to(self._vault_root).parts[:-1]}
        if parts_lower & self._exclude_dirs_lower:
            return
        self._debounce.schedule(path)


def _do_update(changed_paths: set[str], conn: sqlite3.Connection, graph: nx.DiGraph, config: Config) -> None:
    from rich.console import Console

    from keppi.graph.incremental import incremental_update

    console = Console()
    try:
        counts = incremental_update(conn, graph, config)
        console.print(
            f"[dim]watcher:[/dim] +{counts['added']} ~{counts['updated']} -{counts['deleted']} (unchanged {counts['unchanged']})"
        )
    except Exception as e:
        console.print(f"[red]watcher error:[/red] {e}")


def start_watcher(config: Config, db_path: Path) -> None:
    if not HAS_WATCHDOG:
        raise ImportError("watchdog not installed — run: uv add watchdog")

    vault_root = config.vault_root()
    conn = open_db(db_path)
    graph = load_graph(conn)

    debounce = _DebounceHandler(
        config.watch.debounce_ms,
        lambda paths: _do_update(paths, conn, graph, config),
    )

    handler = _VaultEventHandler(
        vault_root,
        config.vault.file_extensions,
        config.vault.exclude_dirs,
        debounce,
    )

    # Wrap in watchdog-compatible FileSystemEventHandler
    class _WatchdogAdapter(FileSystemEventHandler):
        def dispatch(self, event: FileSystemEvent) -> None:
            handler.dispatch(event)

    observer = Observer()
    observer.schedule(_WatchdogAdapter(), str(vault_root), recursive=True)
    observer.start()

    # Write PID file
    _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(os.getpid()))

    Console().print(f"[green]Watching[/green] {vault_root}  (Ctrl+C to stop)")

    try:
        while observer.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()
        if _PID_FILE.exists():
            _PID_FILE.unlink()


def stop_watcher() -> bool:
    if not _PID_FILE.exists():
        return False
    try:
        pid = int(_PID_FILE.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        _PID_FILE.unlink()
        return True
    except (ProcessLookupError, ValueError, OSError):
        _PID_FILE.unlink(missing_ok=True)
        return False
