import streamlit as st
import pandas as pd
import ccxt
import ta
import csv
from datetime import datetime
import os

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

# --- ИНИЦИАЛИЗАЦИЯ ЖУРНАЛА ---
JOURNAL_FILE = "journal.csv"
if not os.path.exists(JOURNAL_FILE):
    with open(JOURNAL_FILE, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["Дата", "Монета", "Действие", "Результат (USDT)", "Рекомендация"])

def log_decision(coin, action, result, recommendation):
    with open(JOURNAL_FILE, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([datetime.now().strftime("%d.%m %H:%M"), coin, action, result, recommendation])

# --- БОКОВОЕ МЕНЮ ---
st.sidebar.title("⚡ AI CENTER")
st.sidebar.markdown("---")
menu = st.sidebar.radio("Навигация", [
    "1. Главная", 
    "2. Сканер рынка", 
    "3. План DCA", 
    "4. План Grid", 
    "5. Капитал и риск",
    "6. Разобрать позицию",
    "7. Журнал решений",
    "8. Подключения"
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
    st.write("Система сама подбирает настройки под текущую волатильность (ATR) и тренд (ADX).")
    
    if st.button("🚀 Сканировать OKX", type="primary"):
        with st.spinner("Анализируем рынок..."):
            try:
                exchange = ccxt.okx()
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
                        
                        df['RSI'] = ta.momentum.RSIIndicator(df['c'], window=14).rsi()
                        adx_indicator = ta.trend.ADXIndicator(df['h'], df['l'], df['c'], window=14)
                        df['ADX'] = adx_indicator.adx()
                        df['ATR'] = ta.volatility.AverageTrueRange(df['h'], df['l'], df['c'], window=14).average_true_range()
                        
                        atr_pct = (df['ATR'].iloc[-1] / df['c'].iloc[-1]) * 100
                        rsi = df['RSI'].iloc[-1]
                        adx_val = df['ADX'].iloc[-1]
                        
                        # АДАПТИВНАЯ ЛОГИКА
                        if atr_pct < 1.5: tp = 1.0
                        elif atr_pct < 3.0: tp = 1.5
                        else: tp = 2.5
                            
                        step = round(atr_pct * 0.8, 1)
                        if step < 1.0: step = 1.0
                            
                        if adx_val > 30: martingale = 1.4
                        elif adx_val > 25: martingale = 1.3
                        else: martingale = 1.2
                            
                        if adx_val > 25:
                            phase = "Тренд"
                            rec = "DCA"
                            direction = "LONG" if rsi > 50 else "SHORT"
                        else:
                            phase = "Боковик"
                            rec = "Grid"
                            direction = "Нейтрально"

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
                            "Тейк %": tp,
                            "Шаг СО %": step,
                            "Мартингейл": martingale
                        })
                    except Exception:
                        pass
                
                if results:
                    df_res = pd.DataFrame(results)
                    st.dataframe(df_res, use_container_width=True)
                    st.success("✅ Настройки подобраны автоматически!")
                else:
                    st.warning("Монет не найдено.")
            except Exception as e:
                st.error(f"Ошибка подключения: {e}")

# ==========================================
# РАЗДЕЛ 3: ПЛАН DCA
# ==========================================
elif menu == "3. План DCA":
    st.title("План DCA и риск")
    with st.form("dca_form"):
        c1, c2, c3 = st.columns(3)
        entry = c1.number_input("Цена входа (USDT)", value=0.344, format="%.4f")
        capital = c2.number_input("Капитал на бота (USDT)", value=1000.0)
        first_buy = c3.number_input("Первый вход (USDT)", value=20.0)
        
        c4, c5, c6 = st.columns(3)
        so_count = c4.number_input("Кол-во доп. покупок (СО)", value=9, step=1)
        step = c5.number_input("Шаг между покупками (%)", value=2.0)
        tp = c6.number_input("Тейк от средней (%)", value=1.5)
        
        if st.form_submit_button("Рассчитать план", type="primary"):
            st.markdown("### 4 числа до запуска")
            ladder = []
            current_price = entry
            current_sum = first_buy
            total_buys = first_buy
            
            for i in range(1, int(so_count) + 1):
                current_price = current_price * (1 - step/100)
                current_sum = current_sum * 1.2
                total_buys += current_sum
                ladder.append({"Шаг": i, "Цена": round(current_price, 4), "Сумма": round(current_sum, 2)})
                
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Всего покупок", f"{round(total_buys, 1)} USDT")
            m2.metric("Нужно капитала", f"{capital} USDT" if capital > total_buys else "⚠️ МАЛО")
            m3.metric("Убыток при стопе 20%", f"-{round(total_buys*0.2, 1)} USDT")
            m4.metric("Глубина лестницы", f"{int(so_count) * step}%")
            
            st.dataframe(pd.DataFrame(ladder), use_container_width=True)

# ==========================================
# РАЗДЕЛ 4: ПЛАН GRID
# ==========================================
elif menu == "4. План Grid":
    st.title("План Grid")
    c1, c2 = st.columns(2)
    lower = c1.number_input("Нижняя граница", value=100.50)
    upper = c2.number_input("Верхняя граница", value=109.00)
    c3, c4 = st.columns(2)
    grids = c3.number_input("Число сеток", value=30, step=1)
    capital = c4.number_input("Капитал на бота", value=50.0)
    
    if st.button("Рассчитать Grid", type="primary"):
        width = ((upper - lower) / lower) * 100
        step_pct = width / grids
        budget = capital / grids
        
        m1, m2, m3 = st.columns(3)
        m1.metric("Ширина коридора", f"{round(width, 2)}%")
        m2.metric("Шаг сетки", f"{round(step_pct, 2)}%")
        m3.metric("Бюджет на сетку", f"{round(budget, 2)} USDT")
        
        if step_pct < 0.3:
            st.warning("⚠️ Шаг сетки меньше 0.3%. Комиссия съест прибыль!")

# ==========================================
# РАЗДЕЛ 5: КАПИТАЛ И РИСК
# ==========================================
elif menu == "5. Капитал и риск":
    st.title("Капитал и риск")
    total_cap = st.number_input("Мой капитал, USDT", value=5000.0)
    max_per_bot = st.slider("Макс. на 1 бота (% капитала)", 5, 50, 20)
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Лимит на 1 бота", f"{(total_cap * max_per_bot/100)} USDT", "Правило 20-25%")
    c2.metric("Свободно", f"{total_cap} USDT", "Весь баланс")
    c3.metric("Допустимый риск", f"{(total_cap * 0.25)} USDT", "Худший сценарий")
    
    new_bot_cap = st.number_input("Планируемый капитал нового бота", value=500.0)
    if new_bot_cap > (total_cap * max_per_bot/100):
        st.error("❌ СТОП. Превышен лимит риска на одного бота!")
    else:
        st.success("✅ Можно запускать. Риски в норме.")

# ==========================================
# РАЗДЕЛ 6: РАЗОБРАТЬ ПОЗИЦИЮ
# ==========================================
elif menu == "6. Разобрать позицию":
    st.title("Разобрать позицию")
    
    c1, c2, c3 = st.columns(3)
    coin = c1.text_input("Монета", value="CRV")
    current_price = c2.number_input("Текущая цена", value=0.3482, format="%.4f")
    avg_price = c3.number_input("Средняя цена входа", value=0.3500, format="%.4f")
    
    c4, пу c5 = st.columns(2)
    position_usdст = c4.number_input("Размер позиции (USDT)", value=75.0)
    drop_sim = c.")
5.slider("Симуляция падения цены (%)", 1, 30, 10)
    
    new_price =    current_price * ( else1 - drop_sim/100)
    
    if current_price > 0 and new_price > 0:
        loss_now = (avg_price - current_price) * (position_usd / current_price)
        loss_if_drops = (avg_price - new_price) * (position_usd / new_price)
    else:
        loss_now = 0
        loss_if_drops = 0
    
    st.markdown("### 4 действия")
    col_a, col_b, col_c, col_d = st.columns(4)
    
    if col_a.button("1. Оставить как есть", use_container_width=True):
        st.info(f"Убыток сейчас: **{loss_now:.2f}** USDT.\nПри падении на {drop_sim}%: **{loss_if_drops:.2f}** USDT.")
        log_decision(coin, "Оставить", f"{loss_now:.2f}", "Ждать")
        
    if col_b.button("2. Докупить 20 USDT", use_container_width=True):
        if current_price > 0:
            new_pos_usd = position_usd + 20
            new_avg = ((avg_price * (position_usd/avg_price)) + (current_price * (20/current_price))) / (position_usd/avg_price + 20/current_price)
            new_loss = (new_avg - new_price) * (new_pos_usd / new_price)
            st.warning(f"Новая средняя: **{new_avg:.4f}**.\nНовый убыток: **{new_loss:.2f}** USDT.")
            log_decision(coin, "Докупить 20", f"{loss_now:.2f}", "Снизить среднюю")

    if col_c.button("3. Продать 50%", use_container_width=True):
        st.warning(f"Зафиксировано убытка: **{loss_now/2:.2f}** USDT.\nСвободно: **{position_usd/2:.2f}** USDT.")
        log_decision(coin, "Продать 50%", f"{loss_now/2:.2f}", "Сократить риск")

    if col_d.button("4. Закрыть всё", use_container_width=True):
        st.error(f"Зафиксирован убыток: **{loss_now:.2f}** USDT.")
        log_decision(coin, "Закрыть всё", f"{loss_now:.2f}", "Принять убыток")

# ==========================================
# РАЗДЕЛ 7: ЖУРНАЛ РЕШЕНИЙ
# ==========================================
elif menu == "7. Журнал решений":
    st.title("Журнал решений")
    
    if os.path.exists(JOURNAL_FILE):
        try:
            df_journal = pd.read_csv(JOURNAL_FILE)
            if not df_journal.empty:
                st.dataframe(df_journal, use_container_width=True)
                if st.button("Очистить журнал"):
                    os.remove(JOURNAL_FILE)
                    st.rerun()
            else:
                st.info("Журнал пока пуст.")
        except:
             st.info("Журнал пока:
        st.info("Журнал пока пуст.")

# ==========================================
# РАЗДЕЛ 8: ПОДКЛЮЧЕНИЯ
# ==========================================
elif menu == "8. Подключения":
    st.title("Подключения")
    st.write("Для работы с ботами введите API-ключи (только чтение).")
    
    with st.expander("Подключить OKX", expanded=True):
        api_key = st.text_input("API Key", type="password")
        secret_key = st.text_input("Secret Key", type="password")
        passphrase = st.text_input("Passphrase", type="password")
        
        if st.button("Проверить и загрузить"):
            if api_key and secret_key and passphrase:
                st.success("✅ Ключи сохранены в системе! (Демо-режим)")
            else:
                st.error("Пожалуйста, заполните все три поля.")
