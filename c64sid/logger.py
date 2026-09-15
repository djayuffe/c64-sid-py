from __future__ import annotations

import sys
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Literal, Optional

Level = Literal['debug', 'info', 'warn', 'error']


@dataclass
class LogEntry:
    ts: float
    tag: str
    msg: str
    level: Level
    category: Optional[str] = None


class SystemLogger:
    """Small logger compatible with the archive's SystemLogger API."""

    _enabled: bool = True
    _level_order = {'debug': 10, 'info': 20, 'warn': 30, 'error': 40}
    _min_level: Level = 'info'
    _ring: Deque[LogEntry] = deque(maxlen=5000)

    @classmethod
    def set_enabled(cls, enabled: bool) -> None:
        cls._enabled = bool(enabled)

    @classmethod
    def set_min_level(cls, level: Level) -> None:
        if level not in cls._level_order:
            raise ValueError(f"Unknown level: {level}")
        cls._min_level = level

    @classmethod
    def log(cls, tag: str, msg: str, level: Level = 'info', *, category: Optional[str] = None) -> None:
        if not cls._enabled:
            return
        if cls._level_order[level] < cls._level_order[cls._min_level]:
            return
        entry = LogEntry(time.time(), tag, msg, level, category)
        cls._ring.append(entry)
        # stderr for warnings/errors, stdout otherwise
        out = sys.stderr if level in ('warn', 'error') else sys.stdout
        t = time.strftime('%H:%M:%S', time.localtime(entry.ts))
        out.write(f"[{t}] {tag}: {msg}\n")
        out.flush()

    @classmethod
    def tail(cls, n: int = 50) -> list[LogEntry]:
        n = max(0, int(n))
        if n == 0:
            return []
        return list(cls._ring)[-n:]
