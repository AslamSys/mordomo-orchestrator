"""
NATS message handlers for mordomo-orchestrator.

Subscriptions:
  mordomo.speaker.verified        → update session, mark speaker active
  mordomo.speech.transcribed      → forward to brain
  mordomo.brain.action.*          → dispatch to target service
  iot.command.executed            → log IoT result (success/failure)
  *.event.>                       → store in EventMemory
  mordomo.orchestrator.request    → handle text requests from OpenClaw (WhatsApp/Telegram/etc.)
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
            "source": "mordomo",
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


async def handle_tts_status(msg: Msg) -> None:
    """Receive tts.status.* events and update session state accordingly."""
    try:
        data = json.loads(msg.data.decode())
        speaker_id = data.get("speaker_id", "unknown")
        status = data.get("status", "")
        if status == "started":
            await session.set_state(speaker_id, SessionState.SPEAKING)
        elif status in ("completed", "interrupted"):
            await session.set_state(speaker_id, SessionState.LISTENING)
    except Exception as exc:
        logger.error("handle_tts_status error: %s", exc)


async def handle_external_event(msg: Msg) -> None:
    """Store all external module events in EventMemory."""
    try:
        data = json.loads(msg.data.decode())
        event_memory.store(msg.subject, data)
    except Exception as exc:
        logger.error("handle_external_event error: %s", exc)


async def handle_iot_result(nc: NATS, msg: Msg) -> None:
    """
    Receive execution confirmation from mordomo-iot-orchestrator.

    Expected payload (published on iot.command.executed):
      {
        "command_id": str,
        "device_id":  str,
        "success":    bool,
        "latency_ms": int,
        "error":      str | None   # only on failure
      }

    On failure: publishes TTS correction to the active session speaker.
    On success: logs only (state is tracked in Redis db2 by iot-orchestrator).
    """
    try:
        data = json.loads(msg.data.decode())
        device_id = data.get("device_id", "unknown")
        success = data.get("success", True)
        error = data.get("error")

        event_memory.store(msg.subject, data)

        if not success:
            logger.warning("IoT command failed for device %s: %s", device_id, error)
            # Find the most recent active speaker to send a correction
            active = await session.get_any_active_speaker()
            if active:
                tts_payload = json.dumps({
                    "speaker_id": active,
                    "text": f"Não consegui executar o comando no dispositivo {device_id}.",
                }).encode()
                await nc.publish(config.SUBJECT_TTS_GENERATE, tts_payload)
        else:
            logger.info("IoT command executed: device=%s latency=%sms", device_id, data.get("latency_ms"))
    except Exception as exc:
        logger.error("handle_iot_result error: %s", exc)


async def handle_openclaw_request(nc: NATS, msg: Msg) -> None:
    """
    Handle text-channel requests coming from OpenClaw (WhatsApp, Telegram, etc.).

    Expected payload:
      {
        "user_id":   str,       # channel identifier: "whatsapp:+55...", "telegram:123..."
        "channel":   str,       # "whatsapp" | "telegram" | "discord" | ...
        "text":      str,       # raw user message
        "session_id": str       # optional openclaw session id
      }

    Flow:
      1. Resolve person_id via mordomo.people.resolve
      2. Ask brain via mordomo.brain.generate (request/reply)
      3. Dispatch any actions[] returned by brain
      4. Reply with text on msg.reply (NATS request/reply)
    """
    if not msg.reply:
        logger.warning("handle_openclaw_request: no reply-to, dropping message")
        return

    try:
        data = json.loads(msg.data.decode())
        user_id: str = data.get("user_id", "unknown")
        channel: str = data.get("channel", "unknown")
        text: str = data.get("text", "").strip()

        if not text:
            await nc.publish(msg.reply, json.dumps({"text": "", "error": "empty text"}).encode())
            return

        # 1. Resolve person_id via mordomo-people
        speaker_id = user_id
        confidence = 1.0  # text channels have full identity certainty
        try:
            people_payload = json.dumps({"identifier": user_id, "channel": channel}).encode()
            people_resp = await nc.request(
                config.SUBJECT_PEOPLE_RESOLVE,
                people_payload,
                timeout=config.OPENCLAW_PEOPLE_TIMEOUT,
            )
            person_data = json.loads(people_resp.data.decode())
            if person_data.get("person_id"):
                speaker_id = person_data["person_id"]
        except Exception as exc:
            logger.warning("people.resolve failed for %s: %s — using raw user_id", user_id, exc)

        # 2. Ask brain
        brain_payload = json.dumps({
            "speaker_id": speaker_id,
            "text": text,
            "confidence": confidence,
            "source": "openclaw",
            "channel": channel
        }).encode()

        brain_resp = await nc.request(
            config.SUBJECT_BRAIN_GENERATE,
            brain_payload,
            timeout=config.OPENCLAW_BRAIN_TIMEOUT,
        )
        brain_data = json.loads(brain_resp.data.decode())
        reply_text: str = brain_data.get("text", "")
        actions: list = brain_data.get("actions", [])

        # 3. Dispatch actions (fire-and-forget, same as voice flow)
        for action in actions:
            action_type = action.pop("type", None)
            if action_type:
                try:
                    await dispatcher.dispatch(nc, action_type, action, speaker_id, confidence)
                except Exception as exc:
                    logger.error("dispatch error for action %s: %s", action_type, exc)

        # 4. Reply to OpenClaw
        await nc.publish(msg.reply, json.dumps({"text": reply_text}).encode())
        logger.info("openclaw_request handled: channel=%s speaker=%s text='%s'", channel, speaker_id, text[:60])

    except Exception as exc:
        logger.error("handle_openclaw_request error: %s", exc)
        try:
            await nc.publish(msg.reply, json.dumps({"text": "Desculpe, ocorreu um erro interno.", "error": str(exc)}).encode())
        except Exception:
            pass
