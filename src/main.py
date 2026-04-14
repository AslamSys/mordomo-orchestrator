"""
mordomo-orchestrator — entry point.

Subscriptions:
  mordomo.speaker.verified        → session update
  mordomo.speech.transcribed      → forward to brain
  mordomo.brain.action.*          → action dispatch
  mordomo.tts.started             → session SPEAKING
  mordomo.tts.finished            → session LISTENING
  *.event.>                       → event memory
  mordomo.orchestrator.request    → text requests from OpenClaw
"""

import asyncio
import logging
import signal

import nats
from nats.aio.client import Client as NATS

from . import config, session
from .events import memory as event_memory
from .handlers import (
    handle_brain_action,
    handle_external_event,
    handle_openclaw_request,
    handle_speaker_verified,
    handle_speech_transcribed,
    handle_tts_finished,
    handle_tts_started,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

_stop = asyncio.Event()


def _handle_signal(*_) -> None:
    _stop.set()


async def main() -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    nc: NATS = await nats.connect(
        config.NATS_URL,
        name="mordomo-orchestrator",
        reconnect_time_wait=2,
        max_reconnect_attempts=-1,
    )
    logger.info("connected to NATS at %s", config.NATS_URL)

    await nc.subscribe(
        config.SUBJECT_SPEAKER_VERIFIED,
        cb=handle_speaker_verified,
    )
    await nc.subscribe(
        config.SUBJECT_SPEECH_TRANSCRIBED,
        cb=lambda msg: asyncio.create_task(handle_speech_transcribed(nc, msg)),
    )
    await nc.subscribe(
        config.SUBJECT_BRAIN_ACTION + "*",
        cb=lambda msg: asyncio.create_task(handle_brain_action(nc, msg)),
    )
    await nc.subscribe(
        "mordomo.tts.started",
        cb=handle_tts_started,
    )
    await nc.subscribe(
        "mordomo.tts.finished",
        cb=handle_tts_finished,
    )
    await nc.subscribe(
        config.SUBJECT_EVENTS_WILDCARD,
        cb=handle_external_event,
    )
    await nc.subscribe(
        config.SUBJECT_OPENCLAW_REQUEST,
        cb=lambda msg: asyncio.create_task(handle_openclaw_request(nc, msg)),
    )

    logger.info("mordomo-orchestrator ready")

    # Periodic event memory cleanup
    async def _cleanup_loop():
        while not _stop.is_set():
            await asyncio.sleep(3600)
            event_memory.cleanup()

    asyncio.create_task(_cleanup_loop())

    await _stop.wait()
    logger.info("shutting down")
    await nc.drain()
    await session.close()


if __name__ == "__main__":
    asyncio.run(main())
