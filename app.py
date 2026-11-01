import streamlit as st
import pandas as pd
import requests
import time
from ta.momentum import RSIIndicator
from ta.trend import ADXIndicator
from ta.volatility import AverageTrueRange

# --- НАСТРОЙКА И ДИЗАЙН ---
st.set_page_config(page_title="OKX Bot Manager", page_icon="📈", layout="wide")

st.markdown("""
<style>
.stApp { background-color: #050505; color: #ffffff; }
[data-testid="stSidebar"] { background-color: #0b0b0b; border-right: 1px solid #252525; }
h1, h2, h3, p, label, span { color: #ffffff; }
.metric-card {
    background-color: #111111; border: 1px solid #333333; border-radius: 14px;
    padding: 18px 20px; min-height: 120px;
}
.metric-label { color: #a9a9a9; font-size: 0.9rem; }
.metric-value { color: #ffffff; font-size: 1.65rem; font-weight: 700; margin-top: 8px; }
.stButton > button {
    background: linear-gradient(135deg, #00ff87, #60efff);
    color: #000000; border: 0; border-radius: 10px; font-weight: 700;
}
.stButton > button:hover { background: #00cc6a; color: #000000; }
div[data-testid="stDataFrame"] { border: 1px solid #333333; border-radius: 10px; }
</style>
""", unsafe_allow_html=True)

# --- ПАМЯТЬ ---
if "tg_token" not in st.session_state: st.session_state.tg_token = ""
if "tg_chat" not in st.session_state: st.session_state.tg_chat = ""

COINS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT"]
URL = "https://www.okx.com/api/v5/market/candles"
URL_INFO = "https://www.okx.com/api/v5/public/instruments"
HEADERS = {"User-Agent": "Mozilla/5.0"}

def metric_card(label, value):
    st.markdown(f'<div class="metric-card"><div class="metric-label">{label}</div><div class="metric-value">{value}</div></div>', unsafe_allow_html=True)

# --- TELEGRAM ---
def send_tg(msg):
    token = st.secrets.get("telegram", {}).get("token", st.session_state.tg_token)
    chat = st.secrets.get("telegram", {}).get("chat_id", st.session_state.tg_chat)
    
    if token and chat:
        try:
            # Склеиваем строку через + чтобы избежать обрывов
            base_url = "https://api.telegram.org/bot"
            full_url = base_url + token + "/sendMessage"
            
            res = requests.post(full_url, json={"chat_id": chat, "text": msg, "parse_mode": "Markdown"}, timeout=5)
            if res.status_code == 200: 
                return True
            else: 
                st.error(f"Ошибка ТГ: {res.text}")
                return False
        except Exception as e: 
            st.error(f"Ошибка: {e}")
            return False
    return False

# --- ПРОВЕРКА ВОЗРАСТА ---
@st.cache_data(ttl=3600)
def check_coin_age(symbol, market_type):
    try:
        inst_type = "SWAP" if market_type == "Фьючерсы (SWAP)" else "SPOT"
        params = {"instType": inst_type}
        response = requests.get(URL_INFO, params=params, headers=HEADERS, timeout=10)
        data = response.json().get("data", [])
        
        for item in data:
            if item["instId"] == symbol:
                list_time = int(item.get("listTime", 0))
                if list_time == 0: return True
                
                days_old = (time.time() * 1000 - list_time) / (1000 * 60 * 60 * 24)
                return days_old > 180
        return True
    except:
        return True

# --- СКАНЕР ---
def fetch_market_data(symbol):
    params = {"instId": symbol, "bar": "1D", "limit": "30"}
    response = requests.get(URL, params=params, headers=HEADERS, timeout=15)
    payload = response.json()
    if payload.get("code") != "0" or not payload.get("data"): raise ValueError("OKX error")
    raw = list(reversed(payload["data"]))
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume", "volume_ccy", "volume_quote", "confirm"])
    for col in ["open", "high", "low", "close", "volume"]: df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["high", "low", "close"]).reset_index(drop=True)

def analyze(coin, symbol, market_type):
    is_old = check_coin_age(symbol, market_type)
    
    df = fetch_market_data(symbol)
    close, high, low = df["close"], df["high"], df["low"]
    rsi = float(RSIIndicator(close=close, window=14).rsi().iloc[-1])
    adx = float(ADXIndicator(high=high, low=low, close=close, window=14).adx().iloc[-1])
    atr = float(AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range().iloc[-1])
    price = float(close.iloc[-1])
    atr_pct = (atr / price * 100) if price else 0.0
    
    tp_reason = ""
    if atr_pct < 1.5:
        tp = 1.0
        tp_reason = "спокойный рынок"
    elif atr_pct < 3.0:
        tp = 1.5
        tp_reason = "стандарт"
    else:
        tp = 2.0
        tp_reason = "высокая волатильность"
        
    step = 2.0
    mart = 1.2
    so_count = 4

    reason = ""
    if adx > 25:
        if rsi < 40:
            signal, phase, bot = "🟢 ЛОНГ", "Тренд", "DCA Long"
            reason = f"RSI={rsi:.0f} (перепродан) + ADX={adx:.0f} (тренд вверх)"
        elif rsi > 50:
            signal, phase, bot = "⏳ ЖДАТЬ", "Тренд", "Пауза"
            reason = "Цена высокая, ждем отката"
        else:
            signal, phase, bot = "🔴 ШОРТ", "Тренд", "DCA Short"
            reason = f"RSI={rsi:.0f} (перекуплен) + ADX={adx:.0f} (тренд вниз)"
    else:
        signal, phase, bot = "🟡 СЕТКА", "Флэт", "Grid"
        reason = f"ADX={adx:.0f} (нет тренда, боковик)"

    if not is_old:
        classification = "🔴 Молодая (риск)"
    elif coin in ("BTC", "ETH"): 
        classification = "🟢 Консерв."
    elif atr_pct > 3: 
        classification = "🔴 Агрессив."
    else: 
        classification = "🟡 Умерен."
    
    return {
        "Монета": coin, "Цена": price, "Фаза": phase, "Класс": classification, 
        "RSI": rsi, "ADX": adx, "Сигнал": signal, "Бот": bot,
        "TP": tp, "TP_Reason": tp_reason, "Step": step, "Mart": mart, "SO": so_count, "Reason": reason
    }

def signal_style(value):
    if "ЛОНГ" in str(value): return "color: #00ff87; font-weight: bold"
    if "ШОРТ" in str(value): return "color: #ff4d4f; font-weight: bold"
    if "СЕТКА" in str(value): return "color: #ffd700; font-weight: bold"
    return "color: #bbbbbb"

# --- МЕНЮ ---
with st.sidebar:
    st.title("📈 OKX Manager")
    page = st.radio("Раздел", ["Главная", "Сканер", "DCA", "Grid", "Позиция", "Настройки"])

st.title(page)

# --- 1. ГЛАВНАЯ ---
if page == "Главная":
    st.subheader("Добрый день, брат! 👋")
    cols = st.columns(4)
    values = [("Статус", "Онлайн"), ("Баланс", "0 USDT"), ("Боты", "0"), ("Риск", "Низкий")]
    for col, (label, value) in zip(cols, values):
        with col: metric_card(label, value)

# --- 2. СКАНЕР ---
elif page == "Сканер":
    market = st.radio("Рынок:", ["Фьючерсы (SWAP)", "Спот"], horizontal=True)
    
    if st.button("🚀 Сканировать ТОП-10", use_container_width=True):
        res = []
        bar = st.progress(0)
        for i, coin in enumerate(COINS):
            sym = f"{coin}-USDT-SWAP" if market == "Фьючерсы (SWAP)" else f"{coin}-USDT"
            try:
                data = analyze(coin, sym, market)
                if data: res.append(data)
            except: pass
            bar.progress((i+1)/len(COINS))
        
        if res:
            df = pd.DataFrame(res)
            display_df = df[["Монета", "Цена", "RSI", "ADX", "Сигнал", "Класс"]]
            styled = display_df.style.format({"Цена": "{:.6f}", "RSI": "{:.2f}", "ADX": "{:.2f}"}).map(signal_style, subset=["Сигнал"])
            st.dataframe(styled, use_container_width=True, hide_index=True)
            
            market_name = "ФЬЮЧЕРСЫ" if market == "Фьючерсы (SWAP)" else "СПОТ"
            msg = f"📊 **Сигналы ({market_name}):**\n\n"
            has_sig = False
            
            for row in res:
                if "ЛОНГ" in row["Сигнал"] or "ШОРТ" in row["Сигнал"]:
                    msg += f"**{row['Монета']}** | {row['Сигнал']} ({row['Класс']})\n"
                    msg += f"Тейк: {row['TP']}% ({row['TP_Reason']})\n"
                    msg += f"Шаг: {row['Step']}% | СО: {row['SO']} шт\n"
                    msg += f"Мартингейл: {row['Mart']}\n"
                    msg += f"💡 Почему: {row['Reason']}\n\n"
                    has_sig = True
            
            if has_sig:
                if send_tg(msg): st.success("✉️ Отправлено в ТГ с объяснением!")
            else:
                st.info("Нет сильных сигналов.")

# --- 3. DCA ---
elif page == "DCA":
    entry = st.number_input("Цена входа", value=100.0)
    count = st.number_input("Кол-во СО", value=4)
    step = st.number_input("Шаг %", value=2.0)
    if st.button("Рассчитать", use_container_width=True):
        rows, total = [], 0
        for i in range(int(count)):
            p = entry * (1 - step / 100 * i)
            a = 10.0 * (1.2 ** i)
            total += a
            rows.append({"Шаг": i + 1, "Цена": p, "Сумма": a})
        st.dataframe(pd.DataFrame(rows), use_container_width=True)
        st.success(f"Всего: {total:.2f} USDT")

# --- 4. GRID ---
elif page == "Grid":
    low = st.number_input("Нижняя", value=90.0)
    high = st.number_input("Верхняя", value=110.0)
    grids = st.number_input("Сеток", value=10)
    if st.button("Рассчитать", use_container_width=True):
        w = (high - low) / low * 100
        s = (high - low) / (grids - 1) / low * 100
        st.metric("Ширина", f"{w:.2f}%")
        st.metric("Шаг", f"{s:.2f}%")

# --- 5. ПОЗИЦИЯ ---
elif page == "Позиция":
    cur = st.number_input("Текущая цена", value=100.0)
    avg = st.number_input("Средняя цена", value=100.0)
    size = st.number_input("Размер", value=100.0)
    if st.button("Разобрать", use_container_width=True):
        pnl = (cur - avg) / avg * size
        st.metric("PnL", f"{pnl:.2f} USDT")
        if send_tg(f"🔔 PnL: {pnl:.2f} USDT"): st.info("Уведомление в ТГ.")

# --- 6. НАСТРОЙКИ ---
elif page == "Настройки":
    st.subheader("Настройки Telegram")
    try:
        st.success("✅ Настройки найдены в Secrets (работают навсегда)")
        st.code(f"Chat ID: {st.secrets['telegram']['chat_id']}")
    except:
        st.warning("⚠️ Secrets не настроены. Введите вручную:")
        st.session_state.tg_token = st.text_input("Bot Token", value=st.session_state.tg_token)
        st.session_state.tg_chat = st.text_input("Chat ID", value=st.session_state.tg_chat)
    
    if st.button("Тест Telegram", use_container_width=True):
        if send_tg("Привет, брат! Это тест."): st.success("✅ Отправлено!")
        else: st.error("❌ Ошибка.")
