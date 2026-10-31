import streamlit as st
import pandas as pd
import requests
import ta

st.set_page_config(page_title="AI Center", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #050505; color: #ffffff; }
    div[data-testid="stMetric"] { background-color: #111111; padding: 15px; border-radius: 10px; border: 1px solid #333333; }
    .stButton>button { background: linear-gradient(90deg, #ffffff 0%, #cccccc 100%); color: #000000; border-radius: 8px; font-weight: bold; border: none; }
</style>
""", unsafe_allow_html=True)

if "okx_api" not in st.session_state: st.session_state.okx_api = ""
if "okx_secret" not in st.session_state: st.session_state.okx_secret = ""
if "okx_pass" not in st.session_state: st.session_state.okx_pass = ""

st.sidebar.title("⚡ AI CENTER")
menu = st.sidebar.radio("Навигация", ["1. Главная", "2. Сканер рынка", "3. План DCA", "4. План Grid", "5. Позиция", "6. Настройки"])

# --- 1. ГЛАВНАЯ ---
if menu == "1. Главная":
    st.title("Добрый день, Владимир! 👋")
    c1, c2, c3 = st.columns(3)
    c1.metric("Статус системы", "Онлайн", "OK")
    c2.metric("Сканер", "Готов", "1D")
    c3.metric("Режим", "Демо", "Безопасно")

# --- 2. СКАНЕР (ТОЛЬКО ДНЕВКИ, 10 МОНЕТ) ---
elif menu == "2. Сканер рынка":
    st.title("Сканер рынка (Дневной тренд)")
    st.write("Только дневные свечи (1D). ТОП-10 монет.")
    
    if st.button("🚀 Сканировать ТОП-10"):
        with st.spinner("Загрузка дневных свечей..."):
            # РОВНО 10 МОНЕТ
            coins = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT"]
            res = []
            
            for c in coins:
                try:
                    # ТОЛЬКО 1D
                    url = f"https://www.okx.com/api/v5/market/candles?instId={c}-USDT-SWAP&bar=1D&limit=20"
                    response = requests.get(url).json()
                    
                    if response.get("code") != "0": continue
                    data = response["data"]
                    if len(data) < 20: continue
                    
                    data.reverse()
                    df = pd.DataFrame(data, columns=["t","o","h","l","c","vol","volCcy","volCcyQuote","confirm"])
                    for col in ["o","h","l","c"]:
                        df[col] = df[col].astype(float)
                        
                    rsi = ta.momentum.RSIIndicator(df["c"]).rsi().iloc[-1]
                    adx = ta.trend.ADXIndicator(df["h"], df["l"], df["c"]).adx().iloc[-1]
                    atr = ta.volatility.AverageTrueRange(df["h"], df["l"], df["c"]).average_true_range().iloc[-1]
                    atr_pct = (atr / df["c"].iloc[-1]) * 100
                    
                    if adx > 25:
                        phase = "Тренд"
                        if rsi < 40: signal = "🟢 ЛОНГ"; bot = "DCA Long"
                        elif rsi > 50: signal = "⏳ ЖДАТЬ"; bot = "—"
                        else: signal = "🔴 ШОРТ"; bot = "DCA Short"
                    else:
                        phase = "Боковик"; signal = "🟡 СЕТКА"; bot = "Grid"

                    if c in ["BTC", "ETH"]: reliability = "🟢 Консерв."
                    elif atr_pct > 3.0: reliability = "🔴 Агрессив."
                    else: reliability = "🟡 Умерен."
                        
                    tp = 1.5 if atr_pct < 3 else 2.5
                    step = round(atr_pct * 0.8, 1) if atr_pct > 1 else 1.0
                    
                    res.append({
                        "Монета": c, "Цена": round(df["c"].iloc[-1], 4), 
                        "Фаза": phase, "Класс": reliability,
                        "RSI": round(rsi,1), "ADX": round(adx,1), "Сигнал": signal,
                        "Бот": bot, "Тейк %": tp, "Шаг %": step
                    })
                except:
                    pass
                
            if res:
                df_res = pd.DataFrame(res)
                def color_sig(val):
                    if "ЛОНГ" in val: return 'color: #00ff00; font-weight: bold;'
                    elif "ШОРТ" in val: return 'color: #ff0000; font-weight: bold;'
                    elif "СЕТКА" in val: return 'color: #ffd700; font-weight: bold;'
                    return 'color: #aaaaaa;'
                st.dataframe(df_res.style.map(color_sig, subset=["Сигнал"]), use_container_width=True)
            else:
                st.error("Ошибка загрузки. Попробуйте позже.")

# --- 3. DCA ---
elif menu == "3. План DCA":
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
elif menu == "4. План Grid":
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

# --- 6. НАСТРОЙКИ ---
elif menu == "6. Настройки":
    st.title("Настройки")
    st.markdown("### OKX API")
    st.session_state.okx_api = st.text_input("API Key", value=st.session_state.okx_api, type="password")
    st.session_state.okx_secret = st.text_input("Secret Key", value=st.session_state.okx_secret, type="password")
    st.session_state.okx_pass = st.text_input("Passphrase", value=st.session_state.okx_pass, type="password")
    if st.button("Проверить OKX"):
        st.success("✅ Ключи сохранены (Демо)!")
