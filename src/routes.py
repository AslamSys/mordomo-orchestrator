"""
Dynamic action route registry — backed by Redis db1 key `mordomo:routes`.

Pattern mirrors tools.py: seed defaults with HSETNX on startup, cache with TTL.
Any service can register its own routes via:
    HSET mordomo:routes <action_type> <nats_subject>
"""

import json
import logging
import time

import redis.asyncio as aioredis

from . import config

logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None
_cache: dict[str, str] = {}
_cache_ts: float = 0.0


def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(config.REDIS_URL, decode_responses=True)
    return _redis


async def fetch_routes() -> dict[str, str]:
    """Read all routes from Redis HGETALL mordomo:routes."""
    r = _get_redis()
    raw = await r.hgetall("mordomo:routes")
    return dict(raw)


async def get_routes() -> dict[str, str]:
    """Return cached routes, refreshing after ROUTES_CACHE_TTL seconds."""
    global _cache, _cache_ts
    now = time.monotonic()
    if now - _cache_ts < config.ROUTES_CACHE_TTL and _cache:
        return _cache
    try:
        _cache = await fetch_routes()
        _cache_ts = now
        logger.debug("routes refreshed: %d entries", len(_cache))
    except Exception as exc:
        logger.warning("failed to fetch routes from Redis: %s", exc)
        if not _cache:
            _cache = dict(config.ACTION_ROUTES)  # fall back to static seed
    return _cache


async def init_routes() -> None:
    """Seed default routes into Redis using HSETNX (no-overwrite)."""
    r = _get_redis()
    # Merge generic category routes + specific tool-name routes
    seed: dict[str, str] = {
        **config.ACTION_ROUTES,
        # tool-name → service subject mappings
        "pix_send": "mordomo.financas.pix.command",
        "balance_query": "mordomo.financas.contas.command",
        "iot_control": "mordomo.iot.command",
        "alarm_control": "mordomo.iot.command",
        "media_control": "mordomo.iot.command",
        "openclaw_execute": "mordomo.openclaw.command",
        "reminder_create": "mordomo.brain.reminder",
    }
    pipe = r.pipeline()
    for action_type, subject in seed.items():
        pipe.hsetnx("mordomo:routes", action_type, subject)
    await pipe.execute()
    logger.info("routes seed applied (%d entries)", len(seed))
