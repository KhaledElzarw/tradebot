# tradebot (Binance Spot Testnet)

## Setup

1) Create `.env` (already done):
- `BINANCE_BASE_URL=https://testnet.binance.vision`
- `BINANCE_API_KEY=...`
- `BINANCE_API_SECRET=...`
- `BINANCE_SYMBOL=BTCUSDT`

2) Create venv + install deps:
```bash
cd /home/claw/.openclaw/workspace/tradebot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Smoke test
```bash
source .venv/bin/activate
python bot.py
```

Expected output:
- OK ping + server time
- Authenticated + balances count
- Klines OK + last close

## Local AI

The grid engine can consume local AI decisions from `ai_sidecar.py`. Configure an OpenAI-compatible local endpoint such as Ollama:

```bash
TRADEBOT_AI_BASE_URL=http://127.0.0.1:11434/v1
TRADEBOT_AI_MODEL=qwen3.5:9b
```

The dashboard exposes named Ollama endpoints:

- Local: `http://127.0.0.1:11434/v1`
- Battlestation GPU: `http://192.168.1.20:11435/v1`
- Battlestation CPU: `http://192.168.1.20:11436/v1`

Run a one-off review:

```bash
python ai_playground.py
```

## Runtime Boundary

Use the service orchestrator for normal operations:

```bash
python dashboard_orchestrator.py start
python dashboard_orchestrator.py status
python dashboard_orchestrator.py stop
```

SQLite (`tradebot.sqlite3`) is the canonical runtime store. JSON files remain compatibility mirrors.

Dashboard realtime channels are split by responsibility:

- SSE `/api/live/events`: engine/runtime/status/events.
- WebSocket `/ws/chart`: chart ticks.
- Polling `/api/market`: fallback and chart seed.
- Heavy `/api/dashboard`: boot/config/intelligence.

Realtime payloads use `dashboard.snapshot.v1`, monotonic `seq` ids, and SSE patch fields: `eventsPatch` for event snapshots/deltas and `ordersPatch` for order snapshot/upsert/remove operations.
