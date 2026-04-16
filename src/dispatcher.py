"""
Action Dispatcher — routes brain actions to the correct NATS subject.

Brain publishes actions as: mordomo.brain.action.{type}
Dispatcher maps type → target NATS subject and forwards.
"""

import json
import logging

from nats.aio.client import Client as NATS

from . import config
from . import vault as vault_client
from .routes import get_routes

logger = logging.getLogger(__name__)


async def dispatch(
    nc: NATS,
    action_type: str,
    action_payload: dict,
    speaker_id: str,
    confidence: float,
) -> None:
    """
    Routes an action extracted by mordomo-brain to the correct service.
    For sensitive actions, fetches secret from vault first.
    """
    # Vault check for sensitive actions
    if action_type in config.VAULT_REQUIRED_ACTIONS:
        secret_key = _secret_for_action(action_type)
        if secret_key:
            secret = await vault_client.fetch_secret(
                nc,
                secret_key=secret_key,
                requester_module=f"mordomo-orchestrator:{action_type}",
                person_id=speaker_id,
                confidence=confidence,
            )
            if secret is None:
                logger.warning("action %s blocked: vault denied or unavailable", action_type)
                return
            action_payload["__secret"] = secret

    # Resolve target subject (dynamic via Redis, falls back to static seed)
    routes = await get_routes()
    target = _resolve_subject(action_type, action_payload, routes)
    if not target:
        logger.warning("no route for action type: %s", action_type)
        return

    payload = json.dumps({
        "speaker_id": speaker_id,
        "action_type": action_type,
        **action_payload,
    }).encode()

    await nc.publish(target, payload)
    logger.info("dispatched %s → %s", action_type, target)


def _resolve_subject(action_type: str, payload: dict, routes: dict[str, str]) -> str | None:
    # Exact match first
    if action_type in routes:
        return routes[action_type]
    # Prefix match (e.g. "iot.turn_on" → "iot")
    prefix = action_type.split(".")[0]
    return routes.get(prefix)


def _secret_for_action(action_type: str) -> str | None:
    mapping = {
        "pix": "asaas_api_key",
        "transfer": "asaas_api_key",
        "balance": "asaas_api_key",
        "trade": None,  # escalated to investimentos-brain directly
    }
    return mapping.get(action_type)
