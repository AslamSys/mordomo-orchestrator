"""
Vault helper — request-reply to mordomo-vault for secret fetching.
"""

import json
import logging

from nats.aio.client import Client as NATS

from . import config

logger = logging.getLogger(__name__)


async def fetch_secret(
    nc: NATS,
    secret_key: str,
    requester_module: str,
    person_id: str,
    confidence: float,
) -> str | None:
    """
    Sends a voice-auth request to mordomo-vault.
    Returns the secret value on success, None on failure/denied.
    """
    payload = json.dumps({
        "secret_key": secret_key,
        "requester_module": requester_module,
        "auth_mode": "voice",
        "person_id": person_id,
        "confidence": confidence,
    }).encode()

    try:
        msg = await nc.request(
            config.SUBJECT_VAULT_GET,
            payload,
            timeout=config.VAULT_REQUEST_TIMEOUT,
        )
        data = json.loads(msg.data.decode())
        if data.get("allowed"):
            return data.get("value")
        logger.warning("vault denied: %s (reason=%s)", secret_key, data.get("reason"))
    except Exception as exc:
        logger.error("vault request failed: %s", exc)
    return None
