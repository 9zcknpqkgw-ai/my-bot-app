import streamlit as st
import pandas as pd
import requests
import time
from ta.momentum import RSIIndicator
from ta.trend import ADXIndicator
from ta.volatility import AverageTrueRange

# --- НАСТРОЙКА ---
st.set_page_config(page_title="OKX Bot Manager", page_icon="📈", layout="wide")

st.markdown("""
<style>
.stApp { background: #050505; color: #ffffff; }
[data-testid="stSidebar"] { background: #0b0b0b; border-right: 1px solid #252525; }
.metric-card { background: #111111; border: 1px solid #333; border-radius: 10px; padding: 15px; }
.stButton>button { background: #fff; color: #000; font-weight: bold; border-radius: 5px; }
</style>
""", unsafe_allow_html=True)

if "last_signals" not in st.session_state: st.session_state.last_signals = {}

COINS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT"]
OKX_URL = "https://www.okx.com/api/v5/market/candles"
HEADERS = {"User-Agent": "Mozilla/5.0"}

# --- ЧТЕНИЕ ТОКЕНА ИЗ SECRETS ---
def get_tg_data():
    try:
        return st.secrets["telegram"]["token"], st.secrets["telegram"]["chat_id"]
    except:
        return "", ""

def send_tg(msg):
    token, chat = get_tg_data()
    if token and chat:
        try:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat, "text": msg})
            return True
        except: return False
    return False

# --- ФУНКЦИИ СКАНЕРА ---
def fetch_market_data(symbol):
    params = {"instId": symbol, "bar": "1D", "limit": "30"}
    response = requests.get(OKX_URL, params=params, headers=HEADERS, timeout=15)
    payload = response.json()
    if payload.get("code") != "0" or not payload.get("data"): raise ValueError("OKX error")
    raw = list(reversed(payload["data"]))
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume", "volume_ccy", "volume_quote", "confirm"])
    for col in ["open", "high", "low", "close", "volume"]: df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["high", "low", "close"]).reset_index(drop=True)

def analyze(coin, symbol):
    df = fetch_market_data(symbol)
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

# --- МЕНЮ ---
with st.sidebar:
    st.title("📈 OKX Manager")
    page = st.radio("Раздел", ["Главная", "Сканер рынка", "План DCA", "План Grid", "Позиция", "Настройки"])

st.title(page)

# --- 1. ГЛАВНАЯ ---
if page == "Главная":
    st.subheader("Добрый день, брат! 👋")
    c1, c2, c3 = st.columns(3)
    c1.metric("Статус", "Онлайн")
    c2.metric("Баланс", "0 USDT")
    c3.metric("Риск", "Низкий")

# --- 2. СКАНЕР (С ВЫБОРОМ РЫНКА) ---
elif page == "Сканер рынка":
    market = st.radio("Рынок:", ["Фьючерсы (SWAP)", "Спот"], horizontal=True)
    
    if st.button("🚀 Сканировать ТОП-10"):
        res = []
        bar = st.progress(0)
        for i, coin in enumerate(COINS):
            sym = f"{coin}-USDT-SWAP" if market == "Фьючерсы (SWAP)" else f"{coin}-USDT"
            data = analyze(coin, sym)
            if data: res.append(data)
            bar.progress((i+1)/len(COINS))
        
        if res:
            st.dataframe(pd.DataFrame(res), use_container_width=True)
            token, chat = get_tg_data()
            if token and chat:
                msg = "📊 Сигналы:\n\n"
                has_new = False
                for row in res:
                    if "ЛОНГ" in row["Сигнал"] or "ШОРТ" in row["Сигнал"]:
                        msg += f"{row['Монета']}: {row['Сигнал']}\n"
                        has_new = True
                if has_new: send_tg(msg); st.success("✉️ Сигналы в ТГ!")
        else: st.error("Ошибка.")

# --- 3. DCA ---
elif page == "План DCA":
    entry = st.number_input("Цена входа", value=100.0)
    count = st.number_input("Кол-во СО", value=5)
    step = st.number_input("Шаг %", value=2.0)
    if st.button("Рассчитать"):
        rows, total = [], 0
        for i in range(int(count)):
            p = entry * (1 - step/100 * i)
            a = 10.0 * (1.2 ** i)
            total += a
            rows.append({"Шаг": i+1, "Цена": p, "Сумма": a})
        st.dataframe(pd.DataFrame(rows))
        st.success(f"Всего: {total:.2f} USDT")

# --- 4. GRID ---
elif page == "План Grid":
    low = st.number_input("Нижняя", value=90.0)
    high = st.number_input("Верхняя", value=110.0)
    grids = st.number_input("Сеток", value=10)
    if st.button("Рассчитать"):
        w = (high - low) / low * 100
        s = (high - low) / (grids - 1) / low * 100
        st.metric("Ширина", f"{w:.2f}%")
        st.metric("Шаг", f"{s:.2f}%")

# --- 5. ПОЗИЦИЯ ---
elif page == "Позиция":
    cur = st.number_input("Текущая цена", value=100.0)
    avg = st.number_input("Средняя цена", value=100.0)
    size = st.number_input("Размер", value=100.0)
    if st.button("Разобрать"):
        pnl = (cur - avg) / avg * size
        st.metric("PnL", f"{pnl:.2f} USDT")
        if send_tg(f"🔔 PnL: {pnl:.2f} USDT"): st.info("Уведомление в ТГ.")

# --- 6. НАСТРОЙКИ (ТОЛЬКО ПРОВЕРКА) ---
elif page == "Настройки":
    st.subheader("Настройки")
    st.info("Telegram настраивается через Secrets на сайте Streamlit Cloud.")
    if st.button("Тест Telegram"):
        if send_tg("Привет, брат! Это тест."): st.success("✅ Отправлено!")
        else: st.error("❌ Ошибка. Проверьте Secrets.")
