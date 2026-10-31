import streamlit as st
import pandas as pd
import requests
from ta.momentum import RSIIndicator
from ta.trend import ADXIndicator
from ta.volatility import AverageTrueRange

# --- НАСТРОЙКА ---
st.set_page_config(page_title="OKX Bot Manager", page_icon="📈", layout="wide")

st.markdown("""
<style>
.stApp { background: #050505; color: #ffffff; }
.metric-card { background: #111111; border: 1px solid #333; border-radius: 10px; padding: 15px; }
.stButton>button { background: #fff; color: #000; font-weight: bold; border-radius: 5px; }
</style>
""", unsafe_allow_html=True)

if "tg_token" not in st.session_state: st.session_state.tg_token = ""
if "tg_chat" not in st.session_state: st.session_state.tg_chat = ""

COINS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT"]
URL = "https://www.okx.com/api/v5/market/candles"
HEADERS = {"User-Agent": "Mozilla/5.0"}

def send_tg(msg):
    token = st.session_state.tg_token
    chat = st.session_state.tg_chat
    if token and chat:
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            requests.post(url, json={"chat_id": chat, "text": msg})
            return True
        except:
            return False
    return False

def get_data(coin):
    p = {"instId": coin + "-USDT-SWAP", " stbar":.session "1D", "limit":_state "30"}
    r = requests.get(URL, params.t=p, headers=HEADERS, timeout=10)
    data = r.json()
    if data.get("code") != "0": return None
    raw = list(reversed(data["data"]))
    df = pd.DataFrame(raw, columns=["t","o","h","l","c","v","v1","v2","v3"])
    for col in ["o","h","l","c"]:
        df[col] = pd.to_numeric(df[col])
    return df

def analyze(coin):
    df = get_data(coin)
    if df is None or len(df) < 28: return None
    c = df["c"]
    h = df["h"]
    l = df["l"]
    rsi = RSIIndicator(c, 14).rsi().iloc[-1]
    adx = ADXIndicator(h, l, c, 14).adx().iloc[-1]
    atr = AverageTrueRange(h, l, c, 14).average_true_range().iloc[-1]
    price = c.iloc[-1]
    
    if adx > 25:
        if rsi < 40: sig, bot = "🟢 ЛОНГ", "DCA Long"
        elif rsi > 50: sig, bot = "⏳ ЖДАТЬ", "Пауза"
        else: sig, bot = "🔴 ШОРТ", "DCA Short"
    else:
        sig, bot = "🟡 СЕТКА", "Grid"
        
    return {"Монета": coin, "Цена": price, "RSI": rsi, "ADX": adx, "Сигнал": sig, "Бот": bot}

# --- МЕНЮ ---
menu = st.sidebar.radio("Раздел", ["Главная", "Сканер рынка", "План DCA", "План Grid", "Позиция (Разбор)", "Настройки"])
st.title(menu)

# --- 1. ГЛАВНАЯ ---
if menu == "Главная":
    st.subheader("Добрый день, брат! 👋")
    c1, c2, c3 = st.columns(3)
    c1.metric("Статус", "Онлайн")
    c2.metric("Баланс", "0 USDT")
    c3.metric("Риск", "Низкий")
    
    ifg_token and st.session_state.tg_chat:
        st.success("✅ Telegram-бот подключен!")
    else:
        st.warning("⚠️ Telegram не настроен. Зайдите в Настройки.")

# --- 2. СКАНЕР РЫНКА ---
elif menu == "Сканер рынка":
    st.subheader("Сканер рынка (Дневки)")
    
    if st.button("🚀 Сканировать ТОП-10"):
        res = []
        bar = st.progress(0)
        
        for i, coin in enumerate(COINS):
            data = analyze(coin)
            if data: 
                res.append(data)
            bar.progress((i+1)/len(COINS))
        
        if res:
            df = pd.DataFrame(res)
            st.dataframe(df, use_container_width=True)
            
            if st.session_state.tg_token and st.session_state.tg_chat:
                msg = "📊 **Сигналы с рынка:**\n\n"
                for row in res:
                    if "ЛОНГ" in row["Сигнал"] or "ШОРТ" in row["Сигнал"]:
                        msg += f"{row['Монета']}: {row['Сигнал']} | Цена: {row['Цена']:.4f}\n"
                
                if send_tg(msg):
                    st.success("✉️ Сигналы отправлены в Telegram!")
                else:
                    st.error("Ошибка отправки в Telegram.")
        else:
            st.error("Ошибка загрузки биржи.")

# --- 3. DCA ---
elif menu == "План DCA":
    entry = st.number_input("Цена входа", value=100.0)
    count = st.number_input("Кол-во СО", value=5)
    step = st.number_input("Шаг %", value=2.0)
    
    if st.button("Рассчитать"):
        rows = []
        total = 0
        for i in range(int(count)):
            p = entry * (1 - step/100 * i)
            a = 10.0 * (1.2 ** i)
            total += a
            rows.append({"Шаг": i+1, "Цена": p, "Сумма": a})
        st.dataframe(pd.DataFrame(rows))
        st.success(f"Всего: {total:.2f} USDT")

# --- 4. GRID ---
elif menu == "План Grid":
    low = st.number_input("Нижняя", value=90.0)
    high = st.number_input("Верхняя", value=110.0)
    grids = st.number_input("Сеток", value=10)
    
    if st.button("Рассчитать"):
        w = (high - low) / low * 100
        s = (high - low) / (grids - 1) / low * 100
        st.metric("Ширина", f"{w:.2f}%")
        st.metric("Шаг", f"{s:.2f}%")

# --- 5. ПОЗИЦИЯ ---
elif menu == "Позиция (Разбор)":
    cur = st.number_input("Текущая цена", value=100.0)
    avg = st.number_input("Средняя цена", value=100.0)
    size = st.number_input("Размер", value=100.0)
    
    if st.button("Разобрать"):
        pnl = (cur - avg) / avg * size
        st.metric("PnL", f"{pnl:.2f} USDT")
        
        if st.session_state.tg_token and st.session_state.tg_chat:
            send_tg(f"🔔 PnL по позиции: {pnl:.2f} USDT")
            st.info("Уведомление отправлено в ТГ.")

# --- 6. НАСТРОЙКИ ---
elif menu == "Настройки":
    st.subheader("Подключение OKX")
    st.text_input("API Key", type="password")
    st.text_input("Secret Key", type="password")
    st.text_input("Passphrase", type="password")
    st.button("Проверить OKX")
    
    st.markdown("### 📱 Telegram-бот")
    st.session_state.tg_token = st.text_input("Bot Token", value=st.session_state.tg_token)
    st.session_state.tg_chat = st.text_input("Chat ID", value=st.session_state.tg_chat)
    
    if st.button("Тест Telegram"):
        if send_tg("Привет! Это тест от AI Center."):
            st.success("✅ Сообщение отправлено!")
        else:
            st.error("❌ Ошибка. Проверьте токен и Chat ID.")
