import hashlib
import html
import json
import sqlite3
import threading
import time
import uuid

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

from plotly.subplots import make_subplots
from ta.momentum import RSIIndicator
from ta.trend import ADXIndicator
from ta.volatility import AverageTrueRange


# ============================================================
# CONFIG
# ============================================================

st.set_page_config(
    page_title="OKX Bot Manager",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="auto",
)

API = "https://www.okx.com/api/v5"
DB_FILE = "bots.sqlite3"
ENGINE_VERSION = "manager-v3"

GREEN = "#00E5A8"
RED = "#FF5977"
BLUE = "#5ABEFF"
YELLOW = "#FFD166"

COINS = [
    "BTC", "ETH", "SOL", "BNB", "XRP",
    "DOGE", "ADA", "AVAX", "LINK", "DOT",
    "TON", "TRX", "LTC", "NEAR", "APT",
    "ARB", "OP", "SUI", "PEPE", "INJ",
]

BARS = {
    "15m": 900_000,
    "30m": 1_800_000,
    "1H": 3_600_000,
    "4H": 14_400_000,
    "1Dutc": 86_400_000,
}

PAGES = [
    "🏠 Главная",
    "📡 Сканер",
    "🧠 ИИ-Центр",
    "🤖 Мои боты",
    "📚 Журнал решений",
    "⚙️ Настройки",
]


# ============================================================
# DESIGN
# ============================================================

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

:root {
    color-scheme: dark;
}

html, body, .stApp {
    font-family: Inter, sans-serif;
}

.stApp {
    color: #E9F0FC;
    background:
        radial-gradient(
            900px 500px at 0% 0%,
            rgba(0, 229, 168, .075),
            transparent 65%
        ),
        radial-gradient(
            800px 450px at 100% 0%,
            rgba(90, 190, 255, .06),
            transparent 65%
        ),
        #070B13;
}

[data-testid="stHeader"] {
    background: #0B111D !important;
}

[data-testid="stSidebar"],
[data-testid="stSidebar"] > div {
    background: #0C1220 !important;
    opacity: 1 !important;
}

[data-testid="stSidebar"] {
    border-right: 1px solid #223149;
}

h1, h2, h3, h4 {
    color: #F2F7FF !important;
    letter-spacing: -.025em;
}

[data-testid="stMarkdownContainer"] p,
[data-testid="stWidgetLabel"] p,
[data-testid="stCaptionContainer"] p,
[data-testid="stRadio"] p,
[data-testid="stCheckbox"] p {
    color: #D2DDF0 !important;
}

[data-testid="stSidebar"] [data-testid="stRadio"] label {
    background: #141E30 !important;
    border: 1px solid #283953;
    border-radius: 13px;
    padding: 10px 12px;
    margin-bottom: 7px;
    transition: border-color .2s ease, background .2s ease;
}

[data-testid="stSidebar"] [data-testid="stRadio"] label:hover {
    background: #1A2940 !important;
    border-color: #00E5A8;
}

[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input {
    background: #121D2F !important;
    color: #F0F6FF !important;
    -webkit-text-fill-color: #F0F6FF !important;
    caret-color: #00E5A8;
}

[data-testid="stNumberInput"] button {
    background: #1A2A42 !important;
    color: #F0F6FF !important;
}

[data-baseweb="select"] > div,
[role="listbox"],
[role="option"] {
    background: #121D2F !important;
    color: #F0F6FF !important;
}

[data-baseweb="select"] span {
    color: #F0F6FF !important;
}

.stButton > button,
.stFormSubmitButton > button {
    min-height: 45px;
    border: 0 !important;
    border-radius: 12px !important;
    background:
        linear-gradient(110deg, #00E5A8, #50BFFF) !important;
    transition: transform .18s ease, box-shadow .18s ease;
}

.stButton > button p,
.stFormSubmitButton > button p {
    color: #04131D !important;
    font-weight: 750 !important;
}

.stButton > button:hover,
.stFormSubmitButton > button:hover {
    transform: translateY(-2px);
    box-shadow: 0 10px 28px rgba(0,229,168,.17);
}

.stDownloadButton > button {
    background: #17263C !important;
    border: 1px solid #345375 !important;
    border-radius: 12px !important;
}

.stDownloadButton > button p {
    color: #E9F0FC !important;
}

.hero {
    background:
        linear-gradient(
            120deg,
            rgba(0,229,168,.11),
            rgba(90,190,255,.065)
        ),
        #101827;
    border: 1px solid #29425A;
    border-radius: 22px;
    padding: 25px;
    margin-bottom: 22px;
}

.hero-title {
    color: #F2F7FF;
    font-size: 1.6rem;
    font-weight: 800;
    margin-bottom: 9px;
}

.hero-text {
    color: #B7C8E0;
    line-height: 1.6;
}

.bot-card {
    background: linear-gradient(140deg, #152136, #101725);
    border: 1px solid #293B56;
    border-radius: 18px;
    padding: 19px;
    margin-top: 8px;
    margin-bottom: 10px;
}

.bot-name {
    color: #F2F7FF;
    font-size: 1.12rem;
    font-weight: 750;
    margin-bottom: 8px;
}

.bot-meta {
    color: #AFC0D9;
    font-size: .9rem;
    line-height: 1.7;
}

.badge {
    display: inline-block;
    padding: 4px 10px;
    margin: 3px 5px 3px 0;
    border-radius: 999px;
    background: #1B3045;
    border: 1px solid #35506B;
    color: #D6E8FC;
    font-size: .77rem;
}

[data-testid="stMetric"] {
    background: linear-gradient(140deg, #152136, #101725);
    border: 1px solid #293B56;
    border-radius: 16px;
    padding: 17px;
}

[data-testid="stMetricLabel"] p,
[data-testid="stMetricValue"] {
    color: #E9F0FC !important;
}

[data-testid="stDataFrame"] {
    border: 1px solid #293B56;
    border-radius: 12px;
    overflow: hidden;
}

@media(max-width:768px) {
    .block-container {
        padding: 1rem 1rem 4rem !important;
    }

    h1 {
        font-size: 1.9rem !important;
    }

    .hero {
        padding: 19px;
    }

    .hero-title {
        font-size: 1.35rem;
    }
}
</style>
""",
    unsafe_allow_html=True,
)


# ============================================================
# HELPERS
# ============================================================

def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def hero(title, text):
    st.markdown(
        '<div class="hero">'
        f'<div class="hero-title">{html.escape(str(title))}</div>'
        f'<div class="hero-text">{html.escape(str(text))}</div>'
        '</div>',
        unsafe_allow_html=True,
    )


def show_figure(fig, height=420):
    fig.update_layout(
        template="plotly_dark",
        height=height,
        paper_bgcolor="#0D1523",
        plot_bgcolor="#0D1523",
        font=dict(color="#E5EEFC"),
        margin=dict(l=15, r=15, t=50, b=25),
    )
    fig.update_xaxes(gridcolor="#22334B")
    fig.update_yaxes(gridcolor="#22334B")

    st.plotly_chart(
        fig,
        use_container_width=True,
        config={"displaylogo": False},
    )


def default_config(seed=None):
    config = {
        "market": "Спот",
        "strategy": "DCA",
        "side": "Long",
        "symbol": "BTC-USDT",
        "budget": 100.0,
        "leverage": 1.0,
        "base": 10.0,
        "safety": 12.0,
        "so": 4,
        "step": 2.0,
        "step_mult": 1.0,
        "amount_mult": 1.2,
        "tp": 1.5,
        "lower": 90.0,
        "upper": 110.0,
        "grids": 10,
        "grid_type": "Арифметическая",
        "stop": 0.0,
        "fee": 0.05,
        "loss_limit": 10.0,
        "liq_warning": 15.0,
        "stale_hours": 24.0,
        "notify": True,
    }
    if seed:
        config.update(seed)
    return config


def config_hash(config):
    payload = {
        "engine": ENGINE_VERSION,
        "config": config,
    }
    text = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def available_sides(market, strategy):
    if market == "Спот":
        return ["Long"]
    if strategy == "DCA":
        return ["Long", "Short"]
    return ["Long", "Short", "Neutral"]


def navigate(page, bot_id=None, mode=None, seed=None):
    st.session_state["page"] = page

    if bot_id:
        st.session_state["bot_id"] = bot_id

    if mode:
        st.session_state["bots_mode"] = mode

    if mode == "edit":
        st.session_state["edit_id"] = bot_id
        st.session_state["edit_seed"] = seed
        st.session_state["edit_nonce"] = uuid.uuid4().hex[:8]


# ============================================================
# DATABASE
# ============================================================

def connect():
    db = sqlite3.connect(DB_FILE, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=30000")
    return db


def init_db():
    with connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS bots (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                config TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Проект',
                confirmed TEXT,
                checked REAL NOT NULL DEFAULT 0,
                snapshot TEXT,
                state TEXT,
                lease REAL NOT NULL DEFAULT 0,
                created TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_id TEXT NOT NULL,
                config_hash TEXT NOT NULL,
                created TEXT NOT NULL,
                result TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_id TEXT,
                created TEXT NOT NULL,
                kind TEXT NOT NULL,
                message TEXT NOT NULL,
                notify TEXT NOT NULL DEFAULT 'off'
            );
            """
        )


def get_bot(bot_id):
    with connect() as db:
        row = db.execute(
            "SELECT * FROM bots WHERE id=?",
            (bot_id,),
        ).fetchone()

    if not row:
        return None

    bot = dict(row)
    bot["config"] = default_config(json.loads(bot["config"]))

    for key in ["confirmed", "snapshot"]:
        bot[key] = json.loads(bot[key]) if bot[key] else None

    return bot


def all_bots():
    with connect() as db:
        ids = [
            row[0]
            for row in db.execute(
                "SELECT id FROM bots ORDER BY created DESC"
            )
        ]
    return [get_bot(bot_id) for bot_id in ids]


def add_event(bot_id, kind, message, notify=False):
    with connect() as db:
        cursor = db.execute(
            """
            INSERT INTO events (
                bot_id, created, kind, message, notify
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                bot_id,
                now_utc(),
                kind,
                message,
                "pending" if notify else "off",
            ),
        )
        return cursor.lastrowid


def tests_for(bot_id):
    with connect() as db:
        rows = db.execute(
            """
            SELECT * FROM tests
            WHERE bot_id=?
            ORDER BY id DESC
            LIMIT 30
            """,
            (bot_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def matching_test(bot):
    fingerprint = config_hash(bot["config"])
    for row in tests_for(bot["id"]):
        if row["config_hash"] == fingerprint:
            return json.loads(row["result"])
    return None


# ============================================================
# API
# ============================================================

@st.cache_resource
def request_state():
    return {
        "lock": threading.Lock(),
        "last": [0.0],
    }


REQUEST_STATE = request_state()


def api_get(endpoint, params=None):
    error = "Нет ответа OKX"

    for attempt in range(4):
        with REQUEST_STATE["lock"]:
            elapsed = (
                time.monotonic()
                - REQUEST_STATE["last"][0]
            )
            time.sleep(max(0.0, 0.18 - elapsed))
            REQUEST_STATE["last"][0] = time.monotonic()

        try:
            response = requests.get(
                API + endpoint,
                params=params,
                timeout=(8, 25),
                headers={"User-Agent": "OKX-Manager/3.0"},
            )

            if response.status_code == 429:
                error = "Лимит запросов OKX"
                time.sleep(1 + attempt)
                continue

            response.raise_for_status()
            payload = response.json()

            if payload.get("code") == "0":
                return payload.get("data", [])

            error = (
                f"OKX {payload.get('code')}: "
                f"{payload.get('msg', '')}"
            )

        except (requests.RequestException, ValueError) as exc:
            error = str(exc)

        time.sleep(0.5 * (attempt + 1))

    raise RuntimeError(error)


@st.cache_data(ttl=3600, show_spinner=False)
def instruments(market):
    inst_type = "SPOT" if market == "Спот" else "SWAP"

    rows = api_get(
        "/public/instruments",
        {"instType": inst_type},
    )

    result = {}

    for item in rows:
        symbol = item.get("instId", "")

        if market == "Спот":
            valid = item.get("quoteCcy") == "USDT"
        else:
            valid = (
                item.get("settleCcy") == "USDT"
                and item.get("ctType") == "linear"
                and symbol.endswith("-USDT-SWAP")
            )

        if valid and item.get("state") == "live":
            result[symbol] = item

    if not result:
        raise RuntimeError("Нет доступных USDT-инструментов")

    return result


@st.cache_data(ttl=45, show_spinner=False)
def tickers(market):
    inst_type = "SPOT" if market == "Спот" else "SWAP"
    rows = api_get(
        "/market/tickers",
        {"instType": inst_type},
    )
    return {row["instId"]: row for row in rows}


def live_price(symbol):
    rows = api_get(
        "/market/ticker",
        {"instId": symbol},
    )

    if not rows:
        raise RuntimeError("Цена недоступна")

    price = float(rows[0].get("last", 0) or 0)

    if price <= 0:
        raise RuntimeError("Некорректная цена")

    return price


def candle_frame(rows):
    if not rows:
        raise RuntimeError("Нет свечей")

    columns = [
        "ts", "o", "h", "l", "c",
        "vol", "baseVol", "quoteVol", "confirm",
    ]

    df = pd.DataFrame(rows, columns=columns)

    for column in columns:
        df[column] = pd.to_numeric(
            df[column],
            errors="coerce",
        )

    df = df[df["confirm"] == 1]
    df = df.dropna(subset=["ts", "o", "h", "l", "c"])
    df = df[(df[["o", "h", "l", "c"]] > 0).all(axis=1)]

    df = (
        df.drop_duplicates("ts")
        .sort_values("ts")
        .reset_index(drop=True)
    )

    df["time"] = pd.to_datetime(
        df["ts"],
        unit="ms",
        utc=True,
    )

    return df


def recent_raw(symbol, bar):
    rows = api_get(
        "/market/candles",
        {
            "instId": symbol,
            "bar": bar,
            "limit": "300",
        },
    )

    df = candle_frame(rows)

    if len(df) < 60:
        raise RuntimeError("Нужно минимум 60 закрытых свечей")

    return df


@st.cache_data(ttl=90, show_spinner=False)
def recent(symbol, bar):
    return recent_raw(symbol, bar)


@st.cache_data(ttl=1800, show_spinner=False)
def history(symbol, bar, start_ms, end_ms):
    rows = []
    cursor = end_ms
    expected = max(1, int((end_ms - start_ms) / BARS[bar]))

    for _ in range(expected // 100 + 10):
        batch = api_get(
            "/market/history-candles",
            {
                "instId": symbol,
                "bar": bar,
                "after": str(cursor),
                "limit": "100",
            },
        )

        if not batch:
            break

        rows.extend(batch)
        oldest = min(int(item[0]) for item in batch)

        if oldest <= start_ms:
            break

        if oldest >= cursor:
            raise RuntimeError("Ошибка пагинации")

        cursor = oldest

    df = candle_frame(rows)
    df = df[
        (df["ts"] >= start_ms)
        & (df["ts"] < end_ms)
    ].reset_index(drop=True)

    if len(df) < 30:
        raise RuntimeError("Недостаточно истории")

    return df


# ============================================================
# INDICATORS / MARKET SIGNAL
# ============================================================

def indicators(df):
    df = df.copy()

    df["RSI"] = RSIIndicator(
        close=df["c"],
        window=14,
    ).rsi()

    trend = ADXIndicator(
        high=df["h"],
        low=df["l"],
        close=df["c"],
        window=14,
    )

    df["ADX"] = trend.adx()
    df["+DI"] = trend.adx_pos()
    df["-DI"] = trend.adx_neg()

    df["ATR"] = AverageTrueRange(
        high=df["h"],
        low=df["l"],
        close=df["c"],
        window=14,
    ).average_true_range()

    return df


def market_signal(last):
    values = [
        last["RSI"],
        last["ADX"],
        last["+DI"],
        last["-DI"],
    ]

    if not all(np.isfinite(value) for value in values):
        return "Нет данных", "Индикаторы ещё не сформированы"

    if last["ADX"] < 25:
        return (
            "Нейтрально",
            "ADX ниже 25: направленный тренд не подтверждён",
        )

    if last["+DI"] > last["-DI"]:
        return (
            "Лонг",
            "+DI выше -DI при ADX не ниже 25",
        )

    if last["-DI"] > last["+DI"]:
        return (
            "Шорт",
            "-DI выше +DI при ADX не ниже 25",
        )

    return "Нет условий", "Направление неоднозначно"


def price_chart(symbol, bar):
    df = indicators(recent(symbol, bar))

    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.58, 0.21, 0.21],
        vertical_spacing=0.04,
    )

    fig.add_trace(
        go.Candlestick(
            x=df["time"],
            open=df["o"],
            high=df["h"],
            low=df["l"],
            close=df["c"],
            name="Цена",
            increasing_line_color=GREEN,
            decreasing_line_color=RED,
        ),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=df["time"],
            y=df["RSI"],
            name="RSI 14",
            line=dict(color=BLUE),
        ),
        row=2,
        col=1,
    )

    for value in [30, 70]:
        fig.add_hline(
            y=value,
            line_dash="dot",
            row=2,
            col=1,
        )

    for column, color in [
        ("ADX", YELLOW),
        ("+DI", GREEN),
        ("-DI", RED),
    ]:
        fig.add_trace(
            go.Scatter(
                x=df["time"],
                y=df[column],
                name=column,
                line=dict(color=color, width=1.6),
            ),
            row=3,
            col=1,
        )

    fig.add_hline(
        y=25,
        line_dash="dot",
        row=3,
        col=1,
    )

    fig.update_yaxes(
        range=[0, 100],
        row=2,
        col=1,
    )

    fig.update_layout(
        title=f"{symbol} · {bar}",
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h"),
    )

    show_figure(fig, 660)


# ============================================================
# TELEGRAM
# ============================================================

def telegram_credentials():
    try:
        section = st.secrets.get("telegram", {})
        return (
            str(section.get("token", "")).strip(),
            str(section.get("chat_id", "")).strip(),
        )
    except Exception:
        return "", ""


def send_telegram(message):
    token, chat_id = telegram_credentials()

    if not token or not chat_id:
        return "error: Telegram Secrets не настроены"

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": str(message)[:4000],
            },
            timeout=(8, 15),
        )

        payload = response.json()

        if response.ok and payload.get("ok"):
            return "sent"

        code = payload.get(
            "error_code",
            response.status_code,
        )

        return (
            f"error: Telegram {code}. "
            "Проверьте token, chat_id и Start у бота."
        )

    except requests.Timeout:
        return (
            "unknown: Тайм-аут. "
            "Перед повтором проверьте чат."
        )
    except Exception:
        return "error: Нет соединения с Telegram"


def dispatch():
    with connect() as db:
        rows = db.execute(
            """
            SELECT * FROM events
            WHERE notify='pending'
            ORDER BY id
            LIMIT 20
            """
        ).fetchall()

    for row in rows:
        row = dict(row)

        with connect() as db:
            claimed = db.execute(
                """
                UPDATE events
                SET notify='sending'
                WHERE id=? AND notify='pending'
                """,
                (row["id"],),
            ).rowcount

        if not claimed:
            continue

        result = send_telegram(
            "OKX Bot Manager\n"
            f"{row['kind']}\n"
            f"UTC: {row['created']}\n\n"
            f"{row['message']}"
        )

        with connect() as db:
            db.execute(
                "UPDATE events SET notify=? WHERE id=?",
                (result, row["id"]),
            )

        time.sleep(0.1)


# ============================================================
# CONFIGURATION / DCA
# ============================================================

def dca_orders(config, entry):
    direction = 1 if config["side"] == "Long" else -1
    leverage = (
        config["leverage"]
        if config["market"] != "Спот"
        else 1.0
    )

    rows = []
    offset = 0.0
    total_margin = 0.0
    total_notional = 0.0
    total_quantity = 0.0

    for index in range(int(config["so"]) + 1):
        if index == 0:
            amount = config["base"]
        else:
            offset += (
                config["step"]
                * config["step_mult"] ** (index - 1)
            )
            amount = (
                config["safety"]
                * config["amount_mult"] ** (index - 1)
            )

        price = entry * (
            1 - direction * offset / 100
        )

        if price <= 0:
            raise ValueError(
                "Один из уровней СО неположительный. "
                "Уменьшите шаг или количество СО."
            )

        notional = amount * leverage
        total_margin += amount
        total_notional += notional
        total_quantity += notional / price

        rows.append({
            "Ордер": (
                "Базовый"
                if index == 0
                else f"СО {index}"
            ),
            "Цена": price,
            "Сумма / маржа USDT": amount,
            "Номинал USDT": notional,
            "Всего сумма / маржа": total_margin,
            "Средняя цена": total_notional / total_quantity,
        })

    return pd.DataFrame(rows)


def reserve(config):
    amount = config["base"] + sum(
        config["safety"]
        * config["amount_mult"] ** index
        for index in range(int(config["so"]))
    )

    leverage = (
        config["leverage"]
        if config["market"] != "Спот"
        else 1.0
    )

    return amount * (
        1 + leverage * config["fee"] / 100
    )


def validate(config):
    errors = []

    if config["side"] not in available_sides(
        config["market"],
        config["strategy"],
    ):
        errors.append("Направление не подходит выбранному продукту.")

    if config["strategy"] == "DCA":
        try:
            dca_orders(config, 100.0)
        except ValueError as exc:
            errors.append(str(exc))

        if reserve(config) > config["budget"]:
            errors.append(
                f"Не хватает бюджета: нужно минимум "
                f"{reserve(config):.2f} USDT."
            )

        if (
            config["side"] == "Short"
            and config["tp"] >= 100
        ):
            errors.append("Для Short TP должен быть меньше 100%.")

    elif (
        config["lower"] <= 0
        or config["upper"] <= config["lower"]
    ):
        errors.append("Проверьте границы Grid.")

    if (
        config["side"] == "Neutral"
        and config["stop"] > 0
    ):
        errors.append(
            "Один направленный стоп для Neutral неоднозначен. "
            "В этой модели для Neutral используйте 0."
        )

    return errors


def passport(config):
    rows = [
        (
            "Продукт",
            f"{config['market']} · {config['strategy']}",
        ),
        ("Инструмент", config["symbol"]),
        ("Направление", config["side"]),
        ("Бюджет USDT", config["budget"]),
    ]

    if config["market"] != "Спот":
        rows.append(("Плечо", config["leverage"]))

    if config["strategy"] == "DCA":
        rows.extend([
            ("Price steps %", config["step"]),
            ("Price steps multiplier", config["step_mult"]),
            ("TP target per cycle %", config["tp"]),
            ("Initial order amount / margin USDT", config["base"]),
            ("Safety order amount / margin USDT", config["safety"]),
            ("Max safety orders", config["so"]),
            ("Amount multiplier", config["amount_mult"]),
        ])
    else:
        rows.extend([
            ("Lower price", config["lower"]),
            ("Upper price", config["upper"]),
            ("Grid intervals", config["grids"]),
            ("Grid type", config["grid_type"]),
        ])

    rows.extend([
        ("Стоп-цена, 0 — нет", config["stop"]),
        ("Комиссия модели за сторону %", config["fee"]),
    ])

    return pd.DataFrame(
        rows,
        columns=["Поле", "Значение"],
    )


# ============================================================
# BACKTEST ENGINE
# ============================================================

def backtest(df, config, bar, start_ms, end_ms, path_mode):
    errors = validate(config)

    if errors:
        raise ValueError(" ".join(errors))

    if (
        config["market"] != "Спот"
        and config["leverage"] != 1
    ):
        raise ValueError(
            "В этой версии тест поддерживает только 1x. "
            "Плечо, funding и ликвидации не моделируются. "
            "Параметры сохранённого бота не изменены."
        )

    initial = float(config["budget"])
    fee_rate = config["fee"] / 100
    cash = initial
    fees = 0.0
    cycles = 0
    stopped = False
    curve = []

    direction = 1 if config["side"] == "Long" else -1
    quantity = 0.0
    locked = 0.0
    next_so = 1
    orders = []
    safety_blocked = False

    slots = {}
    lots = {}

    first_price = float(df.iloc[0]["o"])

    if config["strategy"] == "Grid":
        if config["grid_type"] == "Арифметическая":
            levels = np.linspace(
                config["lower"],
                config["upper"],
                int(config["grids"]) + 1,
            )
        else:
            levels = np.geomspace(
                config["lower"],
                config["upper"],
                int(config["grids"]) + 1,
            )

        for index in range(len(levels) - 1):
            lower = float(levels[index])
            upper = float(levels[index + 1])

            if (
                config["side"] in ["Long", "Neutral"]
                and lower < first_price
            ):
                slots[f"L{index}"] = {
                    "direction": 1,
                    "entry": lower,
                    "target": upper,
                }

            if (
                config["side"] in ["Short", "Neutral"]
                and upper > first_price
            ):
                slots[f"S{index}"] = {
                    "direction": -1,
                    "entry": upper,
                    "target": lower,
                }

        if not slots:
            raise ValueError(
                "Нет стартовых уровней для выбранного "
                "направления. Проверьте диапазон и период."
            )

        grid_amount = (
            initial / len(slots) / (1 + fee_rate)
        )

    def equity(price):
        if config["strategy"] == "DCA":
            return (
                cash
                + locked
                + direction * (quantity * price - locked)
                - quantity * price * fee_rate
            )

        value = cash

        for key, lot in lots.items():
            slot = slots[key]
            value += (
                lot["locked"]
                + slot["direction"]
                * lot["quantity"]
                * (price - lot["entry"])
                - lot["quantity"] * price * fee_rate
            )

        return value

    def point(row, price):
        curve.append({
            "time": str(row["time"]),
            "equity": float(equity(price)),
        })

    def dca_buy(amount, price):
        nonlocal cash, quantity, locked, fees

        entry_fee = amount * fee_rate

        if amount + entry_fee > cash + 1e-9:
            return False

        cash -= amount + entry_fee
        quantity += amount / price
        locked += amount
        fees += entry_fee
        return True

    def dca_close(price):
        nonlocal cash, quantity, locked, fees

        pnl = direction * (quantity * price - locked)
        exit_fee = quantity * price * fee_rate

        cash += locked + pnl - exit_fee
        fees += exit_fee
        quantity = 0.0
        locked = 0.0

    def grid_open(key, price):
        nonlocal cash, fees

        if key in lots:
            return

        entry_fee = grid_amount * fee_rate

        if grid_amount + entry_fee > cash + 1e-9:
            return

        cash -= grid_amount + entry_fee
        fees += entry_fee

        lots[key] = {
            "quantity": grid_amount / price,
            "locked": grid_amount,
            "entry": price,
        }

    def grid_close(key, price):
        nonlocal cash, fees, cycles

        lot = lots.pop(key)
        slot = slots[key]

        pnl = (
            slot["direction"]
            * lot["quantity"]
            * (price - lot["entry"])
        )
        exit_fee = lot["quantity"] * price * fee_rate

        cash += lot["locked"] + pnl - exit_fee
        fees += exit_fee
        cycles += 1

    def stop_reached(price):
        if config["stop"] <= 0 or config["side"] == "Neutral":
            return False
        return direction * (price - config["stop"]) <= 0

    for _, row in df.iterrows():
        opening = float(row["o"])
        low = float(row["l"])
        high = float(row["h"])
        closing = float(row["c"])

        point(row, opening)

        if stop_reached(opening):
            if config["strategy"] == "DCA" and quantity > 0:
                dca_close(opening)

            if config["strategy"] == "Grid":
                for key in list(lots):
                    grid_close(key, opening)

            point(row, opening)
            stopped = True
            break

        if path_mode == "Сначала Low":
            path = [opening, low, high, closing]
        else:
            path = [opening, high, low, closing]

        if config["strategy"] == "DCA":
            closed_at_open = False

            if quantity > 0:
                target = (
                    locked / quantity
                    * (1 + direction * config["tp"] / 100)
                )

                if direction * (opening - target) >= 0:
                    dca_close(opening)
                    cycles += 1
                    closed_at_open = True
                    point(row, opening)

            if quantity == 0 and not closed_at_open:
                if dca_buy(config["base"], opening):
                    orders = dca_orders(
                        config,
                        opening,
                    ).to_dict("records")
                    next_so = 1
                    safety_blocked = False
                    point(row, opening)

            if quantity > 0:
                while (
                    next_so <= config["so"]
                    and direction * (
                        opening - orders[next_so]["Цена"]
                    ) <= 0
                ):
                    if not dca_buy(
                        orders[next_so]["Номинал USDT"],
                        opening,
                    ):
                        safety_blocked = True
                        break

                    next_so += 1
                    point(row, opening)

            for segment_start, segment_end in zip(path, path[1:]):
                if quantity <= 0 or stopped:
                    break

                current_price = segment_start
                upward = segment_end > segment_start

                if segment_end == segment_start:
                    continue

                for _ in range(int(config["so"]) + 5):
                    if quantity <= 0:
                        break

                    target = (
                        locked / quantity
                        * (1 + direction * config["tp"] / 100)
                    )

                    candidates = []

                    def reachable(price):
                        if upward:
                            return current_price < price <= segment_end
                        return segment_end <= price < current_price

                    if reachable(target):
                        candidates.append((target, "tp"))

                    if (
                        not safety_blocked
                        and next_so <= config["so"]
                    ):
                        safety_price = orders[next_so]["Цена"]
                        if reachable(safety_price):
                            candidates.append((safety_price, "so"))

                    if (
                        config["stop"] > 0
                        and reachable(config["stop"])
                    ):
                        candidates.append((config["stop"], "stop"))

                    if not candidates:
                        break

                    candidates.sort(
                        key=lambda item: (
                            abs(item[0] - current_price),
                            0 if item[1] == "stop" else 1,
                        )
                    )

                    fill, action = candidates[0]
                    point(row, fill)

                    if action == "stop":
                        dca_close(fill)
                        stopped = True
                        point(row, fill)
                        break

                    if action == "tp":
                        dca_close(fill)
                        cycles += 1
                        point(row, fill)
                        break

                    if dca_buy(
                        orders[next_so]["Номинал USDT"],
                        fill,
                    ):
                        next_so += 1
                    else:
                        safety_blocked = True

                    point(row, fill)
                    current_price = fill

                if not stopped:
                    point(row, segment_end)

        else:
            for key in list(lots):
                slot = slots[key]
                if slot["direction"] * (
                    opening - slot["target"]
                ) >= 0:
                    grid_close(key, opening)

            for key, slot in slots.items():
                if (
                    key not in lots
                    and slot["direction"]
                    * (opening - slot["entry"]) <= 0
                ):
                    grid_open(key, opening)

            point(row, opening)

            nodes = set()

            for slot in slots.values():
                nodes.add(slot["entry"])
                nodes.add(slot["target"])

            if config["stop"] > 0:
                nodes.add(config["stop"])

            for segment_start, segment_end in zip(path, path[1:]):
                if stopped or segment_start == segment_end:
                    continue

                upward = segment_end > segment_start

                crossed = [
                    price
                    for price in nodes
                    if (
                        segment_start < price <= segment_end
                        if upward
                        else segment_end <= price < segment_start
                    )
                ]
                crossed.sort(reverse=not upward)

                for price in crossed:
                    point(row, price)

                    if stop_reached(price):
                        for key in list(lots):
                            grid_close(key, price)
                        stopped = True
                        point(row, price)
                        break

                    for key in list(lots):
                        slot = slots[key]
                        if (
                            abs(slot["target"] - price)
                            <= max(1e-12, abs(price) * 1e-12)
                            and (
                                slot["direction"] == 1
                                if upward
                                else slot["direction"] == -1
                            )
                        ):
                            grid_close(key, price)

                    for key, slot in slots.items():
                        if key in lots:
                            continue

                        entry_hit = (
                            abs(slot["entry"] - price)
                            <= max(1e-12, abs(price) * 1e-12)
                        )

                        valid_direction = (
                            slot["direction"] == -1
                            if upward
                            else slot["direction"] == 1
                        )

                        if entry_hit and valid_direction:
                            grid_open(key, price)

                    point(row, price)

                if not stopped:
                    point(row, segment_end)

        if not stopped:
            point(row, closing)

        if stopped or curve[-1]["equity"] <= 0:
            break

    frame = pd.DataFrame(curve)
    peaks = frame["equity"].cummax().clip(lower=initial)
    dd = peaks - frame["equity"]

    final = float(frame.iloc[-1]["equity"])
    expected = max(1, int((end_ms - start_ms) / BARS[bar]))

    metrics = {
        "Итоговая equity USDT": round(final, 3),
        "PnL USDT": round(final - initial, 3),
        "Доходность %": round((final / initial - 1) * 100, 3),
        "Макс. просадка USDT": round(float(dd.max()), 3),
        "Макс. просадка %": round(
            float((dd / peaks * 100).max()), 3
        ),
        "Комиссии уплачены": round(fees, 4),
        "Закрытий / циклов": cycles,
        "Свечей": len(df),
        "Покрытие %": round(
            min(100, len(df) / expected * 100), 2
        ),
        "Пропуски": bool(
            (df["ts"].diff().dropna() != BARS[bar]).any()
        ),
        "Стоп сработал": stopped,
    }

    return {
        "metrics": metrics,
        "curve": curve,
        "config": config,
        "bar": bar,
        "path": path_mode,
        "start": str(df.iloc[0]["time"]),
        "end": str(df.iloc[-1]["time"]),
        "created": now_utc(),
    }


# ============================================================
# RECOMMENDATIONS
# ============================================================

def recommendations(bot):
    config = bot["config"]
    result = []

    for error in validate(config):
        result.append("Исправить: " + error)

    if config["strategy"] == "DCA":
        result.append(
            f"Резерв всех ордеров с оценкой входных комиссий: "
            f"{reserve(config):.2f} USDT из "
            f"{config['budget']:.2f} USDT."
        )
        if config["tp"] <= 2 * config["fee"]:
            result.append(
                "TP может не покрывать комиссию полного оборота."
            )
    else:
        if config["grid_type"] == "Геометрическая":
            step = (
                (config["upper"] / config["lower"])
                ** (1 / config["grids"]) - 1
            ) * 100
        else:
            step = (
                (config["upper"] - config["lower"])
                / config["grids"]
                / config["upper"] * 100
            )

        result.append(
            f"Минимальный приблизительный шаг: {step:.3f}%. "
            f"Комиссия оборота около {2 * config['fee']:.3f}%."
        )

        if step <= 2 * config["fee"]:
            result.append(
                "Комиссии могут съедать прибыль сеточного шага."
            )

    test = matching_test(bot)

    if not test:
        result.append(
            "Нет теста текущей версии. "
            "Старые тесты не подтверждают новые настройки."
        )
    else:
        metrics = test["metrics"]
        profitability = metrics.get("Доходность %", 0)
        drawdown = metrics.get("Макс. просадка %", 0)

        result.append(
            f"Сохранённый тест: доходность "
            f"{profitability:.2f}%, просадка {drawdown:.2f}%. "
            "Это не прогноз."
        )

        if profitability <= 0:
            result.append(
                "На этом периоде модель не дала "
                "положительный результат."
            )

        if drawdown > config["loss_limit"]:
            result.append(
                "Просадка теста превышает ваш порог риска."
            )

        if (
            metrics.get("Покрытие %", 0) < 95
            or metrics.get("Пропуски", False)
        ):
            result.append("История неполная или с пропусками.")

    if config["market"] != "Спот":
        result.append(
            "Фактическая маржа, funding и ликвидации "
            "в симуляции не моделируются."
        )

    result.append(
        "Перед запуском на OKX подтвердите минимальные ордера, "
        "округление, единицы сумм и доступность продукта."
    )

    return result


# ============================================================
# MONITORING
# ============================================================

def evaluate(bot, price):
    config = bot["config"]
    actual = bot["confirmed"] or {}
    conditions = []
    reasons = []

    quantity = float(actual.get("qty", 0))
    average = float(actual.get("avg", 0))
    liquidation = float(actual.get("liq", 0))

    direction = 1 if config["side"] == "Long" else -1
    pnl = None
    distance = None

    age_hours = (
        time.time() - float(actual.get("updated", 0))
    ) / 3600

    if age_hours > config["stale_hours"]:
        conditions.append("stale")
        reasons.append("Данные позиции устарели: нужна сверка.")

    if (
        quantity > 0
        and average > 0
        and config["side"] != "Neutral"
    ):
        pnl = (
            direction * quantity * (price - average)
            - quantity * price * config["fee"] / 100
            - float(actual.get("fees", 0))
        )

        loss_pct = -pnl / config["budget"] * 100

        if loss_pct >= config["loss_limit"]:
            conditions.append("loss")
            reasons.append(
                f"Оценочный убыток {loss_pct:.1f}% бюджета "
                "достиг заданного порога."
            )
    else:
        conditions.append("position_unknown")
        reasons.append(
            "Полный PnL неизвестен: фактическая позиция "
            "или обе стороны Neutral не заданы."
        )

    if (
        config["market"] != "Спот"
        and config["side"] != "Neutral"
    ):
        if liquidation > 0:
            distance = (
                direction * (price - liquidation)
                / price * 100
            )

            if distance <= config["liq_warning"]:
                conditions.append("liquidation")
                reasons.append(
                    f"До введённой ликвидации {distance:.2f}% "
                    "по last-цене. Проверьте mark price на OKX."
                )
        else:
            conditions.append("liq_unknown")
            reasons.append("Цена ликвидации неизвестна.")

    if config["strategy"] == "Grid":
        lower = config["lower"]
        upper = config["upper"]

        if price < lower:
            conditions.append("below_grid")
            reasons.append("Цена ниже диапазона Grid.")
        elif price > upper:
            conditions.append("above_grid")
            reasons.append("Цена выше диапазона Grid.")
        elif (
            min(price - lower, upper - price)
            / (upper - lower) < 0.05
        ):
            conditions.append("grid_edge")
            reasons.append("Цена у края диапазона Grid.")

    else:
        anchor = float(actual.get("anchor", 0))
        completed = int(actual.get("completed", 0))

        if anchor > 0 and completed < config["so"]:
            orders = dca_orders(config, anchor)
            level = float(orders.iloc[completed + 1]["Цена"])

            gap = direction * (price - level) / price * 100

            if gap <= 0.3:
                conditions.append("safety_level")
                reasons.append(
                    f"Цена у/за расчётным СО {completed + 1}: "
                    f"{level:.8f}. Исполнение не подтверждено."
                )

        if quantity > 0 and average > 0:
            target = average * (
                1 + direction * config["tp"] / 100
            )

            if direction * (price - target) >= 0:
                conditions.append("tp_level")
                reasons.append(
                    f"Цена у/за расчётным TP {target:.8f}. "
                    "Исполнение не подтверждено."
                )

    if (
        config["stop"] > 0
        and config["side"] != "Neutral"
        and direction * (price - config["stop"]) <= 0
    ):
        conditions.append("stop_level")
        reasons.append("Цена у/за указанным стопом.")

    critical = any(
        item in conditions
        for item in ["loss", "liquidation", "stop_level"]
    )

    unknown = any(
        item in conditions
        for item in ["stale", "position_unknown", "liq_unknown"]
    )

    status = (
        "Высокий риск" if critical
        else "Нужна сверка" if unknown
        else "Внимание" if conditions
        else "Пороги не сработали"
    )

    health = (
        None if unknown
        else 20 if critical
        else 55 if conditions
        else 85
    )

    return {
        "price": price,
        "pnl": pnl,
        "distance": distance,
        "status": status,
        "health": health,
        "reasons": reasons or [
            "Заданные пороги не сработали. "
            "Это не гарантия безопасности."
        ],
        "code": "|".join(sorted(conditions)) or "ok",
        "time": now_utc(),
    }


def check_bot(bot_id, force=False):
    now = time.time()

    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT checked, lease, status FROM bots WHERE id=?",
            (bot_id,),
        ).fetchone()

        if not row or row["status"] != "Наблюдается":
            return

        if row["lease"] > now:
            return

        if not force and now - row["checked"] < 55:
            return

        db.execute(
            "UPDATE bots SET lease=? WHERE id=?",
            (now + 180, bot_id),
        )

    bot = get_bot(bot_id)

    try:
        snapshot = evaluate(
            bot,
            live_price(bot["config"]["symbol"]),
        )

        with connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                "SELECT state, status FROM bots WHERE id=?",
                (bot_id,),
            ).fetchone()

            if (
                not current
                or current["status"] != "Наблюдается"
            ):
                return

            if current["state"] != snapshot["code"]:
                message = (
                    f"{bot['name']}\n"
                    f"{bot['config']['symbol']} · "
                    f"{bot['config']['strategy']} "
                    f"{bot['config']['side']}\n"
                    f"{snapshot['status']}\n"
                    f"Цена: {snapshot['price']:.8f}\n\n"
                    + "\n".join(snapshot["reasons"])
                )

                db.execute(
                    """
                    INSERT INTO events (
                        bot_id, created, kind, message, notify
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        bot_id,
                        now_utc(),
                        "Состояние изменилось",
                        message,
                        "pending" if bot["config"]["notify"] else "off",
                    ),
                )

            db.execute(
                """
                UPDATE bots
                SET snapshot=?, state=?, checked=?
                WHERE id=?
                """,
                (
                    json.dumps(snapshot, ensure_ascii=False),
                    snapshot["code"],
                    time.time(),
                    bot_id,
                ),
            )

    except Exception as exc:
        snapshot = {"error": str(exc), "time": now_utc()}

        with connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT state, status FROM bots WHERE id=?",
                (bot_id,),
            ).fetchone()

            if old and old["status"] == "Наблюдается":
                if old["state"] != "api_error":
                    db.execute(
                        """
                        INSERT INTO events (
                            bot_id, created, kind, message, notify
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            bot_id,
                            now_utc(),
                            "Данные недоступны",
                            f"{bot['name']}: нет свежих данных OKX.",
                            "pending" if bot["config"]["notify"] else "off",
                        ),
                    )

                db.execute(
                    """
                    UPDATE bots
                    SET snapshot=?, state='api_error', checked=?
                    WHERE id=?
                    """,
                    (
                        json.dumps(snapshot, ensure_ascii=False),
                        time.time(),
                        bot_id,
                    ),
                )

    finally:
        with connect() as db:
            db.execute(
                "UPDATE bots SET lease=0 WHERE id=?",
                (bot_id,),
            )


# ============================================================
# EVENTS
# ============================================================

def render_events(bot_id=None):
    query = """
        SELECT e.*, b.name AS bot_name
        FROM events e
        LEFT JOIN bots b ON b.id=e.bot_id
    """
    params = ()

    if bot_id:
        query += " WHERE e.bot_id=?"
        params = (bot_id,)

    query += " ORDER BY e.id DESC LIMIT 500"

    with connect() as db:
        rows = db.execute(query, params).fetchall()

    if not rows:
        st.info("Событий пока нет.")
        return

    df = pd.DataFrame([dict(row) for row in rows])

    delivery_names = {
        "off": "Без отправки",
        "pending": "Ожидает отправки",
        "sending": "Отправка начата",
        "sent": "Отправлено",
    }

    visible = df[
        ["created", "bot_name", "kind", "message", "notify"]
    ].copy()

    visible["notify"] = visible["notify"].map(
        lambda value: delivery_names.get(value, value)
    )

    visible = visible.rename(columns={
        "created": "Дата UTC",
        "bot_name": "Бот",
        "kind": "Событие",
        "message": "Описание",
        "notify": "Telegram",
    })

    st.dataframe(
        visible,
        hide_index=True,
        use_container_width=True,
    )

    st.download_button(
        "Скачать журнал CSV",
        visible.to_csv(index=False).encode("utf-8-sig"),
        file_name="bot_events.csv",
        mime="text/csv",
        key=f"events_download_{bot_id}",
    )

    failed = df[
        df["notify"].str.startswith(
            ("error:", "unknown:", "sending")
        )
    ]

    if not failed.empty:
        with st.expander("Повторить неудачную отправку"):
            st.caption(
                "При тайм-ауте сообщение могло доставиться. "
                "Перед повтором проверьте чат."
            )
            selected = st.selectbox(
                "Событие",
                failed["id"].tolist(),
                key=f"retry_select_{bot_id}",
            )
            if st.button(
                "Повторить отправку",
                key=f"retry_button_{bot_id}",
            ):
                with connect() as db:
                    db.execute(
                        "UPDATE events SET notify='pending' WHERE id=?",
                        (int(selected),),
                    )
                dispatch()
                st.success("Попытка выполнена.")


# ============================================================
# BOT EDITOR
# ============================================================

def render_editor():
    edit_id = st.session_state.get("edit_id")
    existing = get_bot(edit_id) if edit_id else None

    config = default_config(
        existing["config"]
        if existing
        else st.session_state.get("edit_seed")
    )

    nonce = st.session_state.get("edit_nonce", "new")

    st.button(
        "← К списку ботов",
        on_click=navigate,
        args=(PAGES[3], None, "list"),
    )

    if existing and existing["status"] in ["Наблюдается", "Пауза"]:
        st.warning(
            "Для изменения параметров запущенного бота "
            "создайте копию проекта. Позицию обновляйте "
            "через ручную сверку."
        )
        st.button(
            "Создать копию",
            on_click=navigate,
            args=(PAGES[3], None, "edit", config),
        )
        return

    hero(
        "Конструктор бота",
        "Каждый проект хранит собственные параметры. "
        "Ничего не запускается на бирже автоматически.",
    )

    a, b = st.columns(2)

    market = a.selectbox(
        "Рынок",
        ["Спот", "Фьючерсы"],
        index=0 if config["market"] == "Спот" else 1,
        key=f"edit_market_{nonce}",
    )

    strategy = b.selectbox(
        "Стратегия",
        ["DCA", "Grid"],
        index=0 if config["strategy"] == "DCA" else 1,
        key=f"edit_strategy_{nonce}",
    )

    sides = available_sides(market, strategy)

    side = st.radio(
        "Направление бота",
        sides,
        index=sides.index(config["side"]) if config["side"] in sides else 0,
        horizontal=True,
        key=f"edit_side_{nonce}_{market}_{strategy}",
    )

    if market == "Спот":
        st.caption(
            "Спот: покупка и последующая продажа. "
            "Short/Neutral доступны в фьючерсных моделях."
        )

    try:
        options = sorted(instruments(market))
        candidate = (
            config["symbol"].split("-")[0]
            + "-USDT"
            + ("-SWAP" if market != "Спот" else "")
        )

        symbol = st.selectbox(
            "Монета / инструмент",
            options,
            index=options.index(candidate) if candidate in options else 0,
            key=f"edit_symbol_{nonce}_{market}",
        )
    except Exception as exc:
        st.error(str(exc))
        return

    with st.form(f"edit_form_{nonce}_{market}_{strategy}"):
        name = st.text_input(
            "Название",
            value=(
                existing["name"]
                if existing
                else f"{symbol.split('-')[0]} · {strategy} {side}"
            ),
        )

        a, b = st.columns(2)

        budget = a.number_input(
            "Бюджет USDT",
            min_value=1.0,
            value=float(config["budget"]),
        )

        leverage = b.number_input(
            "Плечо",
            min_value=1.0,
            max_value=125.0,
            value=float(config["leverage"]) if market != "Спот" else 1.0,
            disabled=market == "Спот",
        )

        edited = {
            **config,
            "market": market,
            "strategy": strategy,
            "side": side,
            "symbol": symbol,
            "budget": budget,
            "leverage": leverage,
        }

        if strategy == "DCA":
            a, b, c = st.columns(3)

            edited["base"] = a.number_input(
                "Первый ордер / маржа USDT",
                min_value=0.01,
                value=float(config["base"]),
            )
            edited["safety"] = b.number_input(
                "Первая страховка / маржа USDT",
                min_value=0.01,
                value=float(config["safety"]),
            )
            edited["so"] = int(c.number_input(
                "Количество СО",
                min_value=0,
                max_value=30,
                value=int(config["so"]),
            ))

            a, b, c = st.columns(3)

            edited["tp"] = a.number_input(
                "TP на цикл %",
                min_value=0.01,
                value=float(config["tp"]),
            )
            edited["step"] = b.number_input(
                "Шаг цены %",
                min_value=0.01,
                value=float(config["step"]),
            )
            edited["amount_mult"] = c.number_input(
                "Множитель суммы СО",
                min_value=1.0,
                value=float(config["amount_mult"]),
            )
            edited["step_mult"] = st.number_input(
                "Множитель шага цены",
                min_value=1.0,
                value=float(config["step_mult"]),
            )

            st.caption(
                "Шаблон: TP 1.5%, шаг 2%, 4 СО, множитель 1.2. "
                "Первая страховка задаётся отдельно. "
                "При множителе шага 1 отклонения Long "
                "составляют −2%, −4%, −6%, −8%."
            )
        else:
            a, b, c = st.columns(3)

            edited["lower"] = a.number_input(
                "Нижняя граница",
                min_value=0.00000001,
                value=float(config["lower"]),
                format="%.8f",
            )
            edited["upper"] = b.number_input(
                "Верхняя граница",
                min_value=0.00000001,
                value=float(config["upper"]),
                format="%.8f",
            )
            edited["grids"] = int(c.number_input(
                "Интервалов сетки",
                min_value=2,
                max_value=200,
                value=int(config["grids"]),
            ))
            edited["grid_type"] = st.selectbox(
                "Тип сетки",
                ["Арифметическая", "Геометрическая"],
                index=0 if config["grid_type"] == "Арифметическая" else 1,
            )

        a, b = st.columns(2)

        edited["stop"] = a.number_input(
            "Стоп-цена, 0 — нет",
            min_value=0.0,
            value=0.0 if side == "Neutral" else float(config["stop"]),
            format="%.8f",
            disabled=side == "Neutral",
        )
        edited["fee"] = b.number_input(
            "Комиссия за сторону %",
            min_value=0.0,
            max_value=5.0,
            value=float(config["fee"]),
            format="%.4f",
        )

        a, b, c = st.columns(3)

        edited["loss_limit"] = a.number_input(
            "Порог убытка % бюджета",
            min_value=0.1,
            value=float(config["loss_limit"]),
        )
        edited["liq_warning"] = b.number_input(
            "Порог расстояния до ликвидации %",
            min_value=0.1,
            value=float(config["liq_warning"]),
        )
        edited["stale_hours"] = c.number_input(
            "Сверять позицию каждые N часов",
            min_value=1.0,
            value=float(config["stale_hours"]),
        )

        edited["notify"] = st.checkbox(
            "Telegram-события этого бота",
            value=bool(config["notify"]),
        )

        submitted = st.form_submit_button(
            "Сохранить бота",
            use_container_width=True,
        )

    if not submitted:
        return

    errors = validate(edited)

    if not name.strip():
        errors.append("Введите название.")

    if errors:
        for error in errors:
            st.error(error)
        return

    bot_id = edit_id or uuid.uuid4().hex

    with connect() as db:
        if existing:
            db.execute(
                """
                UPDATE bots SET name=?, config=?, state=NULL
                WHERE id=?
                """,
                (name.strip(), json.dumps(edited), bot_id),
            )
        else:
            db.execute(
                """
                INSERT INTO bots (id, name, config, created)
                VALUES (?, ?, ?, ?)
                """,
                (bot_id, name.strip(), json.dumps(edited), now_utc()),
            )

    add_event(
        bot_id,
        "Настройки изменены" if existing else "Проект создан",
        f"{name.strip()}: сохранена новая конфигурация.",
    )

    st.session_state["bot_id"] = bot_id
    st.session_state["bots_mode"] = "detail"
    st.rerun()


# ============================================================
# BOT DETAIL
# ============================================================

def render_bot_detail():
    bot = get_bot(st.session_state.get("bot_id", ""))

    if not bot:
        st.info("Выберите бота из списка.")
        st.button(
            "К списку",
            on_click=navigate,
            args=(PAGES[3], None, "list"),
        )
        return

    bot_id = bot["id"]
    config = bot["config"]

    st.button(
        "← Мои боты",
        on_click=navigate,
        args=(PAGES[3], None, "list"),
    )

    hero(
        bot["name"],
        f"{config['symbol']} · {config['market']} · "
        f"{config['strategy']} {config['side']} · {bot['status']}",
    )

    a, b = st.columns(2)

    a.button(
        "Изменить настройки",
        on_click=navigate,
        args=(PAGES[3], bot_id, "edit"),
    )
    b.button(
        "Копия для сравнения",
        on_click=navigate,
        args=(PAGES[3], None, "edit", config),
    )

    tabs = st.tabs([
        "План и OKX",
        "Бэктест",
        "Запуск / сверка",
        "Состояние",
        "События",
    ])

    with tabs[0]:
        for line in recommendations(bot):
            st.write("• " + line)

        st.subheader("Значения для переноса на OKX")

        table = passport(config)

        st.dataframe(
            table.astype(str),
            hide_index=True,
            use_container_width=True,
        )

        st.download_button(
            "Скачать памятку OKX",
            table.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"okx_{bot_id[:8]}.csv",
            mime="text/csv",
        )

        st.caption(
            "Названия полей и единицы проверьте в вашем "
            "интерфейсе OKX. Для Futures DCA суммы ордеров "
            "в карточке обозначают маржу. "
            "Приложение не отправляет торговые команды."
        )

        if config["strategy"] == "DCA":
            actual = bot["confirmed"] or {}
            anchor = st.number_input(
                "Первый вход для расчёта уровней",
                min_value=0.00000001,
                value=float(actual.get("anchor", 100) or 100),
                format="%.8f",
                key=f"plan_anchor_{bot_id}",
            )
            st.dataframe(
                dca_orders(config, anchor),
                hide_index=True,
                use_container_width=True,
            )

    with tabs[1]:
        st.info(
            "Доступны DCA Long/Short и Grid Long/Short/Neutral "
            "в модели 1x. Без funding, ликвидаций, очереди "
            "лимитных ордеров и реального внутрисвечного потока."
        )

        a, b = st.columns(2)

        bar = a.selectbox(
            "Таймфрейм",
            list(BARS),
            key=f"bt_bar_{bot_id}",
        )
        days = int(b.number_input(
            "Дней истории",
            min_value=1,
            max_value=180,
            value=30,
            key=f"bt_days_{bot_id}",
        ))

        path_mode = st.radio(
            "Предположение о движении внутри свечи",
            ["Сначала Low", "Сначала High"],
            horizontal=True,
            key=f"bt_path_{bot_id}",
        )

        st.caption(
            "Полезно проверить оба варианта: результат может "
            "зависеть от неизвестного порядка High и Low. "
            "Grid стартует без позиции, с фиксированными "
            "парами уровней относительно цены начала теста."
        )

        if st.button(
            "Тестировать эту конфигурацию",
            key=f"run_bt_{bot_id}",
            use_container_width=True,
        ):
            try:
                end_ms = (
                    int(time.time() * 1000)
                    // BARS[bar] * BARS[bar]
                )
                start_ms = end_ms - days * 86_400_000

                with st.spinner("История и расчёт..."):
                    df = history(
                        config["symbol"],
                        bar,
                        start_ms,
                        end_ms,
                    )
                    result = backtest(
                        df,
                        config,
                        bar,
                        start_ms,
                        end_ms,
                        path_mode,
                    )

                with connect() as db:
                    db.execute(
                        """
                        INSERT INTO tests (
                            bot_id, config_hash, created, result
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (
                            bot_id,
                            config_hash(config),
                            now_utc(),
                            json.dumps(result, ensure_ascii=False),
                        ),
                    )

                add_event(
                    bot_id,
                    "Бэктест завершён",
                    (
                        f"{bot['name']}: {days} дней, {bar}, "
                        f"{path_mode}. Доходность "
                        f"{result['metrics']['Доходность %']:.2f}%."
                    ),
                    config["notify"],
                )
                dispatch()
                st.success("Результат сохранён.")

            except Exception as exc:
                st.error(str(exc))

        tests = tests_for(bot_id)

        if tests:
            chosen = st.selectbox(
                "Сохранённый результат",
                list(range(len(tests))),
                format_func=lambda index: (
                    tests[index]["created"] + " · "
                    + (
                        "текущая версия"
                        if tests[index]["config_hash"] == config_hash(config)
                        else "прежняя версия"
                    )
                ),
                key=f"saved_bt_{bot_id}",
            )

            test = json.loads(tests[chosen]["result"])

            if tests[chosen]["config_hash"] != config_hash(config):
                st.warning(
                    "Этот результат относится к прежней "
                    "конфигурации или версии расчётного движка."
                )

            st.dataframe(
                pd.DataFrame([test["metrics"]]),
                hide_index=True,
                use_container_width=True,
            )

            curve = pd.DataFrame(test["curve"])
            curve["time"] = pd.to_datetime(curve["time"], utc=True)

            fig = go.Figure(go.Scatter(
                x=curve["time"],
                y=curve["equity"],
                name="Equity",
                line=dict(color=GREEN, width=2),
            ))
            fig.update_layout(
                title="Капитал с открытыми позициями",
                yaxis_title="USDT",
            )
            show_figure(fig)

            st.caption(
                f"Период: {test['start']} — {test['end']}. "
                f"Путь: {test.get('path', 'не указан')}. "
                "Equity включает оценочную комиссию выхода. "
                "TP DCA — движение от средней; комиссии отдельно."
            )
        else:
            st.info("Тестов пока нет.")

    with tabs[2]:
        st.info(
            "Сначала настройте и запустите бота на OKX. "
            "Здесь подтверждается только факт ручного запуска."
        )

        actual = bot["confirmed"] or {}

        if config["side"] == "Neutral":
            st.caption(
                "Для Neutral здесь отслеживается диапазон. "
                "Полный фактический PnL без данных обеих сторон "
                "не рассчитывается."
            )

        with st.form(f"confirm_{bot_id}"):
            a, b = st.columns(2)

            average = a.number_input(
                "Фактическая средняя входа",
                min_value=0.0,
                value=float(actual.get("avg", 0)),
                format="%.8f",
                disabled=config["side"] == "Neutral",
            )
            quantity = b.number_input(
                "Количество базовой монеты",
                min_value=0.0,
                value=float(actual.get("qty", 0)),
                format="%.8f",
                help="Не число контрактов; эквивалент в BTC, ETH и т. п.",
                disabled=config["side"] == "Neutral",
            )

            a, b = st.columns(2)

            liquidation = a.number_input(
                "Ликвидация из OKX, 0 — неизвестна",
                min_value=0.0,
                value=float(actual.get("liq", 0)),
                format="%.8f",
                disabled=(
                    config["market"] == "Спот"
                    or config["side"] == "Neutral"
                ),
            )
            fees = b.number_input(
                "Комиссии текущего входа USDT",
                min_value=0.0,
                value=float(actual.get("fees", 0)),
                format="%.6f",
            )

            anchor = st.number_input(
                "Первый вход текущего цикла DCA",
                min_value=0.0,
                value=float(actual.get("anchor", 0)),
                format="%.8f",
                disabled=config["strategy"] != "DCA",
            )
            completed = int(st.number_input(
                "Подтверждённые СО текущего цикла",
                min_value=0,
                max_value=int(config["so"]),
                value=min(
                    int(actual.get("completed", 0)),
                    int(config["so"]),
                ),
                disabled=config["strategy"] != "DCA",
            ))

            consent = st.checkbox(
                "Подтверждаю: бот запущен на OKX, данные сверены"
            )

            submitted = st.form_submit_button(
                "Сохранить сверку и наблюдать",
                use_container_width=True,
            )

        if submitted:
            if not consent:
                st.error("Подтвердите фактический запуск.")
            elif (
                config["side"] != "Neutral"
                and (average <= 0 or quantity <= 0)
            ):
                st.error(
                    "Введите среднюю и количество. "
                    "Если позиции нет, используйте паузу."
                )
            else:
                confirmed = {
                    "avg": average,
                    "qty": quantity,
                    "liq": liquidation,
                    "fees": fees,
                    "anchor": anchor,
                    "completed": completed,
                    "updated": time.time(),
                    "time": now_utc(),
                }

                with connect() as db:
                    db.execute(
                        """
                        UPDATE bots
                        SET confirmed=?, status='Наблюдается',
                            state=NULL, checked=0
                        WHERE id=?
                        """,
                        (json.dumps(confirmed), bot_id),
                    )

                add_event(
                    bot_id,
                    "Ручная сверка",
                    f"{bot['name']}: данные подтверждены пользователем.",
                )
                check_bot(bot_id, True)
                dispatch()
                st.success("Сверка сохранена. Проверка выполнена.")

        a, b = st.columns(2)

        if a.button("Пауза наблюдения", key=f"pause_{bot_id}"):
            with connect() as db:
                db.execute(
                    "UPDATE bots SET status='Пауза' WHERE id=?",
                    (bot_id,),
                )
            add_event(
                bot_id,
                "Пауза",
                f"{bot['name']}: остановлен мониторинг, не бот на OKX.",
            )
            st.success("Мониторинг на паузе.")

        if b.button("Пометить закрытым", key=f"closed_{bot_id}"):
            with connect() as db:
                db.execute(
                    "UPDATE bots SET status='Закрыт' WHERE id=?",
                    (bot_id,),
                )
            add_event(
                bot_id,
                "Закрытие подтверждено",
                f"{bot['name']}: пользователь отметил закрытие.",
            )
            st.success("Карточка отмечена закрытой.")

    with tabs[3]:
        if st.button("Проверить сейчас", key=f"check_{bot_id}"):
            check_bot(bot_id, True)
            dispatch()

        fresh = get_bot(bot_id)
        snapshot = fresh["snapshot"]

        if snapshot:
            if "error" in snapshot:
                st.error(snapshot["error"])
            else:
                hero(snapshot["status"], " ".join(snapshot["reasons"]))

                a, b, c = st.columns(3)

                a.metric(
                    "Last-цена",
                    f"{snapshot['price']:.8f}",
                )
                b.metric(
                    "Условная оценка",
                    (
                        f"{snapshot['health']}/100"
                        if snapshot["health"] is not None
                        else "Неизвестно"
                    ),
                )
                c.metric(
                    "Оценочный PnL позиции",
                    (
                        f"{snapshot['pnl']:.4f} USDT"
                        if snapshot["pnl"] is not None
                        else "Неизвестно"
                    ),
                )

            st.caption(
                f"Проверка: {snapshot['time']} UTC. "
                f"Сверка позиции: "
                f"{(fresh['confirmed'] or {}).get('time', 'нет')}."
            )
        else:
            st.info("Подтвердите запуск и выполните проверку.")

        with st.expander("Ограничения наблюдения"):
            st.write(
                "Без приватного API не подтверждаются исполнения, "
                "funding и фактическая прибыль всего бота. "
                "Проверка цены не обновляет позицию. "
                "После нового цикла DCA обновите первый вход "
                "и количество выполненных СО."
            )

        chart_bar = st.selectbox(
            "Таймфрейм графика",
            list(BARS),
            index=2,
            key=f"chart_bar_{bot_id}",
        )

        if st.checkbox(
            "Показать свечи и индикаторы",
            key=f"show_chart_{bot_id}",
        ):
            try:
                price_chart(config["symbol"], chart_bar)
            except Exception as exc:
                st.error(str(exc))

    with tabs[4]:
        render_events(bot_id)


# ============================================================
# BOT LIST
# ============================================================

def render_bot_list():
    hero(
        "Ваши торговые проекты",
        "DCA и Grid, спот и фьючерсы. "
        "У каждого бота собственные настройки и история.",
    )

    st.button(
        "＋ Добавить бота",
        on_click=navigate,
        args=(PAGES[3], None, "edit"),
        use_container_width=True,
    )

    bots = all_bots()

    if not bots:
        st.info("Пока нет карточек. Создайте первого бота.")
        return

    status_filter = st.selectbox(
        "Показывать",
        ["Все", "Проект", "Наблюдается", "Пауза", "Закрыт"],
    )

    for bot in bots:
        if status_filter != "Все" and bot["status"] != status_filter:
            continue

        config = bot["config"]
        snapshot = bot["snapshot"] or {}

        badges = [
            config["market"],
            config["strategy"],
            config["side"],
            bot["status"],
        ]

        badge_html = "".join(
            f'<span class="badge">{html.escape(item)}</span>'
            for item in badges
        )

        st.markdown(
            '<div class="bot-card">'
            f'<div class="bot-name">{html.escape(bot["name"])}</div>'
            f'{badge_html}'
            '<div class="bot-meta">'
            f'{html.escape(config["symbol"])} · '
            f'Бюджет {config["budget"]:.2f} USDT<br>'
            f'Состояние: {html.escape(snapshot.get("status", "не оценено"))}'
            '</div></div>',
            unsafe_allow_html=True,
        )

        st.button(
            "Открыть бота",
            key=f"open_{bot['id']}",
            on_click=navigate,
            args=(PAGES[3], bot["id"], "detail"),
            use_container_width=True,
        )


# ============================================================
# SCANNER
# ============================================================

def scan_one(symbol, market, strategy, side, bar, info, ticker):
    last = indicators(recent_raw(symbol, bar)).iloc[-1]
    signal, reason = market_signal(last)

    volume = float(ticker.get("volCcy24h", 0) or 0)

    if market != "Спот":
        volume *= float(ticker.get("last", 0) or 0)

    listed = int(info.get("listTime", 0) or 0)
    young = (
        listed > 0
        and (time.time() * 1000 - listed) / 86_400_000 < 180
    )

    if strategy == "Grid":
        suitable = signal == "Нейтрально"
    elif side == "Long":
        suitable = signal == "Лонг" and 30 <= last["RSI"] <= 65
    else:
        suitable = signal == "Шорт" and 35 <= last["RSI"] <= 70

    if volume < 10_000_000:
        status = "Низкая ликвидность"
    elif young:
        status = "Молодой инструмент"
    elif suitable:
        status = "Кандидат"
    else:
        status = "Нет условий"

    return {
        "Инструмент": symbol,
        "Рынок": market,
        "Стратегия проекта": strategy,
        "Направление бота": side,
        "Сигнал рынка": signal,
        "Подходит": status,
        "Цена": float(ticker["last"]),
        "RSI": float(last["RSI"]),
        "ADX": float(last["ADX"]),
        "Объём USDT, оценка": volume,
        "Причина": reason,
    }


def render_scanner():
    hero(
        "Сканер рынка",
        "Сигнал рынка и направление вашего бота — "
        "разные поля. Выбор Short не создаёт сигнал Short.",
    )

    a, b = st.columns(2)

    market = a.selectbox("Рынок", ["Спот", "Фьючерсы"])
    strategy = b.selectbox("Стратегия", ["DCA", "Grid"])

    side = st.radio(
        "Направление создаваемого бота",
        available_sides(market, strategy),
        horizontal=True,
    )

    bar = st.selectbox("Таймфрейм", list(BARS), index=2)

    if st.button("Сканировать 20 монет", use_container_width=True):
        try:
            info_map = instruments(market)
            ticker_map = tickers(market)

            wanted = [
                coin + "-USDT"
                + ("-SWAP" if market != "Спот" else "")
                for coin in COINS
            ]

            available = [
                symbol for symbol in wanted
                if symbol in info_map and symbol in ticker_map
            ]

            rows = []
            errors = []
            progress = st.progress(0.0)

            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = {
                    pool.submit(
                        scan_one,
                        symbol,
                        market,
                        strategy,
                        side,
                        bar,
                        info_map[symbol],
                        ticker_map[symbol],
                    ): symbol
                    for symbol in available
                }

                for index, future in enumerate(as_completed(futures), 1):
                    try:
                        rows.append(future.result())
                    except Exception as exc:
                        errors.append(f"{futures[future]}: {exc}")

                    progress.progress(
                        index / max(len(available), 1)
                    )

            progress.empty()

            rows.sort(
                key=lambda row: row["Объём USDT, оценка"],
                reverse=True,
            )

            st.session_state["scan_result"] = {
                "rows": rows,
                "errors": errors,
                "missing": [
                    symbol for symbol in wanted
                    if symbol not in available
                ],
                "bar": bar,
                "time": now_utc(),
            }

        except Exception as exc:
            st.error(str(exc))

    saved = st.session_state.get("scan_result")

    if not saved:
        return

    st.caption(f"Сканирование: {saved['time']} UTC")

    if saved["missing"]:
        st.warning("Недоступны: " + ", ".join(saved["missing"]))

    if saved["errors"]:
        with st.expander("Ошибки отдельных монет"):
            st.write("\n".join(saved["errors"]))

    if not saved["rows"]:
        st.info("Нет результатов.")
        return

    table = pd.DataFrame(saved["rows"])

    a, b, c = st.columns(3)
    a.metric("Лонг", int((table["Сигнал рынка"] == "Лонг").sum()))
    b.metric("Шорт", int((table["Сигнал рынка"] == "Шорт").sum()))
    c.metric(
        "Нейтрально",
        int((table["Сигнал рынка"] == "Нейтрально").sum()),
    )

    def color_signal(value):
        if value == "Лонг":
            return f"color:{GREEN};font-weight:bold"
        if value == "Шорт":
            return f"color:{RED};font-weight:bold"
        if value == "Нейтрально":
            return f"color:{YELLOW};font-weight:bold"
        return "color:#AFC0D9"

    visible_columns = [
        "Инструмент",
        "Сигнал рынка",
        "Направление бота",
        "Подходит",
        "Цена",
        "RSI",
        "ADX",
        "Объём USDT, оценка",
    ]

    styled = (
        table[visible_columns]
        .style.format({
            "Цена": "{:,.8f}",
            "RSI": "{:.1f}",
            "ADX": "{:.1f}",
            "Объём USDT, оценка": "{:,.0f}",
        })
        .map(color_signal, subset=["Сигнал рынка"])
    )

    st.dataframe(
        styled,
        hide_index=True,
        use_container_width=True,
    )

    symbol = st.selectbox(
        "Выбранный инструмент",
        table["Инструмент"].tolist(),
    )

    row = table[table["Инструмент"] == symbol].iloc[0]

    st.write(
        f"Сигнал рынка: {row['Сигнал рынка']}. "
        f"Причина: {row['Причина']}."
    )

    seed = default_config({
        "market": row["Рынок"],
        "strategy": row["Стратегия проекта"],
        "side": row["Направление бота"],
        "symbol": symbol,
        "lower": float(row["Цена"]) * 0.9,
        "upper": float(row["Цена"]) * 1.1,
    })

    st.button(
        "Создать проект бота",
        on_click=navigate,
        args=(PAGES[3], None, "edit", seed),
        use_container_width=True,
    )

    if st.checkbox("Показать график с индикаторами"):
        try:
            price_chart(symbol, saved["bar"])
        except Exception as exc:
            st.error(str(exc))

    if st.button("Отправить сводку в Telegram"):
        message = (
            "Сканер OKX\nUTC: " + saved["time"] + "\n\n"
            + "\n".join(
                f"{row['Инструмент']}: рынок {row['Сигнал рынка']}; "
                f"бот {row['Стратегия проекта']} "
                f"{row['Направление бота']}; {row['Подходит']}"
                for row in saved["rows"]
            )
        )
        st.info(send_telegram(message))

    st.caption(
        "Сигналы — техническая классификация, не команда "
        "на сделку. Низкая ликвидность и молодой инструмент "
        "не становятся безопасными из-за сигнала."
    )


# ============================================================
# AI CENTER
# ============================================================

def render_ai_center():
    hero(
        "Разбор вашего бота",
        "Проверка настроек, тестов и последней сверки. "
        "Здесь используется объяснимая логика, "
        "а не подключённая языковая модель.",
    )

    bots = all_bots()

    if not bots:
        st.info("Сначала создайте бота в «Моих ботах».")
        return

    names = {bot["id"]: bot["name"] for bot in bots}
    ids = list(names)

    bot_id = st.selectbox(
        "Выберите бота для разбора",
        ids,
        format_func=lambda value: names[value],
    )

    bot = get_bot(bot_id)
    config = bot["config"]

    a, b, c = st.columns(3)
    a.metric("Рынок", config["market"])
    b.metric("Стратегия", config["strategy"])
    c.metric("Направление", config["side"])

    bar = st.selectbox(
        "Таймфрейм анализа",
        list(BARS),
        index=2,
        key="ai_bar",
    )

    if st.button(
        "Разобрать бота",
        use_container_width=True,
    ):
        try:
            with st.spinner("Проверка рынка и сохранённого плана..."):
                last = indicators(
                    recent(config["symbol"], bar)
                ).iloc[-1]

                signal, reason = market_signal(last)
                lines = recommendations(bot)

                text = (
                    f"{bot['name']}\n"
                    f"{config['symbol']} | "
                    f"{config['market']} | "
                    f"{config['strategy']} {config['side']}\n\n"
                    f"Сигнал рынка: {signal}\n"
                    f"Причина: {reason}\n"
                    f"RSI: {last['RSI']:.1f}, "
                    f"ADX: {last['ADX']:.1f}\n\n"
                    + "\n".join("• " + line for line in lines)
                )

                st.session_state["ai_analysis"] = {
                    "bot_id": bot_id,
                    "config_hash": config_hash(config),
                    "time": now_utc(),
                    "text": text,
                }

        except Exception as exc:
            st.error(str(exc))

    analysis = st.session_state.get("ai_analysis")

    if analysis and analysis["bot_id"] == bot_id:
        if analysis["config_hash"] != config_hash(config):
            st.warning(
                "Настройки изменились после анализа. "
                "Выполните новый разбор."
            )

        st.caption(
            f"Разбор выполнен: {analysis['time']} UTC"
        )
        st.text(analysis["text"])

        a, b = st.columns(2)

        if a.button("Сохранить решение в журнал"):
            add_event(
                bot_id,
                "Разбор сохранён",
                analysis["text"],
                False,
            )
            st.success("Сохранено.")

        if b.button("Отправить разбор в Telegram"):
            st.info(send_telegram(analysis["text"]))

    st.button(
        "Открыть настройки и тесты бота",
        on_click=navigate,
        args=(PAGES[3], bot_id, "detail"),
    )


# ============================================================
# APP START / SIX SECTIONS
# ============================================================

init_db()

with st.sidebar:
    st.markdown("## ⚡ OKX TERMINAL")
    st.caption("Боты · аналитика · контроль")

    page = st.radio(
        "Раздел",
        PAGES,
        key="page",
        label_visibility="collapsed",
    )

    st.divider()

    monitoring_enabled = st.checkbox(
        "Автопроверка активных карточек",
        value=True,
    )

    st.caption(
        "Раз в 60 секунд при работающей сессии. "
        "События отправляются без повторов "
        "каждой обычной проверки."
    )

st.title(page)


@st.fragment(
    run_every="60s" if monitoring_enabled else None
)
def monitor_fragment():
    if not monitoring_enabled:
        st.caption("Автопроверка выключена.")
        return

    try:
        active = [
            bot for bot in all_bots()
            if bot["status"] == "Наблюдается"
        ]

        for bot in active:
            check_bot(bot["id"])

        dispatch()

        st.caption(
            f"Последний цикл проверки: {now_utc()} UTC · "
            f"наблюдаемых карточек: {len(active)}"
        )

    except Exception as exc:
        st.warning("Проверка временно недоступна: " + str(exc))


monitor_fragment()


if page == PAGES[0]:
    hero(
        "Планируйте бота до запуска",
        "Выберите рынок и стратегию, настройте проект, "
        "проверьте историю и получите значения для OKX. "
        "После запуска подтверждайте фактическую позицию.",
    )

    bots = all_bots()
    active = sum(bot["status"] == "Наблюдается" for bot in bots)
    projects = sum(bot["status"] == "Проект" for bot in bots)

    warnings = sum(
        (bot["snapshot"] or {}).get("status")
        in ["Высокий риск", "Нужна сверка", "Внимание"]
        for bot in bots
        if bot["status"] == "Наблюдается"
    )

    a, b, c, d = st.columns(4)
    a.metric("Всего карточек", len(bots))
    b.metric("Наблюдаются", active)
    c.metric("Проекты", projects)
    d.metric("Требуют внимания", warnings)

    st.write("")

    a, b = st.columns(2)

    a.button(
        "＋ Создать своего бота",
        on_click=navigate,
        args=(PAGES[3], None, "edit"),
        use_container_width=True,
    )
    b.button(
        "Открыть сканер",
        on_click=navigate,
        args=(PAGES[1],),
        use_container_width=True,
    )

    st.subheader("Последние карточки")

    if not bots:
        st.info("Карточек пока нет.")
    else:
        for bot in bots[:4]:
            config = bot["config"]
            snapshot = bot["snapshot"] or {}

            with st.container(border=True):
                st.write(
                    f"{bot['name']} · "
                    f"{config['strategy']} {config['side']}"
                )
                st.caption(
                    f"{config['market']} · {config['symbol']} · "
                    f"{bot['status']} · "
                    f"{snapshot.get('status', 'ещё не оценён')}"
                )
                st.button(
                    "Открыть",
                    key=f"home_open_{bot['id']}",
                    on_click=navigate,
                    args=(PAGES[3], bot["id"], "detail"),
                )

    with st.expander("Что приложение делает и чего не делает"):
        st.write(
            "Приложение использует публичные цены OKX, "
            "хранит ваши проекты и проверяет заданные пороги. "
            "Оно не размещает ордера и не подтверждает "
            "фактические исполнения без приватного API. "
            "Локальная база требует резервных копий. "
            "Приложение рассчитано на одного владельца."
        )

elif page == PAGES[1]:
    render_scanner()

elif page == PAGES[2]:
    render_ai_center()

elif page == PAGES[3]:
    mode = st.session_state.get("bots_mode", "list")

    if mode == "edit":
        render_editor()
    elif mode == "detail":
        render_bot_detail()
    else:
        render_bot_list()

elif page == PAGES[4]:
    hero(
        "Журнал решений",
        "Только важные события: настройки, тесты, "
        "сохранённые разборы, ручные сверки "
        "и изменения состояния.",
    )

    bots = all_bots()
    names = {bot["id"]: bot["name"] for bot in bots}

    selection = st.selectbox(
        "Фильтр по боту",
        ["all"] + list(names),
        format_func=lambda value: (
            "Все боты" if value == "all" else names[value]
        ),
    )

    render_events(None if selection == "all" else selection)

elif page == PAGES[5]:
    hero(
        "Настройки терминала",
        "Telegram, резервная копия и ограничения мониторинга.",
    )

    token, chat_id = telegram_credentials()

    if token and chat_id:
        st.success("Telegram Secrets найдены.")
    else:
        st.warning("Telegram Secrets не настроены.")

    if st.button("Тест Telegram", use_container_width=True):
        st.info(send_telegram(
            "OKX Bot Manager: связь проверена ✅"
        ))

    with st.expander("Формат Telegram Secrets"):
        st.code(
            '[telegram]\n'
            'token = "ВАШ_ТОКЕН"\n'
            'chat_id = "ВАШ_CHAT_ID"',
            language="toml",
        )
        st.caption(
            "Вводите это в Secrets Streamlit, "
            "не публикуйте в GitHub."
        )

    st.subheader("Резервная копия")

    with connect() as source:
        backup = sqlite3.connect(":memory:")
        source.backup(backup)
        dump = "\n".join(backup.iterdump())
        backup.close()

    st.download_button(
        "Скачать карточки, тесты и события SQL",
        dump.encode("utf-8"),
        file_name="bots_backup.sql",
        mime="text/plain",
        use_container_width=True,
    )

    st.caption(
        "Копия содержит сведения о позициях. "
        "Не публикуйте её. Telegram-токен в базу не записывается."
    )

    st.warning(
        "Проверки выполняются при работающей сессии. "
        "При закрытой странице или спящем приложении "
        "круглосуточные уведомления не гарантируются. "
        "На облачном локальном диске нельзя гарантировать "
        "постоянную сохранность базы."
    )

    st.info(
        "Long / Short / Neutral — направление бота. "
        "Лонг / Шорт / Нейтрально в Сканере — "
        "отдельная техническая классификация рынка."
    )
