import streamlit as st
import pandas as pd
import ccxt
import ta
import csv
from datetime import datetime
import os

# --- ДИЗАЙН ---
st.set_page_config(page_title="AI Center", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #0a0b10; color: #e0e0e0; }
    .stButton>button {
        background: #00ff87;
        color: #000;
        font-weight: bold;
        border-radius: 5px;
    }
    div[data-testid="stMetric"] {
        background: #1e1e24;
        padding: 15px;
        border-radius: 10px;
    }
</style>
""", unsafe_allow_html=True)

# --- ЖУРНАЛ ---
JOURNAL = "journal.csv"
if not os.path.exists(JOURNAL):
    with open(JOURNAL, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Дата", "Монета", "Действие", "Результат", "Совет"])

def save_log(coin, action, result, rec):
    with open(JOURNAL, "a", newline="") as f:
        w = csv.writer(f)
        date = datetime.now().strftime("%d.%m %H:%M")
        w.writerow([date, coin, action, result, rec])

# --- МЕНЮ ---
st.sidebar.title("AI CENTER")
menu = st.sidebar.radio("Меню", [
    "1. Главная", 
    "2. Сканер", 
    "3. DCA", 
    "4. Grid", 
    "5. Риск",
    "6. Разбор",
    "7. Журнал",
    "8. API"
])

# --- 1. ГЛАВНАЯ ---
if menu == "1. Главная":
    st.title("Главная")
    c1, c2, c3 = st.columns(3)
    c1.metric("Статус", "Онлайн", "OK")
    c2.metric("Боты", "0", "Нет")
    c3.metric("Риск", "Низкий", "OK")
    st.info("Выбери 'Сканер' в меню слева.")

# --- 2. СКАНЕР ---
elif menu == "2. Сканер":
    st.title("Сканер рынка")
    
    if st.button("Сканировать OKX"):
        with st.spinner("Идет анализ..."):
            ex = ccxt.okx()
            coins = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT"]
            res = []
            
            for c in coins:
                sym = c + "/USDT:USDT"
                try:
                    data = ex.fetch_ohlcv(sym, "1d", limit=50)
                    df = pd.DataFrame(data, columns=["t","o","h","l","c","v"])
                    
                    # Индикаторы
                    df["rsi"] = ta.momentum.RSIIndicator(df["c"]).rsi()
                    df["adx"] = ta.trend.ADXIndicator(df["h"], df["l"], df["c"]).adx()
                    df["atr"] = ta.volatility.AverageTrueRange(df["h"], df["l"], df["c"]).average_true_range()
                    
                    # Значения
                    rsi = df["rsi"].iloc[-1]
                    adx = df["adx"].iloc[-1]
                    atr = df["atr"].iloc[-1]
                    price = df["c"].iloc[-1]
                    
                    atr_pct = (atr / price) * 100
                    
                    # Настройки
                    if atr_pct < 1.5: tp = 1.0
                    elif atr_pct < 3.0: tp = 1.5
                    else: tp = 2.5
                    
                    step = round(atr_pct * 0.8, 1)
                    if step < 1.0: step = 1.0
                    
                    if adx > 30: mart = 1.4
                    elif adx > 25: mart = 1.3
                    else: mart = 1.2
                    
                    # Логика
                    if adx > 25:
                        phase = "Тренд"
                        bot = "DCA"
                        if rsi > 50: dir = "LONG"
                        else: dir = "SHORT"
                    else:
                        phase = "Боковик"
                        bot = "Grid"
                        dir = "Нейтрально"
                        
                    res.append({
                        "Монета": c,
                        "Цена": price,
                        "ATR%": round(atr_pct, 2),
                        "RSI": round(rsi, 1),
                        "ADX": round(adx, 1),
                        "Фаза": phase,
                        "Бот": bot,
                        "Направление": dir,
                        "Тейк": tp,
                        "Шаг": step,
                        "Март": mart
                    })
                except:
                    pass
            
            if res:
                df_res = pd.DataFrame(res)
                st.dataframe(df_res, use_container_width=True)
            else:
                st.error("Ошибка сканирования.")

# --- 3. DCA ---
elif menu == "3. DCA":
    st.title("Калькулятор DCA")
    
    entry = st.number_input("Цена входа", value=1.0)
    cap = st.number_input("Капитал", value=1000.0)
    first = st.number_input("Первый вход", value=20.0)
    count = st.number_input("Кол-во СО", value=5)
    step = st.number_input("Шаг %", value=2.0)
    tp = st.number_input("Тейк %", value=1.5)
    
    if st.button("Рассчитать"):
        ladder = []
        cur_p = entry
        cur_s = first
        total = first
        
        for i in range(int(count)):
            cur_p = cur_p * (1 - step/100)
            cur_s = cur_s * 1.2
            total += cur_s
            ladder.append({"Шаг": i+1, "Цена": round(cur_p, 4), "Сумма": round(cur_s, 2)})
            
        m1, m2, m3 = st.columns(3)
        m1.metric("Всего", f"{round(total,1)} USDT")
        m2.metric("Стоп 20%", f"-{round(total*0.2,1)} USDT")
        m3.metric("Глубина", f"{count*step}%")
        
        st.dataframe(pd.DataFrame(ladder))

# --- 4. GRID ---
elif menu == "4. Grid":
    st.title("Калькулятор Grid")
    
    low = st.number_input("Нижняя граница", value=100.0)
    high = st.number_input("Верхняя граница", value=110.0)
    grids = st.number_input("Кол-во сеток", value=30)
    cap = st.number_input("Капитал", value=100.0)
    
    if st.button("Рассчитать"):
        width = ((high - low) / low) * 100
        step_pct = width / grids
        budget = cap / grids
        
        m1, m2, m3 = st.columns(3)
        m1.metric("Ширина", f"{round(width,2)}%")
        m2.metric("Шаг", f"{round(step_pct,2)}%")
        m3.metric("Бюджет", f"{round(budget,2)} USDT")
        
        if step_pct < 0.3:
            st.warning("Шаг меньше 0.3%! Комиссия съест прибыль.")

# --- 5. РИСК ---
elif menu == "5. Риск":
    st.title("Капитал и Риск")
    
    total = st.number_input("Общий капитал", value=5000.0)
    limit = st.slider("Лимит на 1 бота %", 5, 50, 20)
    
    max_bot = total * (limit / 100)
    
    c1, c2 = st.columns(2)
    c1.metric("Лимит на бота", f"{max_bot} USDT")
    c2.metric("Остаток", f"{total} USDT")
    
    new_bot = st.number_input("Новый бот USDT", value=500.0)
    
    if new_bot > max_bot:
        st.error("Превышен лимит риска!")
    else:
        st.success("Риски в норме.")

# --- 6. РАЗБОР ---
elif menu == "6. Разбор":
    st.title("Разбор позиции")
    
    coin = st.text_input("Монета", value="SOL")
    cur = st.number_input("Текущая цена", value=100.0)
    avg = st.number_input("Средняя цена", value=105.0)
    pos = st.number_input("Размер USDT", value=100.0)
    drop = st.slider("Падение %", 1, 30, 10)
    
    new_p = cur * (1 - drop/100)
    
    loss_now = (avg - cur) * (pos / cur)
    loss_drop = (avg - new_p) * (pos / new_p)
    
    st.markdown("### 4 действия")
    c1, c2, c3, c4 = st.columns(4)
    
    if c1.button("Оставить"):
        st.info(f"Убыток: {loss_now:.2f}")
        save_log(coin, "Оставить", loss_now, "Ждать")
        
    if c2.button("Докупить 20"):
        new_pos = pos + 20
        new_avg = ((avg * (pos/avg)) + (cur * (20/cur))) / (pos/avg + 20/cur)
        new_loss = (new_avg - new_p) * (new_pos / new_p)
        st.warning(f"Новая средняя: {new_avg:.2f}")
        save_log(coin, "Докупить", new_loss, "Снизить среднюю")
        
    if c3.button("Продать 50%"):
        st.warning(f"Зафиксировано: {loss_now/2:.2f}")
        save_log(coin, "Продать", loss_now/2, "Сократить риск")
        
    if c4.button("Закрыть всё"):
        st.error(f"Убыток: {loss_now:.2f}")
        save_log(coin, "Закрыть", loss_now, "Принять")

# --- 7. ЖУРНАЛ ---
elif menu == "7. Журнал":
    st.title("Журнал решений")
    
    if os.path.exists(JOURNAL):
        try:
            df = pd.read_csv(JOURNAL)
            if not df.empty:
                st.dataframe(df)
                if st.button("Очистить"):
                    os.remove(JOURNAL)
                    st.rerun()
            else:
                st.info("Журнал пуст.")
        except:
            st.info("Журнал пуст.")
    else:
        st.info("Журнал пуст.")

# --- 8. API ---
elif menu == "8. API":
    st.title("Подключение")
    
    key = st.text_input("API Key", type="password")
    sec = st.text_input("Secret Key", type="password")
    pwd = st.text_input("Passphrase", type="password")
    
    if st.button("Проверить"):
        if key and sec and pwd:
            st.success("Ключи сохранены (Демо)!")
        else:
            st.error("Заполни все поля!")
