import csv
import html
import os
import tempfile
import threading
import time

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

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
    page_title="OKX Terminal",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="auto",
)

API = "https://www.okx.com/api/v5"
JOURNAL = Path("journal.csv")

COINS = [
    "BTC", "ETH", "SOL", "BNB", "XRP",
    "DOGE", "ADA", "AVAX", "LINK", "DOT",
    "TON", "TRX", "LTC", "NEAR", "APT",
    "ARB", "OP", "SUI", "PEPE", "INJ",
]

TP = 1.5
STEP = 2.0
SO_COUNT = 4
MART = 1.2
BASE_ORDER = 10.0
FEE = 0.0005
MIN_VOLUME = 10_000_000

GREEN = "#00EFA7"
RED = "#FF5575"
BLUE = "#49BFFF"
YELLOW = "#FFD166"

BAR_MS = {
    "15m": 15 * 60_000,
    "30m": 30 * 60_000,
    "1H": 60 * 60_000,
    "4H": 4 * 60 * 60_000,
    "1Dutc": 24 * 60 * 60_000,
}

BAR_LABELS = {
    "15m": "15 минут",
    "30m": "30 минут",
    "1H": "1 час",
    "4H": "4 часа",
    "1Dutc": "1 день · UTC",
}

MARKETS = ["Спот", "Фьючерсы (SWAP)"]

JOURNAL_COLUMNS = [
    "Дата",
    "Монета",
    "Инструмент",
    "Рынок",
    "Направление",
    "Здоровье",
    "Статус",
    "Совет",
    "PnL, USDT",
    "PnL, %",
    "До ликвидации, %",
]

for key, value in {
    "tg_token": "",
    "tg_chat": "",
    "scan_result": None,
    "ai_result": None,
    "bt_result": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = value


# ============================================================
# STYLE
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
        radial-gradient(900px 450px at 0% 0%,
            rgba(0,239,167,.06), transparent 65%),
        radial-gradient(900px 450px at 100% 0%,
            rgba(73,191,255,.06), transparent 65%),
        #060910;
}

[data-testid="stHeader"] {
    background: #090E18 !important;
}

[data-testid="stToolbar"] {
    color: #E8EEF8 !important;
}

[data-testid="stSidebar"] {
    background: #0B101B !important;
    border-right: 1px solid #243047 !important;
    opacity: 1 !important;
}

[data-testid="stSidebar"] > div {
    background-color: #0B101B !important;
}

h1, h2, h3, h4 {
    color: #F0F5FF !important;
    letter-spacing: -.025em;
}

[data-testid="stMarkdownContainer"] p,
[data-testid="stWidgetLabel"] p,
[data-testid="stCaptionContainer"] p,
[data-testid="stRadio"] p {
    color: #D3DDED !important;
}

[data-testid="stSidebar"] [data-testid="stRadio"] label {
    background: #151F30 !important;
    border: 1px solid #2B3A53 !important;
    border-radius: 12px;
    padding: 10px 12px;
    margin-bottom: 6px;
    transition: border-color .2s ease, background .2s ease;
}

[data-testid="stSidebar"] [data-testid="stRadio"] label:hover {
    background: #1B2A3F !important;
    border-color: #00EFA7 !important;
}

[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input {
    background: #121C2C !important;
    color: #F2F6FF !important;
    -webkit-text-fill-color: #F2F6FF !important;
    caret-color: #00EFA7 !important;
}

[data-testid="stNumberInput"] button {
    background: #1B2A40 !important;
    color: #F2F6FF !important;
}

[data-baseweb="select"] > div {
    background: #121C2C !important;
    color: #F2F6FF !important;
    border-color: #2B3A53 !important;
}

[data-baseweb="select"] span {
    color: #F2F6FF !important;
}

[data-baseweb="popover"] {
    color: #E8EEF8;
}

.stButton > button {
    min-height: 46px;
    border: 0 !important;
    border-radius: 12px !important;
    background: linear-gradient(110deg, #00EFA7, #3BBEFF) !important;
    box-shadow: 0 5px 20px rgba(0,239,167,.08);
    transition: transform .18s ease, box-shadow .18s ease;
}

.stButton > button,
.stButton > button p {
    color: #031019 !important;
    font-weight: 700 !important;
}

.stButton > button:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 26px rgba(0,239,167,.2);
}

.stDownloadButton > button {
    background: #142339 !important;
    border: 1px solid #355475 !important;
    color: #E8EEF8 !important;
    border-radius: 12px !important;
}

.stDownloadButton > button p {
    color: #E8EEF8 !important;
}

.panel {
    background: linear-gradient(135deg, #131C2B, #0D1420);
    border: 1px solid #27344B;
    border-radius: 18px;
    padding: 20px;
    margin-bottom: 16px;
    box-shadow: 0 12px 32px rgba(0,0,0,.16);
}

.panel-title {
    color: #F2F6FF;
    font-size: 1.1rem;
    font-weight: 700;
    margin-bottom: 8px;
}

.panel-text {
    color: #A9B7CE;
    line-height: 1.6;
}

.kpi {
    background: linear-gradient(145deg, #162033, #101724);
    border: 1px solid #2A3850;
    border-radius: 16px;
    padding: 18px;
    margin-bottom: 12px;
    min-height: 110px;
    transition: transform .2s ease, border-color .2s ease;
}

.kpi:hover {
    transform: translateY(-2px);
    border-color: #00EFA7;
}

.kpi-label {
    color: #AAB9D1;
    font-size: .8rem;
    letter-spacing: .05em;
    margin-bottom: 8px;
}

.kpi-value {
    color: #F1F6FF;
    font-size: 1.55rem;
    font-weight: 800;
    overflow-wrap: anywhere;
}

[data-testid="stDataFrame"] {
    border: 1px solid #27344B;
    border-radius: 12px;
    overflow: hidden;
}

@media (max-width: 768px) {
    .block-container {
        padding: 1.2rem 1rem 4rem !important;
    }

    h1 {
        font-size: 2rem !important;
    }

    .panel {
        padding: 16px;
    }

    .kpi {
        padding: 15px;
        min-height: 94px;
    }

    .kpi-value {
        font-size: 1.35rem;
    }
}
</style>
""",
    unsafe_allow_html=True,
)


# ============================================================
# COMMON UI
# ============================================================

def card(label, value, color=None):
    safe_label = html.escape(str(label))
    safe_value = html.escape(str(value))
    color = color or "#F1F6FF"

    st.markdown(
        f"""
        <div class="kpi">
            <div class="kpi-label">{safe_label}</div>
            <div class="kpi-value" style="color:{color}">
                {safe_value}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def panel(title, text):
    st.markdown(
        f"""
        <div class="panel">
            <div class="panel-title">{html.escape(title)}</div>
            <div class="panel-text">{html.escape(text)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def style_figure(fig, height=420):
    fig.update_layout(
        template="plotly_dark",
        height=height,
        paper_bgcolor="#0C1320",
        plot_bgcolor="#0C1320",
        font=dict(color="#DCE6F5", family="Inter, sans-serif"),
        margin=dict(l=15, r=15, t=50, b=25),
        legend=dict(
            orientation="h",
            y=1.03,
            x=0,
        ),
    )
    fig.update_xaxes(gridcolor="#202C40")
    fig.update_yaxes(gridcolor="#202C40")
    return fig


def show_figure(fig):
    st.plotly_chart(
        fig,
        use_container_width=True,
        config={"displaylogo": False},
    )


def market_type(market):
    return "SPOT" if market == "Спот" else "SWAP"


# ============================================================
# API + RATE LIMIT
# ============================================================

@st.cache_resource
def shared_locks():
    return {
        "api": threading.Lock(),
        "journal": threading.RLock(),
        "last_request": [0.0],
    }


def throttle():
    state = shared_locks()

    with state["api"]:
        elapsed = time.monotonic() - state["last_request"][0]
        delay = 0.16 - elapsed

        if delay > 0:
            time.sleep(delay)

        state["last_request"][0] = time.monotonic()


def api_get(endpoint, params=None):
    last_error = None

    for attempt in range(4):
        throttle()

        try:
            response = requests.get(
                API + endpoint,
                params=params,
                headers={"User-Agent": "OKX-Streamlit-Terminal/2.0"},
                timeout=(8, 25),
            )

            if response.status_code == 429:
                time.sleep(1.0 + attempt)
                continue

            response.raise_for_status()
            payload = response.json()

            if payload.get("code") == "0":
                return payload.get("data", [])

            if payload.get("code") == "50011":
                time.sleep(1.0 + attempt)
                continue

            raise RuntimeError(
                f"OKX {payload.get('code')}: "
                f"{payload.get('msg', 'неизвестная ошибка')}"
            )

        except (requests.RequestException, ValueError, RuntimeError) as exc:
            last_error = str(exc)

            if attempt < 3:
                time.sleep(0.6 * (attempt + 1))

    raise RuntimeError(last_error or "OKX API: лимит запросов или нет ответа")


@st.cache_data(ttl=3600, show_spinner=False)
def instruments(market):
    rows = api_get(
        "/public/instruments",
        {"instType": market_type(market)},
    )

    result = {}

    for item in rows:
        if item.get("state") != "live":
            continue

        inst_id = item.get("instId", "")

        if market == "Спот":
            suitable = item.get("quoteCcy") == "USDT"
        else:
            suitable = (
                item.get("settleCcy") == "USDT"
                and item.get("ctType") == "linear"
                and inst_id.endswith("-USDT-SWAP")
            )

        if suitable:
            result[inst_id] = item

    if not result:
        raise RuntimeError("OKX не вернул доступные USDT-инструменты")

    return result


@st.cache_data(ttl=45, show_spinner=False)
def tickers(market):
    rows = api_get(
        "/market/tickers",
        {"instType": market_type(market)},
    )
    return {item["instId"]: item for item in rows}


@st.cache_data(ttl=20, show_spinner=False)
def current_price(symbol):
    rows = api_get("/market/ticker", {"instId": symbol})

    if not rows:
        raise RuntimeError("Нет текущей цены")

    value = float(rows[0]["last"])

    if value <= 0:
        raise RuntimeError("Некорректная текущая цена")

    return value, rows[0].get("ts", "")


def candle_frame(rows):
    columns = [
        "ts", "o", "h", "l", "c",
        "vol", "volCcy", "volQuote", "confirm",
    ]

    if not rows:
        raise RuntimeError("OKX не вернул свечи")

    df = pd.DataFrame(rows, columns=columns)

    for column in columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df = df[df["confirm"] == 1]
    df = df.dropna(subset=["ts", "o", "h", "l", "c"])
    df = df[(df[["o", "h", "l", "c"]] > 0).all(axis=1)]
    df = df.drop_duplicates("ts").sort_values("ts")
    df["time"] = pd.to_datetime(df["ts"], unit="ms", utc=True)

    return df.reset_index(drop=True)


@st.cache_data(ttl=90, show_spinner=False)
def recent_candles(symbol, bar):
    rows = api_get(
        "/market/candles",
        {"instId": symbol, "bar": bar, "limit": "300"},
    )
    df = candle_frame(rows)

    if len(df) < 60:
        raise RuntimeError("Недостаточно закрытых свечей: нужно минимум 60")

    return df


@st.cache_data(ttl=1800, show_spinner=False)
def history_candles(symbol, bar, start_ms, end_ms):
    all_rows = []
    cursor = end_ms
    interval = BAR_MS[bar]

    expected = max(1, (end_ms - start_ms) // interval)
    max_pages = int(expected // 100) + 8

    for _ in range(max_pages):
        rows = api_get(
            "/market/history-candles",
            {
                "instId": symbol,
                "bar": bar,
                "limit": "100",
                "after": str(cursor),
            },
        )

        if not rows:
            break

        all_rows.extend(rows)
        oldest = min(int(row[0]) for row in rows)

        if oldest <= start_ms:
            break

        if oldest >= cursor:
            raise RuntimeError("Пагинация OKX не продвигается")

        cursor = oldest

    df = candle_frame(all_rows)
    df = df[(df["ts"] >= start_ms) & (df["ts"] < end_ms)]

    if len(df) < 30:
        raise RuntimeError("Недостаточно истории для теста")

    return df.reset_index(drop=True)


# ============================================================
# INDICATORS + SCANNER
# ============================================================

def indicators(df):
    if len(df) < 60:
        raise RuntimeError("Для индикаторов требуется минимум 60 свечей")

    df = df.copy()

    df["RSI"] = RSIIndicator(df["c"], window=14).rsi()

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


def volume_usdt(ticker, market):
    value = float(ticker.get("volCcy24h", 0) or 0)

    if market != "Спот":
        value *= float(ticker.get("last", 0) or 0)

    return value


def scan_one(symbol, market, bar, info, ticker):
    df = indicators(recent_candles(symbol, bar))
    last = df.iloc[-1]

    rsi = float(last["RSI"])
    adx = float(last["ADX"])
    plus = float(last["+DI"])
    minus = float(last["-DI"])

    volume = volume_usdt(ticker, market)
    liquid = volume >= MIN_VOLUME

    list_ms = int(info.get("listTime", 0) or 0)
    age_days = (
        (time.time() * 1000 - list_ms) / 86_400_000
        if list_ms > 0 else None
    )

    atr_pct = float(last["ATR"] / last["c"] * 100)
    coin = symbol.split("-")[0]

    # Направление тренда определяют DI, а не один ADX.
    if not liquid:
        signal = "Низкая ликвидность"
        reason = "24ч оборот ниже 10 млн USDT; сигнал заблокирован"

    elif age_days is not None and age_days < 180:
        signal = "Ждать"
        reason = "Инструмент торгуется менее 180 дней"

    elif adx < 25:
        signal = "Grid-кандидат"
        reason = "ADX ниже 25; это фильтр, а не гарантия боковика"

    elif plus > minus and 35 <= rsi <= 55:
        signal = "Long-кандидат"
        reason = "+DI выше -DI; RSI в зоне возможного отката"

    elif market != "Спот" and minus > plus and 45 <= rsi <= 65:
        signal = "Short-кандидат"
        reason = "-DI выше +DI; RSI в зоне возможного отката"

    else:
        signal = "Ждать"
        reason = "Условия фильтра входа не выполнены"

    if age_days is None:
        risk = "Возраст неизвестен"
    elif age_days < 180:
        risk = "Молодой инструмент"
    elif coin in ("BTC", "ETH"):
        risk = "Относительно умеренный"
    elif atr_pct > 3:
        risk = "Высокая волатильность"
    else:
        risk = "Средняя волатильность"

    return {
        "Монета": coin,
        "Инструмент": symbol,
        "Цена": float(ticker.get("last") or last["c"]),
        "Объём 24ч, USDT": volume,
        "Ликвидность": "Нормальная" if liquid else "Низкая ликвидность",
        "RSI": rsi,
        "ADX": adx,
        "ATR, %": atr_pct,
        "Сигнал": signal,
        "Риск": risk,
        "Причина": reason,
        "TP, %": TP,
    }


def price_chart(df, title):
    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.045,
        row_heights=[0.56, 0.22, 0.22],
    )

    fig.add_trace(
        go.Candlestick(
            x=df["time"],
            open=df["o"],
            high=df["h"],
            low=df["l"],
            close=df["c"],
            name="OHLC",
            increasing_line_color=GREEN,
            decreasing_line_color=RED,
        ),
        row=1, col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=df["time"],
            y=df["RSI"],
            name="RSI 14",
            line=dict(color=BLUE, width=2),
        ),
        row=2, col=1,
    )

    for value, color in [(30, GREEN), (70, RED)]:
        fig.add_hline(
            y=value,
            line_dash="dot",
            line_color=color,
            row=2, col=1,
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
                line=dict(color=color, width=1.7),
            ),
            row=3, col=1,
        )

    fig.add_hline(
        y=25, line_dash="dot",
        line_color="#7E8FA9",
        row=3, col=1,
    )

    fig.update_yaxes(range=[0, 100], row=2, col=1)
    fig.update_layout(title=title, xaxis_rangeslider_visible=False)

    return style_figure(fig, 680)


# ============================================================
# TELEGRAM
# ============================================================

def telegram_credentials():
    token = st.session_state.tg_token
    chat = st.session_state.tg_chat

    try:
        section = st.secrets.get("telegram", {})
        token = section.get("token") or token
        chat = section.get("chat_id") or chat
    except Exception:
        pass

    return str(token).strip(), str(chat).strip()


def send_tg(message):
    token, chat = telegram_credentials()

    if not token or not chat:
        return False, "Не заданы token или chat_id"

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat,
                "text": message,
            },
            timeout=10,
        )
        payload = response.json()

        if response.ok and payload.get("ok"):
            return True, "Отправлено"

        return False, "Telegram отклонил сообщение. Проверьте настройки."

    except Exception:
        return False, "Ошибка соединения с Telegram"


# ============================================================
# JOURNAL
# ============================================================

def read_journal():
    with shared_locks()["journal"]:
        if not JOURNAL.exists():
            return pd.DataFrame(columns=JOURNAL_COLUMNS)

        try:
            return pd.read_csv(JOURNAL)
        except pd.errors.EmptyDataError:
            return pd.DataFrame(columns=JOURNAL_COLUMNS)


def save_journal(record):
    # Блокировка защищает сессии одного процесса приложения.
    with shared_locks()["journal"]:
        old = read_journal()
        new = pd.concat([old, pd.DataFrame([record])], ignore_index=True)

        columns = JOURNAL_COLUMNS + [
            column for column in new.columns
            if column not in JOURNAL_COLUMNS
        ]
        new = new.reindex(columns=columns)

        path = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                suffix=".csv",
                dir=str(JOURNAL.parent),
                delete=False,
            ) as file:
                path = file.name
                new.to_csv(file, index=False)

            os.replace(path, JOURNAL)

        finally:
            if path and os.path.exists(path):
                os.unlink(path)


# ============================================================
# DCA MATH
# ============================================================

def dca_levels(entry, base, count, step, mart, mode):
    rows = []
    total = 0.0
    quantity = 0.0

    for index in range(count + 1):
        if mode == "От первого входа":
            price = entry * (1 - step / 100 * index)
        else:
            price = entry * (1 - step / 100) ** index

        if price <= 0:
            raise ValueError("Уровень DCA должен быть больше нуля")

        amount = base * mart ** index

        total += amount
        quantity += amount / price
        average = total / quantity

        rows.append({
            "Ордер": "Базовый" if index == 0 else f"СО {index}",
            "Цена": price,
            "Сумма, USDT": amount,
            "Всего, USDT": total,
            "Средняя цена": average,
            "TP без комиссий": average * (1 + TP / 100),
        })

    return pd.DataFrame(rows)


# ============================================================
# BACKTEST
# ============================================================

def simulate_dca(df, initial, base, mode):
    cash = float(initial)
    quantity = 0.0
    cost = 0.0
    fees = 0.0
    cycles = 0
    safety_index = 0
    levels = []
    curve = []

    # Equity: денежный остаток + позиция - оценка комиссии выхода.
    def equity(price):
        return cash + quantity * price * (1 - FEE)

    def buy(amount, price):
        nonlocal cash, quantity, cost, fees

        fee = amount * FEE
        debit = amount + fee

        if debit > cash + 1e-9:
            return False

        cash -= debit
        quantity += amount / price
        cost += debit
        fees += fee

        return True

    for _, row in df.iterrows():
        opened_this_bar = False
        added_this_bar = False

        opening = float(row["o"])
        low = float(row["l"])
        closing = float(row["c"])

        if quantity <= 0:
            if buy(base, opening):
                levels = dca_levels(
                    opening, base, SO_COUNT, STEP, MART, mode
                ).to_dict("records")
                safety_index = 1
                opened_this_bar = True

        # При открытии ниже TP: сначала считаем неблагоприятный
        # участок open -> low, затем возможное восстановление.
        if quantity > 0:
            target = cost * (1 + TP / 100) / (
                quantity * (1 - FEE)
            )

            if not opened_this_bar and opening >= target:
                proceeds = quantity * opening
                fee = proceeds * FEE
                cash += proceeds - fee
                fees += fee
                quantity = 0.0
                cost = 0.0
                cycles += 1

            else:
                while (
                    quantity > 0
                    and safety_index <= SO_COUNT
                    and low <= levels[safety_index]["Цена"]
                ):
                    level = levels[safety_index]
                    fill = min(opening, float(level["Цена"]))

                    if not buy(float(level["Сумма, USDT"]), fill):
                        break

                    safety_index += 1
                    added_this_bar = True

                # Минимум капитала при неблагоприятном движении.
                curve.append({
                    "time": row["time"],
                    "Этап": "Внутрисвечная оценка",
                    "Equity": equity(low),
                })

                if quantity > 0:
                    target = cost * (1 + TP / 100) / (
                        quantity * (1 - FEE)
                    )

                    # После покупки в этой свече TP проверяется
                    # только по закрытию: не предполагаем, что high
                    # произошёл после покупки.
                    if opened_this_bar or added_this_bar:
                        hit = closing >= target
                    else:
                        hit = float(row["h"]) >= target

                    if hit:
                        proceeds = quantity * target
                        fee = proceeds * FEE
                        cash += proceeds - fee
                        fees += fee
                        quantity = 0.0
                        cost = 0.0
                        cycles += 1

        curve.append({
            "time": row["time"],
            "Этап": "Закрытие",
            "Equity": equity(closing),
        })

    realized = cash + cost - initial
    return finish_test(
        curve, initial, fees, cycles, realized,
        quantity * float(df.iloc[-1]["c"]),
    )


def simulate_grid(df, initial, lower_pct, upper_pct, count):
    start_price = float(df.iloc[0]["o"])
    lower = start_price * (1 - lower_pct / 100)
    upper = start_price * (1 + upper_pct / 100)
    levels = np.linspace(lower, upper, count + 1)

    # Без предварительной покупки монет:
    # стартуют только buy-уровни ниже начальной цены.
    active_indices = [
        index for index in range(count)
        if levels[index] < start_price
    ]

    if not active_indices:
        raise ValueError("Нет buy-уровней ниже стартовой цены")

    order_amount = initial / len(active_indices) / (1 + FEE)

    cash = float(initial)
    lots = {}
    fees = 0.0
    cycles = 0
    realized = 0.0
    curve = []

    def equity(price):
        return cash + sum(
            lot["quantity"] * price * (1 - FEE)
            for lot in lots.values()
        )

    for _, row in df.iterrows():
        opening = float(row["o"])
        low = float(row["l"])
        high = float(row["h"])
        closing = float(row["c"])

        held_at_start = set(lots)
        sold = set()

        # Сначала учитываем неблагоприятный участок свечи.
        # Новые покупки не продаются в той же свече.
        for index in active_indices:
            if index in held_at_start:
                continue

            buy_level = float(levels[index])

            if low <= buy_level:
                fill = min(opening, buy_level)
                fee = order_amount * FEE
                debit = order_amount + fee

                if cash + 1e-9 < debit:
                    continue

                cash -= debit
                fees += fee

                lots[index] = {
                    "quantity": order_amount / fill,
                    "cost": debit,
                    "target": float(levels[index + 1]),
                }

        curve.append({
            "time": row["time"],
            "Этап": "Внутрисвечная оценка",
            "Equity": equity(low),
        })

        for index in held_at_start:
            lot = lots[index]

            if high >= lot["target"]:
                # Консервативное исполнение по лимиту.
                gross = lot["quantity"] * lot["target"]
                fee = gross * FEE
                net = gross - fee

                cash += net
                fees += fee
                realized += net - lot["cost"]
                cycles += 1
                sold.add(index)

        for index in sold:
            del lots[index]

        curve.append({
            "time": row["time"],
            "Этап": "Закрытие",
            "Equity": equity(closing),
        })

    position_value = sum(
        lot["quantity"] * float(df.iloc[-1]["c"])
        for lot in lots.values()
    )

    return finish_test(
        curve, initial, fees, cycles,
        realized, position_value,
    )


def finish_test(curve, initial, fees, cycles, realized, position_value):
    frame = pd.DataFrame(curve)

    peaks = frame["Equity"].cummax().clip(lower=initial)
    drawdown = peaks - frame["Equity"]
    drawdown_pct = drawdown / peaks * 100

    final = float(frame.iloc[-1]["Equity"])

    return {
        "Метрики": {
            "Циклов": cycles,
            "Итоговая equity, USDT": round(final, 2),
            "Общий PnL, USDT": round(final - initial, 2),
            "Реализованный PnL, USDT": round(realized, 2),
            "Доходность, %": round((final / initial - 1) * 100, 2),
            "Макс. просадка, USDT": round(float(drawdown.max()), 2),
            "Макс. просадка, %": round(float(drawdown_pct.max()), 2),
            "Уплаченные комиссии, USDT": round(fees, 2),
            "Открытая позиция, USDT": round(position_value, 2),
        },
        "Кривая": frame,
    }


# ============================================================
# POSITION ANALYZER
# ============================================================

def analyze_position(
    symbol, market, side, quantity, entry,
    price, liquidation, margin, opening_fee,
):
    direction = 1 if side == "Long" else -1

    gross = direction * quantity * (price - entry)
    closing_fee = quantity * price * FEE
    net = gross - opening_fee - closing_fee

    notional = quantity * entry
    pnl_pct = net / notional * 100 if notional > 0 else 0.0

    distance = None

    if market != "Спот" and liquidation > 0:
        distance = (
            (price - liquidation) / price * 100
            if side == "Long"
            else (liquidation - price) / price * 100
        )

    health = 100.0
    health -= min(45.0, max(0.0, -pnl_pct) * 3)

    if distance is not None:
        if distance <= 0:
            health = 0.0
        elif distance < 5:
            health = min(health, 15)
        elif distance < 10:
            health -= 50
        elif distance < 20:
            health -= 30
        elif distance < 35:
            health -= 12

    health = float(np.clip(health, 0, 100))

    if distance is not None and distance <= 0:
        status = "Цена достигла указанной границы"
        advice = (
            "Проверьте фактический статус позиции на OKX. "
            "Указанная цена находится за границей ликвидации."
        )
    elif health <= 40:
        status = "Высокий риск"
        advice = (
            "Проверьте лимит допустимого убытка и возможность "
            "сокращения позиции. Автоматическое усреднение отключите "
            "до проверки. Добавление маржи не устраняет торговый риск."
        )
    elif health <= 70:
        status = "Требует внимания"
        advice = (
            "Проверьте оставшийся резерв для СО и соблюдение плана. "
            "Не увеличивайте позицию только ради улучшения средней цены."
        )
    else:
        status = "Нет срабатывания критических порогов"
        advice = (
            "По введённым данным критические пороги не сработали. "
            "Это не прогноз цены и не гарантия безопасности позиции."
        )

    roi = None

    if market != "Спот" and margin > 0:
        roi = net / margin * 100

    return {
        "symbol": symbol,
        "market": market,
        "side": side,
        "quantity": quantity,
        "entry": entry,
        "price": price,
        "liquidation": liquidation,
        "opening_fee": opening_fee,
        "gross": gross,
        "net": net,
        "pnl_pct": pnl_pct,
        "roi": roi,
        "distance": distance,
        "health": health,
        "status": status,
        "advice": advice,
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def gauge_chart(health):
    color = GREEN if health > 70 else YELLOW if health > 40 else RED

    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=health,
            number={"suffix": "/100", "font": {"size": 34}},
            title={"text": "Условная оценка риска"},
            gauge={
                "axis": {"range": [0, 100]},
                "bar": {"color": color},
                "borderwidth": 0,
                "steps": [
                    {"range": [0, 40], "color": "#492333"},
                    {"range": [40, 70], "color": "#4A3D24"},
                    {"range": [70, 100], "color": "#143E36"},
                ],
            },
        )
    )

    return style_figure(fig, 300)


def position_pnl_chart(result):
    entry = result["entry"]
    price = result["price"]
    liquidation = result["liquidation"]

    minimum = min(entry, price) * 0.8
    maximum = max(entry, price) * 1.2

    if result["market"] != "Спот" and liquidation > 0:
        minimum = min(minimum, liquidation * 0.95)
        maximum = max(maximum, liquidation * 1.05)

    prices = np.linspace(max(minimum, 1e-12), maximum, 200)
    sign = 1 if result["side"] == "Long" else -1

    values = (
        sign * result["quantity"] * (prices - entry)
        - result["opening_fee"]
        - result["quantity"] * prices * FEE
    )

    fig = go.Figure(
        go.Scatter(
            x=prices,
            y=values,
            name="Расчётный PnL",
            line=dict(color=BLUE, width=3),
        )
    )

    fig.add_hline(y=0, line_dash="dot")
    fig.add_vline(
        x=entry,
        line_color=BLUE,
        annotation_text="Вход",
    )
    fig.add_vline(
        x=price,
        line_color=YELLOW,
        annotation_text="Текущая",
    )

    if result["market"] != "Спот" and liquidation > 0:
        fig.add_vline(
            x=liquidation,
            line_color=RED,
            annotation_text="Указанная ликвидация",
        )

    fig.update_layout(
        title="Сценарный PnL, не история доходности",
        xaxis_title="Цена",
        yaxis_title="PnL, USDT",
    )

    return style_figure(fig)


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.markdown("## ⚡ OKX Terminal")
    st.caption("Аналитика • правила • журнал")

    page = st.radio(
        "Раздел",
        [
            "Главная",
            "Сканер",
            "ИИ-Центр",
            "DCA",
            "Grid",
            "Бэктест",
            "Журнал решений",
            "Настройки",
        ],
        label_visibility="collapsed",
    )

    st.divider()
    st.caption("DCA: TP 1.5% · шаг 2%")
    st.caption("Базовый ордер + 4 СО · ×1.2")
    st.caption("Приложение не размещает торговые ордера.")

st.title(page)


# ============================================================
# HOME
# ============================================================

if page == "Главная":
    panel(
        "Терминал аналитики OKX",
        "Реальные рыночные данные, индикаторы, "
        "калькуляторы и журнал решений.",
    )

    columns = st.columns(3)

    with columns[0]:
        card("Режим", "Аналитика", BLUE)

    with columns[1]:
        card("Торговое подключение", "Не подключено", YELLOW)

    with columns[2]:
        card("Параметры DCA", "1.5% / 2% / 4 СО", GREEN)

    st.info(
        "Баланс и активные боты не отображаются: приватный API "
        "аккаунта не подключён. Приложение не подменяет эти данные нулями."
    )

    panel(
        "Как пользоваться",
        "Сканер — рынок и индикаторы. ИИ-Центр — анализ введённой "
        "позиции. DCA и Grid — расчёт уровней. Бэктест — моделирование "
        "на истории. Журнал — сохранённые результаты анализа.",
    )


# ============================================================
# SCANNER PAGE
# ============================================================

elif page == "Сканер":
    market = st.radio("Рынок", MARKETS, horizontal=True)
    bar = st.selectbox(
        "Таймфрейм анализа",
        list(BAR_MS),
        index=4,
        format_func=lambda value: BAR_LABELS[value],
    )

    st.caption(
        "Сигналы — технические кандидаты, а не торговые команды. "
        "TP фиксирован: 1.5%. Объём SWAP в USDT — приближённая оценка."
    )

    if st.button("Сканировать 20 монет", use_container_width=True):
        try:
            info = instruments(market)
            ticker_map = tickers(market)

            wanted = [
                f"{coin}-USDT" + (
                    "-SWAP" if market != "Спот" else ""
                )
                for coin in COINS
            ]

            available = [
                symbol for symbol in wanted
                if symbol in info and symbol in ticker_map
            ]

            unavailable = [
                symbol for symbol in wanted
                if symbol not in available
            ]

            result = []
            errors = []

            progress = st.progress(0.0)

            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = {
                    pool.submit(
                        scan_one,
                        symbol,
                        market,
                        bar,
                        info[symbol],
                        ticker_map[symbol],
                    ): symbol
                    for symbol in available
                }

                total = len(futures)

                for index, future in enumerate(as_completed(futures), 1):
                    try:
                        result.append(future.result())
                    except Exception as exc:
                        errors.append(f"{futures[future]}: {exc}")

                    progress.progress(index / max(total, 1))

            progress.empty()

            st.session_state.scan_result = {
                "market": market,
                "bar": bar,
                "rows": result,
                "errors": errors,
                "unavailable": unavailable,
                "time": datetime.now(timezone.utc).isoformat(
                    timespec="seconds"
                ),
            }

        except Exception as exc:
            st.error(str(exc))

    saved = st.session_state.scan_result

    if saved:
        st.caption(
            f"Результат: {saved['market']} · "
            f"{BAR_LABELS[saved['bar']]} · {saved['time']}"
        )

        if saved["unavailable"]:
            st.warning(
                "Недоступны на выбранном рынке: "
                + ", ".join(saved["unavailable"])
            )

        if saved["errors"]:
            with st.expander("Ошибки отдельных инструментов"):
                st.write("\n".join(saved["errors"]))

        if saved["rows"]:
            table = pd.DataFrame(saved["rows"]).sort_values(
                "Объём 24ч, USDT",
                ascending=False,
            )

            low_count = int(
                (table["Ликвидность"] == "Низкая ликвидность").sum()
            )

            c1, c2 = st.columns(2)

            with c1:
                card("Проанализировано", len(table))

            with c2:
                card("Низкая ликвидность", low_count, YELLOW)

            st.dataframe(
                table.style.format({
                    "Цена": "{:,.8f}",
                    "Объём 24ч, USDT": "{:,.0f}",
                    "RSI": "{:.1f}",
                    "ADX": "{:.1f}",
                    "ATR, %": "{:.2f}",
                    "TP, %": "{:.1f}",
                }),
                hide_index=True,
                use_container_width=True,
            )

            selected = st.selectbox(
                "График инструмента",
                table["Инструмент"].tolist(),
            )

            try:
                df = indicators(
                    recent_candles(selected, saved["bar"])
                )

                show_figure(
                    price_chart(
                        df,
                        f"{selected} · {BAR_LABELS[saved['bar']]}",
                    )
                )

                st.caption(
                    "Только закрытые свечи. Индикаторы: RSI 14, "
                    "ADX 14, +DI и -DI. Данные кэшируются до 90 секунд."
                )

            except Exception as exc:
                st.error(str(exc))

        else:
            st.info("Нет успешно проанализированных инструментов.")


# ============================================================
# AI CENTER PAGE
# ============================================================

elif page == "ИИ-Центр":
    panel(
        "Анализ позиции по правилам",
        "Выберите рынок и инструмент. PnL считается по количеству "
        "монет, а не по внесённой марже. Для USDT-линейных SWAP "
        "вводите эквивалент позиции в базовой монете, не число контрактов.",
    )

    market = st.radio(
        "Рынок позиции",
        MARKETS,
        horizontal=True,
        key="ai_market",
    )

    try:
        info = instruments(market)
        options = sorted(info)

        default_symbol = (
            "BTC-USDT" if market == "Спот"
            else "BTC-USDT-SWAP"
        )

        symbol = st.selectbox(
            "Инструмент",
            options,
            index=options.index(default_symbol)
            if default_symbol in options else 0,
            key=f"ai_symbol_{market}",
        )

    except Exception as exc:
        st.error(str(exc))
        st.stop()

    side = (
        "Long" if market == "Спот"
        else st.radio(
            "Направление",
            ["Long", "Short"],
            horizontal=True,
        )
    )

    price_key = f"position_price_{symbol}"

    if price_key not in st.session_state:
        st.session_state[price_key] = 0.0

    if st.button("Загрузить текущую цену OKX"):
        try:
            value, _ = current_price(symbol)
            st.session_state[price_key] = value
        except Exception as exc:
            st.error(str(exc))

    current = st.number_input(
        "Текущая цена — загрузите с OKX или введите вручную",
        min_value=0.0,
        format="%.8f",
        key=price_key,
    )

    with st.form("position_form"):
        c1, c2 = st.columns(2)

        quantity = c1.number_input(
            "Количество базовой монеты",
            min_value=0.0,
            value=0.001,
            format="%.8f",
            help="Например, 0.001 BTC. Для SWAP не число контрактов.",
        )

        entry = c2.number_input(
            "Средняя цена входа",
            min_value=0.0,
            value=float(current) if current > 0 else 100.0,
            format="%.8f",
        )

        liquidation = 0.0
        margin = 0.0

        if market != "Спот":
            c3, c4 = st.columns(2)

            liquidation = c3.number_input(
                "Цена ликвидации из OKX, 0 — неизвестна",
                min_value=0.0,
                value=0.0,
                format="%.8f",
            )

            margin = c4.number_input(
                "Текущая маржа, USDT — для оценки ROI",
                min_value=0.0,
                value=0.0,
            )

        opening_fee = st.number_input(
            "Уплаченные комиссии входа, USDT",
            min_value=0.0,
            value=0.0,
            format="%.6f",
        )

        submitted = st.form_submit_button(
            "Анализировать и записать в журнал",
            use_container_width=True,
        )

    if submitted:
        if current <= 0 or entry <= 0 or quantity <= 0:
            st.error("Цена, вход и количество должны быть больше нуля.")

        else:
            result = analyze_position(
                symbol, market, side, quantity, entry,
                current, liquidation, margin, opening_fee,
            )

            st.session_state.ai_result = result

            record = {
                "Дата": result["time"],
                "Монета": symbol.split("-")[0],
                "Инструмент": symbol,
                "Рынок": market,
                "Направление": side,
                "Здоровье": round(result["health"], 1),
                "Статус": result["status"],
                "Совет": result["advice"],
                "PnL, USDT": round(result["net"], 6),
                "PnL, %": round(result["pnl_pct"], 3),
                "До ликвидации, %": (
                    round(result["distance"], 3)
                    if result["distance"] is not None else None
                ),
            }

            try:
                save_journal(record)
                st.success("Результат сохранён в журнал.")

            except Exception as exc:
                st.error(
                    f"Анализ выполнен, но запись журнала не удалась: {exc}"
                )

    result = st.session_state.ai_result

    if result:
        st.divider()

        st.caption(
            f"Сохранённый анализ: {result['symbol']} · "
            f"{result['market']} · {result['side']} · {result['time']}. "
            "После изменения полей нажмите «Анализировать» повторно."
        )

        c1, c2 = st.columns([1, 1.3])

        with c1:
            show_figure(gauge_chart(result["health"]))

        with c2:
            card(
                "PnL после оценки комиссии выхода",
                f"{result['net']:,.4f} USDT",
                GREEN if result["net"] >= 0 else RED,
            )

            card(
                "PnL к номиналу входа",
                f"{result['pnl_pct']:.2f}%",
            )

            if result["distance"] is not None:
                card(
                    "До указанной ликвидации",
                    f"{result['distance']:.2f}%",
                    YELLOW,
                )

            if result["roi"] is not None:
                card(
                    "PnL / введённая маржа",
                    f"{result['roi']:.2f}%",
                )

        panel(result["status"], result["advice"])

        st.caption(
            "Здоровье — условная шкала порогов, не вероятность успеха. "
            "Комиссия выхода оценена как 0.05%. Funding и уже "
            "реализованный PnL бота здесь не учитываются."
        )

        show_figure(position_pnl_chart(result))

        if st.button(
            "Отправить этот анализ в Telegram",
            use_container_width=True,
        ):
            message = (
                f"OKX Terminal\n"
                f"{result['symbol']} | {result['market']} | "
                f"{result['side']}\n"
                f"Здоровье: {result['health']:.0f}/100\n"
                f"PnL: {result['net']:.4f} USDT\n"
                f"Статус: {result['status']}\n"
                f"{result['advice']}"
            )

            ok, text = send_tg(message)

            if ok:
                st.success(text)
            else:
                st.error(text)


# ============================================================
# DCA PAGE
# ============================================================

elif page == "DCA":
    panel(
        "Ваши параметры DCA",
        "TP 1.5%, шаг 2%, базовый ордер + 4 страховочных, "
        "каждый следующий ордер в 1.2 раза больше предыдущего.",
    )

    entry = st.number_input(
        "Цена первого входа",
        min_value=0.00000001,
        value=100.0,
        format="%.8f",
    )

    base = st.number_input(
        "Базовый ордер, USDT",
        min_value=1.0,
        value=BASE_ORDER,
    )

    mode = st.radio(
        "Как считать шаг 2%",
        ["От первого входа", "От предыдущего ордера"],
        horizontal=True,
    )

    table = dca_levels(
        entry, base, SO_COUNT, STEP, MART, mode
    )

    st.dataframe(
        table.style.format({
            "Цена": "{:,.8f}",
            "Сумма, USDT": "{:,.4f}",
            "Всего, USDT": "{:,.4f}",
            "Средняя цена": "{:,.8f}",
            "TP без комиссий": "{:,.8f}",
        }),
        hide_index=True,
        use_container_width=True,
    )

    total = float(table.iloc[-1]["Всего, USDT"])
    quantity = float(
        (table["Сумма, USDT"] / table["Цена"]).sum()
    )

    target_with_fees = (
        total * (1 + FEE) * (1 + TP / 100)
        / (quantity * (1 - FEE))
    )

    c1, c2 = st.columns(2)

    with c1:
        card(
            "Резерв с комиссией входа",
            f"{total * (1 + FEE):.4f} USDT",
        )

    with c2:
        card(
            "TP для чистых +1.5% после комиссий",
            f"{target_with_fees:,.8f}",
            GREEN,
        )

    st.caption(
        "Средняя цена рассчитана через общее количество монет. "
        "TP с комиссиями: чистые +1.5% к затратам на вход. "
        "Калькулятор показывает Long-сетку."
    )

    fig = go.Figure(
        go.Bar(
            x=table["Ордер"],
            y=table["Цена"],
            text=table["Сумма, USDT"].map(
                lambda value: f"{value:.2f} USDT"
            ),
            marker_color=GREEN,
            name="Уровни покупки",
        )
    )

    fig.update_layout(
        title="Уровни DCA и размеры ордеров",
        yaxis_title="Цена",
    )

    show_figure(style_figure(fig))


# ============================================================
# GRID PAGE
# ============================================================

elif page == "Grid":
    panel(
        "Арифметическая Grid-сетка",
        "Количество интервалов и количество уровней различаются: "
        "10 интервалов означают 11 ценовых уровней.",
    )

    c1, c2, c3 = st.columns(3)

    lower = c1.number_input(
        "Нижняя граница",
        min_value=0.00000001,
        value=90.0,
        format="%.8f",
    )

    upper = c2.number_input(
        "Верхняя граница",
        min_value=0.00000001,
        value=110.0,
        format="%.8f",
    )

    count = c3.number_input(
        "Количество интервалов",
        min_value=2,
        max_value=100,
        value=10,
    )

    if upper <= lower:
        st.error("Верхняя граница должна быть выше нижней.")

    else:
        levels = np.linspace(lower, upper, int(count) + 1)
        step_value = (upper - lower) / count

        table = pd.DataFrame({
            "Уровень": np.arange(len(levels)),
            "Цена": levels,
        })

        st.dataframe(
            table,
            hide_index=True,
            use_container_width=True,
        )

        card("Шаг в цене", f"{step_value:,.8f}", BLUE)

        st.caption(
            "Процент прибыли на арифметической сетке зависит "
            "от уровня покупки. Комиссии уменьшают прибыль каждого цикла."
        )

        fig = go.Figure(
            go.Scatter(
                x=table["Уровень"],
                y=table["Цена"],
                mode="lines+markers",
                line=dict(color=BLUE, width=2),
                marker=dict(size=7),
                name="Цена уровня",
            )
        )

        fig.update_layout(title="Уровни Grid")
        show_figure(style_figure(fig))


# ============================================================
# BACKTEST PAGE
# ============================================================

elif page == "Бэктест":
    st.warning(
        "Модель Long без плеча. Для SWAP используется цена контракта, "
        "но funding, маржинальные требования и ликвидации не моделируются. "
        "Проскальзывание, очередь лимитных ордеров и точный порядок "
        "сделок внутри свечи неизвестны."
    )

    market = st.radio(
        "Рынок истории",
        MARKETS,
        horizontal=True,
        key="bt_market",
    )

    try:
        available_info = instruments(market)

        universe = [
            f"{coin}-USDT" + (
                "-SWAP" if market != "Спот" else ""
            )
            for coin in COINS
        ]

        options = [
            symbol for symbol in universe
            if symbol in available_info
        ]

        if not options:
            raise RuntimeError("Нет доступных инструментов")

    except Exception as exc:
        st.error(str(exc))
        st.stop()

    selected = st.multiselect(
        "Монеты для теста",
        options,
        default=options[:1],
    )

    strategy = st.radio(
        "Стратегия",
        ["DCA", "Grid"],
        horizontal=True,
    )

    c1, c2, c3 = st.columns(3)

    bar = c1.selectbox(
        "Таймфрейм",
        list(BAR_MS),
        format_func=lambda value: BAR_LABELS[value],
    )

    days = c2.number_input(
        "Дней истории",
        min_value=1,
        max_value=180,
        value=30,
    )

    initial = c3.number_input(
        "Начальный капитал, USDT",
        min_value=10.0,
        value=1000.0,
    )

    mode = "От первого входа"
    base = BASE_ORDER
    lower_pct = 10.0
    upper_pct = 10.0
    grid_count = 10

    if strategy == "DCA":
        st.caption(
            "TP 1.5% · шаг 2% · 4 СО · мартингейл 1.2. "
            "Вход нового цикла — на открытии следующей свечи. "
            "Сигналы Сканера в этот тест не встроены."
        )

        base = st.number_input(
            "Базовый ордер, USDT",
            min_value=1.0,
            value=BASE_ORDER,
            key="bt_base",
        )

        mode = st.radio(
            "Шаг страховочных",
            ["От первого входа", "От предыдущего ордера"],
            horizontal=True,
            key="bt_mode",
        )

    else:
        c1, c2, c3 = st.columns(3)

        lower_pct = c1.number_input(
            "Нижняя граница от старта, %",
            min_value=0.1,
            max_value=90.0,
            value=10.0,
        )

        upper_pct = c2.number_input(
            "Верхняя граница от старта, %",
            min_value=0.1,
            max_value=200.0,
            value=10.0,
        )

        grid_count = c3.number_input(
            "Интервалов",
            min_value=2,
            max_value=100,
            value=10,
        )

        st.caption(
            "Grid начинает с USDT без стартового запаса монет. "
            "Работают пары уровней ниже стартовой цены. "
            "Новые покупки не продаются в той же свече."
        )

    estimate = int(days * 86_400_000 / BAR_MS[bar])

    st.caption(
        f"Примерно {estimate:,} свечей на инструмент. "
        "Длинный тест по многим монетам может занять несколько минут. "
        "История кэшируется на 30 минут."
    )

    if st.button("Запустить бэктест", use_container_width=True):
        if not selected:
            st.error("Выберите хотя бы одну монету.")

        elif strategy == "DCA" and (
            base * sum(MART ** i for i in range(SO_COUNT + 1))
            * (1 + FEE) > initial
        ):
            st.error(
                "Капитала недостаточно для базового ордера и всех 4 СО."
            )

        else:
            end_ms = (
                int(time.time() * 1000) // BAR_MS[bar]
            ) * BAR_MS[bar]

            start_ms = end_ms - int(days) * 86_400_000

            rows = []
            curves = {}
            errors = []
            progress = st.progress(0.0)

            for index, symbol in enumerate(selected, 1):
                try:
                    with st.spinner(f"История и расчёт: {symbol}"):
                        df = history_candles(
                            symbol, bar, start_ms, end_ms
                        )

                        deltas = df["ts"].diff().dropna()
                        has_gaps = bool(
                            (deltas != BAR_MS[bar]).any()
                        )

                        if strategy == "DCA":
                            result = simulate_dca(
                                df, initial, base, mode
                            )
                        else:
                            result = simulate_grid(
                                df,
                                initial,
                                lower_pct,
                                upper_pct,
                                int(grid_count),
                            )

                        row = {
                            "Инструмент": symbol,
                            **result["Метрики"],
                            "Свечей": len(df),
                            "Начало UTC": str(df.iloc[0]["time"]),
                            "Последняя свеча UTC": str(
                                df.iloc[-1]["time"]
                            ),
                            "Покрытие, %": round(
                                min(100.0, len(df) / max(estimate, 1) * 100),
                                1,
                            ),
                            "Пропуски": "Да" if has_gaps else "Нет",
                        }

                        rows.append(row)
                        curves[symbol] = result["Кривая"]

                except Exception as exc:
                    errors.append(f"{symbol}: {exc}")

                progress.progress(index / len(selected))

            progress.empty()

            st.session_state.bt_result = {
                "rows": rows,
                "curves": curves,
                "errors": errors,
                "strategy": strategy,
                "market": market,
                "bar": bar,
            }

    saved = st.session_state.bt_result

    if saved:
        st.caption(
            f"Сохранённый тест: {saved['strategy']} · "
            f"{saved['market']} · {BAR_LABELS[saved['bar']]}"
        )

        if saved["errors"]:
            with st.expander("Ошибки загрузки"):
                st.write("\n".join(saved["errors"]))

        if saved["rows"]:
            table = pd.DataFrame(saved["rows"])

            st.dataframe(
                table,
                hide_index=True,
                use_container_width=True,
            )

            symbol = st.selectbox(
                "Кривая капитала",
                list(saved["curves"]),
            )

            frame = saved["curves"][symbol]

            fig = go.Figure(
                go.Scatter(
                    x=frame["time"],
                    y=frame["Equity"],
                    mode="lines",
                    name="Equity",
                    line=dict(color=GREEN, width=2),
                )
            )

            fig.update_layout(
                title=f"{symbol} — денежный остаток + открытая позиция",
                yaxis_title="USDT",
            )

            show_figure(style_figure(fig))

            st.caption(
                "Equity включает оценочную комиссию закрытия открытой "
                "позиции. Уплаченные комиссии показываются отдельно. "
                "Просадка — падение equity от предыдущего максимума. "
                "Внутрисвечные оценки используют неблагоприятный "
                "порядок движения цены; это не тиковая симуляция."
            )

            st.download_button(
                "Скачать результаты",
                table.to_csv(index=False).encode("utf-8-sig"),
                file_name="backtest.csv",
                mime="text/csv",
                use_container_width=True,
            )


# ============================================================
# JOURNAL PAGE
# ============================================================

elif page == "Журнал решений":
    panel(
        "История анализов",
        "Запись создаётся после нажатия кнопки анализа в ИИ-Центре. "
        "Время сохраняется в UTC.",
    )

    try:
        journal = read_journal()

        if journal.empty:
            st.info("Журнал пока пуст.")

        else:
            filtered = journal.copy()

            if "Монета" in journal:
                coins = sorted(
                    journal["Монета"].dropna().astype(str).unique()
                )

                chosen = st.multiselect(
                    "Фильтр по монетам",
                    coins,
                )

                if chosen:
                    filtered = filtered[
                        filtered["Монета"].astype(str).isin(chosen)
                    ]

            c1, c2 = st.columns(2)

            with c1:
                card("Записей в выборке", len(filtered))

            with c2:
                if "Здоровье" in filtered and len(filtered):
                    average = pd.to_numeric(
                        filtered["Здоровье"],
                        errors="coerce",
                    ).mean()

                    card("Средняя условная оценка", f"{average:.1f}/100")

            st.dataframe(
                filtered.iloc[::-1],
                hide_index=True,
                use_container_width=True,
            )

            st.caption(
                "PnL разных записей не суммируется: несколько анализов "
                "одной позиции не являются отдельными сделками."
            )

            st.download_button(
                "Скачать журнал CSV",
                filtered.to_csv(index=False).encode("utf-8-sig"),
                file_name="journal.csv",
                mime="text/csv",
                use_container_width=True,
            )

        st.warning(
            "journal.csv — локальный файл сервера. "
            "В облачном развёртывании его нельзя считать "
            "гарантированным постоянным хранилищем. "
            "Делайте выгрузки; для постоянной истории нужна база данных. "
            "Этот журнал общий для экземпляра приложения, "
            "а не персональное хранилище пользователей."
        )

    except Exception as exc:
        st.error(f"Не удалось прочитать журнал: {exc}")


# ============================================================
# SETTINGS PAGE
# ============================================================

elif page == "Настройки":
    panel(
        "Telegram",
        "Secrets имеют приоритет. Если их нет, "
        "токен и Chat ID хранятся только в текущей сессии.",
    )

    has_secrets = False

    try:
        section = st.secrets.get("telegram", {})
        has_secrets = bool(
            section.get("token") and section.get("chat_id")
        )
    except Exception:
        pass

    if has_secrets:
        st.success("Telegram token и chat_id найдены в Secrets.")

    else:
        st.text_input(
            "Bot Token",
            type="password",
            key="tg_token",
        )

        st.text_input(
            "Chat ID",
            key="tg_chat",
        )

    if st.button("Тест Telegram", use_container_width=True):
        ok, text = send_tg("OKX Terminal: тест подключения ✅")

        if ok:
            st.success(text)
        else:
            st.error(text)

    st.divider()

    panel(
        "Параметры расчётов",
        "Комиссия модели: 0.05% на вход и 0.05% на выход. "
        "DCA: тейк 1.5%, шаг 2%, 4 страховочных, мартингейл 1.2. "
        "Комиссия модели может отличаться от вашего тарифа OKX.",
    )

    st.caption(
        "Ни токен Telegram, ни приватные ключи нельзя "
        "публиковать в репозитории."
    )
