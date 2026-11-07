import os
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import streamlit as st
import pandas as pd
import numpy as np
import requests
import plotly.graph_objects as go

from ta.momentum import RSIIndicator
from ta.trend import ADXIndicator
from ta.volatility import AverageTrueRange

# ================= НАСТРОЙКИ =================

st.set_page_config(
    page_title="OKX Terminal Pro",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

OKX = "https://www.okx.com/api/v5"
CANDLES_URL = f"{OKX}/market/candles"
TICKERS_URL = f"{OKX}/market/tickers"
HEADERS = {"User-Agent": "Mozilla/5.0"}

COINS = [
    "BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT",
    "TON", "TRX", "LTC", "NEAR", "APT", "ARBITRUM", "OP", "SUI", "PEPE", "INJ",
]

MIN_LIQUIDITY_USD = 10_000_000
FEE_RATE = 0.0005
DB_FILE = "bots.sqlite3"

# ================= БАЗА ДАННЫХ =================

def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS bots (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            strategy TEXT NOT NULL,
            coin TEXT NOT NULL,
            market TEXT NOT NULL,
            direction TEXT NOT NULL,
            status TEXT NOT NULL,
            settings TEXT NOT NULL,
            position TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            bot_id TEXT NOT NULL,
            event TEXT NOT NULL,
            details TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()

init_db()

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def save_bot(bot):
    bot["updated_at"] = now_iso()

    conn = get_db()
    conn.execute("""
        INSERT INTO bots
        (id, name, strategy, coin, market, direction, status, settings, position, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name,
            strategy=excluded.strategy,
            coin=excluded.coin,
            market=excluded.market,
            direction=excluded.direction,
            status=excluded.status,
            settings=excluded.settings,
            position=excluded.position,
            updated_at=excluded.updated_at
    """, (
        bot["id"], bot["name"], bot["strategy"], bot["coin"], bot["market"],
        bot["direction"], bot["status"],
        json.dumps(bot["settings"], ensure_ascii=False),
        json.dumps(bot["position"], ensure_ascii=False),
        bot["created_at"], bot["updated_at"],
    ))
    conn.commit()
    conn.close()

def load_bots():
    conn = get_db()
    rows = conn.execute("SELECT * FROM bots ORDER BY updated_at DESC").fetchall()
    conn.close()

    bots = []

    for row in rows:
        bots.append({
            "id": row["id"],
            "name": row["name"],
            "strategy": row["strategy"],
            "coin": row["coin"],
            "market": row["market"],
            "direction": row["direction"],
            "status": row["status"],
            "settings": json.loads(row["settings"] or "{}"),
            "position": json.loads(row["position"] or "{}"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        })

    return bots

def delete_bot(bot_id):
    conn = get_db()
    conn.execute("DELETE FROM bots WHERE id = ?", (bot_id,))
    conn.execute("DELETE FROM events WHERE bot_id = ?", (bot_id,))
    conn.commit()
    conn.close()

def add_event(bot_id, event, details):
    conn = get_db()
    conn.execute(
        "INSERT INTO events (id, bot_id, event, details, created_at) VALUES (?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), bot_id, event, details, now_iso()),
    )
    conn.commit()
    conn.close()

def load_events(bot_id, limit=30):
    conn = get_db()
    rows = conn.execute(
        "SELECT event, details, created_at FROM events WHERE bot_id = ? ORDER BY created_at DESC LIMIT ?",
        (bot_id, limit),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]

def export_backup():
    conn = get_db()
    bots = [dict(row) for row in conn.execute("SELECT * FROM bots").fetchall()]
    events = [dict(row) for row in conn.execute("SELECT * FROM events").fetchall()]
    conn.close()

    for bot in bots:
        bot["settings"] = json.loads(bot["settings"] or "{}")
        bot["position"] = json.loads(bot["position"] or "{}")

    return {
        "exported_at": now_iso(),
        "version": 1,
        "bots": bots,
        "events": events,
    }

def import_backup(data):
    if not isinstance(data, dict) or "bots" not in data:
        raise ValueError("Неверный файл резервной копии.")

    conn = get_db()

    for bot in data["bots"]:
        bot.setdefault("id", str(uuid.uuid4()))
        bot.setdefault("created_at", now_iso())
        bot.setdefault("updated_at", now_iso())
        bot.setdefault("status", "Активен")
        bot.setdefault("settings", {})
        bot.setdefault("position", {})

        conn.execute("""
            INSERT OR REPLACE INTO bots
            (id, name, strategy, coin, market, direction, status, settings, position, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            bot["id"], bot["name"], bot["strategy"], bot["coin"], bot["market"],
            bot["direction"], bot["status"],
            json.dumps(bot["settings"], ensure_ascii=False),
            json.dumps(bot["position"], ensure_ascii=False),
            bot["created_at"], bot["updated_at"],
        ))

    for event in data.get("events", []):
        conn.execute("""
            INSERT OR IGNORE INTO events (id, bot_id, event, details, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            event.get("id", str(uuid.uuid4())),
            event.get("bot_id"),
            event.get("event", ""),
            event.get("details", ""),
            event.get("created_at", now_iso()),
        ))

    conn.commit()
    conn.close()

# ================= ДИЗАЙН =================

st.markdown("""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">

<style>
:root {
    --bg-1: #05070c;
    --bg-2: #080b12;
    --panel: rgba(17, 22, 33, 0.72);
    --border: rgba(255, 255, 255, 0.08);
    --accent: #00ff9d;
    --accent-2: #00c2ff;
    --violet: #8b7bff;
    --red: #ff4d6d;
    --yellow: #ffd166;
    --muted: #8b94a7;
    --text: #e8ecf4;
}

.stApp {
    background:
        radial-gradient(1100px 650px at 5% -10%, rgba(0, 255, 157, 0.10), transparent 60%),
        radial-gradient(900px 600px at 100% 0%, rgba(139, 123, 255, 0.13), transparent 55%),
        radial-gradient(800px 600px at 50% 120%, rgba(0, 194, 255, 0.09), transparent 60%),
        linear-gradient(180deg, var(--bg-1) 0%, var(--bg-2) 100%);
    color: var(--text);
    font-family: 'Inter', sans-serif;
}

h1, h2, h3, h4, p, label, span, div {
    font-family: 'Inter', sans-serif;
}

h1 {
    font-size: 2.35rem !important;
    font-weight: 900 !important;
    letter-spacing: -0.045em !important;
    margin-bottom: .35rem !important;
}

.glass {
    background: linear-gradient(145deg, rgba(23, 28, 41, 0.82), rgba(10, 13, 21, 0.88));
    border: 1px solid var(--border);
    border-radius: 24px;
    padding: 26px;
    box-shadow: 0 22px 60px rgba(0, 0, 0, 0.42);
    backdrop-filter: blur(20px);
}

.hero {
    position: relative;
    overflow: hidden;
    background:
        radial-gradient(700px 300px at 10% 0%, rgba(0, 255, 157, 0.16), transparent 60%),
        radial-gradient(600px 300px at 95% 10%, rgba(139, 123, 255, 0.18), transparent 60%),
        linear-gradient(145deg, rgba(20, 25, 38, 0.92), rgba(8, 11, 18, 0.94));
    border: 1px solid rgba(255, 255, 255, 0.09);
    border-radius: 28px;
    padding: 34px;
    box-shadow: 0 28px 80px rgba(0, 0, 0, 0.48);
}

.hero-title {
    font-size: 2.7rem;
    font-weight: 900;
    letter-spacing: -0.05em;
    line-height: 1.05;
    margin: 0;
}

.hero-sub {
    color: #aab4c6;
    font-size: 1.05rem;
    max-width: 760px;
    margin-top: 12px;
    line-height: 1.55;
}

.hero-badge {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 7px 14px;
    border-radius: 999px;
    background: rgba(0, 255, 157, 0.10);
    border: 1px solid rgba(0, 255, 157, 0.28);
    color: var(--accent);
    font-size: .8rem;
    font-weight: 800;
    letter-spacing: .04em;
    text-transform: uppercase;
}

.metric-card {
    background: linear-gradient(145deg, rgba(23, 28, 41, 0.86), rgba(10, 13, 21, 0.90));
    border: 1px solid var(--border);
    border-radius: 20px;
    padding: 20px;
    box-shadow: 0 16px 40px rgba(0, 0, 0, 0.35);
    transition: transform .22s ease, border-color .22s ease, box-shadow .22s ease;
}

.metric-card:hover {
    transform: translateY(-4px);
    border-color: rgba(0, 255, 157, 0.32);
    box-shadow: 0 20px 48px rgba(0, 255, 157, 0.10);
}

.metric-label {
    color: var(--muted);
    font-size: .76rem;
    font-weight: 800;
    letter-spacing: .11em;
    text-transform: uppercase;
}

.metric-value {
    color: #fff;
    font-size: 1.75rem;
    font-weight: 850;
    margin-top: 8px;
    font-family: 'JetBrains Mono', monospace;
}

.metric-positive { color: var(--accent); }
.metric-negative { color: var(--red); }
.metric-warning { color: var(--yellow); }

.direction-button {
    width: 100%;
    border-radius: 22px;
    padding: 26px 18px;
    text-align: center;
    border: 1px solid var(--border);
    background: linear-gradient(145deg, rgba(23, 28, 41, 0.88), rgba(10, 13, 21, 0.94));
    transition: all .2s ease;
    cursor: pointer;
}

.direction-button:hover {
    transform: translateY(-5px);
    border-color: rgba(255, 255, 255, 0.20);
}

.direction-long {
    border-color: rgba(0, 255, 157, 0.35);
    box-shadow: 0 18px 50px rgba(0, 255, 157, 0.10);
}

.direction-short {
    border-color: rgba(255, 77, 109, 0.35);
    box-shadow: 0 18px 50px rgba(255, 77, 109, 0.10);
}

.direction-neutral {
    border-color: rgba(255, 209, 102, 0.35);
    box-shadow: 0 18px 50px rgba(255, 209, 102, 0.10);
}

.direction-icon {
    font-size: 2.3rem;
    margin-bottom: 10px;
}

.direction-title {
    font-size: 1.35rem;
    font-weight: 900;
    letter-spacing: -0.03em;
}

.direction-text {
    color: #9aa5b8;
    font-size: .9rem;
    margin-top: 6px;
}

.feature {
    background: linear-gradient(145deg, rgba(23, 28, 41, 0.80), rgba(10, 13, 21, 0.90));
    border: 1px solid var(--border);
    border-radius: 20px;
    padding: 20px;
    height: 100%;
    transition: transform .22s ease, border-color .22s ease;
}

.feature:hover {
    transform: translateY(-4px);
    border-color: rgba(0, 194, 255, 0.30);
}

.feature-icon {
    font-size: 1.7rem;
    margin-bottom: 10px;
}

.feature-title {
    font-weight: 800;
    font-size: 1.05rem;
    margin-bottom: 6px;
}

.feature-text {
    color: #9aa5b8;
    font-size: .9rem;
    line-height: 1.5;
}

.pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    border-radius: 999px;
    font-size: .76rem;
    font-weight: 800;
}

.pill-green {
    background: rgba(0, 255, 157, .12);
    color: var(--accent);
    border: 1px solid rgba(0, 255, 157, .30);
}

.pill-red {
    background: rgba(255, 77, 109, .12);
    color: var(--red);
    border: 1px solid rgba(255, 77, 109, .30);
}

.pill-yellow {
    background: rgba(255, 209, 102, .12);
    color: var(--yellow);
    border: 1px solid rgba(255, 209, 102, .30);
}

.pill-gray {
    background: rgba(139, 148, 167, .12);
    color: #b7c0d0;
    border: 1px solid rgba(139, 148, 167, .25);
}

.stButton > button {
    width: 100%;
    border: none;
    border-radius: 14px;
    padding: .72rem 1rem;
    font-weight: 800;
    color: #04120c;
    background: linear-gradient(135deg, var(--accent), var(--accent-2));
    box-shadow: 0 10px 28px rgba(0, 255, 157, 0.16);
    transition: transform .18s ease, filter .18s ease, box-shadow .18s ease;
}

.stButton > button:hover {
    transform: translateY(-2px);
    filter: brightness(1.08);
    box-shadow: 0 14px 34px rgba(0, 255, 157, 0.24);
}

[data-testid="stSidebar"] {
    background: rgba(6, 8, 14, 0.96);
    border-right: 1px solid var(--border);
}

[data-testid="stSidebar"] .stRadio label {
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid transparent;
    border-radius: 14px;
    padding: 10px 12px;
    margin-bottom: 6px;
    transition: all .18s ease;
}

[data-testid="stSidebar"] .stRadio label:hover {
    background: rgba(0, 255, 157, 0.07);
    border-color: rgba(0, 255, 157, 0.20);
}

[data-testid="stDataFrame"] {
    border: 1px solid var(--border);
    border-radius: 16px;
    overflow: hidden;
}

[data-testid="stExpander"] {
    border: 1px solid var(--border);
    border-radius: 16px;
    background: rgba(13, 17, 26, 0.65);
}
</style>
""", unsafe_allow_html=True)

def metric_card(label, value, tone="neutral"):
    cls = {
        "positive": "metric-positive",
        "negative": "metric-negative",
        "warning": "metric-warning",
        "neutral": "",
    }.get(tone, "")

    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value {cls}">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

def pill(text, tone="gray"):
    return f'<span class="pill pill-{tone}">{text}</span>'

# ================= OKX ДАННЫЕ =================

def http_get(url, params=None, timeout=12):
    try:
        response = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except Exception:
        return {"code": "ERROR", "data": []}

def symbol_for(coin, market):
    return f"{coin}-USDT-SWAP" if market == "Фьючерсы (SWAP)" else f"{coin}-USDT"

def inst_type_for(market):
    return "SWAP" if market == "Фьючерсы (SWAP)" else "SPOT"

@st.cache_data(ttl=60, show_spinner=False)
def get_ticker(symbol, market):
    payload = http_get(TICKERS_URL, {"instType": inst_type_for(market), "instId": symbol})
    rows = payload.get("data", [])

    if not rows:
        return None

    row = rows[0]
    price = float(row.get("last", 0) or 0)

    if market == "Фьючерсы (SWAP)":
        volume_usd = float(row.get("volCcy24h", 0) or 0) * price
    else:
        volume_usd = float(row.get("volCcy24h", 0) or 0)

    return {
        "price": price,
        "volume_usd": volume_usd,
        "high24h": float(row.get("high24h", 0) or 0),
        "low24h": float(row.get("low24h", 0) or 0),
    }

@st.cache_data(ttl=120, show_spinner=False)
def get_data(symbol, bar="1D", limit=300):
    payload = http_get(CANDLES_URL, {"instId": symbol, "bar": bar, "limit": str(limit)})

    if payload.get("code") != "0":
        return None

    raw = payload.get("data", [])
    if not raw:
        return None

    raw.reverse()
    columns = ["t", "o", "h", "l", "c", "v", "v1", "v2", "v3"]
    df = pd.DataFrame(raw, columns=columns)

    for column in ["o", "h", "l", "c", "v"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df["t"] = pd.to_numeric(df["t"], errors="coerce")
    df["time"] = pd.to_datetime(df["t"], unit="ms")

    return df.dropna(subset=["o", "h", "l", "c"]).reset_index(drop=True)

def compute_indicators(df):
    df = df.copy()
    df["rsi"] = RSIIndicator(close=df["c"], window=14).rsi()
    df["adx"] = ADXIndicator(high=df["h"], low=df["l"], close=df["c"], window=14).adx()
    df["atr"] = AverageTrueRange(high=df["h"], low=df["l"], close=df["c"], window=14).average_true_range()
    return df

def analyze_coin(coin, market):
    symbol = symbol_for(coin, market)
    df = get_data(symbol, "1D", 120)
    ticker = get_ticker(symbol, market)

    if df is None or len(df) < 20 or not ticker or ticker["price"] <= 0:
        return None

    df = compute_indicators(df)
    last = df.iloc[-1]

    price = float(last["c"])
    rsi = float(last["rsi"]) if pd.notna(last["rsi"]) else 50.0
    adx = float(last["adx"]) if pd.notna(last["adx"]) else 0.0
    atr = float(last["atr"]) if pd.notna(last["atr"]) else 0.0
    atr_pct = atr / price * 100 if price else 0.0

    if adx > 25:
        if rsi < 40:
            signal = "🟢 ЛОНГ"
        elif rsi > 50:
            signal = "⏳ ЖДАТЬ"
        else:
            signal = "🔴 ШОРТ"
    else:
        signal = "🟡 НЕЙТРАЛЬНО"

    return {
        "Монета": coin,
        "Инструмент": symbol,
        "Цена": price,
        "Объём 24ч, $": ticker["volume_usd"],
        "RSI": rsi,
        "ADX": adx,
        "ATR %": atr_pct,
        "Сигнал": signal,
    }

def scan_market(market):
    results = []

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(analyze_coin, coin, market): coin for coin in COINS}

        for future in as_completed(futures):
            try:
                result = future.result()
                if result:
                    results.append(result)
            except Exception:
                pass

    order = {"BTC": 0, "ETH": 1}
    results.sort(key=lambda x: (order.get(x["Монета"], 99), x["Монета"]))
    return results

# ================= TELEGRAM =================

def send_tg(text):
    try:
        token = st.secrets["telegram"]["token"]
        chat_id = st.secrets["telegram"]["chat_id"]
    except Exception:
        token = st.session_state.get("tg_token", "")
        chat_id = st.session_state.get("tg_chat", "")

    if not token or not chat_id:
        return False

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=8,
        )
        return response.status_code == 200
    except Exception:
        return False

def build_event_message(bot, event, details):
    return f"""
<b>{bot['name']}</b>
{bot['coin']} · {bot['strategy']} · {bot['direction']}

<b>Событие:</b>
{event}

<b>Что делать по плану:</b>
{details}

<b>Важно:</b>
Приложение не отправляло торговую команду.
Фактическое добавление маржи или закрытие позиции выполняется на OKX.
""".strip()

# ================= DCA =================

def dca_levels(entry, step_pct, so_count, mart, base_amount):
    levels = []

    for i in range(int(so_count) + 1):
        if i == 0:
            price = float(entry)
            amount = float(base_amount)
        else:
            price = float(entry) * (1 - (step_pct * i) / 100)
            amount = float(base_amount) * (mart ** i)

        levels.append({
            "level": i,
            "price": price,
            "amount": amount,
        })

    return levels

def dca_avg_price(levels):
    total_amount = sum(level["amount"] for level in levels)
    total_cost = sum(level["price"] * level["amount"] for level in levels)

    if total_amount <= 0:
        return 0.0

    return total_cost / total_amount

def dca_status(bot, current_price):
    settings = bot["settings"]
    position = bot["position"]

    entry = float(settings.get("entry", 0) or 0)
    tp_pct = float(settings.get("tp", 1.5) or 1.5)
    step_pct = float(settings.get("step", 2.0) or 2.0)
    so_count = int(settings.get("so_count", 4) or 4)
    mart = float(settings.get("mart", 1.2) or 1.2)
    base_amount = float(settings.get("base_amount", 10.0) or 10.0)
    total_budget = float(settings.get("total_budget", 0) or 0)
    max_loss = float(settings.get("max_loss", 0) or 0)

    direction = bot["direction"]
    avg_price = float(position.get("avg_price", 0) or 0)
    volume = float(position.get("volume", 0) or 0)
    executed_so = int(position.get("executed_so", 0) or 0)
    added_margin = float(position.get("added_margin", 0) or 0)

    levels = dca_levels(entry, step_pct, so_count, mart, base_amount)

    if avg_price > 0:
        used_avg = avg_price
    else:
        used_avg = dca_avg_price(levels[:executed_so + 1])

    if direction == "Long":
        pnl_pct = (current_price - used_avg) / used_avg * 100 if used_avg else 0.0
        pnl_usd = volume * (current_price - used_avg) if volume and used_avg else 0.0
        tp_price = used_avg * (1 + tp_pct / 100) if used_avg else 0.0
    else:
        pnl_pct = (used_avg - current_price) / used_avg * 100 if used_avg else 0.0
        pnl_usd = volume * (used_avg - current_price) if volume and used_avg else 0.0
        tp_price = used_avg * (1 - tp_pct / 100) if used_avg else 0.0

    used_budget = sum(level["amount"] for level in levels[:executed_so + 1]) + added_margin
    remaining_budget = max(0.0, total_budget - used_budget)

    next_so = levels[executed_so + 1] if executed_so < so_count else None

    if max_loss > 0 and pnl_usd <= -max_loss:
        return {
            "action": "Выход по плану",
            "reason": "Достигнут заданный предел убытка.",
            "tone": "red",
            "pnl_pct": pnl_pct,
            "pnl_usd": pnl_usd,
            "tp_price": tp_price,
            "next_so": next_so,
            "remaining_budget": remaining_budget,
        }

    if next_so and (
        (direction == "Long" and current_price <= next_so["price"])
        or (direction == "Short" and current_price >= next_so["price"])
    ):
        return {
            "action": "Проверить на OKX",
            "reason": f"Цена достигла уровня СО {next_so['level']}. Проверь исполнение и обнови позицию.",
            "tone": "yellow",
            "pnl_pct": pnl_pct,
            "pnl_usd": pnl_usd,
            "tp_price": tp_price,
            "next_so": next_so,
            "remaining_budget": remaining_budget,
        }

    if used_avg > 0 and (
        (direction == "Long" and current_price >= tp_price)
        or (direction == "Short" and current_price <= tp_price)
    ):
        return {
            "action": "Проверить на OKX",
            "reason": "Цена достигла TP текущего цикла. Проверь исполнение и начало следующего цикла.",
            "tone": "green",
            "pnl_pct": pnl_pct,
            "pnl_usd": pnl_usd,
            "tp_price": tp_price,
            "next_so": next_so,
            "remaining_budget": remaining_budget,
        }

    if remaining_budget <= 0:
        return {
            "action": "Проверить на OKX",
            "reason": "Лимит бюджета DCA достигнут. Дальнейшее добавление маржи не рекомендуется.",
            "tone": "yellow",
            "pnl_pct": pnl_pct,
            "pnl_usd": pnl_usd,
            "tp_price": tp_price,
            "next_so": next_so,
            "remaining_budget": 0.0,
        }

    return {
        "action": "Не трогать",
        "reason": "TP и следующий СО не достигнуты, лимит бюджета не исчерпан.",
        "tone": "green",
        "pnl_pct": pnl_pct,
        "pnl_usd": pnl_usd,
        "tp_price": tp_price,
        "next_so": next_so,
        "remaining_budget": remaining_budget,
    }

def dca_alternatives(entry, tp, step, so_count, mart, base_amount):
    variants = []

    for label, step_value, so_value, mart_value in [
        ("Консервативный", step, max(1, so_count - 1), 1.0),
        ("Твой план", step, so_count, mart),
        ("Агрессивный", step * 1.5, so_count + 1, mart * 1.2),
    ]:
        levels = dca_levels(entry, step_value, so_value, mart_value, base_amount)

        variants.append({
            "Вариант": label,
            "TP, %": tp,
            "Шаг, %": step_value,
            "СО": so_value,
            "Множитель": mart_value,
            "Общий объём, USDT": round(sum(level["amount"] for level in levels), 2),
            "Средняя цена": round(dca_avg_price(levels), 6),
        })

    return pd.DataFrame(variants)

# ================= GRID =================

def grid_status(bot, current_price):
    settings = bot["settings"]
    position = bot["position"]

    lower = float(settings.get("lower", 0) or 0)
    upper = float(settings.get("upper", 0) or 0)
    total_budget = float(settings.get("total_budget", 0) or 0)
    max_loss = float(settings.get("max_loss", 0) or 0)

    direction = bot["direction"]
    avg_price = float(position.get("avg_price", 0) or 0)
    volume = float(position.get("volume", 0) or 0)
    base_margin = float(position.get("base_margin", 0) or 0)
    added_margin = float(position.get("added_margin", 0) or 0)

    used_budget = base_margin + added_margin
    remaining_budget = max(0.0, total_budget - used_budget)

    if avg_price > 0:
        if direction == "Long":
            pnl_pct = (current_price - avg_price) / avg_price * 100
            pnl_usd = volume * (current_price - avg_price)
        elif direction == "Short":
            pnl_pct = (avg_price - current_price) / avg_price * 100
            pnl_usd = volume * (avg_price - current_price)
        else:
            pnl_pct = 0.0
            pnl_usd = 0.0
    else:
        pnl_pct = 0.0
        pnl_usd = 0.0

    if max_loss > 0 and pnl_usd <= -max_loss:
        return {
            "action": "Выход по плану",
            "reason": "Достигнут заданный предел убытка.",
            "tone": "red",
            "pnl_pct": pnl_pct,
            "pnl_usd": pnl_usd,
            "remaining_budget": remaining_budget,
        }

    if current_price < lower:
        return {
            "action": "Проверить на OKX",
            "reason": "Цена ниже нижней границы Grid. Новые ордера могут не ставиться, но открытая позиция продолжает нести риск.",
            "tone": "red",
            "pnl_pct": pnl_pct,
            "pnl_usd": pnl_usd,
            "remaining_budget": remaining_budget,
        }

    if current_price > upper:
        return {
            "action": "Проверить на OKX",
            "reason": "Цена выше верхней границы Grid. Проверь исполнение и состояние позиции.",
            "tone": "yellow",
            "pnl_pct": pnl_pct,
            "pnl_usd": pnl_usd,
            "remaining_budget": remaining_budget,
        }

    if remaining_budget <= 0:
        return {
            "action": "Проверить на OKX",
            "reason": "Лимит общего бюджета достигнут. Дальнейшее добавление маржи не рекомендуется.",
            "tone": "yellow",
            "pnl_pct": pnl_pct,
            "pnl_usd": pnl_usd,
            "remaining_budget": 0.0,
        }

    return {
        "action": "Не трогать",
        "reason": "Цена внутри диапазона Grid, лимит бюджета не достигнут.",
        "tone": "green",
        "pnl_pct": pnl_pct,
        "pnl_usd": pnl_usd,
        "remaining_budget": remaining_budget,
    }

def grid_alternatives(current_price, lower_pct, upper_pct, grid_count):
    variants = []

    for label, lower_value, upper_value, count in [
        ("Узкий", current_price * (1 - lower_pct / 100), current_price * (1 + upper_pct / 100), grid_count),
        ("Широкий", current_price * (1 - lower_pct * 1.5 / 100), current_price * (1 + upper_pct * 1.5 / 100), grid_count),
        ("Консервативный", current_price * (1 - lower_pct / 100), current_price * (1 + upper_pct / 100), max(3, grid_count - 3)),
    ]:
        if upper_value <= lower_value:
            continue

        step = (upper_value - lower_value) / max(1, count - 1)

        variants.append({
            "Вариант": label,
            "Нижняя граница": round(lower_value, 6),
            "Верхняя граница": round(upper_value, 6),
            "Grid": count,
            "Шаг, %": round(step / current_price * 100, 2),
        })

    return pd.DataFrame(variants)

# ================= БЭКТЕСТ =================

def backtest_dca(symbol, days, tp_pct, step_pct, so_count, mart, bar="1H"):
    bars_needed = min(1000, days * 24)
    df = get_data(symbol, bar, bars_needed)

    if df is None or len(df) < 30:
        return None

    base_amount = 10.0
    position = 0.0
    invested = 0.0
    cycles = 0
    fees = 0.0
    capital = 1000.0
    equity = []

    for i in range(1, len(df)):
        price = float(df["c"].iloc[i])

        if position == 0:
            fee = base_amount * FEE_RATE
            position = (base_amount - fee) / price
            invested = base_amount
            fees += fee

        else:
            avg_price = invested / position

            if price >= avg_price * (1 + tp_pct / 100):
                gross = position * price
                exit_fee = gross * FEE_RATE
                profit = gross - exit_fee - invested

                capital += profit
                fees += exit_fee
                cycles += 1

                position = 0.0
                invested = 0.0

        equity.append(capital + position * price)

    return {
        "Циклов": cycles,
        "Чистая прибыль, USDT": round(capital - 1000, 2),
        "Комиссии, USDT": round(fees, 2),
        "Equity": equity,
    }

def backtest_grid(symbol, days, grid_count, lower_pct, upper_pct, bar="1H"):
    bars_needed = min(1000, days * 24)
    df = get_data(symbol, bar, bars_needed)

    if df is None or len(df) < 30:
        return None

    start_price = float(df["c"].iloc[0])
    lower = start_price * (1 - lower_pct / 100)
    upper = start_price * (1 + upper_pct / 100)

    if upper <= lower:
        return None

    step = (upper - lower) / max(1, grid_count)
    levels = [lower + i * step for i in range(grid_count + 1)]

    capital = 1000.0
    position = 0.0
    invested = 0.0
    cycles = 0
    fees = 0.0
    equity = []

    for i in range(1, len(df)):
        price = float(df["c"].iloc[i])
        high = float(df["h"].iloc[i])
        low = float(df["l"].iloc[i])

        if lower <= price <= upper:
            for level in levels:
                if low <= level <= high:
                    if position == 0:
                        order_size = 10.0
                        fee = order_size * FEE_RATE
                        position = (order_size - fee) / level
                        invested = order_size
                        fees += fee
                        break

                    elif level >= invested / position * 1.01:
                        gross = position * level
                        exit_fee = gross * FEE_RATE
                        profit = gross - exit_fee - invested

                        capital += profit
                        fees += exit_fee
                        cycles += 1

                        position = 0.0
                        invested = 0.0
                        break

        equity.append(capital + position * price)

    return {
        "Циклов": cycles,
        "Чистая прибыль, USDT": round(capital - 1000, 2),
        "Комиссии, USDT": round(fees, 2),
        "Equity": equity,
    }

# ================= СТРАНИЦЫ =================

if "page" not in st.session_state:
    st.session_state["page"] = "1. Главная"

with st.sidebar:
    st.markdown("## ⚡ OKX Terminal")
    st.caption("Анализ, подготовка и контроль ботов OKX")

    page = st.radio(
        "Раздел",
        [
            "1. Главная",
            "2. Сканер",
            "3. Мои боты",
            "4. Новый Grid-бот",
            "5. Новый DCA-бот",
            "6. Журнал",
            "7. Настройки",
        ],
        label_visibility="collapsed",
        key="sidebar_page",
    )

    st.session_state["page"] = page

st.title(page.split(". ", 1)[1])

# ---------- ГЛАВНАЯ ----------

if page == "1. Главная":
    bots = load_bots()

    active_bots = len([bot for bot in bots if bot["status"] != "Закрыт"])
    grid_bots = len([bot for bot in bots if bot["strategy"] == "Grid"])
    dca_bots = len([bot for bot in bots if bot["strategy"] == "DCA"])

    st.markdown("""
    <div class="hero">
        <div class="hero-badge">⚡ OKX Terminal Pro</div>
        <h1 class="hero-title">Твой контроль<br>над крипто-ботами</h1>
        <p class="hero-sub">
            Выбери направление, подготовь Grid или DCA, задай бюджет, резерв маржи и план выхода.
            Приложение помогает контролировать бота и присылает понятные уведомления в Telegram.
        </p>
    </div>
    """, unsafe_allow_html=True)

    st.write("")

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        metric_card("Активные боты", str(active_bots), "positive")

    with c2:
        metric_card("Grid-боты", str(grid_bots), "positive")

    with c3:
        metric_card("DCA-боты", str(dca_bots), "positive")

    with c4:
        metric_card("Режим", "Ручной контроль", "warning")

    st.write("")
    st.markdown("### Выбери направление")

    c1, c2, c3 = st.columns(3)

    with c1:
        if st.button("🟢 ЛОНГ", key="home_long", use_container_width=True):
            st.session_state["selected_direction"] = "Long"
            st.session_state["page"] = "2. Сканер"
            st.rerun()

        st.markdown("""
        <div class="direction-button direction-long">
            <div class="direction-icon">🟢</div>
            <div class="direction-title">ЛОНГ</div>
            <div class="direction-text">Ожидание роста цены</div>
        </div>
        """, unsafe_allow_html=True)

    with c2:
        if st.button("🔴 ШОРТ", key="home_short", use_container_width=True):
            st.session_state["selected_direction"] = "Short"
            st.session_state["page"] = "2. Сканер"
            st.rerun()

        st.markdown("""
        <div class="direction-button direction-short">
            <div class="direction-icon">🔴</div>
            <div class="direction-title">ШОРТ</div>
            <div class="direction-text">Ожидание падения цены</div>
        </div>
        """, unsafe_allow_html=True)

    with c3:
        if st.button("🟡 НЕЙТРАЛЬНО", key="home_neutral", use_container_width=True):
            st.session_state["selected_direction"] = "Neutral"
            st.session_state["page"] = "2. Сканер"
            st.rerun()

        st.markdown("""
        <div class="direction-button direction-neutral">
            <div class="direction-icon">🟡</div>
            <div class="direction-title">НЕЙТРАЛЬНО</div>
            <div class="direction-text">Диапазон и Grid</div>
        </div>
        """, unsafe_allow_html=True)

    st.write("")
    st.markdown("### Как работает приложение")

    c1, c2, c3 = st.columns(3)

    with c1:
        st.markdown("""
        <div class="feature">
            <div class="feature-icon">🔍</div>
            <div class="feature-title">1. Найди идею</div>
            <div class="feature-text">
                Открой Сканер, выбери рынок и посмотри монеты с сигналами,
                ликвидностью, RSI, ADX и волатильностью.
            </div>
        </div>
        """, unsafe_allow_html=True)

    with c2:
        st.markdown("""
        <div class="feature">
            <div class="feature-icon">🧮</div>
            <div class="feature-title">2. Подготовь бота</div>
            <div class="feature-text">
                Создай Grid или DCA, задай бюджет, резерв маржи, TP,
                уровни усреднения и максимальный допустимый убыток.
            </div>
        </div>
        """, unsafe_allow_html=True)

    with c3:
        st.markdown("""
        <div class="feature">
            <div class="feature-icon">🛡️</div>
            <div class="feature-title">3. Контролируй риск</div>
            <div class="feature-text">
                Следи за ценой, PnL и остатком резерва. Получай понятные события
                и принимай решение: не трогать, проверить или выйти по плану.
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.info(
        "Приложение не подключено к торговому API OKX и не закрывает позиции автоматически. "
        "Оно помогает подготовить, контролировать и не терять контроль."
    )

# ---------- СКАНЕР ----------

elif page == "2. Сканер":
    market = st.radio("Рынок:", ["Фьючерсы (SWAP)", "Спот"], horizontal=True)

    if st.button("Сканировать ТОП-20", use_container_width=True):
        with st.spinner("Загружаю данные OKX..."):
            results = scan_market(market)

        if results:
            st.session_state["scan_results"] = pd.DataFrame(results)
        else:
            st.error("Не удалось получить данные OKX.")

    if "scan_results" in st.session_state:
        df = st.session_state["scan_results"]

        st.dataframe(
            df[["Монета", "Цена", "Объём 24ч, $", "RSI", "ADX", "ATR %", "Сигнал"]],
            use_container_width=True,
            hide_index=True,
            height=500,
        )

# ---------- МОИ БОТЫ ----------

elif page == "3. Мои боты":
    bots = load_bots()

    st.markdown('<div class="glass"><div class="section-title">Мои боты</div><div class="section-sub">Карточки сохраняются в базе и не должны исчезать после перезагрузки.</div></div>', unsafe_allow_html=True)
    st.write("")

    if not bots:
        st.info("Ботов пока нет. Создай Grid или DCA-бота в боковом меню.")

    for bot in bots:
        with st.container(border=True):
            c1, c2, c3 = st.columns([3, 1, 1])

            with c1:
                st.markdown(f"### {bot['name']}")
                st.caption(
                    f"{bot['coin']} · {bot['strategy']} · {bot['direction']} · "
                    f"обновлён {bot['updated_at'][:19]}"
                )

            with c2:
                st.markdown(pill(bot["status"], "green"), unsafe_allow_html=True)

            with c3:
                if st.button("Удалить", key=f"delete_{bot['id']}"):
                    delete_bot(bot["id"])
                    st.rerun()

            ticker = get_ticker(symbol_for(bot["coin"], bot["market"]), bot["market"])
            current_price = ticker["price"] if ticker else 0.0

            if bot["strategy"] == "Grid":
                state = grid_status(bot, current_price)
            else:
                state = dca_status(bot, current_price)

            c1, c2, c3, c4 = st.columns(4)

            with c1:
                metric_card("Цена", f"{current_price:.6f}")

            with c2:
                metric_card(
                    "Оценочный PnL",
                    f"{state['pnl_usd']:.2f} USDT",
                    "positive" if state["pnl_usd"] >= 0 else "negative",
                )

            with c3:
                metric_card(
                    "Остаток резерва",
                    f"{state['remaining_budget']:.2f} USDT",
                    "warning" if state["remaining_budget"] <= 0 else "positive",
                )

            with c4:
                metric_card("Действие", state["action"], state["tone"])

            st.info(state["reason"])

            c1, c2, c3 = st.columns(3)

            with c1:
                if st.button("Не трогать", key=f"hold_{bot['id']}", use_container_width=True):
                    bot["status"] = "Не трогать"
                    save_bot(bot)
                    add_event(bot["id"], "Решение: не трогать", "Пользователь подтвердил продолжение плана.")
                    st.rerun()

            with c2:
                if st.button("Проверить на OKX", key=f"check_{bot['id']}", use_container_width=True):
                    bot["status"] = "Проверить на OKX"
                    save_bot(bot)
                    add_event(bot["id"], "Требуется сверка", "Пользователю нужно сверить позицию на OKX.")
                    st.rerun()

            with c3:
                if st.button("Выход по плану", key=f"exit_{bot['id']}", use_container_width=True):
                    bot["status"] = "Выход по плану"
                    save_bot(bot)
                    add_event(bot["id"], "Условие выхода", "Достигнуто условие выхода по плану пользователя.")
                    st.rerun()

            with st.expander("Обновить позицию вручную"):
                position = bot["position"]

                c1, c2, c3 = st.columns(3)
                volume = c1.number_input("Объём позиции", value=float(position.get("volume", 0)), min_value=0.0, key=f"vol_{bot['id']}")
                avg_price = c2.number_input("Средняя цена", value=float(position.get("avg_price", 0)), min_value=0.0, key=f"avg_{bot['id']}")
                liq_price = c3.number_input("Ликвидационная цена", value=float(position.get("liq_price", 0)), min_value=0.0, key=f"liq_{bot['id']}")

                c4, c5 = st.columns(2)
                base_margin = c4.number_input("Базовая маржа", value=float(position.get("base_margin", 0)), min_value=0.0, key=f"base_{bot['id']}")
                added_margin = c5.number_input("Добавленная маржа", value=float(position.get("added_margin", 0)), min_value=0.0, key=f"added_{bot['id']}")

                if bot["strategy"] == "DCA":
                    executed_so = st.number_input(
                        "Исполнено СО",
                        value=int(position.get("executed_so", 0)),
                        min_value=0,
                        step=1,
                        key=f"so_{bot['id']}",
                    )
                else:
                    executed_so = 0

                if st.button("Сохранить сверку", key=f"save_pos_{bot['id']}", use_container_width=True):
                    bot["position"].update({
                        "volume": volume,
                        "avg_price": avg_price,
                        "liq_price": liq_price,
                        "base_margin": base_margin,
                        "added_margin": added_margin,
                        "executed_so": int(executed_so),
                        "last_check": now_iso(),
                    })
                    save_bot(bot)
                    add_event(bot["id"], "Позиция сверена", "Пользователь обновил фактические данные позиции.")
                    st.success("Позиция обновлена.")
                    st.rerun()

            if st.button("Отправить статус в Telegram", key=f"tg_{bot['id']}", use_container_width=True):
                message = build_event_message(bot, f"Статус: {state['action']}", state["reason"])

                if send_tg(message):
                    st.success("Статус отправлен в Telegram.")
                else:
                    st.error("Не удалось отправить сообщение.")

            with st.expander("История событий"):
                events = load_events(bot["id"])

                if not events:
                    st.info("Событий пока нет.")
                else:
                    for event in events:
                        st.markdown(f"**{event['created_at'][:19]}** — {event['event']}")
                        st.caption(event["details"])

# ---------- НОВЫЙ GRID-БОТ ----------

elif page == "4. Новый Grid-бот":
    st.markdown('<div class="glass"><div class="section-title">Новый Grid-бот</div><div class="section-sub">Создай план до запуска на OKX: диапазон, бюджет, резервы и условия выхода.</div></div>', unsafe_allow_html=True)
    st.write("")

    c1, c2, c3 = st.columns(3)
    name = c1.text_input("Название бота", value="Мой Grid")
    coin = c2.text_input("Монета", value="BTC").upper()
    direction = c3.selectbox(
        "Направление",
        ["Long", "Short", "Neutral"],
        index=["Long", "Short", "Neutral"].index(
            st.session_state.get("selected_direction", "Neutral")
        ),
    )

    c1, c2, c3 = st.columns(3)
    current_price = c1.number_input("Текущая цена", value=100.0, min_value=0.0)
    lower_pct = c2.number_input("Нижняя граница, % ниже цены", value=10.0, min_value=0.0)
    upper_pct = c3.number_input("Верхняя граница, % выше цены", value=10.0, min_value=0.0)

    lower = current_price * (1 - lower_pct / 100)
    upper = current_price * (1 + upper_pct / 100)

    c1, c2, c3 = st.columns(3)
    grids = c1.number_input("Количество Grid", value=10, min_value=2, step=1)
    base_margin = c2.number_input("Базовая маржа, USDT", value=100.0, min_value=0.0)
    reserve = c3.number_input("Резерв маржи, USDT", value=50.0, min_value=0.0)

    c1, c2 = st.columns(2)
    total_budget = c1.number_input("Максимальный общий бюджет, USDT", value=150.0, min_value=0.0)
    max_loss = c2.number_input("Максимальный допустимый убыток, USDT", value=30.0, min_value=0.0)

    st.markdown("### Альтернативы Grid")

    st.dataframe(
        grid_alternatives(current_price, lower_pct, upper_pct, int(grids)),
        use_container_width=True,
        hide_index=True,
    )

    st.info(
        "Альтернативы показывают разные диапазоны и количество уровней. "
        "Они не гарантируют прибыль и не учитывают ликвидацию, funding и исполнение ордеров."
    )

    if st.button("Сохранить Grid-бота", use_container_width=True):
        if upper <= lower:
            st.error("Верхняя граница должна быть выше нижней.")
        elif total_budget < base_margin + reserve:
            st.error("Общий бюджет должен быть не меньше базовой маржи и резерва.")
        else:
            bot = {
                "id": str(uuid.uuid4()),
                "name": name,
                "strategy": "Grid",
                "coin": coin,
                "market": "Фьючерсы (SWAP)",
                "direction": direction,
                "status": "Активен",
                "settings": {
                    "lower": lower,
                    "upper": upper,
                    "grids": grids,
                    "base_margin": base_margin,
                    "reserve": reserve,
                    "total_budget": total_budget,
                    "max_loss": max_loss,
                },
                "position": {
                    "volume": 0.0,
                    "avg_price": 0.0,
                    "liq_price": 0.0,
                    "base_margin": base_margin,
                    "added_margin": 0.0,
                    "last_check": "",
                },
                "created_at": now_iso(),
            }

            save_bot(bot)
            add_event(bot["id"], "Grid-бот создан", "Сохранены диапазон, бюджет, резервы и условия выхода.")
            st.success("Grid-бот сохранён.")
            st.rerun()

# ---------- НОВЫЙ DCA-БОТ ----------

elif page == "5. Новый DCA-бот":
    st.markdown('<div class="glass"><div class="section-title">Новый DCA-бот</div><div class="section-sub">Создай план до запуска на OKX: TP, СО, бюджет, резерв и условия выхода.</div></div>', unsafe_allow_html=True)
    st.write("")

    c1, c2, c3 = st.columns(3)
    name = c1.text_input("Название бота", value="Мой DCA")
    coin = c2.text_input("Монета", value="BTC").upper()
    direction = c3.selectbox(
        "Направление",
        ["Long", "Short"],
        index=["Long", "Short"].index(
            st.session_state.get("selected_direction", "Long")
            if st.session_state.get("selected_direction", "Long") in ["Long", "Short"]
            else "Long"
        ),
    )

    c1, c2, c3, c4 = st.columns(4)
    entry = c1.number_input("Цена входа", value=100.0, min_value=0.0)
    tp = c2.number_input("TP, %", value=1.5, step=0.1)
    step = c3.number_input("Шаг, %", value=2.0, step=0.1)
    so_count = c4.number_input("Количество СО", value=4, min_value=0, step=1)

    c1, c2, c3 = st.columns(3)
    mart = c1.number_input("Множитель СО", value=1.2, step=0.1)
    base_amount = c2.number_input("Первый ордер, USDT", value=10.0, min_value=0.0)
    total_budget = c3.number_input("Общий бюджет, USDT", value=100.0, min_value=0.0)

    c1, c2 = st.columns(2)
    reserve = c1.number_input("Резерв маржи, USDT", value=50.0, min_value=0.0)
    max_loss = c2.number_input("Максимальный допустимый убыток, USDT", value=30.0, min_value=0.0)

    levels = dca_levels(entry, step, so_count, mart, base_amount)
    planned_avg = dca_avg_price(levels)

    st.markdown("### План DCA")

    st.dataframe(
        pd.DataFrame(levels).rename(columns={
            "level": "Уровень",
            "price": "Цена",
            "amount": "Сумма, USDT",
        }),
        use_container_width=True,
        hide_index=True,
    )

    c1, c2, c3 = st.columns(3)

    with c1:
        metric_card("Первый ордер", f"{base_amount:.2f} USDT")

    with c2:
        metric_card("Общий объём", f"{sum(level['amount'] for level in levels):.2f} USDT")

    with c3:
        metric_card("Средняя цена", f"{planned_avg:.6f}")

    st.markdown("### Альтернативы DCA")

    st.dataframe(
        dca_alternatives(entry, tp, step, so_count, mart, base_amount),
        use_container_width=True,
        hide_index=True,
    )

    st.info(
        "Альтернативы показывают разные параметры усреднения. "
        "Они не гарантируют прибыль и не учитывают ликвидацию, funding и исполнение ордеров."
    )

    if st.button("Сохранить DCA-бота", use_container_width=True):
        if entry <= 0:
            st.error("Цена входа должна быть больше нуля.")
        elif total_budget < sum(level["amount"] for level in levels):
            st.error("Общий бюджет меньше суммы всех запланированных ордеров.")
        else:
            bot = {
                "id": str(uuid.uuid4()),
                "name": name,
                "strategy": "DCA",
                "coin": coin,
                "market": "Фьючерсы (SWAP)",
                "direction": direction,
                "status": "Активен",
                "settings": {
                    "entry": entry,
                    "tp": tp,
                    "step": step,
                    "so_count": so_count,
                    "mart": mart,
                    "base_amount": base_amount,
                    "total_budget": total_budget,
                    "reserve": reserve,
                    "max_loss": max_loss,
                },
                "position": {
                    "volume": 0.0,
                    "avg_price": 0.0,
                    "liq_price": 0.0,
                    "base_margin": base_amount,
                    "added_margin": 0.0,
                    "executed_so": 0,
                    "last_check": "",
                },
                "created_at": now_iso(),
            }

            save_bot(bot)
            add_event(bot["id"], "DCA-бот создан", "Сохранены план усреднения, бюджет и условия выхода.")
            st.success("DCA-бот сохранён.")
            st.rerun()

# ---------- ЖУРНАЛ ----------

elif page == "6. Журнал":
    st.markdown('<div class="glass"><div class="section-title">Журнал решений</div><div class="section-sub">Здесь сохраняются решения и события по ботам.</div></div>', unsafe_allow_html=True)
    st.write("")

    conn = get_db()
    events = conn.execute("""
        SELECT b.name, e.event, e.details, e.created_at
        FROM events e
        JOIN bots b ON b.id = e.bot_id
        ORDER BY e.created_at DESC
        LIMIT 200
    """).fetchall()
    conn.close()

    if not events:
        st.info("Событий пока нет.")
    else:
        st.dataframe(pd.DataFrame(events), use_container_width=True, hide_index=True, height=500)

# ---------- НАСТРОЙКИ ----------

elif page == "7. Настройки":
    st.markdown('<div class="glass"><div class="section-title">Настройки</div><div class="section-sub">Telegram и резервное копирование.</div></div>', unsafe_allow_html=True)
    st.write("")

    try:
        st.secrets["telegram"]["token"]
        st.secrets["telegram"]["chat_id"]
        st.success("Telegram найден в Secrets.")
    except Exception:
        st.warning("Telegram не настроен в Secrets. Можно ввести данные для текущей сессии.")
        st.session_state["tg_token"] = st.text_input("Bot Token", value=st.session_state.get("tg_token", ""), type="password")
        st.session_state["tg_chat"] = st.text_input("Chat ID", value=st.session_state.get("tg_chat", ""))

    if st.button("Тест Telegram", use_container_width=True):
        if send_tg("OKX Terminal Pro подключён ✅"):
            st.success("Тестовое сообщение отправлено.")
        else:
            st.error("Не удалось отправить сообщение.")

    st.markdown("### Резервная копия")

    backup = export_backup()

    st.download_button(
        "Скачать резервную копию JSON",
        data=json.dumps(backup, ensure_ascii=False, indent=2),
        file_name=f"okx_bots_backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json",
        mime="application/json",
        use_container_width=True,
    )

    uploaded = st.file_uploader("Восстановить из JSON", type=["json"])

    if uploaded and st.button("Восстановить ботов", use_container_width=True):
        try:
            import_backup(json.loads(uploaded.getvalue()))
            st.success("Боты восстановлены.")
            st.rerun()
        except Exception as error:
            st.error(f"Ошибка восстановления: {error}")
