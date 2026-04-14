import os

# NATS
NATS_URL = os.getenv("NATS_URL", "nats://mordomo-nats:4222")

# Redis (db1 — mordomo-general)
REDIS_URL = os.getenv("REDIS_URL", "redis://mordomo-redis:6379/1")

# Session
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "300"))  # 5 min idle

# Vault
VAULT_REQUEST_TIMEOUT = float(os.getenv("VAULT_REQUEST_TIMEOUT", "3.0"))

# NATS Subjects — inbound
SUBJECT_SPEAKER_VERIFIED = "mordomo.speaker.verified"
SUBJECT_SPEECH_TRANSCRIBED = "mordomo.speech.transcribed"
SUBJECT_BRAIN_ACTION = "mordomo.brain.action."  # prefix, subscribe mordomo.brain.action.*
SUBJECT_EVENTS_WILDCARD = "*.event.>"

# NATS Subjects — outbound
SUBJECT_BRAIN_GENERATE = "mordomo.brain.generate"
SUBJECT_TTS_GENERATE = "mordomo.tts.generate"
SUBJECT_VAULT_GET = "mordomo.vault.secret.get"
SUBJECT_STATUS = "system.orchestrator.status"

# Action routing: action type → NATS subject prefix
ACTION_ROUTES: dict[str, str] = {
    "iot": "iot.command",
    "tts": "mordomo.tts.generate",
    "vault": "mordomo.vault.secret.get",
    "financas": "mordomo.financas.command",
    "security": "seguranca.command",
    "nas": "nas.command",
}

# Sensitive action types requiring vault check
VAULT_REQUIRED_ACTIONS = {"pix", "transfer", "trade", "balance"}

# Event memory
EVENT_MEMORY_CAPACITY = int(os.getenv("EVENT_MEMORY_CAPACITY", "500"))
EVENT_MEMORY_RETENTION_HOURS = int(os.getenv("EVENT_MEMORY_RETENTION_HOURS", "24"))
