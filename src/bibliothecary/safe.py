"""Atomic, recoverable local files. Never silently replace unreadable originals."""
from __future__ import annotations
import contextlib
import json
import os
import tempfile
import threading
import warnings
from pathlib import Path

_locks: dict[str, threading.RLock] = {}
_guard = threading.Lock()

@contextlib.contextmanager
def locked(path: Path):
    """Thread and process lock; never hold this while making model/network calls."""
    key = str(path.resolve())
    with _guard:
        lock = _locks.setdefault(key, threading.RLock())
    with lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a') as f:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX)
            try: yield
            finally: fcntl.flock(f, fcntl.LOCK_UN)

def atomic(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(text); f.flush(); os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)

def write_json(path: Path, data):
    atomic(path, json.dumps(data, ensure_ascii=False, indent=2) + '\n')

def read_json(path: Path, default=None):
    if not path.exists(): return {} if default is None else default
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict): raise ValueError('expected an object')
        return value
    except (ValueError, OSError) as err:
        # Keep the bad bytes, and make a single diagnostic copy for repair.
        quarantine = path.with_suffix(path.suffix + '.corrupt')
        if not quarantine.exists():
            try: atomic(quarantine, path.read_text(encoding='utf-8', errors='replace'))
            except OSError: pass
        warnings.warn(f'Cannot read {path.name}; original kept for repair: {err}', RuntimeWarning)
        return {} if default is None else default
