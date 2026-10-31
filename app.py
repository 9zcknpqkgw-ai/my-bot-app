import streamlit as st
import pandas as pd
import requests
from ta.momentum import RSIIndicator
from ta.trend import ADXIndicator
from ta.volatility import AverageTrueRange

# -------------------- Настройка страницы --------------------
st.set_page_config(page_title="OKX Bot Manager", page_icon="📈", layout="wide")

st.markdown("""
<style>
.stApp { background: #050505; color: #ffffff; }
[data-testid="stSidebar"] { background: #0b0b0b; border-right: 1px solid #252525; }
h1, h2, h3, p, label, span { color: #ffffff; }
.metric-card {
    background: #111111; border: 1px solid #333333; border-radius: 14px;
    padding: 18px 20px; min-height: 120px;
}
.metric-label { color: #a9a9a9; font-size: 0.9rem; }
.metric-value { color: #ffffff; font-size: 1.65rem; font-weight: 700; margin-top: 8px; }
.stButton > button {
    background: linear-gradient(135deg, #ffffff, #d8d8d8);
    color: #000000; border: 0; border-radius: 10px; font-weight: 700;
}
.stButton > button:hover { background: #eeeeee; color: #000000; }
div[data-testid="stDataFrame"] { border: 1px solid #333333; border-radius: 10px; }
</style>
""", unsafe_allow_html=True)

if "tg_token" not in st.session_state: st.session_state.tg_token = ""
if "tg_chat" not in st.session_state: st.session_state.tg_chat = ""

COINS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT"]
OKX_URL = "https://www.okx.com/api/v5/market/candles"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36", "Accept": "application/json"}

def metric_card(label, value):
    st.markdown(f'<div class="metric-card"><div class="metric-label">{label}</div><div class="metric-value">{value}</div></div>', unsafe_allow_html=True)

def send_tg(msg):
    token = st.session_state.tg_token
    chat = st.session_state.tg_chat
    if token and chat:
        try:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat, "text": msg})
            return True
        except: return False
    return False

def fetch_market_data(coin):
    params = {"instId": f"{coin}-USDT-SWAP", "bar": "1D", "limit": "30"}
    response = requests.get(OKX_URL, params=params, headers=HEADERS, timeout=15)
    payload = response.json()
    if payload.get("code") != "0" or not payload.get("data"): raise ValueError("OKX error")
    raw = list(reversed(payload["data"]))
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume", "volume_ccy", "volume_quote", "confirm"])
    for col in ["open", "high", "low", "close", "volume"]: df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["high", "low", "close"]).reset_index(drop=True)

def analyze_coin(coin):
    df = fetch_market_data(coin)
    close, high, low = df["close"], df["high"], df["low"]
    rsi = float(RSIIndicator(close=close, window=14).rsi().iloc[-1])
    adx = float(ADXIndicator(high=high, low=low, close=close, window=14).adx().iloc[-1])
    atr = float(AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range().iloc[-1])
    price = float(close.iloc[-1])
    atr_pct = (atr / price * 100) if price else 0.0
    if adx > 25:
        if rsi < 40: signal, phase, bot = "🟢 ЛОНГ", "Тренд", "DCA Long"
        elif rsi > 50: signal, phase, bot = "⏳ ЖДАТЬ", "Тренд", "Пауза"
        else: signal, phase, bot = "🔴 ШОРТ", "Тренд", "DCA Short"
    else: signal, phase, bot = "🟡 СЕТКА", "Флэт", "Grid"
    if coin in ("BTC", "ETH"): classification = "Консерв."
    elif atr_pct > 3: classification = "Агрессив."
    else: classification = "Умерен."
    return {"Монета": coin, "Цена": price, "Фаза": phase, "Класс": classification, "RSI": rsi, "ADX": adx, "Сигнал": signal, "Бот": bot}

def signal_style(value):
    if "ЛОНГ" in str(value): return "color: #00d084; font-weight: bold"
    if "ШОРТ" in str(value): return "color: #ff4d4f; font-weight: bold"
    if "СЕТКА" in str(value): return "color: #f5c542; font-weight: bold"
    return "color: #bbbbbb"

with st.sidebar:
    st.title("📈 OKX Manager")
    page = st.radio("Раздел", ["Главная", "Сканер рынка", "План DCA", "План Grid", "Позиция (Разбор)", "Настройки"])

st.title(page)

if page == "Главная":
    st.subheader("Добрый день, брат! 👋")
    cols = st.columns(4)
    values = [("Статус", "Онлайн"), ("Баланс", "0 USDT"), ("Боты", "0"), ("Риск", "Низкий")]
    for col, (label, value) in zip(cols, values):
        with col: metric_card(label, value)
    if st.session_state.tg_token and st.session_state.tg_chat: st.success("✅ Telegram подключен!")
    else: st.warning("⚠️ Telegram не настроен.")

elif page == "Сканер рынка":
    if st.button("Сканировать ТОП-10", use_container_width=True):
        results, errors = [], []
        progress = st.progress(0)
        for index, coin in enumerate(COINS, start=1):
            try: results.append(analyze_coin(coin))
            except Exception as exc: errors.append(f"{coin}: {exc}")
            progress.progress(index / len(COINS))
        if results:
            df = pd.DataFrame(results)
            styled = df.style.format({"Цена": "{:.6f}", "RSI": "{:.2f}", "ADX": "{:.2f}"}).map(signal_style, subset=["Сигнал"])
            st.dataframe(styled, use_container_width=True, hide_index=True)
            if st.session_state.tg_token and st.session_state.tg_chat:
                msg = "📊 Сигналы:\n\n"
                for row in results:
                    if "ЛОНГ" in row["Сигнал"] or "ШОРТ" in row["Сигнал"]: msg += f"{row['Монета']}: {row['Сигнал']}\n"
                if send_tg(msg): st.success("✉️ Сигналы в Telegram!")
        else: st.error("Не удалось получить данные.")
        if errors:
            with st.expander(f"Ошибки ({len(errors)})"):
                for error in errors: st.warning(error)

elif page == "План DCA":
    c1, c2, c3 = st.columns(3)
    entry = c1.number_input("Цена входа", min_value=0.000001, value=100.0, format="%.6f")
    orders = c2.number_input("Кол-во СО", min_value=1, max_value=100, value=5, step=1)
    step_pct = c3.number_input("Шаг %", min_value=0.01, value=2.0, step=0.1)
    base_amount = st.number_input("Сумма первой покупки (USDT)", min_value=0.01, value=10.0, step=1.0)
    if st.button("Рассчитать", use_container_width=True):
        rows = []
        total = 0.0
        for i in range(int(orders)):
            price = entry * (1 - (step_pct / 100) * i)
            amount = base_amount * (1.2 ** i)
            total += amount
            rows.append({"№": i + 1, "Цена покупки": max(price, 0), "Сумма (USDT)": amount, "Коэффициент": 1.2 ** i})
        dca_df = pd.DataFrame(rows)
        st.dataframe(dca_df.style.format({"Цена покупки": "{:.6f}", "Сумма (USDT)": "{:.2f}", "Коэффициент": "{:.2f}"}), use_container_width=True, hide_index=True)
        st.success(f"Общая сумма всех покупок: **{total:.2f} USDT**")

elif page == "План Grid":
    c1, c2, c3 = st.columns(3)
    lower = c1.number_input("Нижняя граница", min_value=0.000001, value=90.0, format="%.6f")
    upper = c2.number_input("Верхняя граница", min_value=0.000001, value=110.0, format="%.6f")
    grid_count = c3.number_input("Кол-во сеток", min_value=2, max_value=500, value=10, step=1)
    if st.button("Рассчитать", use_container_width=True):
        if upper <= lower: st.error("Верхняя граница должна быть больше нижней.")
        else:
            corridor_pct = (upper - lower) / lower * 100
            step_pct = ((upper - lower) / (int(grid_count) - 1)) / lower * 100
            st.metric("Ширина коридора", f"{corridor_pct:.2f}%")
            st.metric("Шаг сетки", f"{step_pct:.2f}%")

elif page == "Позиция (Разбор)":
    c1, c2, c3 = st.columns(3)
    current = c1.number_input("Текущая цена", min_value=0.000001, value=100.0, format="%.6f")
    average = c2.number_input("Средняя цена", min_value=0.000001, value=100.0, format="%.6f")
    size = c3.number_input("Размер позиции (USDT)", min_value=0.0, value=100.0, step=1.0)
    direction = st.radio("Направление", ["Лонг", "Шорт"], horizontal=True)
    if st.button("Разобрать", use_container_width=True):
        move_pct = (current - average) / average
        pnl = size * move_pct * (1 if direction == "Лонг" else -1)
        st.metric("PnL", f"{pnl:+.2f} USDT")
        if st.session_state.tg_token and st.session_state.tg_chat: send_tg(f"🔔 PnL: {pnl:.2f} USDT")

elif page == "Настройки":
    st.subheader("Подключение OKX")
    st.text_input("API Key", type="password")
    st.text_input("Secret Key", type="password")
    st.text_input("Passphrase", type="password")
    st.button("Проверить OKX")
    
    st.markdown("### 📱 Telegram")
    st.session_state.tg_token = st.text_input("Bot Token", value=st.session_state.tg_token)
    st.session_state.tg_chat = st.text_input("Chat ID", value=st.session_state.tg_chat)
    if st.button("Тест Telegram"):
        if send_tg("Привет, брат! Это тест."): st.success("✅ Отправлено!")
        else: st.error("❌ Ошибка.")
