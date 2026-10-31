import streamlit as st
import pandas as pd
import ccxt
import ta
import requests

# --- НАСТРОЙКА И СТИЛЬ (БЕЛЫЙ НА ЧЕРНОМ) ---
st.set_page_config(page_title="AI Center", layout="wide")

st.markdown("""
<style>
    /* Глубокий черный фон */
    .stApp { background-color: #000000; color: #ffffff; }
    
    /* Белые карточки с тонкой рамкой */
    div[data-testid="stMetric"] {
        background-color: #111111;
        padding: 15px;
        border-radius: 8px;
        border: 1px solid #333333;
    }
    div[data-testid="stMetricValue"] { color: #ffffff; }
    div[data-testid="stMetricLabel"] { color: #aaaaaa; }
    
    /* Белые кнопки с черным текстом */
    .stButton>button {
        background-color: #ffffff; 
        color: #000000; 
        border-radius: 5px; 
        font-weight: bold;
        border: none;
        transition: 0.3s;
    }
    .stButton>button:hover { background-color: #cccccc; color: #000000; }
    
    /* Поля ввода */
    .stTextInput>div>div>input { background-color: #111111; color: #ffffff; border: 1px solid #333333; }
    
    /* Цвета для Лонг/Шорт */
    .long-text { color: #00ff00; font-weight: bold; }
    .short-text { color: #ff0000; font-weight: bold; }
    .neutral-text { color: #aaaaaa; }
</style>
""", unsafe_allow_html=True)

# --- КЛЮЧИ ---
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
        except: return None
    return None

def send_tg(msg):
    if st.session_state.tg_token and st.session_state.tg_chat:
        try:
            url = f"https://api.telegram.org/bot{st.session_state.tg_token}/sendMessage"
            requests.post(url, json={"chat_id": st.session_state.tg_chat, "text": msg})
        except: pass

# --- МЕНЮ ---
st.sidebar.title("AI CENTER")
menu = st.sidebar.radio("Навигация", ["1. Главная", "2. Сканер", "3. DCA", "4. Grid", "5. Позиция", "6. Настройки"])

# --- 1. ГЛАВНАЯ ---
if menu == "1. Главная":
    st.title("Добрый день, Владимир!")
    st.write("Ваши боты работают. Вот общая картина.")
    
    ex = get_okx()
    c1, c2, c3, c4 = st.columns(4)
    if ex:
        try:
            bal = ex.fetch_balance()
            usdt = bal.get('USDT', {}).get('free', 0.0)
            c1.metric("Статус", "Онлайн", "OK")
            c2.metric("Баланс", f"{usdt:.2f} USDT", "OKX")
            c3.metric("Активных ботов", "0", "Нет")
            c4.metric("Уровень риска", "Низкий", "OK")
        except:
            c1.metric("Статус", "Ошибка ключей", "ERR")
    else:
        c1.metric("Статус", "Не подключено", "OFF")
        c2.metric("Баланс", "0 USDT", "—")
        c3.metric("Активных ботов", "0", "Нет")
        c4.metric("Уровень риска", "Неизвестно", "—")
    st.info("Введите ключи в 'Настройках', чтобы увидеть реальный баланс.")

# --- 2. СКАНЕР ---
elif menu == "2. Сканер":
    st.title("Сканер рынка")
    if st.button("Сканировать ТОП-10"):
        with st.spinner("Анализ..."):
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
                    
                    phase = "Тренд" if adx > 25 else "Боковик"
                    bot = "DCA" if adx > 25 else "Grid"
                    d = "LONG" if rsi > 50 else "SHORT"
                    if adx <= 25: d = "НЕЙТРАЛЬНО"
                    
                    tp = 1.5 if atr_pct < 3 else 2.5
                    step = round(atr_pct * 0.8, 1) if atr_pct > 1 else 1.0
                    
                    res.append({"Монета": c, "Цена": df["c"].iloc[-1], "RSI": round(rsi,1), "ADX": round(adx,1), "Фаза": phase, "Бот": bot, "Направление": d, "Тейк": tp, "Шаг": step})
                except: pass
            
            if res:
                df_res = pd.DataFrame(res)
                
                # Красим колонку "Направление"
                def color_direction(val):
                    if val == "LONG": return 'color: #00ff00; font-weight: bold;'
                    elif val == "SHORT": return 'color: #ff0000; font-weight: bold;'
                    else: return 'color: #aaaaaa;'
                
                # Применяем стили к таблице
                st.dataframe(df_res.style.map(color_direction, subset=["Направление"]), use_container_width=True)
            else:
                st.warning("Нет данных.")

# --- 3. DCA ---
elif menu == "3. DCA":
    st.title("План DCA")
    entry = st.number_input("Цена входа", value=1.0)
    count = st.number_input("Кол-во СО", value=5)
    step = st.number_input("Шаг %", value=2.0)
    if st.button("Рассчитать"):
        ladder = []
        cur_p, cur_s, tot = entry, 20.0, 20.0
        for i in range(int(count)):
            cur_p = cur_p * (1 - step/100)
            cur_s = cur_s * 1.2
            tot += cur_s
            ladder.append({"Шаг": i+1, "Цена": round(cur_p,4), "Сумма": round(cur_s,2)})
        st.metric("Всего покупок", f"{round(tot,1)} USDT")
        st.dataframe(pd.DataFrame(ladder))

# --- 4. GRID ---
elif menu == "4. Grid":
    st.title("План Grid")
    low = st.number_input("Нижняя граница", value=100.0)
    high = st.number_input("Верхняя граница", value=110.0)
    grids = st.number_input("Кол-во сеток", value=30)
    if st.button("Рассчитать"):
        width = ((high - low) / low) * 100
        step_pct = width / grids
        st.metric("Ширина", f"{round(width,2)}%")
        st.metric("Шаг", f"{round(step_pct,2)}%")
        if step_pct < 0.3: st.warning("Шаг < 0.3%!")

# --- 5. ПОЗИЦИЯ ---
elif menu == "5. Позиция":
    st.title("Разбор позиции")
    cur = st.number_input("Текущая цена", value=0.35)
    avg = st.number_input("Средняя цена", value=0.35)
    pos = st.number_input("Позиция (USDT)", value=100.0)
    if avg > 0 and cur > 0:
        loss = (avg - cur) * (pos / cur)
        st.metric("Текущий убыток", f"{loss:.2f} USDT")
        if st.button("Отправить в ТГ"):
            send_tg(f"Убыток: {loss:.2f} USDT")
            st.success("Отправлено!")

# --- 6. НАСТРОЙКИ ---
elif menu == "6. Настройки":
    st.title("Настройки")
    st.markdown("### OKX")
    st.session_state.okx_api = st.text_input("API Key", value=st.session_state.okx_api, type="password")
    st.session_state.okx_secret = st.text_input("Secret Key", value=st.session_state.okx_secret, type="password")
    st.session_state.okx_pass = st.text_input("Passphrase", value=st.session_state.okx_pass, type="password")
    if st.button("Проверить OKX"):
        if get_okx(): st.success("✅ OKX Подключено!")
        else: st.error("❌ Ошибка ключей.")
        
    st.markdown("### Telegram")
    st.session_state.tg_token = st.text_input("Bot Token", value=st.session_state.tg_token)
    st.session_state.tg_chat = st.text_input("Chat ID", value=st.session_state.tg_chat)
    if st.button("Тест ТГ"):
        send_tg("Привет от AI Center!")
        st.info("Проверь телеграм.")
