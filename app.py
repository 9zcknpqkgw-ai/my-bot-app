import streamlit as st
import pandas as pd
import requests
import time
from ta.momentum import RSIIndicator
from ta.trend import ADXIndicator
from ta.volatility import AverageTrueRange

# --- НАСТРОЙКА ---
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
    border-radius: 10px;
    font-weight: 700;
}
</style>
""", unsafe_allow_html=True)

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
    html = '<div class="metric-card">'
    html += f'<div class="metric-label">{label}</div>'
    html += f'<div class="metric-value">{value}</div>'
    html += '</div>'
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
def get_data(symbol, limit=30):
    params = {"instId": symbol, "bar": "1D", "limit": str(limit)}
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

# --- БЭКТЕСТ DCA ---
def backtest_dca(symbol, days, tp_pct, step_pct, so_count, mart):
    df = get_data(symbol, limit=days)
    if df is None or len(df) < 20:
        return None
        
    base_amount = 10.0
    position = 0
    entry_price = 0
    total_invested = 0
    cycles = 0
    max_drawdown = 0
    current_capital = 1000
    
    for i in range(1, len(df)):
        price = df["c"].iloc[i]
        
        if position == 0:
            position = base_amount / price
            entry_price = price
            total_invested = base_amount
        else:
            avg_price = total_invested / position
            
            if price >= avg_price * (1 + tp_pct/100):
                profit = (price - avg_price) * position
                current_capital += profit
                cycles += 1
                position = 0
                entry_price = 0
                total_invested = 0
            elif price <= entry_price * (1 - step_pct/100) and total_invested < base_amount * so_count:
                add_amount = base_amount * mart
                position += add_amount / price
                total_invested += add_amount
                entry_price = price
                
        if position > 0:
            current_value = position * price
            drawdown = (total_invested - current_value) / total_invested * 100
            if drawdown > max_drawdown:
                max_drawdown = drawdown
                
    return {"Циклов": cycles, "Капитал": round(current_capital, 2), "Просадка (%)": round(max_drawdown, 2)}

# --- БЭКТЕСТ GRID ---
def backtest_grid(symbol, days, grid_count, lower_pct, upper_pct):
    df = get_data(symbol, limit=days)
    if df is None or len(df) < 20:
        return None

    start_price = df["c"].iloc[0]
    lower_bound = start_price * (1 - lower_pct/100)
    upper_bound = start_price * (1 + upper_pct/100)
    step = (upper_bound - lower_bound) / grid_count
    levels = [lower_bound + i * step for i in range(grid_count + 1)]
    
    capital = 1000
    position = 0
    buy_price = 0
    cycles = 0
    max_drawdown = 0
    
    for i in range(1, len(df)):
        price = df["c"].iloc[i]
        if lower_bound <= price <= upper_bound:
            high = df["h"].iloc[i]
            low = df["l"].iloc[i]
            for lvl in levels:
                if low <= lvl <= high:
                    if position == 0:
                        position = 10 / lvl
                        buy_price = lvl
                    elif lvl >= buy_price + step:
                        profit = (lvl - buy_price) * position
                        capital += profit
                        cycles += 1
                        position = 0
                        buy_price = 0
                        break 
        if position > 0:
            current_value = position * price
            invested = position * buy_price
            drawdown = (invested - current_value) / invested * 100
            if drawdown > max_drawdown:
                max_drawdown = drawdown
    return {"Циклов": cycles, "Капитал": round(capital, 2), "Просадка (%)": round(max_drawdown, 2)}

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
    
    if atr_pct < 1.5: tp = 1.0; tp_reason = "спокойный"
    elif atr_pct < 3.0: tp = 1.5; tp_reason = "стандарт"
    else: tp = 2.0; tp_reason = "волатильный"
        
    step = 2.0
    mart = 1.2
    so_count = 4

    reason = ""
    if adx > 25:
        if rsi < 40: signal = "🟢 ЛОНГ"; phase = "Тренд"; bot = "DCA Long"; reason = f"RSI={rsi:.0f} + ADX={adx:.0f}"
        elif rsi > 50: signal = "⏳ ЖДАТЬ"; phase = "Тренд"; bot = "Пауза"; reason = "Ждем отката"
        else: signal = "🔴 ШОРТ"; phase = "Тренд"; bot = "DCA Short"; reason = f"RSI={rsi:.0f} + ADX={adx:.0f}"
    else:
        signal = "🟡 НЕЙТРАЛЬНО"; phase = "Флэт"; bot = "Grid"; reason = f"ADX={adx:.0f} (боковик)"

    if not is_old: cls = "🔴 Молодая"
    elif coin in ("BTC", "ETH"): cls = "🟢 Консерв."
    elif atr_pct > 3: cls = "🔴 Агрессив."
    else: cls = "🟡 Умерен."
    
    return {"Монета": coin, "Цена": price, "Фаза": phase, "Класс": cls, "RSI": rsi, "ADX": adx, "Сигнал": signal, "Бот": bot, "TP": tp, "TP_Reason": tp_reason, "Step": step, "Mart": mart, "SO": so_count, "Reason": reason}

def color_sig(val):
    if "ЛОНГ" in str(val): return "color: #00ff87; font-weight: bold"
    if "ШОРТ" in str(val): return "color: #ff4d4f; font-weight: bold"
    if "НЕЙТРАЛЬНО" in str(val): return "color: #ffd700; font-weight: bold"
    return "color: #bbbbbb"

# --- МЕНЮ ---
with st.sidebar:
    st.title("OKX Manager")
    page = st.radio("Раздел", ["1. Главная", "2. Сканер", "3. ИИ-Центр", "4. DCA", "5. Grid", "6. Настройки"])

st.title(page)

# --- 1. ГЛАВНАЯ ---
if page == "1. Главная":
    st.subheader("Добрый день, брат!")
    cols = st.columns(4)
    with cols[0]: metric_card("Статус", "Онлайн")
    with cols[1]: metric_card("Баланс", "0 USDT")
    with cols[2]: metric_card("Боты", "0")
    with cols[3]: metric_card("Риск", "Низкий")

# --- 2. СКАНЕР ---
elif page == "2. Сканер":
    market = st.radio("Рынок:", ["Фьючерсы (SWAP)", "Спот"], horizontal=True)
    
    if st.button("Сканировать ТОП-10", use_container_width=True):
        res = []
        bar = st.progress(0)
        for i, coin in enumerate(COINS):
            sym = coin + "-USDT-SWAP" if market == "Фьючерсы (SWAP)" else coin + "-USDT"
            try:
                data = analyze(coin, sym, market)
                if data: res.append(data)
            except: pass
            bar.progress((i+1)/len(COINS))
        
        if res:
            df = pd.DataFrame(res)
            show_cols = ["Монета", "Цена", "RSI", "ADX", "Сигнал", "Класс"]
            styled = df[show_cols].style.format({"Цена": "{:.6f}", "RSI": "{:.2f}", "ADX": "{:.2f}"}).map(color_sig, subset=["Сигнал"])
            st.dataframe(styled, use_container_width=True, hide_index=True)

    # БЭКТЕСТ
    st.markdown("---")
    st.subheader("Бэктест на истории (90 дней)")
    bt_market = st.radio("Рынок для теста:", ["Фьючерсы (SWAP)", "Спот"], horizontal=True, key="bt_market")
    bt_strat = st.radio("Стратегия:", ["DCA", "Grid"], horizontal=True, key="bt_strat")
    
    c1, c2, c3, c4 = st.columns(4)
    if bt_strat == "DCA":
        bt_tp = c1.number_input("Тейк %", value=1.5, step=0.1)
        bt_step = c2.number_input("Шаг %", value=2.0, step=0.1)
        bt_so = c3.number_input("Кол-во СО", value=4, step=1)
        bt_mart = c4.number_input("Мартингейл", value=1.2, step=0.1)
    else:
        bt_grids = c1.number_input("Кол-во сеток", value=10, step=1)
        bt_low = c2.number_input("Нижн. граница %", value=10.0, step=1.0)
        bt_up = c3.number_input("Верхн. граница %", value=10.0, step=1.0)
    
    if st.button("Сделать бэктест ВСЕХ монет", use_container_width=True):
        with st.spinner("Прогоняем историю..."):
            bt_results = []
            for coin in COINS:
                sym = coin + "-USDT-SWAP" if bt_market == "Фьючерсы (SWAP)" else coin + "-USDT"
                res = backtest_dca(sym, 90, bt_tp, bt_step, int(bt_so), bt_mart) if bt_strat == "DCA" else backtest_grid(sym, 90, int(bt_grids), bt_low, bt_up)
                if res:
                    res["Монета"] = coin
                    bt_results.append(res)
            if bt_results:
                st.dataframe(pd.DataFrame(bt_results)[["Монета", "Циклов", "Капитал", "Просадка (%)"]], use_container_width=True, hide_index=True)

# --- 3. ИИ-ЦЕНТР (НОВЫЙ РАЗДЕЛ) ---
elif page == "3. ИИ-Центр":
    st.subheader("🤖 ИИ-Советник по ботам")
    st.write("Введите данные вашего бота, и ИИ скажет, что с ним делать.")
    
    c1, c2, c3 = st.columns(3)
    coin = c1.text_input("Монета (например, BTC)", value="BTC")
    invested = c2.number_input("Вложено (USDT)", value=131.39)
    current_price = c3.number_input("Текущая цена", value=76741.8)
    
    c4, c5 = st.columns(2)
    avg_price = c4.number_input("Средняя цена входа", value=77908.0)
    liq_price = c5.number_input("Цена ликвидации", value=58063.0)
    
    if st.button("Анализировать бота", use_container_width=True):
        # Расчет PnL
        pnl_pct = ((current_price - avg_price) / avg_price) * 100
        pnl_usd = invested * (pnl_pct / 100)
        
        # Расчет здоровья (упрощенная формула)
        health = 100
        if pnl_pct < 0: health -= abs(pnl_pct) * 3
        if current_price < avg_price: health -= 10
        if (current_price - liq_price) / current_price < 0.2: health -= 30 # близко к ликвидации
        
        health = max(0, min(100, health))
        
        # Логика советов
        if health > 70:
            status = "🟢 Работает по плану"
            advice = "Ждать. Бот в норме, просадка небольшая."
            color = "green"
        elif health > 40:
            status = "🟡 Внимание"
            advice = "Наблюдать. Есть просадка, но ликвидация далеко."
            color = "orange"
        else:
            status = "🔴 Срочно"
            advice = "Докупить маржу или закрыть часть позиции! Бот близок к ликвидации."
            color = "red"

        # Вывод
        st.markdown(f"### Здоровье: {health}/100")
        st.markdown(f"**Статус:** {status}")
        st.markdown(f"**Совет:** {advice}")
        
        st.markdown("---")
        st.write(f"Текущий PnL: **{pnl_usd:.2f} USDT** ({pnl_pct:.2f}%)")
        st.write(f"До ликвидации: **{((current_price - liq_price) / current_price * 100):.2f}%**")

# --- 4. DCA ---
elif page == "4. DCA":
    entry = st.number_input("Цена входа", value=100.0)
    count = st.number_input("Кол-во СО", value=4)
    step = st.number_input("Шаг %", value=2.0)
    if st.button("Рассчитать", use_container_width=True):
        rows, total = [], 0
        for i in range(int(count)):
            p = entry * (1 - step / 100 * i)
            a = 10.0 * (1.2 ** i)
            total += a
            rows.append({"Шаг": i + 1, "Цена": p, "Сумма": a})
        st.dataframe(pd.DataFrame(rows), use_container_width=True)
        st.success(f"Всего: {total:.2f} USDT")

# --- 5. GRID ---
elif page == "5. Grid":
    low = st.number_input("Нижняя", value=90.0)
    high = st.number_input("Верхняя", value=110.0)
    grids = st.number_input("Сеток", value=10)
    if st.button("Рассчитать", use_container_width=True):
        w = (high - low) / low * 100
        s = (high - low) / (grids - 1) / low * 100
        st.metric("Ширина", f"{w:.2f}%")
        st.metric("Шаг", f"{s:.2f}%")

# --- 6. НАСТРОЙКИ ---
elif page == "6. Настройки":
    st.subheader("Настройки Telegram")
    try:
        st.success("Настройки найдены в Secrets")
        st.code(f"Chat ID: {st.secrets['telegram']['chat_id']}")
    except:
        st.warning("Secrets не настроены:")
        st.session_state.tg_token = st.text_input("Bot Token")
        st.session_state.tg_chat = st.text_input("Chat ID")
    
    if st.button("Тест Telegram", use_container_width=True):
        if send_tg("Привет, брат! Тест."): st.success("Отправлено!")
        else: st.error("Ошибка.")
