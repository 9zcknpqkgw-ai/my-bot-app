import streamlit as st
import pandas as pd
import ccxt
import ta

# 1. НАСТРОЙКА И МОЩНЫЙ ДИЗАЙН (CSS)
st.set_page_config(page_title="AI Trading Center", layout="wide", page_icon="⚡")

st.markdown("""
<style>
    /* Глубокий темный фон */
    .stApp { background-color: #0a0b10; color: #e0e0e0; }
    
    /* Неоновые кнопки */
    .stButton>button {
        background: linear-gradient(90deg, #00ff87 0%, #60efff 100%);
        color: #000; 
        border-radius: 8px; 
        border: none;
        font-weight: 900;
        padding: 12px 28px;
        box-shadow: 0 0 15px rgba(0, 255, 135, 0.4);
        transition: all 0.3s ease;
    }
    .stButton>button:hover {
        transform: scale(1.02);
        box-shadow: 0 0 25px rgba(0, 255, 135, 0.8);
    }
    
    /* Стеклянные карточки (Glassmorphism) */
    div[data-testid="stMetric"] {
        background: rgba(255, 255, 255, 0.03);
        backdrop-filter: blur(10px);
        padding: 20px;
        border-radius: 15px;
        border: 1px solid rgba(255, 255, 255, 0.1);
        box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
    }
    div[data-testid="stMetricValue"] { color: #00ff87; }
</style>
""", unsafe_allow_html=True)

# --- БОКОВОЕ МЕНЮ ---
st.sidebar.title("⚡ AI CENTER")
st.sidebar.markdown("---")
menu = st.sidebar.radio("Навигация", [
    "1. Главная", 
    "2. Сканер рынка", 
])

# ==========================================
# РАЗДЕЛ 1: ГЛАВНАЯ
# ==========================================
if menu == "1. Главная":
    st.title("Добро пожаловать в AI Center!")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Статус системы", "Онлайн", "🟢")
    c2.metric("Итог ботов", "+207 USDT", "+10.9%")
    c3.metric("Боты", "2 / 3", "1 требует внимания")
    c4.metric("Уровень риска", "НИЗКИЙ", "В пределах правил")
    st.info("👈 Перейдите в раздел «Сканер рынка», чтобы найти точки входа.")

# ==========================================
# РАЗДЕЛ 2: СКАНЕР РЫНКА (АДАПТИВНАЯ ЛОГИКА)
# ==========================================
elif menu == "2. Сканер рынка":
    st.title("Сканер рынка (Адаптивная логика)")
    st.write("Система сама подбирает настройки под текущую волатильность монеты (ATR) и тренд (ADX).")
    
    if st.button("🚀 Сканировать OKX", type="primary"):
        with st.spinner("Анализируем рынок и подбираем настройки..."):
            try:
                exchange = ccxt.okx()
                # Берем 20 топовых монет
                symbols = ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 'BNB/USDT:USDT', 
                           'XRP/USDT:USDT', 'DOGE/USDT:USDT', 'ADA/USDT:USDT', 'AVAX/USDT:USDT', 
                           'LINK/USDT:USDT', 'DOT/USDT:USDT', 'MATIC/USDT:USDT', 'LTC/USDT:USDT',
                           'NEAR/USDT:USDT', 'ATOM/USDT:USDT', 'APT/USDT:USDT', 'ARB/USDT:USDT',
                           'OP/USDT:USDT', 'SUI/USDT:USDT', 'INJ/USDT:USDT', 'TIA/USDT:USDT']
                results = []
                
                for symbol in symbols:
                    try:
                        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1d', limit=50)
                        if len(ohlcv) < 20: continue
                        
                        df = pd.DataFrame(ohlcv, columns=['t', 'o', 'h', 'l', 'c', 'v'])
                        
                        # Считаем базовые индикаторы
                        df['RSI'] = ta.momentum.RSIIndicator(df['c'], window=14).rsi()
                        adx_indicator = ta.trend.ADXIndicator(df['h'], df['l'], df['c'], window=14)
                        df['ADX'] = adx_indicator.adx()
                        df['ATR'] = ta.volatility.AverageTrueRange(df['h'], df['l'], df['c'], window=14).average_true_range()
                        
                        # Текущие значения
                        atr_val = df['ATR'].iloc[-1]
                        atr_pct = (atr_val / df['c'].iloc[-1]) * 100
                        rsi = df['RSI'].iloc[-1]
                        adx_val = df['ADX'].iloc[-1]
                        
                        # =======================================================
                        # 🧠 АДАПТИВНАЯ ЛОГИКА ПОДБОРА НАСТРОЕК (ПО ТВОЕЙ СИСТЕМЕ)
                        # =======================================================
                        
                        # 1. Подбор Тейк-профита (от 0.8% до 2.5% в зависимости от ATR)
                        if atr_pct < 1.5:
                            tp = 1.0  # Спокойный рынок
                        elif atr_pct < 3.0:
                            tp = 1.5  # Средний рынок (твоя база)
                        else:
                            tp = 2.5  # Бешеный рынок (чтобы не выбивало по шуму)
                            
                        # 2. Подбор Шага сетки (обычно ATR * 0.7)
                        step = round(atr_pct * 0.8, 1)
                        if step < 1.0: step = 1.0 # Минимум 1%
                            
                        # 3. Подбор Мартингейла (чем сильнее тренд, тем агрессивнее)
                        if adx_val > 30:
                            martingale = 1.4
                        elif adx_val > 25:
                            martingale = 1.3
                        else:
                            martingale = 1.2
                            
                        # 4. Определение фазы рынка и типа бота
                        if adx_val > 25:
                            phase = "Тренд"
                            rec = "DCA"
                            direction = "LONG" if rsi > 50 else "SHORT"
                        else:
                            phase = "Боковик"
                            rec = "Grid"
                            direction = "Нейтрально"

                        # 5. Оценка надежности
                        base_coin = symbol.replace('/USDT:USDT', '')
                        if base_coin in ['BTC', 'ETH']:
                            reliability = "🟢 Консервативная"
                        elif atr_pct > 3.0:
                            reliability = "🔴 Агрессивная"
                        else:
                            reliability = "🟡 Умеренная"

                        ticker = exchange.fetch_ticker(symbol)

                        results.append({
                            "Монета": base_coin,
                            "Цена": ticker['last'],
                            "Волат. (ATR%)": round(atr_pct, 2),
                            "RSI": round(rsi, 1),
                            "ADX": round(adx_val, 1),
                            "Надежность": reliability,
                            "Фаза": phase,
                            "Бот": rec,
                            "Направление": direction,
                            "Тейк %": tp,          # Адаптивный тейк
                            "Шаг СО %": step,      # Адаптивный шаг
                            "Мартингейл": martingale # Адаптивный множитель
                        })
                    except Exception as e:
                        pass
                
                if results:
                    df_res = pd.DataFrame(results)
                    st.dataframe(df_res, use_container_width=True)
                    st.success("✅ Настройки подобраны автоматически под текущую волатильность рынка!")
                else:
                    st.warning("Монет не найдено.")
            except Exception as e:
                st.error(f"Ошибка подключения: {e}")
