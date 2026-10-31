import streamlit as st
import pandas as pd
import ccxt
import ta
import time

# --- НАСТРОЙКА И ДИЗАЙН ---
st.set_page_config(page_title="AI Center", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #050505; color: #ffffff; }
    @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
    div[data-testid="stMetric"] { background-color: #111111; padding: 15px; border-radius: 10px; border: 1px solid #333333; animation: fadeIn 0.8s; }
    .stButton>button { background: linear-gradient(90deg, #ffffff 0%, #cccccc 100%); color: #000000; border-radius: 8px; font-weight: bold; border: none; }
    .stButton>button:hover { box-shadow: 0 0 15px rgba(255, 255, 255, 0.5); }
</style>
""", unsafe_allow_html=True)

st.sidebar.title("⚡ AI CENTER")
menu = st.sidebar.radio("Навигация", ["1. Главная", "2. Сканер рынка", "3. План DCA", "4. План Grid"])

# --- 1. ГЛАВНАЯ ---
if menu == "1. Главная":
    st.title("Добрый день, Владимир! 👋")
    st.write("Ваш Центр Управления готов к работе.")
    c1, c2, c3 = st.columns(3)
    c1.metric("Статус системы", "Онлайн", "OK")
    c2.metric("Сканер", "Готов", "OKX")
    c3.metric("Режим", "Демо", "Безопасно")
    st.info("👈 Перейдите в «Сканер рынка», чтобы увидеть точки входа по всему рынку.")

# --- 2. СКАНЕР ВСЕГО РЫНКА ---
elif menu == "2. Сканер рынка":
    st.title("Сканер рынка (Весь рынок)")
    st.write("Ищет сигналы по всем фьючерсным парам USDT на OKX. Отсеивает мусор по объему.")
    
    tf = st.selectbox("Выберите таймфрейм для точки входа:", ["15m", "1h", "4h", "1d"])
    min_vol = st.number_input("Мин. объем торгов (млн $)", value=10.0)
    
    if st.button("🚀 Сканировать весь OKX"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        try:
            ex = ccxt.okx()
            # Получаем ВСЕ тикеры разом, чтобы отфильтровать по объему (быстро)
            tickers = ex.fetch_tickers()
            
            # Оставляем только пары USDT-SWAP с нужным объемом
            valid_symbols = []
            for sym, tick in tickers.items():
                if 'USDT-SWAP' in sym:
                    vol = tick.get('quoteVolume', 0)
                    if vol and vol > (min_vol * 1_000_000):
                        valid_symbols.append(sym)
            
            res = []
            
            # Проходимся только по отфильтрованным
            for idx, sym in enumerate(valid_symbols):
                status_text.text(f"Анализ {sym}... (Осталось: {len(valid_symbols) - idx})")
                progress_bar.progress((idx + 1) / len(valid_symbols))
                
                try:
                    # 1. ГЛОБАЛЬНЫЙ ТРЕНД (Дневка)
                    data_d = ex.fetch_ohlcv(sym, "1d", limit=20)
                    if len(data_d) < 20: continue
                    
                    df_d = pd.DataFrame(data_d, columns=["t","o","h","l","c","v"])
                    adx_d = ta.trend.ADXIndicator(df_d["h"], df_d["l"], df_d["c"]).adx().iloc[-1]
                    global_trend = "Вверх" if adx_d > 25 else "Флэт"
                    
                    # 2. ТОЧКА ВХОДА (Выбранный ТФ)
                    data_t = ex.fetch_ohlcv(sym, tf, limit=20)
                    df_t = pd.DataFrame(data_t, columns=["t","o","h","l","c","v"])
                    
                    rsi = ta.momentum.RSIIndicator(df_t["c"]).rsi().iloc[-1]
                    adx = ta.trend.ADXIndicator(df_t["h"], df_t["l"], df_t["c"]).adx().iloc[-1]
                    atr = ta.volatility.AverageTrueRange(df_t["h"], df_t["l"], df_t["c"]).average_true_range().iloc[-1]
                    atr_pct = (atr / df_t["c"].iloc[-1]) * 100
                    
                    # --- ФАЗА И СИГНАЛ ---
                    if adx > 25:
                        phase = "Тренд"
                        if global_trend == "Вверх" and rsi < 40:
                            signal = "🟢 ВХОД В ЛОНГ (Откат)"
                            bot = "DCA Long"
                        elif global_trend == "Вверх" and rsi > 50:
                            signal = "⏳ ЖДАТЬ"
                            bot = "—"
                        else:
                            signal = "🔴 ВХОД В ШОРТ"
                            bot = "DCA Short"
                    else:
                        phase = "Боковик"
                        signal = "🟡 СЕТКА (Боковик)"
                        bot = "Grid"

                    # --- НАДЕЖНОСТЬ ---
                    base_coin = sym.replace('/USDT:USDT', '')
                    if base_coin in ["BTC", "ETH"]:
                        reliability = "🟢 Консервативная"
                    elif atr_pct > 3.0:
                        reliability = "🔴 Агрессивная"
                    else:
                        reliability = "🟡 Умеренная"
                        
                    tp = 1.5 if atr_pct < 3 else 2.5
                    step = round(atr_pct * 0.8, 1) if atr_pct > 1 else 1.0
                    
                    res.append({
                        "Монета": base_coin, 
                        "Цена": round(df_t["c"].iloc[-1], 4), 
                        "Глоб. Тренд": global_trend,
                        "Фаза": phase,
                        "Надежность": reliability,
                        "RSI": round(rsi,1), 
                        "ADX": round(adx,1), 
                        "Сигнал": signal,
                        "Бот": bot,
                        "Тейк %": tp, 
                        "Шаг %": step
                    })
                except Exception as e:
                    pass # Если монета глючная, просто пропускаем
                
                # Небольшая задержка, чтобы не превысить лимиты API
                time.sleep(0.05)
            
            progress_bar.empty()
            status_text.empty()
            
            if res:
                df_res = pd.DataFrame(res)
                
                # Сортируем по объему (или по сигналу) - давай по сигналу ЛОНГ, чтобы было видно лучшее
                df_res = df_res.sort_values(by=["Сигнал", "ADX"], ascending=[True, False])
                
                def color_signal(val):
                    if "ЛОНГ" in val: return 'color: #00ff00; font-weight: bold;'
                    elif "ШОРТ" in val: return 'color: #ff0000; font-weight: bold;'
                    elif "СЕТКА" in val: return 'color: #ffd700; font-weight: bold;'
                    else: return 'color: #aaaaaa;'
                
                st.dataframe(df_res.style.map(color_signal, subset=["Сигнал"]), use_container_width=True)
                st.success(f"Сканирование завершено! Найдено {len(res)} монет по фильтрам.")
            else:
                st.warning("Данные не загружены.")
        except Exception as e:
            st.error(f"Ошибка: {e}")

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
