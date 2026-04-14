"""
NATS message handlers for mordomo-orchestrator.

Subscriptions:
  mordomo.speaker.verified      → update session, mark speaker active
  mordomo.speech.transcribed    → forward to brain
  mordomo.brain.action.*        → dispatch to target service
  *.event.>                     → store in EventMemory
"""

import json
import logging

from nats.aio.client import Client as NATS
from nats.aio.msg import Msg

from . import config, dispatcher, session
from .events import memory as event_memory
from .session import SessionState

logger = logging.getLogger(__name__)


async def handle_speaker_verified(msg: Msg) -> None:
    try:
        data = json.loads(msg.data.decode())
        speaker_id = data.get("speaker_id") or data.get("person_id")
        confidence = float(data.get("confidence", 0.0))
        if speaker_id:
            await session.update_speaker(speaker_id, confidence)
    except Exception as exc:
        logger.error("handle_speaker_verified error: %s", exc)


async def handle_speech_transcribed(nc: NATS, msg: Msg) -> None:
    """Receive transcribed text and forward to brain for LLM processing."""
    try:
        data = json.loads(msg.data.decode())
        speaker_id = data.get("speaker_id", "unknown")
        text = data.get("text", "").strip()
        if not text:
            return

        sess = await session.get_session(speaker_id)
        await session.set_state(speaker_id, SessionState.THINKING)

        brain_payload = json.dumps({
            "speaker_id": speaker_id,
            "text": text,
            "confidence": sess.get("confidence", 0.0),
        }).encode()

        await nc.publish(config.SUBJECT_BRAIN_GENERATE, brain_payload)
        logger.info("forwarded to brain: speaker=%s text='%s'", speaker_id, text[:60])
    except Exception as exc:
        logger.error("handle_speech_transcribed error: %s", exc)


async def handle_brain_action(nc: NATS, msg: Msg) -> None:
    """Receive an action published by brain and dispatch it."""
    try:
        # Subject: mordomo.brain.action.{type}
        action_type = msg.subject.removeprefix(config.SUBJECT_BRAIN_ACTION)
        data = json.loads(msg.data.decode())
        speaker_id = data.pop("speaker_id", "unknown")

        sess = await session.get_session(speaker_id)
        confidence = sess.get("confidence", 0.0)

        await dispatcher.dispatch(nc, action_type, data, speaker_id, confidence)
    except Exception as exc:
        logger.error("handle_brain_action error: %s", exc)


async def handle_tts_started(msg: Msg) -> None:
    """When TTS starts speaking, update session state."""
    try:
        data = json.loads(msg.data.decode())
        speaker_id = data.get("speaker_id", "unknown")
        await session.set_state(speaker_id, SessionState.SPEAKING)
    except Exception as exc:
        logger.error("handle_tts_started error: %s", exc)


async def handle_tts_finished(msg: Msg) -> None:
    """When TTS finishes, return session to LISTENING."""
    try:
        data = json.loads(msg.data.decode())
        speaker_id = data.get("speaker_id", "unknown")
        await session.set_state(speaker_id, SessionState.LISTENING)
    except Exception as exc:
        logger.error("handle_tts_finished error: %s", exc)


async def handle_external_event(msg: Msg) -> None:
    """Store all external module events in EventMemory."""
    try:
        data = json.loads(msg.data.decode())
        event_memory.store(msg.subject, data)
    except Exception as exc:
        logger.error("handle_external_event error: %s", exc)
