import os
import time
import json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import streamlit as st
import pandas as pd
import numpy as np
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from ta.momentum import RSIIndicator
from ta.trend import ADXIndicator
from ta.volatility import AverageTrueRange

# ---------------- CONFIG ----------------
st.set_page_config(
    page_title="OKX Terminal Pro",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

OKX = "https://www.okx.com/api/v5"
CANDLES_URL = f"{OKX}/market/candles"
TICKERS_URL = f"{OKX}/market/tickers"
INSTRUMENTS_URL = f"{OKX}/public/instruments"
HEADERS = {"User-Agent": "Mozilla/5.0"}

COINS = [
    "BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT",
    "TON", "TRX", "LTC", "NEAR", "APT", "ARBITRUM", "OP", "SUI", "PEPE", "INJ",
]

MIN_LIQUIDITY_USD = 10_000_000
DEFAULT_TP = 1.5
DEFAULT_STEP = 2.0
DEFAULT_SO = 4
DEFAULT_MARTINGALE = 1.2
FEE_RATE = 0.0005  # 0.05% вход и 0.05% выход

JOURNAL_FILE = "journal.csv"

# ---------------- UI ----------------
st.markdown("""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">

<style>
:root {
  --bg: #05070c;
  --panel: rgba(18, 22, 33, 0.72);
  --panel-border: rgba(255, 255, 255, 0.08);
  --accent: #00ff9d;
  --red: #ff4d6d;
  --yellow: #ffd166;
  --muted: #8b94a7;
}

.stApp {
  background:
    radial-gradient(1100px 600px at 8% -10%, rgba(0, 255, 157, 0.09), transparent 60%),
    radial-gradient(900px 600px at 100% 0%, rgba(88, 101, 242, 0.12), transparent 55%),
    linear-gradient(180deg, #05070c 0%, #04050a 100%);
  color: #e8ecf4;
  font-family: 'Inter', sans-serif;
}

h1, h2, h3, h4, p, label, span, div {
  font-family: 'Inter', sans-serif;
}

h1 {
  font-weight: 800;
  letter-spacing: -0.04em;
}

.glass {
  background: var(--panel);
  border: 1px solid var(--panel-border);
  border-radius: 20px;
  padding: 20px;
  backdrop-filter: blur(18px);
  box-shadow: 0 18px 45px rgba(0, 0, 0, 0.38);
}

.metric-card {
  background: linear-gradient(145deg, rgba(23, 28, 41, 0.85), rgba(11, 14, 22, 0.9));
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 18px;
  padding: 18px 20px;
  backdrop-filter: blur(16px);
  transition: transform .25s ease, border-color .25s ease, box-shadow .25s ease;
}

.metric-card:hover {
  transform: translateY(-3px);
  border-color: rgba(0, 255, 157, 0.35);
  box-shadow: 0 14px 34px rgba(0, 255, 157, 0.10);
}

.metric-label {
  color: var(--muted);
  font-size: .82rem;
  text-transform: uppercase;
  letter-spacing: .09em;
  font-weight: 600;
}

.metric-value {
  color: #fff;
  font-size: 1.7rem;
  font-weight: 800;
  margin-top: 7px;
  font-family: 'JetBrains Mono', monospace;
}

.metric-positive { color: var(--accent); }
.metric-negative { color: var(--red); }
.metric-warning { color: var(--yellow); }

.stButton > button {
  width: 100%;
  background: linear-gradient(135deg, #00ff9d, #00c2ff);
  color: #020508;
  border: none;
  border-radius: 14px;
  padding: .65rem 1rem;
  font-weight: 800;
  letter-spacing: .02em;
  transition: transform .18s ease, box-shadow .18s ease, filter .18s ease;
}

.stButton > button:hover {
  transform: translateY(-2px);
  filter: brightness(1.08);
  box-shadow: 0 12px 30px rgba(0, 255, 157, 0.22);
}

.stButton > button:active {
  transform: translateY(0);
}

[data-testid="stSidebar"] {
  background: rgba(7, 9, 15, 0.94);
  border-right: 1px solid rgba(255, 255, 255, 0.06);
}

[data-testid="stSidebar"] .stRadio label {
  background: rgba(255,255,255,0.03);
  border-radius: 12px;
  padding: 8px 10px;
  margin-bottom: 5px;
  transition: background .18s ease;
}

[data-testid="stSidebar"] .stRadio label:hover {
  background: rgba(0,255,157,0.08);
}

[data-testid="stDataFrame"] {
  border: 1px solid rgba(255,255,255,0.07);
  border-radius: 16px;
  overflow: hidden;
}

.section-title {
  font-size: 1.05rem;
  font-weight: 700;
  margin-bottom: 4px;
}

.section-sub {
  color: var(--muted);
  font-size: .88rem;
}

.pill {
  display: inline-block;
  padding: 5px 11px;
  border-radius: 999px;
  font-size: .78rem;
  font-weight: 700;
}

.pill-green { background: rgba(0,255,157,.13); color: #00ff9d; border: 1px solid rgba(0,255,157,.28); }
.pill-red { background: rgba(255,77,109,.13); color: #ff4d6d; border: 1px solid rgba(255,77,109,.28); }
.pill-yellow { background: rgba(255,209,102,.13); color: #ffd166; border: 1px solid rgba(255,209,102,.28); }
.pill-gray { background: rgba(139,148,167,.13); color: #b7c0d0; border: 1px solid rgba(139,148,167,.25); }
</style>
""", unsafe_allow_html=True)

# ---------------- SESSION ----------------
if "tg_token" not in st.session_state:
    st.session_state.tg_token = ""
if "tg_chat" not in st.session_state:
    st.session_state.tg_chat = ""

# ---------------- HELPERS ----------------
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

def http_get(url, params=None, timeout=12):
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {"code": "ERROR", "data": []}

def symbol_for(coin, market):
    return f"{coin}-USDT-SWAP" if market == "Фьючерсы (SWAP)" else f"{coin}-USDT"

def inst_type_for(market):
    return "SWAP" if market == "Фьючерсы (SWAP)" else "SPOT"

# ---------------- TELEGRAM ----------------
def send_tg(msg):
    try:
        token = st.secrets.get("telegram", {}).get("token", st.session_state.tg_token)
        chat = st.secrets.get("telegram", {}).get("chat_id", st.session_state.tg_chat)
    except Exception:
        token = st.session_state.tg_token
        chat = st.session_state.tg_chat

    if not token or not chat:
        return False

    try:
        res = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": msg, "parse_mode": "Markdown"},
            timeout=6,
        )
        return res.status_code == 200
    except Exception:
        return False

# ---------------- MARKET DATA ----------------
@st.cache_data(ttl=3600, show_spinner=False)
def check_age(symbol, market):
    payload = http_get(
        INSTRUMENTS_URL,
        {"instType": inst_type_for(market), "instId": symbol},
    )
    rows = payload.get("data", [])
    if not rows:
        return True

    list_time = int(rows[0].get("listTime", 0) or 0)
    if list_time == 0:
        return True

    age_days = (time.time() * 1000 - list_time) / 86_400_000
    return age_days > 180

@st.cache_data(ttl=60, show_spinner=False)
def get_ticker(symbol, market):
    payload = http_get(TICKERS_URL, {"instType": inst_type_for(market), "instId": symbol})
    rows = payload.get("data", [])
    if not rows:
        return None

    row = rows[0]
    price = float(row.get("last", 0) or 0)

    # Spot: volCcy24h is quote volume (USDT).
    # SWAP: volCcy24h is base volume, so multiply by price.
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
    cols = ["t", "o", "h", "l", "c", "v", "v1", "v2", "v3"]
    df = pd.DataFrame(raw, columns=cols)

    for col in ["o", "h", "l", "c", "v"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["t"] = pd.to_numeric(df["t"], errors="coerce")
    df["time"] = pd.to_datetime(df["t"], unit="ms")

    return df.dropna(subset=["o", "h", "l", "c"]).reset_index(drop=True)

# ---------------- INDICATORS ----------------
def compute_indicators(df):
    close = df["c"]
    high = df["h"]
    low = df["l"]

    rsi_series = RSIIndicator(close=close, window=14).rsi()
    adx_series = ADXIndicator(high=high, low=low, close=close, window=14).adx()
    atr_series = AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range()

    df = df.copy()
    df["rsi"] = rsi_series
    df["adx"] = adx_series
    df["atr"] = atr_series
    return df

# ---------------- SCANNER ----------------
def analyze_coin(coin, market):
    symbol = symbol_for(coin, market)
    df = get_data(symbol, "1D", 120)
    ticker = get_ticker(symbol, market)

    if df is None or len(df) < 20 or ticker is None or ticker["price"] <= 0:
        return None

    df = compute_indicators(df)
    last = df.iloc[-1]

    price = float(last["c"])
    rsi = float(last["rsi"]) if pd.notna(last["rsi"]) else 50.0
    adx = float(last["adx"]) if pd.notna(last["adx"]) else 0.0
    atr = float(last["atr"]) if pd.notna(last["atr"]) else 0.0
    atr_pct = atr / price * 100 if price else 0.0

    volume_usd = ticker["volume_usd"]
    low_liquidity = volume_usd < MIN_LIQUIDITY_USD

    if atr_pct < 1.5:
        tp, tp_reason = 1.0, "Спокойный рынок"
    elif atr_pct < 3.0:
        tp, tp_reason = 1.5, "Стандартная волатильность"
    else:
        tp, tp_reason = 2.0, "Высокая волатильность"

    if adx > 25:
        if rsi < 40:
            signal, bot, phase = "🟢 ЛОНГ", "DCA Long", "Тренд"
            reason = f"RSI {rsi:.0f}, ADX {adx:.0f}: импульс вниз завершается"
        elif rsi > 50:
            signal, bot, phase = "⏳ ЖДАТЬ", "Пауза", "Тренд"
            reason = f"RSI {rsi:.0f}, ADX {adx:.0f}: ожидание отката"
        else:
            signal, bot, phase = "🔴 ШОРТ", "DCA Short", "Тренд"
            reason = f"RSI {rsi:.0f}, ADX {adx:.0f}: слабость цены в тренде"
    else:
        signal, bot, phase = "🟡 НЕЙТРАЛЬНО", "Grid", "Флэт"
        reason = f"ADX {adx:.0f}: боковой рынок"

    is_old = check_age(symbol, market)

    if not is_old:
        risk_class, risk_tone = "🔴 Молодая", "red"
    elif coin in ("BTC", "ETH"):
        risk_class, risk_tone = "🟢 Консервативная", "green"
    elif atr_pct > 3:
        risk_class, risk_tone = "🔴 Агрессивная", "red"
    else:
        risk_class, risk_tone = "🟡 Умеренная", "yellow"

    liquidity = "🔴 Низкая" if low_liquidity else "🟢 Высокая"
    liquidity_tone = "red" if low_liquidity else "green"

    return {
        "Монета": coin,
        "Инструмент": symbol,
        "Цена": price,
        "Объём 24ч, $": volume_usd,
        "Ликвидность": liquidity,
        "Ликвидность_tone": liquidity_tone,
        "Фаза": phase,
        "Класс": risk_class,
        "Класс_tone": risk_tone,
        "RSI": rsi,
        "ADX": adx,
        "ATR %": atr_pct,
        "Сигнал": signal,
        "Бот": bot,
        "TP %": tp,
        "TP_Reason": tp_reason,
        "Step %": DEFAULT_STEP,
        "Martingale": DEFAULT_MARTINGALE,
        "SO": DEFAULT_SO,
        "Reason": reason,
    }

def scan_market(market):
    results = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(analyze_coin, coin, market): coin for coin in COINS}
        for future in as_completed(futures):
            try:
                item = future.result()
                if item:
                    results.append(item)
            except Exception:
                pass

    order = {"BTC": 0, "ETH": 1}
    results.sort(key=lambda x: (order.get(x["Монета"], 99), x["Монета"]))
    return results

def scanner_chart(df, title):
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        row_heights=[0.60, 0.20, 0.20],
        vertical_spacing=0.035,
    )

    fig.add_trace(
        go.Candlestick(
            x=df["time"], open=df["o"], high=df["h"],
            low=df["l"], close=df["c"], name="Цена",
            increasing_line_color="#00ff9d",
            decreasing_line_color="#ff4d6d",
            increasing_fillcolor="#00ff9d",
            decreasing_fillcolor="#ff4d6d",
        ),
        row=1, col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=df["time"], y=df["rsi"], name="RSI",
            line=dict(color="#00c2ff", width=2),
        ),
        row=2, col=1,
    )
    fig.add_hline(y=70, line_color="#ff4d6d", line_dash="dot", row=2, col=1)
    fig.add_hline(y=30, line_color="#00ff9d", line_dash="dot", row=2, col=1)

    fig.add_trace(
        go.Scatter(
            x=df["time"], y=df["adx"], name="ADX",
            line=dict(color="#ffd166", width=2),
        ),
        row=3, col=1,
    )
    fig.add_hline(y=25, line_color="#8b94a7", line_dash="dot", row=3, col=1)

    fig.update_layout(
        title=title,
        template="plotly_dark",
        height=700,
        margin=dict(l=10, r=10, t=55, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter"),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", y=1.05, x=0),
    )
    fig.update_yaxes(title_text="Цена", row=1, col=1)
    fig.update_yaxes(title_text="RSI", row=2, col=1, range=[0, 100])
    fig.update_yaxes(title_text="ADX", row=3, col=1)

    st.plotly_chart(fig, use_container_width=True)

# ---------------- BACKTEST ----------------
def backtest_dca(symbol, days, tp_pct, step_pct, so_count, mart, bar="15m"):
    # DCA logic remains unchanged: TP 1.5%, step 2%, 4 safety orders, martingale 1.2 by default.
    bars_needed = min(1440, days * 96)
    df = get_data(symbol, bar, bars_needed)

    if df is None or len(df) < 30:
        return None

    base_amount = 10.0
    position = 0.0
    entry_price = 0.0
    total_invested = 0.0
    cycles = 0
    fees_paid = 0.0
    max_drawdown_usd = 0.0
    max_drawdown_pct = 0.0
    capital = 1000.0
    equity_curve = []

    for i in range(1, len(df)):
        price = float(df["c"].iloc[i])

        if position == 0:
            buy_fee = base_amount * FEE_RATE
            position = (base_amount - buy_fee) / price
            entry_price = price
            total_invested = base_amount
            fees_paid += buy_fee
        else:
            avg_price = total_invested / position

            if price >= avg_price * (1 + tp_pct / 100):
                gross = position * price
                exit_fee = gross * FEE_RATE
                net = gross - exit_fee
                profit = net - total_invested
                capital += profit
                fees_paid += exit_fee
                cycles += 1

                position = 0.0
                entry_price = 0.0
                total_invested = 0.0

            elif (
                price <= entry_price * (1 - step_pct / 100)
                and total_invested < base_amount * so_count
            ):
                add_amount = base_amount * mart
                buy_fee = add_amount * FEE_RATE
                position += (add_amount - buy_fee) / price
                total_invested += add_amount
                entry_price = price
                fees_paid += buy_fee

        if position > 0:
            current_value = position * price
            unrealized = current_value - total_invested
            drawdown_usd = max(0.0, -unrealized)
            drawdown_pct = drawdown_usd / total_invested * 100 if total_invested else 0.0

            if drawdown_usd > max_drawdown_usd:
                max_drawdown_usd = drawdown_usd
            if drawdown_pct > max_drawdown_pct:
                max_drawdown_pct = drawdown_pct

        equity_curve.append(capital + (position * price if position > 0 else 0))

    return {
        "Циклов": cycles,
        "Капитал, USDT": round(capital, 2),
        "Чистая прибыль, USDT": round(capital - 1000, 2),
        "Макс. просадка, USDT": round(max_drawdown_usd, 2),
        "Макс. просадка, %": round(max_drawdown_pct, 2),
        "Комиссии, USDT": round(fees_paid, 2),
        "Equity": equity_curve,
    }

def backtest_grid(symbol, days, grid_count, lower_pct, upper_pct, bar="15m"):
    bars_needed = min(1440, days * 96)
    df = get_data(symbol, bar, bars_needed)

    if df is None or len(df) < 30:
        return None

    start_price = float(df["c"].iloc[0])
    lower_bound = start_price * (1 - lower_pct / 100)
    upper_bound = start_price * (1 + upper_pct / 100)
    step = (upper_bound - lower_bound) / grid_count
    levels = [lower_bound + i * step for i in range(grid_count + 1)]

    capital = 1000.0
    position = 0.0
    buy_price = 0.0
    invested = 0.0
    cycles = 0
    fees_paid = 0.0
    max_drawdown_usd = 0.0
    max_drawdown_pct = 0.0
    equity_curve = []

    for i in range(1, len(df)):
        price = float(df["c"].iloc[i])
        high = float(df["h"].iloc[i])
        low = float(df["l"].iloc[i])

        if lower_bound <= price <= upper_bound:
            for level in levels:
                if low <= level <= high:
                    if position == 0:
                        order_size = 10.0
                        fee = order_size * FEE_RATE
                        position = (order_size - fee) / level
                        buy_price = level
                        invested = order_size
                        fees_paid += fee
                    elif level >= buy_price + step:
                        gross = position * level
                        exit_fee = gross * FEE_RATE
                        net = gross - exit_fee
                        profit = net - invested
                        capital += profit
                        fees_paid += exit_fee
                        cycles += 1

                        position = 0.0
                        buy_price = 0.0
                        invested = 0.0
                        break

        if position > 0:
            current_value = position * price
            unrealized = current_value - invested
            drawdown_usd = max(0.0, -unrealized)
            drawdown_pct = drawdown_usd / invested * 100 if invested else 0.0

            if drawdown_usd > max_drawdown_usd:
                max_drawdown_usd = drawdown_usd
            if drawdown_pct > max_drawdown_pct:
                max_drawdown_pct = drawdown_pct

        equity_curve.append(capital + (position * price if position > 0 else 0))

    return {
        "Циклов": cycles,
        "Капитал, USDT": round(capital, 2),
        "Чистая прибыль, USDT": round(capital - 1000, 2),
        "Макс. просадка, USDT": round(max_drawdown_usd, 2),
        "Макс. просадка, %": round(max_drawdown_pct, 2),
        "Комиссии, USDT": round(fees_paid, 2),
        "Equity": equity_curve,
    }

def backtest_chart(equity, title):
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            y=equity,
            mode="lines",
            name="Капитал",
            line=dict(color="#00ff9d", width=2.5),
            fill="tozeroy",
            fillcolor="rgba(0,255,157,0.08)",
        )
    )
    fig.update_layout(
        title=title,
        template="plotly_dark",
        height=360,
        margin=dict(l=10, r=10, t=50, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter"),
    )
    st.plotly_chart(fig, use_container_width=True)

# ---------------- JOURNAL ----------------
def append_journal(record):
    df_new = pd.DataFrame([record])
    if os.path.exists(JOURNAL_FILE):
        try:
            df_old = pd.read_csv(JOURNAL_FILE)
            df_all = pd.concat([df_old, df_new], ignore_index=True)
        except Exception:
            df_all = df_new
    else:
        df_all = df_new

    df_all.to_csv(JOURNAL_FILE, index=False)

def load_journal():
    if not os.path.exists(JOURNAL_FILE):
        return pd.DataFrame(
            columns=[
                "Дата", "Монета", "Здоровье", "Статус",
                "Совет", "PnL, USDT", "PnL, %", "До ликвидации, %",
            ]
        )
    try:
        return pd.read_csv(JOURNAL_FILE)
    except Exception:
        return pd.DataFrame(
            columns=[
                "Дата", "Монета", "Здоровье", "Статус",
                "Совет", "PnL, USDT", "PnL, %", "До ликвидации, %",
            ]
        )

# ---------------- CHARTS: AI CENTER ----------------
def health_gauge(health, status_color):
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=health,
            number={"font": {"size": 44, "family": "JetBrains Mono"}},
            gauge={
                "axis": {"range": [0, 100], "tickcolor": "#8b94a7"},
                "bar": {"color": status_color, "thickness": 0.28},
                "bgcolor": "rgba(0,0,0,0)",
                "borderwidth": 0,
                "steps": [
                    {"range": [0, 40], "color": "rgba(255,77,109,.18)"},
                    {"range": [40, 70], "color": "rgba(255,209,102,.16)"},
                    {"range": [70, 100], "color": "rgba(0,255,157,.16)"},
                ],
            },
        )
    )
    fig.update_layout(
        height=330,
        margin=dict(t=40, b=10, l=20, r=20),
        paper_bgcolor="rgba(0,0,0,0)",
        font={"family": "Inter", "color": "#e8ecf4"},
    )
    return fig

def pnl_chart(current_price, avg_price, liq_price, invested):
    prices = np.linspace(min(current_price, avg_price, liq_price) * 0.85,
                         max(current_price, avg_price, liq_price) * 1.15, 120)
    pnl = invested * (prices - avg_price) / avg_price

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=prices, y=pnl, mode="lines", name="PnL",
            line=dict(color="#00ff9d", width=3),
        )
    )
    fig.add_hline(y=0, line_color="#8b94a7", line_dash="dot")
    fig.add_vline(x=avg_price, line_color="#00c2ff", line_dash="dash", annotation_text="Средняя вход")
    fig.add_vline(x=current_price, line_color="#ffd166", line_dash="dash", annotation_text="Текущая цена")
    fig.add_vline(x=liq_price, line_color="#ff4d6d", line_dash="dash", annotation_text="Ликвидация")

    fig.update_layout(
        title="Профиль PnL позиции",
        template="plotly_dark",
        height=380,
        margin=dict(l=10, r=10, t=55, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter"),
    )
    return fig

# ---------------- PAGES ----------------
with st.sidebar:
    st.markdown("## ⚡ OKX Terminal")
    st.caption("Профессиональная панель управления ботами")
    page = st.radio(
        "Раздел",
        [
            "1. Главная",
            "2. Сканер",
            "3. ИИ-Центр",
            "4. DCA",
            "5. Grid",
            "6. Журнал решений",
            "7. Настройки",
        ],
        label_visibility="collapsed",
    )

st.title(page.split(". ", 1)[1] if ". " in page else page)

# ---------- HOME ----------
if page == "1. Главная":
    st.markdown('<div class="glass"><div class="section-title">Добро пожаловать</div><div class="section-sub">Терминал для анализа, мониторинга и управления крипто-ботами OKX.</div></div>', unsafe_allow_html=True)
    st.write("")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        metric_card("Статус", "Онлайн", "positive")
    with c2:
        metric_card("Баланс", "0 USDT")
    with c3:
        metric_card("Активные боты", "0")
    with c4:
        metric_card("Риск-профиль", "Низкий", "positive")

    st.write("")
    st.markdown('<div class="glass"><div class="section-title">Быстрый старт</div><div class="section-sub">1. Откройте Сканер и выберите рынок.<br>2. Проверьте сигналы, ликвидность и риск-класс.<br>3. Запустите умный бэктест на 15-минутных свечах.<br>4. Сохраняйте решения в Журнал.</div></div>', unsafe_allow_html=True)

# ---------- SCANNER ----------
elif page == "2. Сканер":
    market = st.radio("Рынок:", ["Фьючерсы (SWAP)", "Спот"], horizontal=True)

    left, right = st.columns([1, 3])
    with left:
        run_scan = st.button("Сканировать ТОП-20", use_container_width=True)

    if run_scan:
        with st.spinner("Загружаю рыночные данные параллельно..."):
            results = scan_market(market)

        if results:
            df = pd.DataFrame(results)
            st.session_state["scan_results"] = df
        else:
            st.error("Не удалось получить данные. Проверьте соединение с OKX API.")

    if "scan_results" in st.session_state:
        df = st.session_state["scan_results"]

        st.write("")
        c1, c2, c3, c4 = st.columns(4)
        longs = df["Сигнал"].str.contains("ЛОНГ").sum()
        shorts = df["Сигнал"].str.contains("ШОРТ").sum()
        low_liq = df["Ликвидность"].str.contains("Низкая").sum()

        with c1:
            metric_card("Лонг-сигналы", str(longs), "positive")
        with c2:
            metric_card("Шорт-сигналы", str(shorts), "negative")
        with c3:
            metric_card("Низкая ликвидность", str(low_liq), "warning" if low_liq else "positive")
        with c4:
            metric_card("Проанализировано", str(len(df)))

        st.write("")
        show_cols = [
            "Монета", "Цена", "Объём 24ч, $", "Ликвидность",
            "RSI", "ADX", "ATR %", "Сигнал", "Бот", "Класс",
        ]

        def color_signal(val):
            if "ЛОНГ" in str(val):
                return "color: #00ff9d; font-weight: 700"
            if "ШОРТ" in str(val):
                return "color: #ff4d6d; font-weight: 700"
            if "НЕЙТРАЛЬНО" in str(val):
                return "color: #ffd166; font-weight: 700"
            return "color: #b7c0d0"

        styled = (
            df[show_cols]
            .style.format({
                "Цена": "{:,.4f}",
                "Объём 24ч, $": "${:,.0f}",
                "RSI": "{:.2f}",
                "ADX": "{:.2f}",
                "ATR %": "{:.2f}%",
            })
            .map(color_signal, subset=["Сигнал"])
        )
        st.dataframe(styled, use_container_width=True, hide_index=True, height=520)

        st.markdown("### График и индикаторы")
        selected = st.selectbox("Монета", df["Монета"].tolist())
        row = df[df["Монета"] == selected].iloc[0]
        chart_df = compute_indicators(get_data(row["Инструмент"], "1D", 180))

        col_a, col_b, col_c = st.columns(3)
        with col_a:
            st.markdown(pill(row["Сигнал"], "green" if "ЛОНГ" in row["Сигнал"] else "red" if "ШОРТ" in row["Сигнал"] else "yellow"), unsafe_allow_html=True)
        with col_b:
            st.markdown(pill(row["Класс"], row["Класс_tone"]), unsafe_allow_html=True)
        with col_c:
            st.markdown(pill(f"Ликвидность: {row['Ликвидность']}", row["Ликвидность_tone"]), unsafe_allow_html=True)

        scanner_chart(chart_df, f"{selected}-USDT — цена, RSI и ADX")

    st.markdown("---")
    st.markdown("### Умный бэктест")

    bt_market = st.radio("Рынок для теста:", ["Фьючерсы (SWAP)", "Спот"], horizontal=True, key="bt_market")
    bt_strat = st.radio("Стратегия:", ["DCA", "Grid"], horizontal=True, key="bt_strat")
    bt_bar = st.selectbox("Таймфрейм:", ["15m", "30m", "1H", "1D"], index=0)

    c1, c2, c3, c4 = st.columns(4)
    if bt_strat == "DCA":
        bt_tp = c1.number_input("Тейк %", value=DEFAULT_TP, step=0.1)
        bt_step = c2.number_input("Шаг %", value=DEFAULT_STEP, step=0.1)
        bt_so = c3.number_input("Кол-во СО", value=DEFAULT_SO, step=1)
        bt_mart = c4.number_input("Мартингейл", value=DEFAULT_MARTINGALE, step=0.1)
    else:
        bt_grids = c1.number_input("Кол-во сеток", value=10, step=1)
        bt_low = c2.number_input("Нижняя граница %", value=10.0, step=1.0)
        bt_up = c3.number_input("Верхняя граница %", value=10.0, step=1.0)
        bt_tp = bt_step = bt_so = bt_mart = None

    if st.button("Бэктест всех монет", use_container_width=True):
        with st.spinner("Симулирую сделки с учётом комиссий..."):
            rows = []
            equity_map = {}

            for coin in COINS:
                symbol = symbol_for(coin, bt_market)

                if bt_strat == "DCA":
                    res = backtest_dca(
                        symbol, 90, bt_tp, bt_step, int(bt_so), bt_mart, bt_bar
                    )
                else:
                    res = backtest_grid(
                        symbol, 90, int(bt_grids), bt_low, bt_up, bt_bar
                    )

                if res:
                    equity_map[coin] = res.pop("Equity")
                    res["Монета"] = coin
                    rows.append(res)

            if rows:
                bt_df = pd.DataFrame(rows)[[
                    "Монета", "Циклов", "Капитал, USDT",
                    "Чистая прибыль, USDT", "Макс. просадка, USDT",
                    "Макс. просадка, %", "Комиссии, USDT",
                ]]
                st.session_state["bt_results"] = bt_df
                st.session_state["bt_equity"] = equity_map
                st.session_state["bt_title"] = f"{bt_strat} · {bt_bar} · 90 дней"
            else:
                st.error("Недостаточно исторических данных для бэктеста.")

    if "bt_results" in st.session_state:
        st.write("")
        st.dataframe(
            st.session_state["bt_results"],
            use_container_width=True,
            hide_index=True,
        )

        selected_bt = st.selectbox(
            "Кривая капитала",
            list(st.session_state["bt_equity"].keys()),
        )
        backtest_chart(
            st.session_state["bt_equity"][selected_bt],
            f"{selected_bt} — {st.session_state['bt_title']}",
        )

# ---------- AI CENTER ----------
elif page == "3. ИИ-Центр":
    st.markdown('<div class="glass"><div class="section-title">🤖 ИИ-советник по позиции</div><div class="section-sub">Оценка здоровья бота, риска ликвидации и PnL.</div></div>', unsafe_allow_html=True)
    st.write("")

    c1, c2, c3 = st.columns(3)
    coin = c1.text_input("Монета", value="BTC").upper()
    invested = c2.number_input("Вложено, USDT", value=131.39, min_value=0.0)
    current_price = c3.number_input("Текущая цена", value=76741.8, min_value=0.0)

    c4, c5 = st.columns(2)
    avg_price = c4.number_input("Средняя цена входа", value=77908.0, min_value=0.0)
    liq_price = c5.number_input("Цена ликвидации", value=58063.0, min_value=0.0)

    if st.button("Анализировать бота", use_container_width=True):
        if avg_price <= 0 or current_price <= 0:
            st.error("Цена входа и текущая цена должны быть больше нуля.")
        else:
            pnl_pct = (current_price - avg_price) / avg_price * 100
            pnl_usd = invested * pnl_pct / 100

            distance_to_liq = (
                (current_price - liq_price) / current_price * 100
                if current_price > 0 else 100
            )

            health = 100.0
            if pnl_pct < 0:
                health -= min(45, abs(pnl_pct) * 2.5)
            if current_price < avg_price:
                health -= 8
            if distance_to_liq < 20:
                health -= 30
            elif distance_to_liq < 35:
                health -= 12

            health = max(0.0, min(100.0, health))

            if health > 70:
                status = "🟢 Работает по плану"
                advice = "Сохраняйте позицию. Риск контролируемый, ликвидация достаточно далеко."
                tone = "positive"
                status_color = "#00ff9d"
            elif health > 40:
                status = "🟡 Требует внимания"
                advice = "Наблюдайте позицию. При дальнейшем движении против вас уменьшите риск или добавьте маржу."
                tone = "warning"
                status_color = "#ffd166"
            else:
                status = "🔴 Высокий риск"
                advice = "Срочно снизьте риск: добавьте маржу, сократите позицию или закройте её частично."
                tone = "negative"
                status_color = "#ff4d6d"

            record = {
                "Дата": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "Монета": coin,
                "Здоровье": round(health, 1),
                "Статус": status,
                "Совет": advice,
                "PnL, USDT": round(pnl_usd, 2),
                "PnL, %": round(pnl_pct, 2),
                "До ликвидации, %": round(distance_to_liq, 2),
            }
            append_journal(record)

            st.write("")
            c1, c2 = st.columns([1, 2])

            with c1:
                st.plotly_chart(health_gauge(health, status_color), use_container_width=True)

            with c2:
                metric_card("Здоровье", f"{health:.0f}/100", tone)
                metric_card("PnL", f"{pnl_usd:,.2f} USDT", "positive" if pnl_usd >= 0 else "negative")
                metric_card("До ликвидации", f"{distance_to_liq:.2f}%", "warning" if distance_to_liq < 35 else "positive")

            st.markdown(f"**Статус:** {status}")
            st.markdown(f"**Совет:** {advice}")
            st.plotly_chart(
                pnl_chart(current_price, avg_price, liq_price, invested),
                use_container_width=True,
            )

            if st.button("Отправить отчёт в Telegram", use_container_width=True):
                msg = (
                    f"*OKX Terminal*\n"
                    f"Монета: {coin}\n"
                    f"Здоровье: {health:.0f}/100\n"
                    f"PnL: {pnl_usd:.2f} USDT ({pnl_pct:.2f}%)\n"
                    f"До ликвидации: {distance_to_liq:.2f}%\n"
                    f"Статус: {status}"
                )
                if send_tg(msg):
                    st.success("Отчёт отправлен в Telegram.")
                else:
                    st.error("Не удалось отправить сообщение. Проверьте Telegram-настройки.")

# ---------- DCA ----------
elif page == "4. DCA":
    st.markdown('<div class="glass"><div class="section-title">Калькулятор DCA</div><div class="section-sub">Базовая логика сохранена: TP 1.5%, шаг 2%, 4 safety orders, мартингейл 1.2.</div></div>', unsafe_allow_html=True)
    st.write("")

    c1, c2, c3, c4 = st.columns(4)
    entry = c1.number_input("Цена входа", value=100.0, min_value=0.0)
    count = c2.number_input("Кол-во СО", value=DEFAULT_SO, min_value=1, step=1)
    step = c3.number_input("Шаг %", value=DEFAULT_STEP, step=0.1)
    mart = c4.number_input("Мартингейл", value=DEFAULT_MARTINGALE, step=0.1)

    if st.button("Рассчитать сетку DCA", use_container_width=True):
        rows, total = [], 0.0

        for i in range(int(count)):
            price = entry * (1 - step / 100 * i)
            amount = 10.0 * (mart ** i)
            total += amount
            rows.append({
                "Шаг": i + 1,
                "Цена": price,
                "Сумма, USDT": amount,
                "Накоплено, USDT": total,
            })

        df = pd.DataFrame(rows)
        st.dataframe(df.style.format({
            "Цена": "{:,.4f}",
            "Сумма, USDT": "{:,.2f}",
            "Накоплено, USDT": "{:,.2f}",
        }), use_container_width=True, hide_index=True)

        c1, c2 = st.columns(2)
        with c1:
            metric_card("Общий объём", f"{total:,.2f} USDT")
        with c2:
            weighted = (df["Цена"] * df["Сумма, USDT"]).sum() / total
            metric_card("Средняя цена", f"{weighted:,.4f}")

# ---------- GRID ----------
elif page == "5. Grid":
    st.markdown('<div class="glass"><div class="section-title">Калькулятор Grid</div><div class="section-sub">Оценка ширины коридора и шага между уровнями.</div></div>', unsafe_allow_html=True)
    st.write("")

    c1, c2, c3 = st.columns(3)
    low = c1.number_input("Нижняя граница", value=90.0, min_value=0.0)
    high = c2.number_input("Верхняя граница", value=110.0, min_value=0.0)
    grids = c3.number_input("Кол-во сеток", value=10, min_value=2, step=1)

    if st.button("Рассчитать", use_container_width=True):
        if high <= low:
            st.error("Верхняя граница должна быть выше нижней.")
        else:
            width = (high - low) / low * 100
            grid_step = (high - low) / (grids - 1) / low * 100

            c1, c2 = st.columns(2)
            with c1:
                metric_card("Ширина коридора", f"{width:.2f}%")
            with c2:
                metric_card("Шаг сетки", f"{grid_step:.2f}%")

            fig = go.Figure()
            levels = np.linspace(low, high, int(grids))
            fig.add_trace(go.Scatter(
                x=list(range(len(levels))), y=levels,
                mode="lines+markers", name="Уровни",
                line=dict(color="#00ff9d", width=2),
                marker=dict(size=8),
            ))
            fig.update_layout(
                title="Уровни Grid",
                template="plotly_dark",
                height=420,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(family="Inter"),
            )
            st.plotly_chart(fig, use_container_width=True)

# ---------- JOURNAL ----------
elif page == "6. Журнал решений":
    st.markdown('<div class="glass"><div class="section-title">📚 Журнал решений</div><div class="section-sub">Каждый анализ из ИИ-Центра автоматически сохраняется в journal.csv.</div></div>', unsafe_allow_html=True)
    st.write("")

    journal = load_journal()

    if journal.empty:
        st.info("Журнал пока пуст. Сделайте анализ в разделе «ИИ-Центр».")
    else:
        c1, c2, c3 = st.columns(3)
        with c1:
            metric_card("Записей", str(len(journal)))
        with c2:
            avg_health = journal["Здоровье"].astype(float).mean()
            metric_card("Среднее здоровье", f"{avg_health:.0f}/100")
        with c3:
            total_pnl = pd.to_numeric(journal["PnL, USDT"], errors="coerce").sum()
            metric_card(
                "Суммарный PnL",
                f"{total_pnl:,.2f} USDT",
                "positive" if total_pnl >= 0 else "negative",
            )

        st.write("")
        st.dataframe(journal, use_container_width=True, hide_index=True, height=500)

        csv = journal.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Скачать журнал CSV",
            data=csv,
            file_name="journal.csv",
            mime="text/csv",
            use_container_width=True,
        )

# ---------- SETTINGS ----------
elif page == "7. Настройки":
    st.markdown('<div class="glass"><div class="section-title">⚙️ Telegram</div><div class="section-sub">Токен и Chat ID можно хранить в Streamlit Secrets или ввести локально.</div></div>', unsafe_allow_html=True)
    st.write("")

    secrets_ok = False
    try:
        token = st.secrets["telegram"]["token"]
        chat_id = st.secrets["telegram"]["chat_id"]
        secrets_ok = True
        st.success("Telegram-настройки найдены в Secrets.")
        st.code(f"Chat ID: {chat_id}")
    except Exception:
        st.warning("Secrets не настроены. Введите данные ниже — они будут храниться только в текущей сессии.")
        st.session_state.tg_token = st.text_input("Bot Token", value=st.session_state.tg_token, type="password")
        st.session_state.tg_chat = st.text_input("Chat ID", value=st.session_state.tg_chat)

    if st.button("Тест Telegram", use_container_width=True):
        if send_tg("Привет! OKX Terminal Pro подключён ✅"):
            st.success("Тестовое сообщение отправлено.")
        else:
            st.error("Ошибка отправки. Проверьте токен, Chat ID и доступ бота.")
