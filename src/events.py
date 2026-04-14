"""
Event Memory — circular in-memory buffer for recent events.

Stores up to EVENT_MEMORY_CAPACITY events from all modules.
Supports simple text queries (keyword match) for LLM context injection.
"""

import logging
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any

from . import config

logger = logging.getLogger(__name__)


class EventMemory:
    def __init__(self) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=config.EVENT_MEMORY_CAPACITY)

    def store(self, subject: str, data: dict) -> None:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "subject": subject,
            "module": subject.split(".")[0] if "." in subject else subject,
            "event_type": subject,
            "data": data,
        }
        self._events.append(event)
        logger.debug("event stored: %s", subject)

    def recent(self, minutes: int = 30, module: str | None = None) -> list[dict]:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        result = []
        for e in self._events:
            ts = datetime.fromisoformat(e["timestamp"])
            if ts < cutoff:
                continue
            if module and e["module"] != module:
                continue
            result.append(e)
        return result

    def query(self, text: str, minutes: int = 60) -> str:
        """Returns formatted context string for LLM injection."""
        events = self.recent(minutes=minutes)
        if not text:
            matches = events[-10:]
        else:
            keywords = text.lower().split()
            matches = [
                e for e in events
                if any(kw in str(e).lower() for kw in keywords)
            ][-10:]

        if not matches:
            return "Nenhum evento recente encontrado."

        lines = []
        for e in matches:
            lines.append(f"[{e['timestamp']}] {e['subject']}: {e['data']}")
        return "\n".join(lines)

    def cleanup(self) -> None:
        """Remove events older than retention window."""
        cutoff = datetime.now(timezone.utc) - timedelta(
            hours=config.EVENT_MEMORY_RETENTION_HOURS
        )
        fresh = [e for e in self._events if datetime.fromisoformat(e["timestamp"]) >= cutoff]
        self._events.clear()
        self._events.extend(fresh)


# Singleton
memory = EventMemory()
