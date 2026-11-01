import streamlit as st
import pandas as pd
import requests
import time
from ta.momentum import RSIIndicator
from ta.trend import ADXIndicator
from ta.volatility import AverageTrueRange

# --- НАСТРОЙКА И ДИЗАЙН ---
st.set_page_config(page_title="OKX Bot", page_icon="📈", layout="wide")

st.markdown("""
<style>
.stApp { background-color: #050505; color: #ffffff; }
[data-testid="stSidebar"] { background-color: #0b0b0b; }
h1, h2, h3, p, label, span { color: #ffffff; }
.metric-card {
    background-color: #111111;
    border: 1px solid #333333;
    border-radius: 14px;
    padding: 18px;
}
.metric-label { color: #a9a9a9; font-size: 0.9rem; }
.metric-value { color: #ffffff; font-size: 1.65rem; font-weight: 700; }
.stButton > button {
    background: #00ff87;
    color: #000000;
    border: 0;
    border-radius: 10px;
    font-weight: 700;
}
div[data-testid="stDataFrame"] { border: 1px solid #333333; }
</style>
""", unsafe_allow_html=True)

# --- АВТОРИЗАЦИЯ ---
if "auth" not in st.session_state:
    st.session_state.auth = False

if not st.session_state.auth:
    st.title("Вход")
    pin = st.text_input("PIN", type="password", max_chars=4)
    if st.button("Войти"):
        if pin == "1234":
            st.session_state.auth = True
            st.rerun()
        else:
            st.error("Неверный PIN")
    st.stop()

# --- ПАМЯТЬ ---
if "tg_token" not in st.session_state:
    st.session_state.tg_token = ""
if "tg_chat" not in st.session_state:
    st.session_state.tg_chat = ""

COINS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT"]
URL = "https://www.okx.com/api/v5/market/candles"
URL_INFO = "https://www.okx.com/api/v5/public/instruments"
HEADERS = {"User-Agent": "Mozilla/5.0"}

def metric_card(label, value):
    html = f'<div class="metric-card">'
    html += f'<div class="metric-label">{label}</div>'
    html += f'<div class="metric-value">{value}</div>'
    html += f'</div>'
    st.markdown(html, unsafe_allow_html=True)

# --- TELEGRAM ---
def send_tg(msg):
    token = st.secrets.get("telegram", {}).get("token", st.session_state.tg_token)
    chat = st.secrets.get("telegram", {}).get("chat_id", st.session_state.tg_chat)
    
    if token and chat:
        try:
            base = "https://api.telegram.org/bot"
            url = base + token + "/sendMessage"
            data = {"chat_id": chat, "text": msg, "parse_mode": "Markdown"}
            res = requests.post(url, json=data, timeout=5)
            return res.status_code == 200
        except:
            return False
    return False

# --- ВОЗРАСТ ---
@st.cache_data(ttl=3600)
def check_age(symbol, market):
    try:
        inst_type = "SWAP" if market == "Фьючерсы (SWAP)" else "SPOT"
        params = {"instType": inst_type}
        res = requests.get(URL_INFO, params=params, headers=HEADERS, timeout=10)
        data = res.json().get("data", [])
        
        for item in data:
            if item["instId"] == symbol:
                list_time = int(item.get("listTime", 0))
                if list_time == 0:
                    return True
                days = (time.time() * 1000 - list_time) / (1000 * 60 * 60 * 24)
                return days > 180
        return True
    except:
        return True

# --- ДАННЫЕ ---
def get_data(symbol):
    params = {"instId": symbol, "bar": "1D", "limit": "30"}
    res = requests.get(URL, params=params, headers=HEADERS, timeout=15)
    payload = res.json()
    
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
        
    return df.dropna(subset=["h", "l", "c"]).reset_index(drop=True)

# --- АНАЛИЗ ---
def analyze(coin, symbol, market):
    is_old = check_age(symbol, market)
    df = get_data(symbol)
    
    if df is None or len(df) < 20:
        return None
        
    close = df["c"]
    high = df["h"]
    low = df["l"]
    
    rsi = RSIIndicator(close=close, window=14).rsi().iloc[-1]
    adx = ADXIndicator(high=high, low=low, close=close, window=14).adx().iloc[-1]
    atr = AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range().iloc[-1]
    
    price = float(close.iloc[-1])
    atr_pct = (atr / price * 100) if price else 0.0
    
    if atr_pct < 1.5:
        tp = 1.0
        tp_reason = "спокойный"
    elif atr_pct < 3.0:
        tp = 1.5
        tp_reason = "стандарт"
    else:
        tp = 2.0
        tp_reason = "волатильный"
        
    step = 2.0
    mart = 1.2
    so_count = 4

    reason = ""
    if adx > 25:
        if rsi < 40:
            signal = "🟢 ЛОНГ"
            phase = "Тренд"
            bot = "DCA Long"
            reason = f"RSI={rsi:.0f} + ADX={adx:.0f}"
        elif rsi > 50:
            signal = "⏳ ЖДАТЬ"
            phase = "Тренд"
            bot = "Пауза"
            reason = "Ждем отката"
        else:
            signal = "🔴 ШОРТ"
            phase = "Тренд"
            bot = "DCA Short"
            reason = f"RSI={rsi:.0f} + ADX={adx:.0f}"
    else:
        signal = "🟡 СЕТКА"
        phase = "Флэт"
        bot = "Grid"
        reason = f"ADX={adx:.0f} (боковик)"

    if not is_old:
        cls = "🔴 Молодая"
    elif coin in ("BTC", "ETH"):
        cls = "🟢 Консерв."
    elif atr_pct > 3:
        cls = "🔴 Агрессив."
    else:
        cls = "🟡 Умерен."
    
    return {
        "Монета": coin,
        "Цена": price,
        "Фаза": phase,
        "Класс": cls,
        "RSI": rsi,
        "ADX": adx,
        "Сигнал": signal,
        "Бот": bot,
        "TP": tp,
        "TP_Reason": tp_reason,
        "Step": step,
        "Mart": mart,
        "SO": so_count,
        "Reason": reason
    }

def color_sig(val):
    if "ЛОНГ" in str(val):
        return "color: #00ff87; font-weight: bold"
    if "ШОРТ" in str(val):
        return "color: #ff4d4f; font-weight: bold"
    if "СЕТКА" in str(val):
        return "color: #ffd700; font-weight: bold"
    return "color: #bbbbbb"

# --- МЕНЮ ---
with st.sidebar:
    st.title("OKX Manager")
    page = st.radio("Раздел", ["Главная", "Сканер", "DCA", "Grid", "Позиция", "Настройки"])
    if st.button("Выйти"):
        st.session_state.auth = False
        st.rerun()

st.title(page)

# --- 1. ГЛАВНАЯ ---
if page == "Главная":
    st.subheader("Добрый день, брат!")
    cols = st.columns(4)
    with cols[0]: metric_card("Статус", "Онлайн")
    with cols[1]: metric_card("Баланс", "0 USDT")
    with cols[2]: metric_card("Боты", "0")
    with cols[3]: metric_card("Риск", "Низкий")

# --- 2. СКАНЕР ---
elif page == "Сканер":
    market = st.radio("Рынок:", ["Фьючерсы (SWAP)", "Спот"], horizontal=True)
    
    if st.button("Сканировать ТОП-10", use_container_width=True):
        res = []
        bar = st.progress(0)
        
        for i, coin in enumerate(COINS):
            sym = coin + "-USDT-SWAP" if market == "Фьючерсы (SWAP)" else coin + "-USDT"
            try:
                data = analyze(coin, sym, market)
                if data:
                    res.append(data)
            except:
                pass
            bar.progress((i+1)/len(COINS))
        
        if res:
            df = pd.DataFrame(res)
            show_cols = ["Монета", "Цена", "RSI", "ADX", "Сигнал", "Класс"]
            disp = df[show_cols]
            
            fmt = {"Цена": "{:.6f}", "RSI": "{:.2f}", "ADX": "{:.2f}"}
            styled = disp.style.format(fmt).map(color_sig, subset=["Сигнал"])
            st.dataframe(styled, use_container_width=True, hide_index=True)
            
            m_name = "ФЬЮЧЕРСЫ" if market == "Фьючерсы (SWAP)" else "СПОТ"
            msg = f"📊 **Сигналы ({m_name}):**\n\n"
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
                if send_tg(msg):
                    st.success("Отправлено в ТГ!")
            else:
                st.info("Нет сильных сигналов.")

# --- 3. DCA ---
elif page == "DCA":
    entry = st.number_input("Цена входа", value=100.0)
    count = st.number_input("Кол-во СО", value=4)
    step = st.number_input("Шаг %", value=2.0)
    
    if st.button("Рассчитать", use_container_width=True):
        rows = []
        total = 0
        
        for i in range(int(count)):
            p = entry * (1 - step / 100 * i)
            a = 10.0 * (1.2 ** i)
            total += a
            
            row = {"Шаг": i + 1, "Цена": p, "Сумма": a}
            rows.append(row)
            
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
        
        msg = f"🔔 PnL: {pnl:.2f} USDT"
        if send_tg(msg):
            st.info("Уведомление в ТГ.")

# --- 6. НАСТРОЙКИ ---
elif page == "Настройки":
    st.subheader("Настройки Telegram")
    
    try:
        st.success("Настройки найдены в Secrets")
        cid = st.secrets["telegram"]["chat_id"]
        st.code(f"Chat ID: {cid}")
    except:
        st.warning("Secrets не настроены:")
        st.session_state.tg_token = st.text_input("Bot Token")
        st.session_state.tg_chat = st.text_input("Chat ID")
    
    if st.button("Тест Telegram", use_container_width=True):
        if send_tg("Привет, брат! Тест."):
            st.success("Отправлено!")
        else:
            st.error("Ошибка.")
