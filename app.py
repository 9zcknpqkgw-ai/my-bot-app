import streamlit as st
import pandas as pd
import ccxt
import ta
import requests

# 1. НАСТРОЙКА И ДИЗАЙН
st.set_page_config(page_title="AI Center", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #f4f6f9; color: #1e1e1e; }
    div[data-testid="stMetric"] {
        background-color: #ffffff; padding: 15px; border-radius: 10px; border: 1px solid #e0e0e0;
    }
    .stButton>button { background-color: #0052ff; color: white; border-radius: 5px; }
</style>
""", unsafe_allow_html=True)

# --- ХРАНИЛИЩЕ КЛЮЧЕЙ ---
if "okx_api" not in st.session_state: st.session_state.okx_api = ""
if "okx_secret" not in st.session_state: st.session_state.okx_secret = ""
if "okx_pass" not in st.session_state: st.session_state.okx_pass = ""
if "tg_token" not in st.session_state: st.session_state.tg_token = ""
if "tg_chat" not in st.session_state: st.session_state.tg_chat = ""

def get_okx():
    if st.session_state.okx_api and st.session_state.okx_secret:
        try:
            ex = ccxt.okx({
                'apiKey': st.session_state.okx_api,
                'secret': st.session_state.okx_secret,
                'password': st.session_state.okx_pass,
                'options': {'defaultType': 'swap'},
            })
            ex.enableDemoTrading(True)
            return ex
        except:
            return None
    return None

def send_tg(msg):
    if st.session_state.tg_token and st.session_state.tg_chat:
        try:
            url = f"https://api.telegram.org/bot{st.session_state.tg_token}/sendMessage"
            requests.post(url, json={"chat_id": st.session_state.tg_chat, "text": msg})
        except:
            pass

# --- МЕНЮ (6 РАЗДЕЛОВ) ---
st.sidebar.title("AI CENTER")
menu = st.sidebar.radio("Навигация", [
    "1. Главная", 
    "2. Сканер рынка", 
    "3. План DCA", 
    "4. План Grid", 
    "5. Открытая позиция",
    "6. Настройки"
])

# ==========================================
# 1. ГЛАВНАЯ
# =================================                       =========
if menu == "1 phase. Главная":
    st.title("Добрый вечер!")
    ex = get_okx()
    
    c1, c2, c3, c4 = st.columns(4)
    if ex:
        try:
            bal = ex.fetch_balance()
            usdt = bal.get('USDT', {}).get('free', 0.0)
            c1.metric("Статус", "Онлайн", "🟢")
            c2.metric("Баланс", f"{usdt:.2f} USDT", "OKX")
            c3.metric("Боты", "Загружаются", "OK")
            c4.metric("Риск", "Низкий", "OK")
        except:
            c1.metric("Статус", "Ошибка ключей", "🔴")
    else:
        c1.metric("Статус", "Не подключено", "⚪")
        c2.metric("Баланс", "0 USDT", "—")
        c3.metric("Боты", "0", "Нет")
        c4.metric("Риск", "Неизвестно", "—")
        
    st.info("Перейдите в 'Настройки', чтобы ввести API-ключи.")

# ==========================================
# 2. СКАНЕР РЫНКА (Быстрый)
# ==========================================
elif menu == "2. Сканер рынка":
    st.title("Сканер рынка (Адаптивный)")
    if st.button("🚀 Сканировать ТОП-10"):
        with st.spinner("Анализируем..."):
            ex = ccxt.okx()
            coins = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT"]
            res = []
            for c in coins:
                try:
                    data = ex.fetch_ohlcv(c + "/USDT:USDT", "1d", limit=30)
                    df = pd.DataFrame(data, columns=["t","o","h","l","c","v"])
                    
                    rsi = ta.momentum.RSIIndicator(df["c"]).rsi().iloc[-1]
                    adx = ta.trend.ADXIndicator(df["h"], df["l"], df["c"]).adx().iloc[-1]
                    atr = ta.volatility.AverageTrueRange(df["h"], df["l"], df["c"]).average_true_range().iloc[-1]
                    
                    atr_pct = (atr / df["c"].iloc[-1]) * 100
                    
                    if adx > 25:
 = "Тренд"
                        bot = "DCA"
                        d = "LONG" if rsi > 50 else "SHORT"
                    else:
                        phase = "Боковик"
                        bot = "Grid"
                        d = "Нейтрально"
                        
                    tp = 1.5 if atr_pct < 3 else 2.5
                    step = round(atr_pct * 0.8, 1) if atr_pct > 1 else 1.0
                    
                    res.append({"Монета": c, "Цена": df["c"].iloc[-1], "RSI": round(rsi,1), "ADX": round(adx,1), "Фаза": phase, "Бот": bot, "Направление": d, "Тейк": tp, "Шаг": step})
                except: pass
            if res: st.dataframe(pd.DataFrame(res), use_container_width=True)
            else: st.warning("Нет данных.")

# ==========================================
# 3. ПЛАН DCA
# ==========================================
elif menu == "3. План DCA":
    st.title("План DCA")
    c1, c2, c3 = st.columns(3)
    entry = c1.number_input("Цена входа", value=1.0)
    cap = c2.number_input("Капитал", value=1000.0)
    first = c3.number_input("Первый вход", value=20.0)
    
    c4, c5 = st.columns(2)
    count = c4.number_input("Кол-во СО", value=5)
    step = c5.number_input("Шаг %", value=2.0)
    
    if st.button("Рассчитать"):
        ladder = []
        cur_p, cur_s, tot = entry, first, first
        for i in range(int(count)):
            cur_p = cur_p * (1 - step/100)
            cur_s = cur_s * 1.2
            tot += cur_s
            ladder.append({"Шаг": i+1, "Цена": round(cur_p,4), "Сумма": round(cur_s,2)})
        st.metric("Всего покупок", f"{round(tot,1)} USDT")
        st.dataframe(pd.DataFrame(ladder))

# ==========================================
# 4. ПЛАН GRID
# ==========================================
elif menu == "4. План Grid":
    st.title("План Grid")
    c1, c2 = st.columns(2)
    low = c1.number_input("Нижняя граница", value=100.0)
    high = c2.number_input("Верхняя граница", value=110.0)
    grids = st.number_input("Кол-во сеток", value=30)
    cap = st.number_input("Капитал", value=100.0)
    
    if st.button("Рассчитать"):
        width = ((high - low) / low) * 100
        step_pct = width / grids
        st.metric("Ширина", f"{round(width,2)}%")
        st.metric("Шаг", f"{round(step_pct,2)}%")
        if step_pct < 0.3: st.warning("Шаг < 0.3%! Комиссия съест прибыль.")

# ==========================================
# 5. ОТКРЫТАЯ ПОЗИЦИЯ
# ==========================================
elif menu == "5. Открытая позиция":
    st.title("Разбор позиции")
    c1, c2, c3 = st.columns(3)
    cur = c1.number_input("Текущая цена", value=0.35)
    avg = c2.number_input("Средняя цена", value=0.35)
    pos = c3.number_input("Позиция (USDT)", value=100.0)
    
    if avg > 0 and cur > 0:
        loss = (avg - cur) * (pos / cur)
        st.metric("Текущий убыток", f"{loss:.2f} USDT")
        
        if st.button("Записать в журнал / Отправить в ТГ"):
            send_tg(f"Позиция: убыток {loss:.2f} USDT")
            st.success("Записано и отправлено!")

# ==========================================
# 6. НАСТРОЙКИ
# ==========================================
elif menu == "6. Настройки":
    st.title("Настройки подключения")
    
    st.markdown("### OKX API")
    c1, c2, c3 = st.columns(3)
    st.session_state.okx_api = c1.text_input("API Key", value=st.session_state.okx_api, type="password")
    st.session_state.okx_secret = c2.text_input("Secret Key", value=st.session_state.okx_secret, type="password")
    st.session_state.okx_pass = c3.text_input("Passphrase", value=st.session_state.okx_pass, type="password")
    
    if st.button("Проверить OKX"):
        if get_okx(): st.success("✅ OKX Подключено!")
        else: st.error("❌ Ошибка ключей.")
        
    st.markdown("### Telegram")
    st.session_state.tg_token = st.text_input("Bot Token", value=st.session_state.tg_token)
    st.session_state.tg_chat = st.text_input("Chat ID", value=st.session_state.tg_chat)
    
    if st.button("Тест ТГ"):
        send_tg("Привет! AI Center на связи.")
        st.info("Если настроено, сообщение ушло.")
