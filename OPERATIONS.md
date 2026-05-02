# Tradebot Operations

## Setup

```bash
cd /home/claw/.openclaw/workspace/tradebot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill in Binance credentials before running the smoke test.

```bash
python bot.py
```

Initialize or backfill local runtime storage:

```bash
python migrate_to_sqlite.py
```

The production dashboard freshness path uses SQLite in WAL mode. Set `TRADEBOT_DB_PATH` only when you want a non-default database path.

## Services

Start services through the orchestrator:

```bash
python dashboard_orchestrator.py start
```

Check status without mutating pid files or stopping duplicate processes:

```bash
python dashboard_orchestrator.py status
```

Stop services explicitly:

```bash
python dashboard_orchestrator.py stop
```

The older detached wrappers still exist as implementation details, but operators should use `dashboard_orchestrator.py` so engine, dashboard, and AI sidecar move together.

## Dashboard

Default dashboard URL:

```text
http://localhost:8844/
```

When opening from Codex's in-app browser, use the machine address if `localhost` resolves to an isolated webview namespace:

```text
http://192.168.1.21:8844/
```

Set `TRADEBOT_DASHBOARD_TOKEN` to protect write endpoints. When set, open the dashboard with:

```text
http://192.168.1.21:8844/?token=<token>
```

Read endpoints remain available for monitoring. Mutations to `/api/control` and `/api/config` require the token.

Realtime contract:

- `/api/dashboard`: heavy boot/config/intelligence snapshot.
- `/api/market`: polling fallback for light status/runtime/events and optional chart seed.
- `/api/live/events`: SSE for engine/runtime/status/events only.
- `/ws/chart`: websocket for chart ticks only.

Every realtime payload carries `schemaVersion`, `channel`, `seq`, and `serverTimeUtc`; the browser ignores stale out-of-order sequence ids. Intelligence/news is cached separately so slow feeds do not block chart/status freshness.

SSE sends compact panel data:

- First frame: `eventsPatch.mode=snapshot` and `ordersPatch.mode=snapshot`.
- Later frames: `eventsPatch.mode=delta` with new events after the last event cursor, and `ordersPatch.mode=delta` with order `upsert`/`remove` operations.
- Polling fallback endpoints still return complete snapshots so recovery is simple.

## Local AI

The AI sidecar uses a local OpenAI-compatible endpoint by default. For Ollama, set the base URL to your local `/v1` endpoint:

```text
TRADEBOT_AI_BASE_URL=http://127.0.0.1:11434/v1
TRADEBOT_AI_MODEL=qwen3.5:9b
```

The dashboard can pause/resume AI assist, switch the provider/base URL, and choose quick/deep/fallback models. It includes these named Ollama endpoints:

- Local: `http://127.0.0.1:11434/v1`
- Battlestation GPU: `http://192.168.1.20:11435/v1`
- Battlestation CPU: `http://192.168.1.20:11436/v1`

Dry-run and shadow decisions are displayed and logged but not enforced by the engine.

Run a one-off review without changing the active signal:

```bash
python ai_playground.py
```

Write one review as the current engine signal:

```bash
python ai_playground.py --write-signal
```

Decision and lesson logs are runtime files:

- `ai_signal.json`
- `ai_decisions.jsonl`
- `ai_memory.json`

## Runtime Files

These files are runtime state, not source of truth for code. SQLite is the canonical operational store:

- `tradebot.sqlite3`
- `tradebot.sqlite3-wal`
- `tradebot.sqlite3-shm`

The JSON/JSONL files below are maintained as compatibility mirrors during the SQLite cutover and can be used as rollback input by re-running `python migrate_to_sqlite.py` against a fresh database:

- `state.json`
- `runtime_state.json`
- `engine_status.json`
- `cumulative.json`
- `trades.jsonl`
- `ai_signal.json`
- `ai_decisions.jsonl`
- `ai_memory.json`
- `dashboard_history.json`
- `*.pid`, `*.log`, `*.nohup.out`

They are ignored by git. Backups such as `*.bak` and `*.bak_*` are also ignored.

Retention:

- Use `sqlite_store.compact(event_keep=..., history_keep=...)` for event/history compaction.
- Dashboard initial boot uses compact snapshots; live updates use SSE event/order deltas and chart websocket ticks.
- JSON mirrors should stay small and are not the canonical write path.

## Deprecated Baserow Path

Baserow is no longer used for live engine/dashboard freshness. The Baserow scripts remain available only for manual legacy export/cleanup work, and `TRADEBOT_BASEROW_SYNC` should stay disabled.

## Recovery

If the dashboard shows stale data:

```bash
curl -s http://localhost:8844/api/dashboard
python run_dashboard_detached.py status
python run_engine_detached.py status
```

If the shell endpoint is live but the in-app browser is stale, switch the browser to the machine address shown by:

```bash
hostname -I
```

If pid files are stale, use `status` to inspect and `restart` only when you intentionally want to replace the process.

## Tests

```bash
source .venv/bin/activate
pytest
```
