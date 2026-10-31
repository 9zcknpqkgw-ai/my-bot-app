import streamlit as st
import pandas as pd
import ccxt
import ta
import time

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
    st.title("Сканер рынка")
    market_type = st.radio("Рынок:", ["Фьючерсы (SWAP)", "Спот"], horizontal=True)
    tf = st.selectbox("Таймфрейм:", ["15m", "1h", "4h", "1d"])
    
    if st.button("🚀 Сканировать ТОП-10"):
        progress_bar = st.progress(0)
        try:
            ex = ccxt.okx()
            # ТОЛЬКО 10 САМЫХ НАДЕЖНЫХ МОНЕТ
            coins = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT"]
            res = []
            
            for idx, c in enumerate(coins):
                progress_bar.progress((idx + 1) / len(coins))
                
                symbol = f"{c}/USDT:USDT" if market_type == "Фьючерсы (SWAP)" else f"{c}/USDT"
                
                try:
                    # 1. Тренд (1D)
                    data_d = ex.fetch_ohlcv(symbol, "1d", limit=20)
                    if len(data_d) < 20: continue
                    df_d = pd.DataFrame(data_d, columns=["t","o","h","l","c","v"])
                    adx_d = ta.trend.ADXIndicator(df_d["h"], df_d["l"], df_d["c"]).adx().iloc[-1]
                    global_trend = "Вверх" if adx_d > 25 else "Флэт"
                    
                    # 2. Вход (Выбранный ТФ)
                    data_t = ex.fetch_ohlcv(symbol, tf, limit=20)
                    df_t = pd.DataFrame(data_t, columns=["t","o","h","l","c","v"])
                    
                    rsi = ta.momentum.RSIIndicator(df_t["c"]).rsi().iloc[-1]
                    adx = ta.trend.ADXIndicator(df_t["h"], df_t["l"], df_t["c"]).adx().iloc[-1]
                    atr = ta.volatility.AverageTrueRange(df_t["h"], df_t["l"], df_t["c"]).average_true_range().iloc[-1]
                    atr_pct = (atr / df_t["c"].iloc[-1]) * 100
                    
                    if adx > 25:
                        phase = "Тренд"
                        if global_trend == "Вверх" and rsi < 40: signal = "🟢 ЛОНГ"; bot = "DCA Long"
                        elif global_trend == "Вверх" and rsi > 50: signal = "⏳ ЖДАТЬ"; bot = "—"
                        else: signal = "🔴 ШОРТ"; bot = "DCA Short"
                    else:
                        phase = "Боковик"; signal = "🟡 СЕТКА"; bot = "Grid"

                    if c in ["BTC", "ETH"]: reliability = "🟢 Консерв."
                    elif atr_pct > 3.0: reliability = "🔴 Агрессив."
                    else: reliability = "🟡 Умерен."
                        
                    tp = 1.5 if atr_pct < 3 else 2.5
                    step = round(atr_pct * 0.8, 1) if atr_pct > 1 else 1.0
                    
                    res.append({
                        "Монета": c, "Цена": round(df_t["c"].iloc[-1], 4), 
                        "Тренд": global_trend, "Фаза": phase, "Класс": reliability,
                        "RSI": round(rsi,1), "ADX": round(adx,1), "Сигнал": signal,
                        "Бот": bot, "Тейк %": tp, "Шаг %": step
                    })
                except: pass
                time.sleep(0.1)
            
            progress_bar.empty()
            
            if res:
                df_res = pd.DataFrame(res)
                def color_sig(val):
                    if "ЛОНГ" in val: return 'color: #00ff00; font-weight: bold;'
                    elif "ШОРТ" in val: return 'color: #ff0000; font-weight: bold;'
                    elif "СЕТКА" in val: return 'color: #ffd700; font-weight: bold;'
                    return 'color: #aaaaaa;'
                st.dataframe(df_res.style.map(color_sig, subset=["Сигнал"]), use_container_width=True)
            else:
                st.warning("Не удалось загрузить.")
        except Exception as e:
            st.error(f"Ошибка: {e}")
