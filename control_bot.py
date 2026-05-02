import os
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes
import sqlite_store


def _required(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v


def _admin_only(update: Update) -> bool:
    uid = update.effective_user.id if update.effective_user else None
    return uid == int(_required("TELEGRAM_ADMIN_USER_ID"))


def _chat_info(update: Update) -> str:
    chat = update.effective_chat
    if not chat:
        return "unknown"
    return f"{chat.type}:{chat.id}"


HERE = os.path.dirname(__file__)

# Load env from an explicit file (preferred) or default to .env in this folder.
_ENV_FILE = os.getenv("TRADEBOT_ENV_FILE") or os.path.join(HERE, ".env")
load_dotenv(_ENV_FILE, override=False)

STATE_PATH = os.path.join(HERE, "state.json")
STATUS_PATH = os.path.join(HERE, "engine_status.json")
CUM_PATH = os.path.join(HERE, "cumulative.json")
TRADES_PATH = os.path.join(HERE, "trades.jsonl")
AI_SIGNAL_PATH = os.path.join(HERE, "ai_signal.json")

AI_ENDPOINTS = [
    {"key": "local", "label": "Local", "provider": "ollama", "baseUrl": "http://127.0.0.1:11434/v1"},
    {"key": "battlestation_gpu", "label": "Battlestation GPU", "provider": "ollama", "baseUrl": "http://192.168.1.20:11435/v1"},
    {"key": "battlestation_cpu", "label": "Battlestation CPU", "provider": "ollama", "baseUrl": "http://192.168.1.20:11436/v1"},
    {"key": "custom", "label": "Custom", "provider": "ollama", "baseUrl": ""},
]
AI_ENDPOINT_BY_KEY = {item["key"]: item for item in AI_ENDPOINTS}
AI_ENDPOINT_ALIASES = {
    "local": "local",
    "gpu": "battlestation_gpu",
    "battlestation_gpu": "battlestation_gpu",
    "battlestation-gpu": "battlestation_gpu",
    "cpu": "battlestation_cpu",
    "battlestation_cpu": "battlestation_cpu",
    "battlestation-cpu": "battlestation_cpu",
    "custom": "custom",
}

# Trend instance paths
STATE_TREND_PATH = os.path.join(HERE, "state_trend.json")
STATUS_TREND_PATH = os.path.join(HERE, "engine_status_trend.json")
CUM_TREND_PATH = os.path.join(HERE, "cumulative_trend.json")
TRADES_TREND_PATH = os.path.join(HERE, "trades_trend.jsonl")


def _read_json(path: str) -> dict:
    key = sqlite_store.snapshot_key_for_path(path)
    if key and sqlite_store.has_snapshot(key):
        return sqlite_store.read_snapshot(key)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: str, obj: dict) -> None:
    key = sqlite_store.snapshot_key_for_path(path)
    if key:
        sqlite_store.write_snapshot(key, obj)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


def _read_state() -> dict:
    return _read_json(STATE_PATH)


def _write_state(s: dict) -> None:
    _write_json(STATE_PATH, s)


def _read_state_trend() -> dict:
    return _read_json(STATE_TREND_PATH)


def _write_state_trend(s: dict) -> None:
    _write_json(STATE_TREND_PATH, s)


def _read_status() -> dict | None:
    try:
        return _read_json(STATUS_PATH)
    except Exception:
        return None


def _read_status_trend() -> dict | None:
    try:
        return _read_json(STATUS_TREND_PATH)
    except Exception:
        return None


def _read_cum() -> dict | None:
    try:
        return _read_json(CUM_PATH)
    except Exception:
        return None


def _read_ai_signal() -> dict | None:
    try:
        return _read_json(AI_SIGNAL_PATH)
    except Exception:
        return None


def _read_cum_trend() -> dict | None:
    try:
        return _read_json(CUM_TREND_PATH)
    except Exception:
        return None


def _tail_trade_events(n: int, path: str) -> list[dict]:
    """Return last n ENTER/EXIT events from a trades.jsonl file."""
    if os.path.basename(path) == "trades.jsonl":
        rows = sqlite_store.list_events(limit=max(200, n * 10))
        if rows:
            return [e for e in rows if e.get("event") in ("ENTER", "EXIT")][-n:]
    if not os.path.exists(path):
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
    except Exception:
        return []

    events: list[dict] = []
    for line in lines[-max(200, n * 10):]:
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("event") in ("ENTER", "EXIT"):
            events.append(e)

    return events[-n:]


def _fmt_ts(ts: str) -> str:
    # Normalize ISO to a compact readable timestamp.
    if not ts:
        return "(no-ts)"
    return ts.replace("T", " ").replace("+00:00", " UTC").replace("Z", " UTC")


def _fmt_trade(e: dict) -> str:
    ts = _fmt_ts(e.get("tsUtc") or "")
    ev = e.get("event")
    sym = e.get("symbol") or ""
    side = e.get("side") or ("BUY" if ev == "ENTER" else "SELL")
    qty = float(e.get("qtyBtc") or 0)
    price = float(e.get("price") or 0)
    notion = float(e.get("notionalUsdt") or 0)

    if ev == "ENTER":
        return f"{ts} • ENTER {side} {sym} • qty={qty:.6f} @ {price:.2f} • notional={notion:.2f} USDT"

    if ev == "EXIT":
        pnl = float(e.get("realizedPnlUsdt") or 0)
        reason = e.get("reason") or ""
        reason_txt = f" • reason={reason}" if reason else ""
        return f"{ts} • EXIT {side} {sym} • qty={qty:.6f} @ {price:.2f} • pnl={pnl:.2f} USDT{reason_txt}"

    return f"{ts} • {ev}"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _admin_only(update):
        return
    await update.message.reply_text(
        "TradeBot control is online. GRID: /bind /status /summary /trades /pause /resume /panic /mode /set /maxdayloss /maxinvexp /scalpy /fatty /flexy | AI: /ai_status /ai_on /ai_off /ai_review /ai_models /ai_endpoint /ai_model | TREND: /status_trend /summary_trend /trades_trend /pause_trend /resume_trend /panic_trend /mode_trend /set_trend"
    )


async def bind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _admin_only(update):
        return
    s = _read_state()
    s["adminChatId"] = update.effective_chat.id
    _write_state(s)
    await update.message.reply_text(f"Bound adminChatId to this chat: {update.effective_chat.id}")


async def _status_for(update: Update, *, label: str, state: dict, st: dict | None, cum: dict | None):
    base_url = os.getenv("BINANCE_BASE_URL", "(unset)")
    now = datetime.now(timezone.utc).astimezone(_DUBAI_TZ).strftime("%Y-%m-%d %H:%M GST")

    live = "live: (no engine status yet)"
    if st and st.get("price") is not None:
        p = float(st.get("price"))
        eq = float(st.get("equityUsdt") or 0)
        pos = st.get("position")
        if pos:
            live = (
                f"live: price={p:.2f} equity={eq:.2f} USDT\n"
                f"pos: qty={pos['qtyBtc']:.6f} entry={pos['entryPrice']:.2f} uPnL={pos['unrealizedPnlUsdt']:.2f} ({pos['unrealizedPnlPct']*100:.2f}%)\n"
                f"stop={pos['stop']:.2f} tp={pos['tp']:.2f}"
            )
        else:
            live = f"live: price={p:.2f} equity={eq:.2f} USDT (no open position)"

    cumline = "cumulative: (no data yet)"
    if cum:
        tr = int(cum.get("trades", 0))
        wr = (int(cum.get("wins", 0)) / tr) * 100 if tr else 0.0
        cumline = (
            f"cumulative since {cum.get('sinceUtc')}: trades={tr} winrate={wr:.1f}% "
            f"realizedPnL={float(cum.get('realizedPnlUsdt', 0.0)):.2f} USDT"
        )

    msg = (
        f"{label} Status @ {now}\n"
        f"chat={_chat_info(update)}\n"
        f"state.paused={state.get('paused')} mode={state.get('mode')}\n"
        f"symbol={state.get('symbol')} interval={state.get('interval')}\n"
        f"posCap={state.get('positionCapPct')} risk={state.get('riskPerTradePct')} dailyMaxLoss={state.get('maxDailyLossPct')} maxTrades={state.get('maxTradesPerDay')}\n"
        f"base={base_url}\n"
        f"adminChatId={state.get('adminChatId')}\n"
        f"{cumline}\n"
        f"{live}"
    )
    await update.message.reply_text(msg)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _admin_only(update):
        return

    s = _read_state()
    st = _read_status()
    cum = _read_cum()
    await _status_for(update, label="GRID", state=s, st=st, cum=cum)


async def status_trend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _admin_only(update):
        return

    s = _read_state_trend()
    st = _read_status_trend()
    cum = _read_cum_trend()
    await _status_for(update, label="TREND", state=s, st=st, cum=cum)


def _ai_age(ts: str | None) -> str:
    if not ts:
        return "unknown"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
        return f"{(datetime.now(timezone.utc) - dt).total_seconds():.0f}s"
    except Exception:
        return "unknown"


def _normalize_ai_base_url(base_url: str | None) -> str:
    return str(base_url or "").strip().rstrip("/")


def _ai_endpoint_key(state: dict) -> str:
    selected = state.get("aiEndpointKey")
    if selected in AI_ENDPOINT_BY_KEY:
        if selected != "custom":
            selected_url = _normalize_ai_base_url(AI_ENDPOINT_BY_KEY[selected]["baseUrl"])
            state_url = _normalize_ai_base_url(state.get("aiBaseUrl") or "")
            if state_url and state_url != selected_url:
                return "custom"
        return str(selected)
    base_url = _normalize_ai_base_url(state.get("aiBaseUrl") or os.getenv("TRADEBOT_AI_BASE_URL") or "")
    for endpoint in AI_ENDPOINTS:
        if endpoint["key"] != "custom" and _normalize_ai_base_url(endpoint["baseUrl"]) == base_url:
            return endpoint["key"]
    return "custom"


def _active_ai_endpoint(state: dict) -> dict:
    key = _ai_endpoint_key(state)
    endpoint = dict(AI_ENDPOINT_BY_KEY.get(key) or AI_ENDPOINT_BY_KEY["custom"])
    if key == "custom":
        endpoint["baseUrl"] = _normalize_ai_base_url(state.get("aiBaseUrl") or os.getenv("TRADEBOT_AI_BASE_URL") or "")
        endpoint["provider"] = str(state.get("aiProvider") or endpoint.get("provider") or "ollama")
    return endpoint


def _ai_model_urls(base_url: str) -> list[str]:
    base_url = _normalize_ai_base_url(base_url)
    if not base_url:
        return []
    urls = [f"{base_url}/models"]
    if base_url.endswith("/v1"):
        urls.append(f"{base_url[:-3]}/api/tags")
    else:
        urls.append(f"{base_url}/v1/models")
        urls.append(f"{base_url}/api/tags")
    return urls


def _extract_ai_model_names(payload: dict) -> list[str]:
    items = payload.get("data") or payload.get("models") or []
    names = []
    for item in items:
        if isinstance(item, dict):
            name = item.get("id") or item.get("name") or item.get("model")
            if name:
                names.append(str(name))
        elif item:
            names.append(str(item))
    return list(dict.fromkeys(names))


def _list_ai_models_for_url(base_url: str) -> list[str]:
    for url in _ai_model_urls(base_url):
        try:
            response = requests.get(url, timeout=(0.35, 0.8))
            response.raise_for_status()
            return _extract_ai_model_names(response.json())
        except Exception:
            continue
    return []


def _list_ai_models(state: dict) -> list[str]:
    return _list_ai_models_for_url(_active_ai_endpoint(state).get("baseUrl", ""))


async def ai_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _admin_only(update):
        return
    state = _read_state()
    signal = _read_ai_signal() or {}
    status_payload = _read_status() or {}
    status_ai = ((status_payload.get("stats") or {}).get("ai") or {})
    ai = signal or status_ai
    endpoint = _active_ai_endpoint(state)
    msg = (
        "GRID AI Status\n"
        f"enabled={state.get('aiEnabled')} dryRun={state.get('aiDryRun', False)} shadow={state.get('aiShadowMode', False)}\n"
        f"endpoint={endpoint.get('label')} provider={state.get('aiProvider')} base={state.get('aiBaseUrl')}\n"
        f"quick={state.get('aiQuickModel') or state.get('aiModel')} deep={state.get('aiDeepModel') or state.get('aiFallbackModel') or state.get('aiModel')}\n"
        f"decision={ai.get('decisionId', '--')} age={_ai_age(ai.get('tsUtc'))} stale={ai.get('stale', False)}\n"
        f"action={ai.get('riskAction', '--')} gridAllowed={ai.get('gridAllowed', '--')} confidence={float(ai.get('confidence') or 0):.2f}\n"
        f"regime={ai.get('regime', '--')} bias={ai.get('directionBias', '--')} model={ai.get('model', '--')}\n"
        f"note={ai.get('note', '')[:600]}"
    )
    await update.message.reply_text(msg)


async def ai_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _admin_only(update):
        return
    state = _read_state()
    state["aiEnabled"] = True
    _write_state(state)
    await update.message.reply_text("GRID AI enabled. The sidecar will publish the next local decision on its poll interval.")


async def ai_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _admin_only(update):
        return
    state = _read_state()
    state["aiEnabled"] = False
    _write_state(state)
    await update.message.reply_text("GRID AI disabled.")


async def ai_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _admin_only(update):
        return
    state = _read_state()
    state["aiForceReviewNonce"] = datetime.now(timezone.utc).isoformat()
    _write_state(state)
    await update.message.reply_text("GRID AI review requested. The sidecar will pick it up on the next poll.")


async def ai_models(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _admin_only(update):
        return
    state = _read_state()
    active_key = _active_ai_endpoint(state).get("key")
    blocks = []
    for endpoint in AI_ENDPOINTS:
        if endpoint["key"] == "custom" and active_key != "custom":
            continue
        base_url = endpoint["baseUrl"] or state.get("aiBaseUrl") or ""
        names = _list_ai_models_for_url(base_url)
        marker = " (active)" if endpoint["key"] == active_key else ""
        if names:
            blocks.append(f"{endpoint['label']}{marker}:\n" + "\n".join(f"- {name}" for name in names[:25]))
        else:
            blocks.append(f"{endpoint['label']}{marker}: no models found at {base_url or '(unset)'}")
    await update.message.reply_text("GRID AI models\n" + "\n\n".join(blocks))


async def ai_endpoint(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _admin_only(update):
        return
    state = _read_state()
    if not context.args:
        current = _active_ai_endpoint(state)
        lines = [f"Current: {current.get('label')} -> {current.get('baseUrl') or '(unset)'}", "Use /ai_endpoint local, /ai_endpoint gpu, /ai_endpoint cpu, or /ai_endpoint custom http://host:port/v1"]
        lines.extend(f"- {ep['key']}: {ep['label']} -> {ep['baseUrl'] or '(custom URL)'}" for ep in AI_ENDPOINTS)
        await update.message.reply_text("\n".join(lines))
        return
    requested = AI_ENDPOINT_ALIASES.get(context.args[0].strip().lower())
    if not requested:
        await update.message.reply_text("Unknown endpoint. Use local, gpu, cpu, or custom.")
        return
    endpoint = AI_ENDPOINT_BY_KEY[requested]
    state["aiEndpointKey"] = requested
    state["aiProvider"] = endpoint.get("provider") or "ollama"
    if requested == "custom":
        if len(context.args) < 2:
            await update.message.reply_text("Usage: /ai_endpoint custom http://host:port/v1")
            return
        state["aiBaseUrl"] = _normalize_ai_base_url(context.args[1])
    else:
        state["aiBaseUrl"] = endpoint["baseUrl"]
    _write_state(state)
    await update.message.reply_text(f"GRID AI endpoint set to {endpoint['label']} -> {state['aiBaseUrl']}")


async def ai_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _admin_only(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /ai_model <ollama-model-name>")
        return
    model = " ".join(context.args).strip()
    state = _read_state()
    state["aiModel"] = model
    state["aiQuickModel"] = model
    state["aiDeepModel"] = model
    state["aiFallbackModel"] = model
    _write_state(state)
    await update.message.reply_text(f"GRID AI model set to {model} for primary, quick, deep, and fallback roles.")


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # GRID summary
    if not _admin_only(update):
        return

    await status(update, context)

    events = _tail_trade_events(5, TRADES_PATH)
    if events:
        lines = "\n".join(f"- {_fmt_trade(e)}" for e in events)
        await update.message.reply_text(f"GRID recent trades:\n{lines}")


async def summary_trend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # TREND summary
    if not _admin_only(update):
        return

    await status_trend(update, context)

    events = _tail_trade_events(5, TRADES_TREND_PATH)
    if events:
        lines = "\n".join(f"- {_fmt_trade(e)}" for e in events)
        await update.message.reply_text(f"TREND recent trades:\n{lines}")


def _compute_trade_totals() -> dict:
    out = {"buys": 0, "buyUsdt": 0.0, "sells": 0, "sellUsdt": 0.0}
    try:
        if not os.path.exists(TRADES_PATH):
            return out
        with open(TRADES_PATH, "r", encoding="utf-8") as f:
            for ln in f.read().splitlines():
                if not ln.strip():
                    continue
                try:
                    e = json.loads(ln)
                except Exception:
                    continue
                if e.get("event") not in ("ENTER", "EXIT"):
                    continue
                side = e.get("side")
                notional = float(e.get("notionalUsdt", 0.0))
                if side == "BUY":
                    out["buys"] += 1
                    out["buyUsdt"] += notional
                elif side == "SELL":
                    out["sells"] += 1
                    out["sellUsdt"] += notional
    except Exception:
        pass
    return out


async def hourly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _admin_only(update):
        return

    st = _read_status()
    cum = _read_cum() or {}
    totals = _compute_trade_totals()

    realized = float(cum.get("realizedPnlUsdt", 0.0))
    unreal = 0.0
    if st and st.get("position"):
        unreal = float(st["position"].get("unrealizedPnlUsdt", 0.0))

    recs = ["Next upgrades: fee/slippage model + persist position across restarts + regime filter."]

    msg = (
        f"Hourly Update (paper)\n"
        f"Realized PnL: {realized:.2f} USDT\n"
        f"Unrealized PnL: {unreal:.2f} USDT\n"
        f"BUY trades: {totals['buys']} | USDT spent: {totals['buyUsdt']:.2f}\n"
        f"SELL trades: {totals['sells']} | USDT received: {totals['sellUsdt']:.2f}\n"
        f"Recommendations:\n- " + "\n- ".join(recs)
    )
    await update.message.reply_text(msg)


def _ordinal(n: int) -> str:
    if 10 <= (n % 100) <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


_DUBAI_TZ = ZoneInfo("Asia/Dubai")


def _fmt_day(dt: datetime) -> str:
    # Example: 18th Feb '25 (Dubai time)
    dt = dt.astimezone(_DUBAI_TZ)
    return f"{_ordinal(dt.day)} {dt.strftime('%b')} '{dt.strftime('%y')}"


def _fmt_time(dt: datetime) -> str:
    # Example: 12:00 AM (Dubai time)
    dt = dt.astimezone(_DUBAI_TZ)
    return dt.strftime("%I:%M %p").lstrip("0")


def _parse_ts(ts: str) -> datetime:
    # Expect ISO; normalize to UTC (we format into Dubai later)
    try:
        if ts.endswith("Z"):
            ts = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(ts).astimezone(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def _load_all_trade_events(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    out: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for ln in f.read().splitlines():
            if not ln.strip():
                continue
            try:
                e = json.loads(ln)
            except Exception:
                continue
            if e.get("event") in ("ENTER", "EXIT") and e.get("side") in ("BUY", "SELL"):
                # Guard against legacy corrupted events (0-qty / 0-notional fake fills)
                if float(e.get("qtyBtc") or 0) <= 0:
                    continue
                if float(e.get("notionalUsdt") or 0) <= 0:
                    continue
                out.append(e)
    # sort by timestamp
    out.sort(key=lambda e: e.get("tsUtc") or "")
    return out


def _strip_dot_zero(s: str) -> str:
    return s[:-2] if s.endswith(".0") else s


def _fmt_num_k(x: float, decimals: int = 2) -> str:
    ax = abs(x)
    if ax > 999:
        # 1 decimal K shorthand, but drop trailing .0 (e.g., 3.0K -> 3K)
        return _strip_dot_zero(f"{x/1000:.1f}") + "K"

    # Standard fixed decimals, but drop .00 (e.g., 100.00 -> 100)
    s = f"{x:.{decimals}f}"
    if s.endswith(".00"):
        return s[:-3]
    return s


def _fmt_trade_compact(e: dict) -> str:
    dt = _parse_ts(e.get("tsUtc") or "")
    t = _fmt_time(dt)
    sym_full = e.get("symbol") or ""
    sym = sym_full
    if sym_full.endswith("USDT") and len(sym_full) > 4:
        sym = sym_full[:-4]  # BTCUSDT -> BTC

    qty = float(e.get("qtyBtc") or 0)
    px = float(e.get("price") or 0)
    notion = float(e.get("notionalUsdt") or 0)

    # qty: show up to 6 decimals (BTC sizes can be tiny on small accounts)
    qty_txt = f"{qty:.6f}".rstrip("0").rstrip(".")

    px_txt = _fmt_num_k(px, decimals=2)
    notion_txt = _fmt_num_k(notion, decimals=2)

    if e.get("side") == "BUY":
        return f"- {t} {qty_txt} {sym} @ {px_txt} / {notion_txt} USDT"

    pnl = float(e.get("realizedPnlUsdt") or 0)
    pnl_txt = _fmt_num_k(pnl, decimals=2)
    return f"- {t} {qty_txt} {sym} @ {px_txt} / {notion_txt} USDT (pnl {pnl_txt})"


def _split_telegram(text: str, limit: int = 3500) -> list[str]:
    # Split on line boundaries to avoid Telegram 4096 limit.
    if len(text) <= limit:
        return [text]
    parts = []
    buf = []
    size = 0
    for line in text.splitlines(True):
        if size + len(line) > limit and buf:
            parts.append("".join(buf).rstrip())
            buf = []
            size = 0
        buf.append(line)
        size += len(line)
    if buf:
        parts.append("".join(buf).rstrip())
    return parts


async def _trades_for(update: Update, *, label: str, path: str, st: dict | None, cum: dict | None):
    if not _admin_only(update):
        return

    events = _load_all_trade_events(path)
    if not events:
        await update.message.reply_text(f"No {label} trades yet.")
        return

    buys = [e for e in events if e.get("side") == "BUY"]
    sells = [e for e in events if e.get("side") == "SELL"]

    realized = float((cum or {}).get("realizedPnlUsdt", 0.0))
    unreal = 0.0
    if st and st.get("position"):
        unreal = float(st["position"].get("unrealizedPnlUsdt", 0.0))

    header = (
        f"{label} PnL: realized={_fmt_num_k(realized, decimals=2)} USDT | unrealized={_fmt_num_k(unreal, decimals=2)} USDT\n"
        f"{label} Total Trades={len(buys)+len(sells)} BUY={len(buys)} SELL={len(sells)}"
    )

    def build_section(title: str, evs: list[dict]) -> str:
        if not evs:
            return f"{title}=0"
        lines = [f"{title}={len(evs)}"]
        cur_day = None
        for e in evs:
            dt = _parse_ts(e.get("tsUtc") or "")
            day = _fmt_day(dt)
            if day != cur_day:
                lines.append(day)
                cur_day = day
            lines.append(_fmt_trade_compact(e))
        return "\n".join(lines)

    msg = "\n".join([
        header,
        build_section("BUY", buys),
        build_section("SELL", sells),
    ])

    for part in _split_telegram(msg):
        await update.message.reply_text(part)


async def trades(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _trades_for(update, label="GRID", path=TRADES_PATH, st=_read_status(), cum=_read_cum())


async def trades_trend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _trades_for(update, label="TREND", path=TRADES_TREND_PATH, st=_read_status_trend(), cum=_read_cum_trend())


async def pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _admin_only(update):
        return
    s = _read_state()
    s["paused"] = True
    _write_state(s)
    await update.message.reply_text("GRID paused.")


async def pause_trend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _admin_only(update):
        return
    s = _read_state_trend()
    s["paused"] = True
    _write_state_trend(s)
    await update.message.reply_text("TREND paused.")


async def resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _admin_only(update):
        return
    s = _read_state()
    s["paused"] = False
    _write_state(s)
    await update.message.reply_text("GRID resumed.")


async def resume_trend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _admin_only(update):
        return
    s = _read_state_trend()
    s["paused"] = False
    _write_state_trend(s)
    await update.message.reply_text("TREND resumed.")


async def panic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _admin_only(update):
        return
    s = _read_state()
    s["paused"] = True
    _write_state(s)
    await update.message.reply_text("PANIC: GRID paused. (v1 will also cancel orders when live trading is enabled)")


async def panic_trend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _admin_only(update):
        return
    s = _read_state_trend()
    s["paused"] = True
    _write_state_trend(s)
    await update.message.reply_text("PANIC: TREND paused. (v1 will also cancel orders when live trading is enabled)")


async def mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _admin_only(update):
        return
    if not context.args or context.args[0] not in ("paper", "testnet-live"):
        await update.message.reply_text("Usage: /mode paper | /mode testnet-live")
        return
    s = _read_state()
    s["mode"] = context.args[0]
    _write_state(s)
    await update.message.reply_text(f"GRID mode set to {s['mode']}")


async def mode_trend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _admin_only(update):
        return
    if not context.args or context.args[0] not in ("paper", "testnet-live"):
        await update.message.reply_text("Usage: /mode_trend paper | /mode_trend testnet-live")
        return
    s = _read_state_trend()
    s["mode"] = context.args[0]
    _write_state_trend(s)
    await update.message.reply_text(f"TREND mode set to {s['mode']}")


async def _parse_pct_arg(x: str) -> float:
    x = x.strip().replace("%", "")
    v = float(x)
    return v / 100.0 if v > 1 else v


async def set_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _admin_only(update):
        return
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /set <risk|maxloss|maxtrades|poscap> <value>")
        return
    key, val = context.args
    s = _read_state()
    if key == "risk":
        s["riskPerTradePct"] = await _parse_pct_arg(val)
    elif key == "maxloss":
        s["maxDailyLossPct"] = await _parse_pct_arg(val)
    elif key == "maxtrades":
        s["maxTradesPerDay"] = int(float(val))
    elif key == "poscap":
        s["positionCapPct"] = await _parse_pct_arg(val)
    else:
        await update.message.reply_text("Unknown key. Use risk|maxloss|maxtrades|poscap")
        return
    _write_state(s)
    await update.message.reply_text(f"GRID updated {key} -> {val}")


async def maxdayloss(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _admin_only(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /maxdayloss <X%>")
        return
    s = _read_state()
    s["maxDailyLossPct"] = await _parse_pct_arg(context.args[0])
    _write_state(s)
    await update.message.reply_text(f"GRID maxDailyLossPct -> {s['maxDailyLossPct']*100:.1f}%")


async def maxinvexp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _admin_only(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /maxinvexp <Y%>")
        return
    s = _read_state()
    s["gridMaxExposurePct"] = await _parse_pct_arg(context.args[0])
    _write_state(s)
    await update.message.reply_text(f"GRID gridMaxExposurePct -> {s['gridMaxExposurePct']*100:.1f}%")


async def scalpy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _admin_only(update):
        return
    s = _read_state()
    s["gridMode"] = "scalpy"
    _write_state(s)
    await update.message.reply_text("GRID mode -> scalpy")


async def fatty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _admin_only(update):
        return
    s = _read_state()
    s["gridMode"] = "fatty"
    _write_state(s)
    await update.message.reply_text("GRID mode -> fatty")


async def flexy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _admin_only(update):
        return
    s = _read_state()
    s["gridMode"] = "flexy"
    _write_state(s)
    await update.message.reply_text("GRID mode -> flexy (advisor will choose every 15m)")


async def set_trend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _admin_only(update):
        return
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /set_trend <risk|maxloss|maxtrades|poscap> <value>")
        return
    key, val = context.args
    s = _read_state_trend()
    if key == "risk":
        s["riskPerTradePct"] = float(val) / 100.0 if float(val) > 1 else float(val)
    elif key == "maxloss":
        s["maxDailyLossPct"] = float(val) / 100.0 if float(val) > 1 else float(val)
    elif key == "maxtrades":
        s["maxTradesPerDay"] = int(val)
    elif key == "poscap":
        s["positionCapPct"] = float(val) / 100.0 if float(val) > 1 else float(val)
    else:
        await update.message.reply_text("Unknown key. Use risk|maxloss|maxtrades|poscap")
        return
    _write_state_trend(s)
    await update.message.reply_text(f"TREND updated {key} -> {val}")


async def _post_init(app: Application) -> None:
    # Set command menu so typing "/" shows all commands with descriptions.
    commands = [
        BotCommand("start", "Show help"),
        BotCommand("bind", "Bind this chat as admin destination"),

        # GRID
        BotCommand("status", "GRID status"),
        BotCommand("summary", "GRID status + recent trades"),
        BotCommand("trades", "GRID trades + realized/unrealized PnL"),
        BotCommand("pause", "Pause GRID"),
        BotCommand("resume", "Resume GRID"),
        BotCommand("panic", "PANIC pause GRID"),
        BotCommand("mode", "GRID mode: paper | testnet-live"),
        BotCommand("set", "GRID set: risk|maxloss|maxtrades|poscap"),
        BotCommand("maxdayloss", "GRID set max daily loss (e.g. 10%)"),
        BotCommand("maxinvexp", "GRID set max exposure (e.g. 10%)"),
        BotCommand("scalpy", "GRID scalpy: more trades/day"),
        BotCommand("fatty", "GRID fatty: wider spacing"),
        BotCommand("flexy", "GRID flexy: advisor chooses mode"),

        # AI
        BotCommand("ai_status", "GRID local AI status"),
        BotCommand("ai_on", "Enable GRID local AI"),
        BotCommand("ai_off", "Disable GRID local AI"),
        BotCommand("ai_review", "Request next AI review"),
        BotCommand("ai_models", "List GRID AI endpoint models"),
        BotCommand("ai_endpoint", "Set GRID AI endpoint"),
        BotCommand("ai_model", "Set GRID AI model"),

        # TREND
        BotCommand("status_trend", "TREND status"),
        BotCommand("summary_trend", "TREND status + recent trades"),
        BotCommand("trades_trend", "TREND trades + realized/unrealized PnL"),
        BotCommand("pause_trend", "Pause TREND"),
        BotCommand("resume_trend", "Resume TREND"),
        BotCommand("panic_trend", "PANIC pause TREND"),
        BotCommand("mode_trend", "TREND mode: paper | testnet-live"),
        BotCommand("set_trend", "TREND set: risk|maxloss|maxtrades|poscap"),
    ]
    try:
        await app.bot.set_my_commands(commands)
    except Exception:
        # Non-fatal (Telegram permissions / transient API errors)
        pass


def main():
    # Env is loaded at import-time from TRADEBOT_ENV_FILE (defaults to .env)
    token = _required("TELEGRAM_CONTROL_BOT_TOKEN")

    app = Application.builder().token(token).post_init(_post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("bind", bind))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("summary", summary))
    app.add_handler(CommandHandler("hourly", hourly))
    app.add_handler(CommandHandler("trades", trades))
    app.add_handler(CommandHandler("pause", pause))
    app.add_handler(CommandHandler("resume", resume))
    app.add_handler(CommandHandler("panic", panic))
    app.add_handler(CommandHandler("mode", mode))
    app.add_handler(CommandHandler("set", set_cmd))
    app.add_handler(CommandHandler("maxdayloss", maxdayloss))
    app.add_handler(CommandHandler("maxinvexp", maxinvexp))
    app.add_handler(CommandHandler("scalpy", scalpy))
    app.add_handler(CommandHandler("fatty", fatty))
    app.add_handler(CommandHandler("flexy", flexy))
    app.add_handler(CommandHandler("ai_status", ai_status))
    app.add_handler(CommandHandler("ai_on", ai_on))
    app.add_handler(CommandHandler("ai_off", ai_off))
    app.add_handler(CommandHandler("ai_review", ai_review))
    app.add_handler(CommandHandler("ai_models", ai_models))
    app.add_handler(CommandHandler("ai_endpoint", ai_endpoint))
    app.add_handler(CommandHandler("ai_model", ai_model))

    # TREND command set
    app.add_handler(CommandHandler("status_trend", status_trend))
    app.add_handler(CommandHandler("summary_trend", summary_trend))
    app.add_handler(CommandHandler("trades_trend", trades_trend))
    app.add_handler(CommandHandler("pause_trend", pause_trend))
    app.add_handler(CommandHandler("resume_trend", resume_trend))
    app.add_handler(CommandHandler("panic_trend", panic_trend))
    app.add_handler(CommandHandler("mode_trend", mode_trend))
    app.add_handler(CommandHandler("set_trend", set_trend))

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
