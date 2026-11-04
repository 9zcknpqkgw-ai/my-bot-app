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
# ОСНОВНЫЕ НАСТРОЙКИ
# ============================================================

st.set_page_config(
    page_title="OKX Bot Manager",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="auto",
)

API = "https://www.okx.com/api/v5"
DB_FILE = "bots.sqlite3"

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

GREEN = "#00EFA7"
RED = "#FF5575"
BLUE = "#49BFFF"
YELLOW = "#FFD166"

PAGES = [
    "Мои боты",
    "Добавить / изменить",
    "Карточка бота",
    "Сканер",
    "Журнал событий",
    "Настройки",
]


# ============================================================
# ДИЗАЙН
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
    color: #E8EEF8;
    background:
        radial-gradient(
            950px 500px at 0% 0%,
            rgba(0, 239, 167, .07),
            transparent 65%
        ),
        #060910;
}

[data-testid="stHeader"],
[data-testid="stSidebar"],
[data-testid="stSidebar"] > div {
    background: #0B101B !important;
    opacity: 1 !important;
}

[data-testid="stSidebar"] {
    border-right: 1px solid #27344B;
}

h1, h2, h3, h4 {
    color: #F1F6FF !important;
    letter-spacing: -.025em;
}

[data-testid="stMarkdownContainer"] p,
[data-testid="stWidgetLabel"] p,
[data-testid="stCaptionContainer"] p,
[data-testid="stRadio"] p,
[data-testid="stCheckbox"] p {
    color: #DCE6F5 !important;
}

[data-testid="stSidebar"] [data-testid="stRadio"] label {
    background: #152033 !important;
    border: 1px solid #2D3C56;
    border-radius: 12px;
    padding: 9px 11px;
    margin-bottom: 6px;
}

[data-testid="stSidebar"] [data-testid="stRadio"] label:hover {
    border-color: #00EFA7;
}

[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input {
    background: #121C2C !important;
    color: #F2F6FF !important;
    -webkit-text-fill-color: #F2F6FF !important;
    caret-color: #00EFA7;
}

[data-testid="stNumberInput"] button {
    background: #1B2A40 !important;
    color: #F2F6FF !important;
}

[data-baseweb="select"] > div {
    background: #121C2C !important;
    color: #F2F6FF !important;
    border-color: #2D3C56 !important;
}

[data-baseweb="select"] span {
    color: #F2F6FF !important;
}

[role="listbox"],
[role="option"] {
    background: #121C2C !important;
    color: #F2F6FF !important;
}

.stButton > button,
.stFormSubmitButton > button {
    min-height: 45px;
    border: 0 !important;
    border-radius: 12px !important;
    background:
        linear-gradient(110deg, #00EFA7, #3BBEFF) !important;
    transition:
        transform .18s ease,
        box-shadow .18s ease;
}

.stButton > button p,
.stFormSubmitButton > button p {
    color: #031019 !important;
    font-weight: 700 !important;
}

.stButton > button:hover,
.stFormSubmitButton > button:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 25px rgba(0, 239, 167, .18);
}

.stDownloadButton > button {
    background: #152239 !important;
    border: 1px solid #355475 !important;
    border-radius: 12px !important;
}

.stDownloadButton > button p {
    color: #E8EEF8 !important;
}

.panel {
    background:
        linear-gradient(135deg, #152034, #0D1420);
    border: 1px solid #2B3B55;
    border-radius: 17px;
    padding: 19px;
    margin-bottom: 15px;
}

.panel-title {
    font-size: 1.1rem;
    font-weight: 750;
    color: #F2F6FF;
    margin-bottom: 8px;
}

.panel-text {
    color: #B9C8DF;
    line-height: 1.6;
}

[data-testid="stMetric"] {
    background: #111B2B;
    border: 1px solid #293A54;
    border-radius: 14px;
    padding: 15px;
}

[data-testid="stMetricLabel"] p,
[data-testid="stMetricValue"] {
    color: #E8EEF8 !important;
}

[data-testid="stDataFrame"] {
    border: 1px solid #2B3B55;
    border-radius: 12px;
    overflow: hidden;
}

@media (max-width: 768px) {
    .block-container {
        padding: 1rem 1rem 4rem !important;
    }

    h1 {
        font-size: 1.9rem !important;
    }

    .panel {
        padding: 15px;
    }
}
</style>
""",
    unsafe_allow_html=True,
)


# ============================================================
# СЛУЖЕБНЫЕ ФУНКЦИИ
# ============================================================

def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def panel(title, text):
    st.markdown(
        f"""
        <div class="panel">
            <div class="panel-title">
                {html.escape(str(title))}
            </div>
            <div class="panel-text">
                {html.escape(str(text))}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def show_chart(fig, height=420):
    fig.update_layout(
        template="plotly_dark",
        height=height,
        paper_bgcolor="#0C1320",
        plot_bgcolor="#0C1320",
        font=dict(color="#E8EEF8"),
        margin=dict(l=15, r=15, t=50, b=25),
    )

    fig.update_xaxes(gridcolor="#223047")
    fig.update_yaxes(gridcolor="#223047")

    st.plotly_chart(
        fig,
        use_container_width=True,
        config={"displaylogo": False},
    )


def config_hash(config):
    encoded = json.dumps(
        config,
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest()[:16]


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


# ============================================================
# БАЗА ДАННЫХ
# ============================================================

def db_connect():
    connection = sqlite3.connect(
        DB_FILE,
        timeout=30,
    )

    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")

    return connection


def init_db():
    with db_connect() as db:
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
    with db_connect() as db:
        row = db.execute(
            "SELECT * FROM bots WHERE id=?",
            (bot_id,),
        ).fetchone()

    if not row:
        return None

    bot = dict(row)

    bot["config"] = default_config(
        json.loads(bot["config"])
    )

    for key in ["confirmed", "snapshot"]:
        bot[key] = (
            json.loads(bot[key])
            if bot[key]
            else None
        )

    return bot


def all_bots():
    with db_connect() as db:
        ids = [
            row[0]
            for row in db.execute(
                "SELECT id FROM bots ORDER BY created DESC"
            )
        ]

    return [get_bot(bot_id) for bot_id in ids]


def add_event(bot_id, kind, message, notify=False):
    with db_connect() as db:
        cursor = db.execute(
            """
            INSERT INTO events (
                bot_id, created, kind, message, notify
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                bot_id,
                utc_now(),
                kind,
                message,
                "pending" if notify else "off",
            ),
        )

        return cursor.lastrowid


def get_tests(bot_id):
    with db_connect() as db:
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


def current_test(bot):
    fingerprint = config_hash(bot["config"])

    for row in get_tests(bot["id"]):
        if row["config_hash"] == fingerprint:
            return json.loads(row["result"])

    return None


# ============================================================
# OKX API
# ============================================================

@st.cache_resource
def api_control():
    return {
        "lock": threading.Lock(),
        "last": [0.0],
    }


API_CONTROL = api_control()


def api_get(endpoint, params=None):
    error = "Нет ответа OKX"

    for attempt in range(4):
        with API_CONTROL["lock"]:
            elapsed = (
                time.monotonic()
                - API_CONTROL["last"][0]
            )

            time.sleep(max(0.0, 0.18 - elapsed))
            API_CONTROL["last"][0] = time.monotonic()

        try:
            response = requests.get(
                API + endpoint,
                params=params,
                headers={
                    "User-Agent": "OKX-Bot-Manager/2.0"
                },
                timeout=(8, 25),
            )

            if response.status_code == 429:
                error = "Превышен лимит запросов OKX"
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

        except (
            requests.RequestException,
            ValueError,
        ) as exc:
            error = str(exc)

        time.sleep(0.5 * (attempt + 1))

    raise RuntimeError(error)


def market_type(market):
    return "SPOT" if market == "Спот" else "SWAP"


@st.cache_data(ttl=3600, show_spinner=False)
def get_instruments(market):
    rows = api_get(
        "/public/instruments",
        {"instType": market_type(market)},
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
        raise RuntimeError(
            "OKX не вернул доступные USDT-инструменты"
        )

    return result


@st.cache_data(ttl=45, show_spinner=False)
def get_tickers(market):
    rows = api_get(
        "/market/tickers",
        {"instType": market_type(market)},
    )

    return {
        item["instId"]: item
        for item in rows
    }


def get_price(symbol):
    rows = api_get(
        "/market/ticker",
        {"instId": symbol},
    )

    if not rows:
        raise RuntimeError("Нет текущей цены")

    price = float(rows[0].get("last", 0) or 0)

    if price <= 0:
        raise RuntimeError("Некорректная текущая цена")

    return price


def candles_frame(rows):
    if not rows:
        raise RuntimeError("OKX не вернул свечи")

    columns = [
        "ts", "o", "h", "l", "c",
        "vol", "baseVol", "quoteVol", "confirm",
    ]

    df = pd.DataFrame(
        rows,
        columns=columns,
    )

    for column in columns:
        df[column] = pd.to_numeric(
            df[column],
            errors="coerce",
        )

    df = df[df["confirm"] == 1]
    df = df.dropna(
        subset=["ts", "o", "h", "l", "c"]
    )

    df = df[
        (df[["o", "h", "l", "c"]] > 0).all(axis=1)
    ]

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

    df = candles_frame(rows)

    if len(df) < 60:
        raise RuntimeError(
            "Нужно минимум 60 закрытых свечей"
        )

    return df


@st.cache_data(ttl=90, show_spinner=False)
def get_candles(symbol, bar):
    return recent_raw(symbol, bar)


@st.cache_data(ttl=1800, show_spinner=False)
def get_history(symbol, bar, start_ms, end_ms):
    rows = []
    cursor = end_ms

    expected = max(
        1,
        int((end_ms - start_ms) / BARS[bar]),
    )

    max_pages = expected // 100 + 10

    for _ in range(max_pages):
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
            raise RuntimeError(
                "Ошибка пагинации истории OKX"
            )

        cursor = oldest

    df = candles_frame(rows)

    df = df[
        (df["ts"] >= start_ms)
        & (df["ts"] < end_ms)
    ].reset_index(drop=True)

    if len(df) < 30:
        raise RuntimeError(
            "Недостаточно исторических свечей"
        )

    return df


# ============================================================
# ИНДИКАТОРЫ И ГРАФИКИ
# ============================================================

def with_indicators(df):
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


def render_price_chart(symbol, bar):
    df = with_indicators(
        get_candles(symbol, bar)
    )

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
                line=dict(
                    color=color,
                    width=1.6,
                ),
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

    show_chart(fig, 660)


# ============================================================
# TELEGRAM
# ============================================================

def telegram_credentials():
    token = ""
    chat_id = ""

    try:
        section = st.secrets.get("telegram", {})
        token = section.get("token", "")
        chat_id = section.get("chat_id", "")
    except Exception:
        pass

    return (
        str(token).strip(),
        str(chat_id).strip(),
    )


def send_telegram(message):
    token, chat_id = telegram_credentials()

    if not token or not chat_id:
        return "error: Не заданы Telegram Secrets"

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
            "unknown: Тайм-аут. Перед повторной "
            "отправкой проверьте Telegram."
        )

    except Exception:
        return "error: Не удалось связаться с Telegram"


def dispatch_notifications():
    with db_connect() as db:
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

        with db_connect() as db:
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

        message = (
            f"OKX Bot Manager\n"
            f"{row['kind']}\n"
            f"UTC: {row['created']}\n\n"
            f"{row['message']}"
        )

        result = send_telegram(message)

        with db_connect() as db:
            db.execute(
                """
                UPDATE events
                SET notify=?
                WHERE id=?
                """,
                (result, row["id"]),
            )

        time.sleep(0.1)


# ============================================================
# DCA И ПРОВЕРКА НАСТРОЕК
# ============================================================

def dca_orders(config, entry):
    direction = (
        1
        if config["side"] == "Long"
        else -1
    )

    leverage = (
        config["leverage"]
        if config["market"] != "Спот"
        else 1.0
    )

    rows = []
    total_margin = 0.0
    total_notional = 0.0
    total_quantity = 0.0
    offset = 0.0

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
            "Средняя цена": (
                total_notional / total_quantity
            ),
        })

    return pd.DataFrame(rows)


def required_reserve(config):
    amount = config["base"]

    amount += sum(
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


def validate_config(config):
    errors = []

    if config["budget"] <= 0:
        errors.append(
            "Бюджет должен быть положительным."
        )

    if (
        config["market"] == "Спот"
        and config["side"] != "Long"
    ):
        errors.append(
            "Спотовая модель поддерживает только Long."
        )

    if config["strategy"] == "DCA":
        if config["side"] == "Neutral":
            errors.append(
                "Для DCA выберите Long или Short."
            )

        try:
            dca_orders(config, 100.0)
        except ValueError as exc:
            errors.append(str(exc))

        reserve = required_reserve(config)

        if reserve > config["budget"]:
            errors.append(
                f"Нужно минимум {reserve:.2f} USDT "
                f"на все ордера и входные комиссии. "
                f"Ваш бюджет: {config['budget']:.2f}."
            )

    else:
        if (
            config["lower"] <= 0
            or config["upper"] <= config["lower"]
        ):
            errors.append(
                "Проверьте диапазон Grid."
            )

    return errors


def okx_passport(config):
    rows = [
        (
            "Рынок / продукт",
            f"{config['market']} · {config['strategy']}",
        ),
        ("Инструмент", config["symbol"]),
        ("Направление", config["side"]),
        ("Бюджет USDT", config["budget"]),
    ]

    if config["market"] != "Спот":
        rows.append(
            ("Leverage / Плечо", config["leverage"])
        )

    if config["strategy"] == "DCA":
        rows.extend([
            ("Price steps, %", config["step"]),
            (
                "Price steps multiplier",
                config["step_mult"],
            ),
            (
                "TP target per cycle, %",
                config["tp"],
            ),
            (
                "Initial order amount / margin USDT",
                config["base"],
            ),
            (
                "Safety order amount / margin USDT",
                config["safety"],
            ),
            ("Max safety orders", config["so"]),
            (
                "Amount multiplier",
                config["amount_mult"],
            ),
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
        (
            "Комиссия модели за сторону, %",
            config["fee"],
        ),
    ])

    return pd.DataFrame(
        rows,
        columns=["Поле", "Значение"],
    )


# ============================================================
# БЭКТЕСТ
# ============================================================

def run_backtest(
    df,
    config,
    bar,
    start_ms,
    end_ms,
):
    if (
        config["market"] != "Спот"
        and config["leverage"] != 1
    ):
        raise ValueError(
            "Бэктест фьючерсов с плечом выше 1x "
            "пока не реализован. Настройки не подменяются."
        )

    if (
        config["strategy"] == "Grid"
        and config["side"] != "Long"
    ):
        raise ValueError(
            "Бэктест Short/Neutral Grid пока "
            "не реализован."
        )

    errors = validate_config(config)

    if errors:
        raise ValueError(" ".join(errors))

    initial = float(config["budget"])
    fee_rate = config["fee"] / 100

    cash = initial
    quantity = 0.0
    locked = 0.0
    fees_paid = 0.0
    cycles = 0
    next_so = 1

    orders = []
    lots = {}
    curve = []
    stopped = False

    direction = (
        1
        if config["side"] == "Long"
        else -1
    )

    first_price = float(df.iloc[0]["o"])

    if (
        config["stop"] > 0
        and direction * (
            first_price - config["stop"]
        ) <= 0
    ):
        raise ValueError(
            "Стоп находится с неверной стороны "
            "цены начала теста."
        )

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

    active_grid = [
        index
        for index in range(len(levels) - 1)
        if levels[index] < first_price
    ]

    if (
        config["strategy"] == "Grid"
        and not active_grid
    ):
        raise ValueError(
            "На старте теста нет уровней покупки "
            "ниже рыночной цены."
        )

    grid_amount = (
        initial
        / max(len(active_grid), 1)
        / (1 + fee_rate)
    )

    def equity(price):
        if config["strategy"] == "DCA":
            return (
                cash
                + locked
                + direction * (
                    quantity * price - locked
                )
                - quantity * price * fee_rate
            )

        return cash + sum(
            lot["quantity"]
            * price
            * (1 - fee_rate)
            for lot in lots.values()
        )

    def point(row, price):
        curve.append({
            "time": str(row["time"]),
            "equity": float(equity(price)),
        })

    def close_dca(price):
        nonlocal cash
        nonlocal quantity
        nonlocal locked
        nonlocal fees_paid

        pnl = direction * (
            quantity * price - locked
        )

        exit_fee = (
            quantity * price * fee_rate
        )

        cash += locked + pnl - exit_fee
        fees_paid += exit_fee

        quantity = 0.0
        locked = 0.0

    for _, row in df.iterrows():
        opening = float(row["o"])
        low = float(row["l"])
        high = float(row["h"])
        closing = float(row["c"])

        point(row, opening)

        if config["strategy"] == "DCA":
            closed_at_open = False

            if quantity > 0:
                target = (
                    locked / quantity
                    * (
                        1
                        + direction
                        * config["tp"] / 100
                    )
                )

                if (
                    config["stop"] > 0
                    and direction * (
                        opening - config["stop"]
                    ) <= 0
                ):
                    close_dca(opening)
                    point(row, opening)
                    stopped = True

                elif direction * (
                    opening - target
                ) >= 0:
                    close_dca(opening)
                    cycles += 1
                    closed_at_open = True
                    point(row, opening)

            if stopped:
                break

            if (
                quantity == 0
                and not closed_at_open
                and config["base"]
                * (1 + fee_rate) <= cash
            ):
                amount = config["base"]
                entry_fee = amount * fee_rate

                cash -= amount + entry_fee
                quantity = amount / opening
                locked = amount
                fees_paid += entry_fee

                orders = dca_orders(
                    config,
                    opening,
                ).to_dict("records")

                next_so = 1
                point(row, opening)

            if quantity > 0:
                adverse = (
                    low
                    if direction == 1
                    else high
                )

                favorable = (
                    high
                    if direction == 1
                    else low
                )

                stop_hit = (
                    config["stop"] > 0
                    and direction * (
                        adverse - config["stop"]
                    ) <= 0
                )

                if stop_hit:
                    adverse_limit = (
                        max(adverse, config["stop"])
                        if direction == 1
                        else min(
                            adverse,
                            config["stop"],
                        )
                    )
                else:
                    adverse_limit = adverse

                while (
                    next_so <= config["so"]
                    and direction * (
                        adverse_limit
                        - orders[next_so]["Цена"]
                    ) <= 0
                ):
                    order = orders[next_so]
                    level = order["Цена"]

                    fill = (
                        min(opening, level)
                        if direction == 1
                        else max(opening, level)
                    )

                    point(row, fill)

                    amount = order["Номинал USDT"]
                    entry_fee = amount * fee_rate

                    if (
                        amount + entry_fee
                        > cash + 1e-9
                    ):
                        break

                    cash -= amount + entry_fee
                    quantity += amount / fill
                    locked += amount
                    fees_paid += entry_fee
                    next_so += 1

                    point(row, fill)

                point(row, adverse_limit)

                if stop_hit:
                    close_dca(config["stop"])
                    point(row, config["stop"])
                    stopped = True

                else:
                    target = (
                        locked / quantity
                        * (
                            1
                            + direction
                            * config["tp"] / 100
                        )
                    )

                    if direction * (
                        favorable - target
                    ) >= 0:
                        close_dca(target)
                        cycles += 1
                        point(row, target)
                    else:
                        point(row, favorable)

        else:
            sold_at_open = set()

            for index, lot in list(lots.items()):
                if opening >= lot["target"]:
                    gross = (
                        lot["quantity"]
                        * lot["target"]
                    )

                    exit_fee = gross * fee_rate

                    cash += gross - exit_fee
                    fees_paid += exit_fee
                    cycles += 1

                    del lots[index]
                    sold_at_open.add(index)

            stop_hit = (
                config["stop"] > 0
                and low <= config["stop"]
            )

            if stop_hit and opening <= config["stop"]:
                for lot in lots.values():
                    gross = (
                        lot["quantity"] * opening
                    )

                    exit_fee = gross * fee_rate
                    cash += gross - exit_fee
                    fees_paid += exit_fee

                lots = {}
                point(row, opening)
                stopped = True

            if stopped:
                break

            low_limit = (
                max(low, config["stop"])
                if stop_hit
                else low
            )

            for index in reversed(active_grid):
                if (
                    index in lots
                    or index in sold_at_open
                    or low_limit > levels[index]
                ):
                    continue

                fill = min(
                    opening,
                    float(levels[index]),
                )

                point(row, fill)

                entry_fee = (
                    grid_amount * fee_rate
                )

                debit = grid_amount + entry_fee

                if debit > cash + 1e-9:
                    continue

                cash -= debit
                fees_paid += entry_fee

                lots[index] = {
                    "quantity": grid_amount / fill,
                    "target": float(
                        levels[index + 1]
                    ),
                }

                point(row, fill)

            point(row, low_limit)

            if stop_hit:
                for lot in lots.values():
                    gross = (
                        lot["quantity"]
                        * config["stop"]
                    )

                    exit_fee = gross * fee_rate

                    cash += gross - exit_fee
                    fees_paid += exit_fee

                lots = {}
                stopped = True

                point(row, config["stop"])

            else:
                for index in sorted(list(lots)):
                    lot = lots[index]

                    if high >= lot["target"]:
                        gross = (
                            lot["quantity"]
                            * lot["target"]
                        )

                        exit_fee = (
                            gross * fee_rate
                        )

                        cash += gross - exit_fee
                        fees_paid += exit_fee
                        cycles += 1

                        del lots[index]
                        point(row, lot["target"])

                point(row, high)

        point(row, closing)

        if stopped or curve[-1]["equity"] <= 0:
            break

    curve_df = pd.DataFrame(curve)

    peaks = (
        curve_df["equity"]
        .cummax()
        .clip(lower=initial)
    )

    drawdown = peaks - curve_df["equity"]

    final_equity = float(
        curve_df.iloc[-1]["equity"]
    )

    expected = max(
        1,
        int((end_ms - start_ms) / BARS[bar]),
    )

    metrics = {
        "Итоговая equity USDT": round(
            final_equity, 3
        ),
        "PnL USDT": round(
            final_equity - initial, 3
        ),
        "Доходность %": round(
            (final_equity / initial - 1) * 100,
            3,
        ),
        "Макс. просадка USDT": round(
            float(drawdown.max()), 3
        ),
        "Макс. просадка %": round(
            float(
                (drawdown / peaks * 100).max()
            ),
            3,
        ),
        "Комиссии уплачены": round(
            fees_paid, 4
        ),
        "Завершено циклов": cycles,
        "Свечей": len(df),
        "Покрытие %": round(
            min(
                100,
                len(df) / expected * 100,
            ),
            2,
        ),
        "Пропуски": bool(
            (
                df["ts"].diff().dropna()
                != BARS[bar]
            ).any()
        ),
        "Стоп сработал": stopped,
    }

    return {
        "metrics": metrics,
        "curve": curve,
        "config": config,
        "bar": bar,
        "start": str(df.iloc[0]["time"]),
        "end": str(df.iloc[-1]["time"]),
        "created": utc_now(),
    }


# ============================================================
# РЕКОМЕНДАЦИИ ПО КАРТОЧКЕ
# ============================================================

def bot_recommendations(bot):
    config = bot["config"]
    lines = []

    for error in validate_config(config):
        lines.append(
            "Нужно исправить: " + error
        )

    if config["strategy"] == "DCA":
        lines.append(
            f"Резерв всех ордеров с оценкой "
            f"входных комиссий: "
            f"{required_reserve(config):.2f} USDT. "
            f"Бюджет: {config['budget']:.2f} USDT."
        )

        if config["tp"] <= 2 * config["fee"]:
            lines.append(
                "TP может не покрывать комиссию "
                "полного торгового оборота."
            )

    else:
        if (
            config["grid_type"]
            == "Геометрическая"
        ):
            min_step = (
                (
                    config["upper"]
                    / config["lower"]
                ) ** (
                    1 / config["grids"]
                )
                - 1
            ) * 100
        else:
            min_step = (
                (
                    config["upper"]
                    - config["lower"]
                )
                / config["grids"]
                / config["upper"]
                * 100
            )

        lines.append(
            f"Приблизительный минимальный "
            f"процентный шаг: {min_step:.3f}%. "
            f"Комиссия оборота около "
            f"{2 * config['fee']:.3f}%."
        )

        if min_step <= 2 * config["fee"]:
            lines.append(
                "Комиссия может съедать "
                "прибыль сеточного шага."
            )

    test = current_test(bot)

    if not test:
        lines.append(
            "Текущая версия ещё не протестирована. "
            "Старые результаты не подтверждают "
            "новые настройки."
        )
    else:
        metrics = test["metrics"]

        profitability = metrics.get(
            "Доходность %",
            0,
        )

        drawdown = metrics.get(
            "Макс. просадка %",
            0,
        )

        lines.append(
            f"Тест текущей версии: "
            f"доходность {profitability:.2f}%, "
            f"просадка {drawdown:.2f}%. "
            "Один период не является прогнозом."
        )

        if profitability <= 0:
            lines.append(
                "Модель не дала положительный "
                "результат на выбранном периоде."
            )

        if drawdown > config["loss_limit"]:
            lines.append(
                "Просадка теста превышает "
                "заданный вами порог риска."
            )

        if (
            metrics.get("Покрытие %", 0) < 95
            or metrics.get("Пропуски", False)
        ):
            lines.append(
                "История неполная или с пропусками. "
                "Результат требует осторожной оценки."
            )

    if config["market"] != "Спот":
        lines.append(
            "Funding, фактическая маржа и "
            "ликвидация в тесте не моделируются."
        )

    lines.append(
        "Перед запуском на OKX проверьте "
        "минимальные ордера, округление, "
        "единицы сумм и доступность продукта."
    )

    return lines


# ============================================================
# МОНИТОРИНГ
# ============================================================

def evaluate_bot(bot, price):
    config = bot["config"]
    actual = bot["confirmed"] or {}

    conditions = []
    reasons = []

    quantity = float(
        actual.get("qty", 0)
    )

    average = float(
        actual.get("avg", 0)
    )

    liquidation = float(
        actual.get("liq", 0)
    )

    direction = (
        1
        if config["side"] == "Long"
        else -1
    )

    pnl = None
    distance = None

    age_hours = (
        time.time()
        - float(actual.get("updated", 0))
    ) / 3600

    if age_hours > config["stale_hours"]:
        conditions.append("stale")
        reasons.append(
            "Данные позиции устарели: "
            "нужна ручная сверка с OKX."
        )

    if (
        quantity > 0
        and average > 0
        and config["side"] != "Neutral"
    ):
        pnl = (
            direction
            * quantity
            * (price - average)
            - quantity
            * price
            * config["fee"] / 100
            - float(actual.get("fees", 0))
        )

        loss_pct = (
            -pnl
            / config["budget"]
            * 100
        )

        if loss_pct >= config["loss_limit"]:
            conditions.append("loss")
            reasons.append(
                f"Оценочный убыток "
                f"{loss_pct:.1f}% бюджета "
                "достиг вашего порога."
            )

    else:
        conditions.append("position_unknown")
        reasons.append(
            "Фактическая направленная позиция "
            "не задана: PnL неизвестен."
        )

    if (
        config["market"] != "Спот"
        and config["side"] != "Neutral"
    ):
        if liquidation > 0:
            distance = (
                direction
                * (price - liquidation)
                / price
                * 100
            )

            if (
                distance
                <= config["liq_warning"]
            ):
                conditions.append("liquidation")
                reasons.append(
                    f"До введённой ликвидации "
                    f"{distance:.2f}% по last-цене. "
                    "Проверьте mark price на OKX."
                )
        else:
            conditions.append("liq_unknown")
            reasons.append(
                "Цена ликвидации неизвестна."
            )

    if config["strategy"] == "Grid":
        lower = config["lower"]
        upper = config["upper"]

        if price < lower:
            conditions.append("below_grid")
            reasons.append(
                "Цена ниже диапазона Grid."
            )

        elif price > upper:
            conditions.append("above_grid")
            reasons.append(
                "Цена выше диапазона Grid."
            )

        elif (
            min(
                price - lower,
                upper - price,
            )
            / (upper - lower)
            < 0.05
        ):
            conditions.append("grid_edge")
            reasons.append(
                "Цена у края диапазона Grid."
            )

    else:
        anchor = float(
            actual.get("anchor", 0)
        )

        completed = int(
            actual.get("completed", 0)
        )

        if (
            anchor > 0
            and completed < config["so"]
        ):
            orders = dca_orders(
                config,
                anchor,
            )

            next_price = float(
                orders.iloc[
                    completed + 1
                ]["Цена"]
            )

            gap = (
                direction
                * (price - next_price)
                / price
                * 100
            )

            if gap <= 0.3:
                conditions.append("safety_level")
                reasons.append(
                    f"Цена у/за расчётным СО "
                    f"{completed + 1}: "
                    f"{next_price:.8f}. "
                    "Исполнение не подтверждено."
                )

        if quantity > 0 and average > 0:
            target = average * (
                1
                + direction
                * config["tp"] / 100
            )

            if direction * (
                price - target
            ) >= 0:
                conditions.append("tp_level")
                reasons.append(
                    f"Цена у/за расчётным TP "
                    f"{target:.8f}. "
                    "Исполнение не подтверждено."
                )

    if (
        config["stop"] > 0
        and config["side"] != "Neutral"
        and direction * (
            price - config["stop"]
        ) <= 0
    ):
        conditions.append("stop_level")
        reasons.append(
            "Цена у/за указанным стопом. "
            "Проверьте исполнение на OKX."
        )

    critical = any(
        item in conditions
        for item in [
            "loss",
            "liquidation",
            "stop_level",
        ]
    )

    unknown = any(
        item in conditions
        for item in [
            "stale",
            "position_unknown",
            "liq_unknown",
        ]
    )

    if critical:
        status = "Высокий риск"
    elif unknown:
        status = "Нужна сверка"
    elif conditions:
        status = "Внимание"
    else:
        status = "Пороги не сработали"

    health = (
        None
        if unknown
        else 20
        if critical
        else 55
        if conditions
        else 85
    )

    return {
        "price": price,
        "pnl": pnl,
        "distance": distance,
        "status": status,
        "health": health,
        "reasons": reasons or [
            "Настроенные пороги не сработали. "
            "Это не гарантия безопасности."
        ],
        "code": (
            "|".join(sorted(conditions))
            or "ok"
        ),
        "time": utc_now(),
    }


def check_bot(bot_id, force=False):
    now = time.time()

    with db_connect() as db:
        db.execute("BEGIN IMMEDIATE")

        row = db.execute(
            """
            SELECT checked, lease, status
            FROM bots
            WHERE id=?
            """,
            (bot_id,),
        ).fetchone()

        if not row:
            return

        if row["status"] != "Наблюдается":
            return

        if row["lease"] > now:
            return

        if (
            not force
            and now - row["checked"] < 55
        ):
            return

        db.execute(
            """
            UPDATE bots
            SET lease=?
            WHERE id=?
            """,
            (now + 180, bot_id),
        )

    bot = get_bot(bot_id)

    try:
        price = get_price(
            bot["config"]["symbol"]
        )

        snapshot = evaluate_bot(
            bot,
            price,
        )

        with db_connect() as db:
            db.execute("BEGIN IMMEDIATE")

            current = db.execute(
                """
                SELECT state, status
                FROM bots
                WHERE id=?
                """,
                (bot_id,),
            ).fetchone()

            if (
                not current
                or current["status"]
                != "Наблюдается"
            ):
                return

            if (
                current["state"]
                != snapshot["code"]
            ):
                message = (
                    f"{bot['name']}\n"
                    f"{bot['config']['symbol']} · "
                    f"{bot['config']['strategy']} · "
                    f"{bot['config']['side']}\n"
                    f"{snapshot['status']}\n"
                    f"Цена: {price:.8f}\n\n"
                    + "\n".join(
                        snapshot["reasons"]
                    )
                )

                db.execute(
                    """
                    INSERT INTO events (
                        bot_id, created,
                        kind, message, notify
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        bot_id,
                        utc_now(),
                        "Состояние изменилось",
                        message,
                        (
                            "pending"
                            if bot["config"]["notify"]
                            else "off"
                        ),
                    ),
                )

            db.execute(
                """
                UPDATE bots
                SET snapshot=?,
                    state=?,
                    checked=?
                WHERE id=?
                """,
                (
                    json.dumps(
                        snapshot,
                        ensure_ascii=False,
                    ),
                    snapshot["code"],
                    time.time(),
                    bot_id,
                ),
            )

    except Exception as exc:
        snapshot = {
            "error": str(exc),
            "time": utc_now(),
        }

        with db_connect() as db:
            current = db.execute(
                """
                SELECT state, status
                FROM bots
                WHERE id=?
                """,
                (bot_id,),
            ).fetchone()

            if (
                current
                and current["status"]
                == "Наблюдается"
            ):
                if current["state"] != "api_error":
                    db.execute(
                        """
                        INSERT INTO events (
                            bot_id, created,
                            kind, message, notify
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            bot_id,
                            utc_now(),
                            "Данные недоступны",
                            (
                                f"{bot['name']}: "
                                "нет свежих данных OKX. "
                                "Оценка приостановлена."
                            ),
                            (
                                "pending"
                                if bot["config"]["notify"]
                                else "off"
                            ),
                        ),
                    )

                db.execute(
                    """
                    UPDATE bots
                    SET snapshot=?,
                        state='api_error',
                        checked=?
                    WHERE id=?
                    """,
                    (
                        json.dumps(
                            snapshot,
                            ensure_ascii=False,
                        ),
                        time.time(),
                        bot_id,
                    ),
                )

    finally:
        with db_connect() as db:
            db.execute(
                """
                UPDATE bots
                SET lease=0
                WHERE id=?
                """,
                (bot_id,),
            )


# ============================================================
# НАВИГАЦИЯ
# ============================================================

def navigate(
    page,
    bot_id=None,
    seed=None,
):
    st.session_state["navigation"] = page

    if bot_id:
        st.session_state["selected_bot"] = bot_id

    if page == "Добавить / изменить":
        st.session_state["editing_bot"] = bot_id
        st.session_state["editor_seed"] = seed
        st.session_state["editor_nonce"] = (
            uuid.uuid4().hex[:8]
        )


# ============================================================
# КОНСТРУКТОР БОТА
# ============================================================

def render_editor():
    edit_id = st.session_state.get(
        "editing_bot"
    )

    existing = (
        get_bot(edit_id)
        if edit_id
        else None
    )

    config = default_config(
        existing["config"]
        if existing
        else st.session_state.get(
            "editor_seed"
        )
    )

    nonce = st.session_state.get(
        "editor_nonce",
        "new",
    )

    if (
        existing
        and existing["status"]
        in ["Наблюдается", "Пауза"]
    ):
        st.warning(
            "Не меняем незаметно настройки "
            "запущенного бота. Создайте копию "
            "проекта, а фактическую позицию "
            "обновляйте в карточке."
        )

        st.button(
            "Создать копию проекта",
            on_click=navigate,
            args=(
                "Добавить / изменить",
                None,
                config,
            ),
        )
        return

    panel(
        "Отдельная конфигурация",
        "Все параметры сохраняются только "
        "для этого бота. Изменение одного "
        "проекта не меняет остальные.",
    )

    market = st.selectbox(
        "Рынок",
        ["Спот", "Фьючерсы"],
        index=(
            0
            if config["market"] == "Спот"
            else 1
        ),
        key=f"market_{nonce}",
    )

    strategy = st.selectbox(
        "Стратегия",
        ["DCA", "Grid"],
        index=(
            0
            if config["strategy"] == "DCA"
            else 1
        ),
        key=f"strategy_{nonce}",
    )

    if market == "Спот":
        sides = ["Long"]
    elif strategy == "DCA":
        sides = ["Long", "Short"]
    else:
        sides = ["Long", "Short", "Neutral"]

    side = st.selectbox(
        "Направление",
        sides,
        index=(
            sides.index(config["side"])
            if config["side"] in sides
            else 0
        ),
        key=f"side_{nonce}_{market}_{strategy}",
    )

    try:
        options = sorted(
            get_instruments(market)
        )

        candidate = (
            config["symbol"].split("-")[0]
            + "-USDT"
            + (
                "-SWAP"
                if market != "Спот"
                else ""
            )
        )

        symbol = st.selectbox(
            "Инструмент OKX",
            options,
            index=(
                options.index(candidate)
                if candidate in options
                else 0
            ),
            key=f"symbol_{nonce}_{market}",
        )

    except Exception as exc:
        st.error(str(exc))
        return

    with st.form(
        f"editor_{nonce}_{market}_{strategy}"
    ):
        name = st.text_input(
            "Название",
            value=(
                existing["name"]
                if existing
                else (
                    f"{symbol.split('-')[0]} · "
                    f"{market} · {strategy}"
                )
            ),
        )

        first, second = st.columns(2)

        budget = first.number_input(
            "Бюджет USDT",
            min_value=1.0,
            value=float(config["budget"]),
        )

        leverage = second.number_input(
            "Плечо",
            min_value=1.0,
            max_value=125.0,
            value=(
                float(config["leverage"])
                if market != "Спот"
                else 1.0
            ),
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
            first, second, third = (
                st.columns(3)
            )

            edited["base"] = (
                first.number_input(
                    "Первый ордер / маржа USDT",
                    min_value=0.01,
                    value=float(config["base"]),
                )
            )

            edited["safety"] = (
                second.number_input(
                    "Первая страховка / маржа USDT",
                    min_value=0.01,
                    value=float(
                        config["safety"]
                    ),
                )
            )

            edited["so"] = int(
                third.number_input(
                    "Максимум СО",
                    min_value=0,
                    max_value=30,
                    value=int(config["so"]),
                )
            )

            first, second, third = (
                st.columns(3)
            )

            edited["tp"] = (
                first.number_input(
                    "TP на цикл %",
                    min_value=0.01,
                    value=float(config["tp"]),
                )
            )

            edited["step"] = (
                second.number_input(
                    "Первый шаг %",
                    min_value=0.01,
                    value=float(
                        config["step"]
                    ),
                )
            )

            edited["amount_mult"] = (
                third.number_input(
                    "Множитель суммы СО",
                    min_value=1.0,
                    value=float(
                        config["amount_mult"]
                    ),
                )
            )

            edited["step_mult"] = (
                st.number_input(
                    "Множитель шага цены",
                    min_value=1.0,
                    value=float(
                        config["step_mult"]
                    ),
                )
            )

            st.caption(
                "СО1 — первая страховка. "
                "СО2 = СО1 × множитель суммы. "
                "Шаги накапливаются от первого "
                "входа: при шаге 2% и множителе "
                "шага 1 уровни −2%, −4%, −6%, −8% "
                "для Long."
            )

        else:
            first, second, third = (
                st.columns(3)
            )

            edited["lower"] = (
                first.number_input(
                    "Нижняя граница",
                    min_value=0.00000001,
                    value=float(
                        config["lower"]
                    ),
                    format="%.8f",
                )
            )

            edited["upper"] = (
                second.number_input(
                    "Верхняя граница",
                    min_value=0.00000001,
                    value=float(
                        config["upper"]
                    ),
                    format="%.8f",
                )
            )

            edited["grids"] = int(
                third.number_input(
                    "Интервалов сетки",
                    min_value=2,
                    max_value=200,
                    value=int(
                        config["grids"]
                    ),
                )
            )

            edited["grid_type"] = (
                st.selectbox(
                    "Тип сетки",
                    [
                        "Арифметическая",
                        "Геометрическая",
                    ],
                    index=(
                        0
                        if config["grid_type"]
                        == "Арифметическая"
                        else 1
                    ),
                )
            )

        first, second = st.columns(2)

        edited["stop"] = (
            first.number_input(
                "Стоп-цена, 0 — нет",
                min_value=0.0,
                value=float(config["stop"]),
                format="%.8f",
            )
        )

        edited["fee"] = (
            second.number_input(
                "Комиссия за сторону %",
                min_value=0.0,
                max_value=5.0,
                value=float(config["fee"]),
                format="%.4f",
            )
        )

        first, second, third = (
            st.columns(3)
        )

        edited["loss_limit"] = (
            first.number_input(
                "Предупреждать: убыток % бюджета",
                min_value=0.1,
                value=float(
                    config["loss_limit"]
                ),
            )
        )

        edited["liq_warning"] = (
            second.number_input(
                "Предупреждать: до ликвидации %",
                min_value=0.1,
                value=float(
                    config["liq_warning"]
                ),
            )
        )

        edited["stale_hours"] = (
            third.number_input(
                "Сверять позицию каждые N часов",
                min_value=1.0,
                value=float(
                    config["stale_hours"]
                ),
            )
        )

        edited["notify"] = st.checkbox(
            "Telegram-события этого бота",
            value=bool(config["notify"]),
        )

        submitted = st.form_submit_button(
            "Сохранить бота",
            use_container_width=True,
        )

    if submitted:
        errors = validate_config(edited)

        if not name.strip():
            errors.append(
                "Введите название бота."
            )

        if errors:
            for error in errors:
                st.error(error)
            return

        bot_id = (
            edit_id
            or uuid.uuid4().hex
        )

        with db_connect() as db:
            if existing:
                db.execute(
                    """
                    UPDATE bots
                    SET name=?,
                        config=?,
                        state=NULL
                    WHERE id=?
                    """,
                    (
                        name.strip(),
                        json.dumps(edited),
                        bot_id,
                    ),
                )
            else:
                db.execute(
                    """
                    INSERT INTO bots (
                        id, name,
                        config, created
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        bot_id,
                        name.strip(),
                        json.dumps(edited),
                        utc_now(),
                    ),
                )

        add_event(
            bot_id,
            (
                "Настройки изменены"
                if existing
                else "Проект создан"
            ),
            (
                f"{name.strip()}: "
                f"версия {config_hash(edited)}"
            ),
        )

        st.success(
            "Карточка сохранена."
        )

        st.button(
            "Открыть карточку",
            on_click=navigate,
            args=(
                "Карточка бота",
                bot_id,
            ),
        )


# ============================================================
# ЖУРНАЛ
# ============================================================

def render_events(bot_id=None):
    query = """
        SELECT
            e.*,
            b.name AS bot_name
        FROM events e
        LEFT JOIN bots b
        ON b.id=e.bot_id
    """

    parameters = ()

    if bot_id:
        query += " WHERE e.bot_id=?"
        parameters = (bot_id,)

    query += " ORDER BY e.id DESC LIMIT 500"

    with db_connect() as db:
        rows = db.execute(
            query,
            parameters,
        ).fetchall()

    if not rows:
        st.info("Событий пока нет.")
        return

    df = pd.DataFrame(
        [dict(row) for row in rows]
    )

    visible = df[
        [
            "created",
            "bot_name",
            "kind",
            "message",
            "notify",
        ]
    ].rename(
        columns={
            "created": "Дата UTC",
            "bot_name": "Бот",
            "kind": "Событие",
            "message": "Описание",
            "notify": "Telegram",
        }
    )

    st.dataframe(
        visible,
        hide_index=True,
        use_container_width=True,
    )

    st.download_button(
        "Скачать события CSV",
        visible.to_csv(
            index=False
        ).encode("utf-8-sig"),
        file_name="bot_events.csv",
        mime="text/csv",
        key=f"events_download_{bot_id}",
    )

    failed = df[
        df["notify"].str.startswith(
            (
                "error:",
                "unknown:",
                "sending",
            )
        )
    ]

    if not failed.empty:
        st.caption(
            "Неоднозначная доставка не "
            "повторяется автоматически. "
            "Перед повтором проверьте Telegram."
        )

        selected = st.selectbox(
            "Событие для повторной отправки",
            failed["id"].tolist(),
            key=f"retry_select_{bot_id}",
        )

        if st.button(
            "Повторить выбранную отправку",
            key=f"retry_button_{bot_id}",
        ):
            with db_connect() as db:
                db.execute(
                    """
                    UPDATE events
                    SET notify='pending'
                    WHERE id=?
                    """,
                    (int(selected),),
                )

            dispatch_notifications()
            st.success(
                "Попытка выполнена. "
                "Обновите страницу для статуса."
            )


# ============================================================
# КАРТОЧКА БОТА
# ============================================================

def render_bot_card():
    bots = all_bots()

    if not bots:
        st.info(
            "Сначала добавьте бота."
        )
        return

    ids = [bot["id"] for bot in bots]
    names = {
        bot["id"]: bot["name"]
        for bot in bots
    }

    preferred = st.session_state.get(
        "selected_bot"
    )

    selected = st.selectbox(
        "Бот",
        ids,
        index=(
            ids.index(preferred)
            if preferred in ids
            else 0
        ),
        format_func=lambda value: names[value],
    )

    bot = get_bot(selected)
    config = bot["config"]

    st.caption(
        f"{config['symbol']} · "
        f"{config['market']} · "
        f"{config['strategy']} "
        f"{config['side']} · "
        f"{bot['status']} · "
        f"версия {config_hash(config)}"
    )

    first, second = st.columns(2)

    first.button(
        "Изменить настройки",
        on_click=navigate,
        args=(
            "Добавить / изменить",
            selected,
        ),
    )

    second.button(
        "Создать копию для сравнения",
        on_click=navigate,
        args=(
            "Добавить / изменить",
            None,
            config,
        ),
    )

    tabs = st.tabs([
        "План и OKX",
        "Бэктест",
        "Запуск / сверка",
        "Состояние",
        "События",
    ])

    # ---------------- ПЛАН ----------------

    with tabs[0]:
        for line in bot_recommendations(bot):
            st.write("• " + line)

        st.subheader(
            "Значения для переноса на OKX"
        )

        passport = okx_passport(config)

        st.dataframe(
            passport.astype(str),
            hide_index=True,
            use_container_width=True,
        )

        st.download_button(
            "Скачать памятку OKX",
            passport.to_csv(
                index=False
            ).encode("utf-8-sig"),
            file_name=(
                f"okx_{selected[:8]}.csv"
            ),
            mime="text/csv",
        )

        st.caption(
            "Приложение не отправляет "
            "торговые команды. Названия полей "
            "и единицы перепроверьте в вашем "
            "продукте OKX. Для фьючерсного DCA "
            "суммы ордеров в этой карточке "
            "означают маржу, а не полный номинал."
        )

        if config["strategy"] == "DCA":
            actual = bot["confirmed"] or {}

            anchor = st.number_input(
                "Первый вход для расчёта плана",
                min_value=0.00000001,
                value=float(
                    actual.get("anchor", 100)
                    or 100
                ),
                format="%.8f",
                key=f"plan_anchor_{selected}",
            )

            st.dataframe(
                dca_orders(config, anchor),
                hide_index=True,
                use_container_width=True,
            )

    # ---------------- БЭКТЕСТ ----------------

    with tabs[1]:
        st.warning(
            "OHLC-модель, не тиковая симуляция. "
            "Long: open → low → high → close. "
            "Short: open → high → low → close. "
            "Порядок экстремумов предполагается. "
            "Funding, очередь лимитных ордеров "
            "и ликвидации не моделируются. "
            "Futures выше 1x и Short/Neutral Grid "
            "пока не тестируются."
        )

        first, second = st.columns(2)

        bar = first.selectbox(
            "Таймфрейм теста",
            list(BARS),
            key=f"test_bar_{selected}",
        )

        days = int(
            second.number_input(
                "Дней истории",
                min_value=1,
                max_value=180,
                value=30,
                key=f"test_days_{selected}",
            )
        )

        if st.button(
            "Тестировать текущую версию",
            key=f"run_test_{selected}",
            use_container_width=True,
        ):
            try:
                end_ms = (
                    int(time.time() * 1000)
                    // BARS[bar]
                    * BARS[bar]
                )

                start_ms = (
                    end_ms
                    - days * 86_400_000
                )

                with st.spinner(
                    "Загрузка истории и расчёт..."
                ):
                    history = get_history(
                        config["symbol"],
                        bar,
                        start_ms,
                        end_ms,
                    )

                    result = run_backtest(
                        history,
                        config,
                        bar,
                        start_ms,
                        end_ms,
                    )

                with db_connect() as db:
                    db.execute(
                        """
                        INSERT INTO tests (
                            bot_id,
                            config_hash,
                            created,
                            result
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (
                            selected,
                            config_hash(config),
                            utc_now(),
                            json.dumps(
                                result,
                                ensure_ascii=False,
                            ),
                        ),
                    )

                add_event(
                    selected,
                    "Бэктест завершён",
                    (
                        f"{bot['name']}: "
                        f"{days} дней, {bar}, "
                        f"версия "
                        f"{config_hash(config)}. "
                        f"Доходность: "
                        f"{result['metrics']['Доходность %']:.2f}%."
                    ),
                    config["notify"],
                )

                dispatch_notifications()
                st.success(
                    "Тест сохранён для этой версии."
                )

            except Exception as exc:
                st.error(str(exc))

        tests = get_tests(selected)

        if tests:
            options = list(range(len(tests)))

            index = st.selectbox(
                "Сохранённый результат",
                options,
                format_func=lambda item: (
                    f"{tests[item]['created']} · "
                    + (
                        "текущая версия"
                        if tests[item]["config_hash"]
                        == config_hash(config)
                        else "УСТАРЕВШАЯ версия"
                    )
                ),
                key=f"saved_test_{selected}",
            )

            test = json.loads(
                tests[index]["result"]
            )

            if (
                tests[index]["config_hash"]
                != config_hash(config)
            ):
                st.warning(
                    "Этот тест относится "
                    "к прежним настройкам."
                )

            st.dataframe(
                pd.DataFrame(
                    [test["metrics"]]
                ),
                hide_index=True,
                use_container_width=True,
            )

            curve = pd.DataFrame(
                test["curve"]
            )

            curve["time"] = pd.to_datetime(
                curve["time"],
                utc=True,
            )

            fig = go.Figure(
                go.Scatter(
                    x=curve["time"],
                    y=curve["equity"],
                    name="Equity",
                    line=dict(
                        color=GREEN,
                        width=2,
                    ),
                )
            )

            fig.update_layout(
                title=(
                    "Капитал с открытой позицией"
                ),
                yaxis_title="USDT",
            )

            show_chart(fig)

            st.caption(
                f"История: {test['start']} — "
                f"{test['end']}. "
                "TP — движение от средней цены, "
                "комиссии вычитаются отдельно. "
                "Equity включает оценочную "
                "комиссию закрытия. "
                "Grid стартует в USDT и использует "
                "фиксированные пары уровней "
                "ниже стартовой цены."
            )

        else:
            st.info(
                "У этой карточки ещё нет тестов."
            )

    # ---------------- ЗАПУСК ----------------

    with tabs[2]:
        st.info(
            "Сначала настройте и запустите "
            "бота на OKX. Здесь вы подтверждаете "
            "это вручную. Кнопка ниже "
            "не запускает сделки на бирже."
        )

        actual = bot["confirmed"] or {}

        with st.form(
            f"confirmation_{selected}"
        ):
            first, second = st.columns(2)

            average = first.number_input(
                "Фактическая средняя входа",
                min_value=0.0,
                value=float(
                    actual.get("avg", 0)
                ),
                format="%.8f",
            )

            quantity = second.number_input(
                "Количество базовой монеты",
                min_value=0.0,
                value=float(
                    actual.get("qty", 0)
                ),
                format="%.8f",
                help=(
                    "Для SWAP не число контрактов, "
                    "а эквивалент в BTC, ETH и т. п."
                ),
            )

            first, second = st.columns(2)

            liquidation = first.number_input(
                "Ликвидация из OKX, 0 — неизвестна",
                min_value=0.0,
                value=float(
                    actual.get("liq", 0)
                ),
                format="%.8f",
                disabled=(
                    config["market"] == "Спот"
                ),
            )

            fees = second.number_input(
                "Комиссии текущего входа USDT",
                min_value=0.0,
                value=float(
                    actual.get("fees", 0)
                ),
                format="%.6f",
            )

            anchor = st.number_input(
                "Первый вход текущего цикла DCA",
                min_value=0.0,
                value=float(
                    actual.get("anchor", 0)
                ),
                format="%.8f",
                disabled=(
                    config["strategy"] != "DCA"
                ),
            )

            completed = int(
                st.number_input(
                    "Подтверждённые СО текущего цикла",
                    min_value=0,
                    max_value=int(config["so"]),
                    value=min(
                        int(
                            actual.get(
                                "completed", 0
                            )
                        ),
                        int(config["so"]),
                    ),
                    disabled=(
                        config["strategy"] != "DCA"
                    ),
                )
            )

            consent = st.checkbox(
                "Подтверждаю: бот запущен "
                "на OKX, данные сверены"
            )

            submitted = (
                st.form_submit_button(
                    "Сохранить сверку и наблюдать",
                    use_container_width=True,
                )
            )

        if submitted:
            if not consent:
                st.error(
                    "Подтвердите запуск на OKX."
                )

            elif (
                config["side"] != "Neutral"
                and (
                    average <= 0
                    or quantity <= 0
                )
            ):
                st.error(
                    "Введите среднюю и количество. "
                    "Если позиции нет, используйте "
                    "паузу наблюдения."
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
                    "time": utc_now(),
                }

                with db_connect() as db:
                    db.execute(
                        """
                        UPDATE bots
                        SET confirmed=?,
                            status='Наблюдается',
                            state=NULL,
                            checked=0
                        WHERE id=?
                        """,
                        (
                            json.dumps(confirmed),
                            selected,
                        ),
                    )

                add_event(
                    selected,
                    "Ручная сверка",
                    (
                        f"{bot['name']}: "
                        "пользователь подтвердил "
                        "фактические данные позиции."
                    ),
                )

                check_bot(selected, force=True)
                dispatch_notifications()

                st.success(
                    "Позиция сохранена. "
                    "Первая проверка выполнена."
                )

        first, second = st.columns(2)

        if first.button(
            "Пауза наблюдения",
            key=f"pause_{selected}",
        ):
            with db_connect() as db:
                db.execute(
                    """
                    UPDATE bots
                    SET status='Пауза'
                    WHERE id=?
                    """,
                    (selected,),
                )

            add_event(
                selected,
                "Пауза наблюдения",
                (
                    f"{bot['name']}: "
                    "остановлен мониторинг, "
                    "не торговый бот на OKX."
                ),
            )

            st.success(
                "Наблюдение приостановлено."
            )

        if second.button(
            "Пометить закрытым",
            key=f"closed_{selected}",
        ):
            with db_connect() as db:
                db.execute(
                    """
                    UPDATE bots
                    SET status='Закрыт'
                    WHERE id=?
                    """,
                    (selected,),
                )

            add_event(
                selected,
                "Закрытие подтверждено",
                (
                    f"{bot['name']}: "
                    "пользователь отметил закрытие. "
                    "API-подтверждения нет."
                ),
            )

            st.success(
                "Карточка отмечена закрытой."
            )

    # ---------------- СОСТОЯНИЕ ----------------

    with tabs[3]:
        if st.button(
            "Проверить сейчас",
            key=f"check_{selected}",
        ):
            check_bot(selected, force=True)
            dispatch_notifications()

        fresh = get_bot(selected)
        snapshot = fresh["snapshot"]

        if snapshot:
            if "error" in snapshot:
                st.error(snapshot["error"])

            else:
                panel(
                    snapshot["status"],
                    " ".join(
                        snapshot["reasons"]
                    ),
                )

                first, second, third = (
                    st.columns(3)
                )

                first.metric(
                    "Last-цена",
                    f"{snapshot['price']:.8f}",
                )

                second.metric(
                    "Условная оценка",
                    (
                        f"{snapshot['health']}/100"
                        if snapshot["health"]
                        is not None
                        else "Неизвестно"
                    ),
                )

                third.metric(
                    "Оценочный PnL",
                    (
                        f"{snapshot['pnl']:.4f} USDT"
                        if snapshot["pnl"]
                        is not None
                        else "Неизвестно"
                    ),
                )

                if (
                    snapshot["health"]
                    is not None
                ):
                    gauge = go.Figure(
                        go.Indicator(
                            mode="gauge+number",
                            value=snapshot["health"],
                            gauge={
                                "axis": {
                                    "range": [0, 100]
                                },
                                "bar": {
                                    "color": (
                                        GREEN
                                        if snapshot["health"]
                                        > 70
                                        else YELLOW
                                        if snapshot["health"]
                                        > 40
                                        else RED
                                    )
                                },
                            },
                            title={
                                "text": (
                                    "Условная шкала, "
                                    "не вероятность успеха"
                                )
                            },
                        )
                    )

                    show_chart(gauge, 280)

            st.caption(
                f"Проверка: {snapshot['time']} UTC. "
                f"Сверка позиции: "
                f"{(fresh['confirmed'] or {}).get('time', 'нет')}."
            )

        else:
            st.info(
                "Подтвердите фактический запуск "
                "и выполните проверку."
            )

        st.warning(
            "Без приватного API неизвестны "
            "фактические исполнения, funding "
            "и суммарная прибыль Grid. "
            "После нового цикла DCA обновите "
            "первый вход и число выполненных СО. "
            "Проверка цены не обновляет позицию."
        )

        bar = st.selectbox(
            "Таймфрейм графика",
            list(BARS),
            index=2,
            key=f"chart_bar_{selected}",
        )

        if st.checkbox(
            "Показать свечи и индикаторы",
            key=f"show_chart_{selected}",
        ):
            try:
                render_price_chart(
                    config["symbol"],
                    bar,
                )
            except Exception as exc:
                st.error(str(exc))

    # ---------------- СОБЫТИЯ ----------------

    with tabs[4]:
        render_events(selected)


# ============================================================
# СКАНЕР
# ============================================================

def scan_instrument(
    symbol,
    market,
    strategy,
    side,
    bar,
    instrument,
    ticker,
):
    df = with_indicators(
        recent_raw(symbol, bar)
    )

    last = df.iloc[-1]

    volume = float(
        ticker.get("volCcy24h", 0)
        or 0
    )

    if market != "Спот":
        volume *= float(
            ticker.get("last", 0)
            or 0
        )

    listing = int(
        instrument.get("listTime", 0)
        or 0
    )

    young = (
        listing > 0
        and (
            time.time() * 1000 - listing
        ) / 86_400_000 < 180
    )

    if strategy == "Grid":
        candidate = last["ADX"] < 25

    else:
        trend_direction = (
            last["+DI"] > last["-DI"]
            if side == "Long"
            else last["-DI"] > last["+DI"]
        )

        candidate = (
            last["ADX"] >= 25
            and trend_direction
            and 30 <= last["RSI"] <= 65
        )

    if volume < 10_000_000:
        status = "Низкая ликвидность"
    elif young:
        status = "Молодой инструмент"
    elif candidate:
        status = "Кандидат"
    else:
        status = "Ждать"

    return {
        "Инструмент": symbol,
        "Рынок": market,
        "Стратегия": strategy,
        "Направление": side,
        "Цена": float(ticker["last"]),
        "RSI": float(last["RSI"]),
        "ADX": float(last["ADX"]),
        "Объём USDT, оценка": volume,
        "Статус": status,
    }


def render_scanner():
    first, second, third = (
        st.columns(3)
    )

    market = first.selectbox(
        "Рынок",
        ["Спот", "Фьючерсы"],
    )

    strategy = second.selectbox(
        "Подбираем для",
        ["DCA", "Grid"],
    )

    if market == "Спот":
        sides = ["Long"]
    elif strategy == "DCA":
        sides = ["Long", "Short"]
    else:
        sides = ["Long", "Short", "Neutral"]

    side = third.selectbox(
        "Направление",
        sides,
    )

    bar = st.selectbox(
        "Таймфрейм",
        list(BARS),
        index=2,
    )

    st.caption(
        "Сканер — технический фильтр, "
        "не гарантия прибыльных настроек. "
        "Создание проекта не запускает ордера."
    )

    if st.button(
        "Проверить 20 монет",
        use_container_width=True,
    ):
        try:
            instruments = get_instruments(
                market
            )

            tickers = get_tickers(market)

            wanted = [
                coin
                + "-USDT"
                + (
                    "-SWAP"
                    if market != "Спот"
                    else ""
                )
                for coin in COINS
            ]

            available = [
                symbol
                for symbol in wanted
                if (
                    symbol in instruments
                    and symbol in tickers
                )
            ]

            rows = []
            errors = []
            progress = st.progress(0.0)

            with ThreadPoolExecutor(
                max_workers=4
            ) as executor:
                futures = {
                    executor.submit(
                        scan_instrument,
                        symbol,
                        market,
                        strategy,
                        side,
                        bar,
                        instruments[symbol],
                        tickers[symbol],
                    ): symbol
                    for symbol in available
                }

                for index, future in enumerate(
                    as_completed(futures),
                    1,
                ):
                    try:
                        rows.append(
                            future.result()
                        )
                    except Exception as exc:
                        errors.append(
                            f"{futures[future]}: "
                            f"{exc}"
                        )

                    progress.progress(
                        index
                        / max(
                            len(available),
                            1,
                        )
                    )

            progress.empty()

            rows.sort(
                key=lambda item: item[
                    "Объём USDT, оценка"
                ],
                reverse=True,
            )

            st.session_state[
                "scanner_result"
            ] = {
                "rows": rows,
                "errors": errors,
                "missing": [
                    symbol
                    for symbol in wanted
                    if symbol not in available
                ],
                "bar": bar,
                "time": utc_now(),
            }

        except Exception as exc:
            st.error(str(exc))

    saved = st.session_state.get(
        "scanner_result"
    )

    if not saved:
        return

    st.caption(
        "Результат сканирования: "
        + saved["time"]
        + " UTC"
    )

    if saved["missing"]:
        st.warning(
            "Недоступны: "
            + ", ".join(
                saved["missing"]
            )
        )

    if saved["errors"]:
        with st.expander(
            "Ошибки отдельных инструментов"
        ):
            st.write(
                "\n".join(saved["errors"])
            )

    if not saved["rows"]:
        st.info(
            "Нет успешно "
            "проанализированных инструментов."
        )
        return

    table = pd.DataFrame(
        saved["rows"]
    )

    st.dataframe(
        table.style.format({
            "Цена": "{:,.8f}",
            "RSI": "{:.1f}",
            "ADX": "{:.1f}",
            "Объём USDT, оценка": "{:,.0f}",
        }),
        hide_index=True,
        use_container_width=True,
    )

    symbol = st.selectbox(
        "Инструмент для проекта",
        table["Инструмент"].tolist(),
    )

    selected = table[
        table["Инструмент"] == symbol
    ].iloc[0]

    seed = default_config({
        "market": selected["Рынок"],
        "strategy": selected["Стратегия"],
        "side": selected["Направление"],
        "symbol": symbol,
        "lower": float(
            selected["Цена"]
        ) * 0.9,
        "upper": float(
            selected["Цена"]
        ) * 1.1,
    })

    st.button(
        "Создать и настроить своего бота",
        on_click=navigate,
        args=(
            "Добавить / изменить",
            None,
            seed,
        ),
        use_container_width=True,
    )

    if st.checkbox(
        "Показать график выбранной монеты"
    ):
        try:
            render_price_chart(
                symbol,
                saved["bar"],
            )
        except Exception as exc:
            st.error(str(exc))

    if st.button(
        "Отправить эту сводку в Telegram"
    ):
        lines = [
            "Сканер OKX: технические кандидаты",
            "UTC: " + saved["time"],
        ]

        for item in saved["rows"]:
            lines.append(
                f"{item['Инструмент']} | "
                f"{item['Рынок']} | "
                f"{item['Стратегия']} "
                f"{item['Направление']}: "
                f"{item['Статус']}"
            )

        st.info(
            send_telegram(
                "\n".join(lines)
            )
        )


# ============================================================
# ИНИЦИАЛИЗАЦИЯ
# ============================================================

init_db()

with st.sidebar:
    st.markdown(
        "## ⚡ OKX Bot Manager"
    )

    page = st.radio(
        "Раздел",
        PAGES,
        key="navigation",
        label_visibility="collapsed",
    )

    st.divider()

    monitor_enabled = st.checkbox(
        "Автопроверка наблюдаемых ботов",
        value=True,
    )

    st.caption(
        "Раз в 60 секунд при работающей "
        "сессии. Telegram — при изменении "
        "состояния, без повторов каждой проверки."
    )

st.title(page)


# ============================================================
# АВТОПРОВЕРКА ПРИ АКТИВНОЙ СЕССИИ
# ============================================================

@st.fragment(
    run_every=(
        "60s"
        if monitor_enabled
        else None
    )
)
def monitoring_fragment():
    if not monitor_enabled:
        st.caption(
            "Автопроверка выключена."
        )
        return

    try:
        observed = [
            bot
            for bot in all_bots()
            if bot["status"] == "Наблюдается"
        ]

        for bot in observed:
            check_bot(bot["id"])

        dispatch_notifications()

        st.caption(
            f"Проверка: {utc_now()} UTC · "
            f"наблюдаемых ботов: {len(observed)}"
        )

    except Exception as exc:
        st.warning(
            "Мониторинг временно недоступен: "
            + str(exc)
        )


monitoring_fragment()


# ============================================================
# СТРАНИЦЫ
# ============================================================

if page == "Мои боты":
    panel(
        "Сначала проект — затем OKX",
        "Добавьте отдельного бота, задайте "
        "параметры, проведите тест и изучите "
        "ограничения. Затем вручную перенесите "
        "значения на OKX и подтвердите запуск.",
    )

    st.button(
        "＋ Добавить бота",
        on_click=navigate,
        args=(
            "Добавить / изменить",
        ),
        use_container_width=True,
    )

    bots = all_bots()

    if not bots:
        st.info(
            "Пока нет карточек. "
            "Нажмите «Добавить бота»."
        )

    for bot in bots:
        config = bot["config"]
        snapshot = bot["snapshot"] or {}

        with st.container(border=True):
            st.subheader(bot["name"])

            st.write(
                f"{config['symbol']} · "
                f"{config['market']} · "
                f"{config['strategy']} "
                f"{config['side']}"
            )

            st.caption(
                f"Статус: {bot['status']} · "
                f"Бюджет: "
                f"{config['budget']:.2f} USDT"
            )

            st.caption(
                f"Состояние: "
                f"{snapshot.get('status', 'не оценено')} · "
                f"проверка: "
                f"{snapshot.get('time', 'нет')}"
            )

            st.caption(
                "Есть тест текущей версии"
                if current_test(bot)
                else "Текущая версия не протестирована"
            )

            st.button(
                "Открыть карточку",
                key=f"open_{bot['id']}",
                on_click=navigate,
                args=(
                    "Карточка бота",
                    bot["id"],
                ),
                use_container_width=True,
            )

    st.warning(
        "Приложение рассчитано на одного "
        "владельца. При публичном доступе "
        "карточки и Telegram-действия общие. "
        "SQLite хранится локально на сервере: "
        "делайте резервные копии."
    )

elif page == "Добавить / изменить":
    render_editor()

elif page == "Карточка бота":
    render_bot_card()

elif page == "Сканер":
    render_scanner()

elif page == "Журнал событий":
    panel(
        "Только важные события",
        "Создание и изменение бота, "
        "результаты тестов, ручные сверки "
        "и изменение состояния. Обычная "
        "проверка без изменений не добавляет "
        "новую строку.",
    )

    render_events()

elif page == "Настройки":
    panel(
        "Telegram",
        "Используется существующий блок "
        "[telegram] в Secrets. "
        "Токен в код и GitHub не вставляйте.",
    )

    token, chat_id = telegram_credentials()

    if token and chat_id:
        st.success(
            "Telegram token и chat_id найдены."
        )
    else:
        st.warning(
            "Telegram Secrets не найдены."
        )

    if st.button(
        "Тест Telegram",
        use_container_width=True,
    ):
        st.info(
            send_telegram(
                "OKX Bot Manager: "
                "связь проверена ✅"
            )
        )

    st.code(
        '[telegram]\n'
        'token = "ВАШ_ТОКЕН"\n'
        'chat_id = "ВАШ_CHAT_ID"',
        language="toml",
    )

    st.subheader(
        "Как работают уведомления"
    )

    st.write(
        "После подтверждения запуска карточка "
        "становится наблюдаемой. Приложение "
        "проверяет публичную цену и сравнивает "
        "её с сохранёнными параметрами."
    )

    st.write(
        "Сообщение отправляется при изменении "
        "набора условий: выход из Grid, "
        "порог убытка, цена у СО/TP, "
        "приближение к ликвидации, "
        "устаревшие данные или ошибка OKX."
    )

    st.warning(
        "Это не круглосуточный серверный "
        "мониторинг. Если приложение или "
        "сессия не работают, проверки "
        "не гарантируются. Приложение "
        "не отправляет торговые команды "
        "и не подтверждает исполнения."
    )

    st.subheader(
        "Резервная копия"
    )

    with db_connect() as source:
        backup = sqlite3.connect(":memory:")
        source.backup(backup)
        dump = "\n".join(
            backup.iterdump()
        )
        backup.close()

    st.download_button(
        "Скачать резервную копию SQL",
        dump.encode("utf-8"),
        file_name="bots_backup.sql",
        mime="text/plain",
        use_container_width=True,
    )

    st.caption(
        "Копия содержит карточки, позиции, "
        "тесты и события, но не Telegram-токен. "
        "Не публикуйте её."
    )

    st.caption(
        "Старый journal.csv не импортируется "
        "автоматически: снимки анализов "
        "не являются подтверждёнными "
        "карточками торговых ботов."
    )
