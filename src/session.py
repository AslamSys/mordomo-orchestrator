"""
Session Controller — manages per-speaker session state.

State machine:
  IDLE → LISTENING → PROCESSING → THINKING → SPEAKING → LISTENING/IDLE

Session data is stored in Redis db1 under key: session:{speaker_id}
"""

import json
import logging
from enum import Enum

import redis.asyncio as aioredis

from . import config

logger = logging.getLogger(__name__)


class SessionState(str, Enum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    PROCESSING = "PROCESSING"   # whisper transcribed, waiting brain
    THINKING = "THINKING"       # brain generating
    SPEAKING = "SPEAKING"       # TTS playing


_redis: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(config.REDIS_URL, decode_responses=True)
    return _redis


def _key(speaker_id: str) -> str:
    return f"session:{speaker_id}"


async def get_session(speaker_id: str) -> dict:
    r = await get_redis()
    raw = await r.get(_key(speaker_id))
    if raw:
        return json.loads(raw)
    return {"speaker_id": speaker_id, "state": SessionState.IDLE, "confidence": 0.0}


async def set_state(speaker_id: str, state: SessionState) -> None:
    r = await get_redis()
    session = await get_session(speaker_id)
    session["state"] = state
    await r.setex(_key(speaker_id), config.SESSION_TTL_SECONDS, json.dumps(session))
    logger.debug("session %s → %s", speaker_id, state)


async def update_speaker(speaker_id: str, confidence: float) -> None:
    """Called when speaker.verified arrives. Moves session to LISTENING."""
    r = await get_redis()
    session = await get_session(speaker_id)
    session["speaker_id"] = speaker_id
    session["confidence"] = confidence
    session["state"] = SessionState.LISTENING
    await r.setex(_key(speaker_id), config.SESSION_TTL_SECONDS, json.dumps(session))
    logger.info("speaker %s verified (confidence=%.2f)", speaker_id, confidence)


async def close() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None
