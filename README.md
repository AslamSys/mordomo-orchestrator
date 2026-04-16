# 🎼 mordomo-orchestrator

## 🔗 Navegação

**[🏠 AslamSys](https://github.com/AslamSys)** → **[📚 _system](https://github.com/AslamSys/_system)** → **[📂 Aslam (Orange Pi 5 16GB)](https://github.com/AslamSys/_system/blob/main/hardware/mordomo%20-%20(orange-pi-5-16gb)/README.md)** → **mordomo-orchestrator**

### Containers Relacionados (brain)
- [mordomo-brain](https://github.com/AslamSys/mordomo-brain)
- [mordomo-people](https://github.com/AslamSys/mordomo-people)
- [mordomo-vault](https://github.com/AslamSys/mordomo-vault)
- [mordomo-tts-engine](https://github.com/AslamSys/mordomo-tts-engine)
- [mordomo-iot-orchestrator](https://github.com/AslamSys/mordomo-iot-orchestrator)
- [mordomo-financas-pix](https://github.com/AslamSys/mordomo-financas-pix)
- [mordomo-financas-contas](https://github.com/AslamSys/mordomo-financas-contas)
- [mordomo-speaker-verification](https://github.com/AslamSys/mordomo-speaker-verification)
- [mordomo-whisper-asr](https://github.com/AslamSys/mordomo-whisper-asr)
- [infra/redis](https://github.com/AslamSys/mordomo-deploy) — db1 (sessions + routes)

---

**Container:** `mordomo-orchestrator`  
**Ecossistema:** Brain  
**Hardware:** Orange Pi 5 Ultra  
**Linguagem:** Python 3.11 (asyncio + nats-py)

---

## 📋 Propósito

Orquestrador central do Mordomo. Gerencia sessões de usuário, aplica o gate de autorização por voz, encaminha transcrições ao brain, despacha ações retornadas, e fecha o loop de resultado (feedback de falhas via TTS).

---

## 🎯 Responsabilidades

- Gate de autorização: só processa transcrição após `mordomo.speaker.verified`
- Gerenciar estado de sessão por speaker (Redis db1)
- Encaminhar texto transcrito ao brain (`mordomo.brain.generate`)
- Despachar ações do brain para os serviços corretos (rotas dinâmicas via Redis)
- Consultar Vault para ações sensíveis (PIX, saldo, alarme)
- Receber resultado do IoT e emitir TTS de correção em caso de falha
- Canal de texto para OpenClaw (WhatsApp, Telegram) via `mordomo.orchestrator.request`

---

## 🔌 Subscriptions NATS

| Subject | Handler | Descrição |
|---|---|---|
| `mordomo.speaker.verified` | `handle_speaker_verified` | Registra speaker ativo, libera processamento |
| `mordomo.speech.transcribed` | `handle_speech_transcribed` | Gate: só avança se sessão ativa; encaminha ao brain |
| `mordomo.brain.action.*` | `handle_brain_action` | Despacha ação para o serviço alvo |
| `mordomo.tts.started` | `handle_tts_started` | Atualiza sessão → SPEAKING |
| `mordomo.tts.finished` | `handle_tts_finished` | Atualiza sessão → LISTENING |
| `iot.command.executed` | `handle_iot_result` | Loop de feedback: TTS de correção se `success: false` |
| `*.event.>` | `handle_external_event` | Armazena todos eventos no EventMemory |
| `mordomo.orchestrator.request` | `handle_openclaw_request` | Canal texto — resolve person → brain → dispatch → reply |

---

## 🔐 Gate de Autorização por Voz

Quando `mordomo.audio.snippet` é emitido pelo wake-word-detector, três containers processam **em paralelo**:
- `mordomo-speaker-verification` — verifica se a voz é autorizada
- `mordomo-whisper-asr` — transcreve o áudio
- `mordomo-speaker-id-diarization` — identifica o speaker

O orchestrator aguarda `mordomo.speaker.verified` antes de encaminhar a transcrição ao brain. Se a verificação não chegar (timeout ou rejeição), a transcrição é descartada.

```
[speaker.verified] → sessão ativa (LISTENING)
[speech.transcribed] → só avança se sessão ativa
```

---

## 🗺️ Rotas Dinâmicas (Redis)

As rotas de despacho são carregadas do Redis db1 e cacheadas com TTL de 120s.

**Chave Redis:** `mordomo:routes` (HSET)

**Seed inicial** (via HSETNX ao startup):

| Tipo de Ação | Subject NATS |
|---|---|
| `iot` | `iot.command` |
| `tts` | `mordomo.tts.generate` |
| `vault` | `mordomo.vault.secret.get` |
| `financas` | `mordomo.financas.command` |
| `security` | `seguranca.command` |
| `nas` | `nas.command` |
| `pix_send` | `mordomo.financas.pix.command` |
| `balance_query` | `mordomo.financas.contas.command` |
| `iot_control` | `mordomo.iot.command` |
| `alarm_control` | `mordomo.iot.command` |
| `media_control` | `mordomo.iot.command` |
| `openclaw_execute` | `mordomo.openclaw.command` |
| `reminder_create` | `mordomo.brain.reminder` |

```bash
# Adicionar/alterar rota em runtime (sem restart)
redis-cli -n 1 HSET mordomo:routes nova_acao mordomo.novoservico.command
```

---

## 🏦 Vault (Ações Sensíveis)

Para ações que requerem credenciais (PIX, saldo, alarme, NAS), o dispatcher consulta o vault via request/reply antes de despachar:

```
[dispatcher] mordomo.vault.secret.get (req/reply)
Payload: {"key": "pix_token", "speaker_id": "user_1"}
Reply:   {"secret": "...", "ok": true}
```

Ações marcadas como sensíveis em `config.VAULT_REQUIRED_ACTIONS`.

---

## 🔄 Loop de Resultado (Fire-and-Correct)

O brain responde **otimisticamente** com texto imediatamente. As ações são despachadas em paralelo. O orchestrator fecha o loop escutando resultados:

### IoT (iot.command.executed)
Publicado pelo `mordomo-iot-orchestrator` após cada comando MQTT:
```json
{
  "command_id": "cmd_1748023600123",
  "device_id":  "luz_sala",
  "success":    true,
  "latency_ms": 45
}
```
Se `success: false`, o orchestrator emite TTS de correção para o speaker ativo.

### Finanças
- `mordomo.financas.pix.result` — resultado de transferência PIX
- `mordomo.financas.contas.command` — resposta de consulta de saldo

Eventos armazenados no EventMemory para contexto futuro.

---

## 📱 Canal OpenClaw (Texto)

OpenClaw (agente WhatsApp/Telegram) publica em `mordomo.orchestrator.request`:

```json
{
  "user_id":    "whatsapp:+5511999999999",
  "channel":    "whatsapp",
  "text":       "liga a luz da sala",
  "session_id": "ocl_abc123"
}
```

Fluxo:
1. Resolve `person_id` via `mordomo.people.resolve`
2. Envia ao brain via `mordomo.brain.generate` (request/reply)
3. Despacha ações em paralelo (fire-and-forget)
4. Responde no `msg.reply` com `{"text": "Pronto, luz acesa!"}`

---

## 💾 Sessões (Redis db1)

| Chave | Tipo | TTL | Conteúdo |
|---|---|---|---|
| `session:{speaker_id}` | String (JSON) | `SESSION_TTL_SECONDS` | `{speaker_id, state, confidence}` |

**Estados da sessão:**

```
IDLE → LISTENING → THINKING → SPEAKING → LISTENING/IDLE
                 ↑
         (speaker.verified)
```

---

## ⚙️ Configuração (Variáveis de Ambiente)

| Variável | Default | Descrição |
|---|---|---|
| `NATS_URL` | `nats://nats:4222` | Servidor NATS |
| `REDIS_URL` | `redis://redis:6379/1` | Redis db1 |
| `SESSION_TTL_SECONDS` | `300` | TTL de sessão inativa |
| `ROUTES_CACHE_TTL` | `120` | TTL do cache de rotas |
| `VAULT_URL` | — | URL do mordomo-vault (opcional) |

---

## 🗂️ Estrutura de Arquivos

```
src/
  config.py       # Variáveis de ambiente, subjects NATS, constantes
  session.py      # Estado de sessão por speaker (Redis db1)
  events.py       # EventMemory — ring buffer de eventos recentes
  vault.py        # Consulta mordomo-vault para ações sensíveis
  routes.py       # fetch_routes(), init_routes() — Redis mordomo:routes
  dispatcher.py   # dispatch(): resolve subject, vault check, publish
  handlers.py     # Todos os handlers NATS
  main.py         # Conecta NATS, init_routes(), todas as subscriptions
```

---

## 🐳 Docker

```yaml
# deploy: brain/docker-compose.yml
mordomo-orchestrator:
  image: ghcr.io/aslamsys/mordomo-orchestrator:latest
  environment:
    NATS_URL: nats://nats:4222
    REDIS_URL: redis://redis:6379/1
  depends_on:
    - nats
    - redis
```

---

## 🚀 CI/CD

Build automático via GitHub Actions → `ghcr.io/aslamsys/mordomo-orchestrator:latest`

Workflow: [`.github/workflows/ci.yml`](.github/workflows/ci.yml) — usa reusable workflow `AslamSys/.github`