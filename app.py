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

st.sidebar.title("⚡ AI CENTER")
menu = st.sidebar.radio("Навигация", ["1. Главная", "2. Сканер рынка"])

if menu == "1. Главная":
    st.title("Добрый день, Владимир! 👋")
    st.info("👈 Перейдите в «Сканер рынка».")

elif menu == "2. Сканер рынка":
    st.title("Сканер рынка (Прямой API)")
    st.write("Использует прямой запрос к OKX (без ccxt).")
    
    tf = st.selectbox("Таймфрейм:", ["15m", "1h", "4h", "1d"])
    
    if st.button("🚀 Сканировать ТОП-10"):
        with st.spinner("Загрузка..."):
            coins = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT"]
            res = []
            
            # Маппинг таймфреймов в формат OKX
            tf_map = {"15m": "15m", "1h": "1H", "4h": "4H", "1d": "1D"}
            okx_tf = tf_map.get(tf, "1H")
            
            for c in coins:
                try:
                    # Прямой запрос к OKX API
                    url = f"https://www.okx.com/api/v5/market/candles?instId={c}-USDT-SWAP&bar={okx_tf}&limit=20"
                    response = requests.get(url).json()
                    
                    if response.get("code") != "0":
                        continue
                        
                    data = response["data"]
                    if len(data) < 20: continue
                    
                    # Свечи идут от новых к старым, переворачиваем
                    data.reverse()
                    df = pd.DataFrame(data, columns=["t","o","h","l","c","vol","volCcy","volCcyQuote","confirm"])
                    
                    # Приводим к float
                    for col in ["o","h","l","c"]:
                        df[col] = df[col].astype(float)
                        
                    # Считаем индикаторы
                    rsi = ta.momentum.RSIIndicator(df["c"]).rsi().iloc[-1]
                    adx = ta.trend.ADXIndicator(df["h"], df["l"], df["c"]).adx().iloc[-1]
                    atr = ta.volatility.AverageTrueRange(df["h"], df["l"], df["c"]).average_true_range().iloc[-1]
                    atr_pct = (atr / df["c"].iloc[-1]) * 100
                    
                    # Логика
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
                except Exception as e:
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
                st.error("Не удалось загрузить данные. Биржа блокирует запросы.")
