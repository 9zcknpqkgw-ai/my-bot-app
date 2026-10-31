import streamlit as st
import pandas as pd
import ccxt

# Настройка страницы
st.set_page_config(page_title="Центр Управления Ботами", layout="wide", page_icon="🤖")

# --- ТЕМНАЯ ТЕМА ---
st.markdown("""
<style>
    .stApp { background-color: #0e1117; color: #fafafa; }
    .stButton>button { background-color: #2e7d32; color: white; border-radius: 8px; font-weight: bold; }
    .stButton>button:hover { background-color: #1b5e20; }
    div[data-testid="stMetric"] { background-color: #1e1e24; padding: 15px; border-radius: 10px; border: 1px solid #333; }
</style>
""", unsafe_allow_html=True)

# --- БОКОВОЕ МЕНЮ ---
st.sidebar.title("ЦЕНТР УПРАВЛЕНИЯ")
menu = st.sidebar.radio("Навигация", ["1. Главная", "2. Сканер рынка"])

# ==========================================
# РАЗДЕЛ 1: ГЛАВНАЯ
# ==========================================
if menu == "1. Главная":
    st.title("Добро пожаловать в Центр Управления!")
    c1, c2, c3 = st.columns(3)
    c1.metric("Статус системы", "Онлайн", "🟢")
    c2.metric("Активных ботов", "0", "Нет")
    c3.metric("Доступно бирж", "OKX", "1")
    st.info("👈 Перейдите в раздел «Сканер рынка», чтобы найти точки входа.")

# ==========================================
# РАЗДЕЛ 2: СКАНЕР РЫНКА (С ПРОКСИ)
# ==========================================
elif menu == "2. Сканер рынка":
    st.title("Сканер рынка")
    st.write("Сканирует весь рынок OKX через прокси (обход блокировки IP).")
    
    min_volume = st.number_input("Мин. объем торгов (млн $)", value=1.0, step=1.0)
    
    if st.button("🚀 Сканировать OKX", type="primary"):
        with st.spinner("Загружаем данные с биржи через прокси..."):
            try:
                # СОЗДАЕМ КЛИЕНТ С ПРОКСИ
                exchange = ccxt.okx({
                    'proxies': {
                        'http': 'http://188.245.226.105:8090/proxy_url.php?caller=https://ccxt.com&url=', # <--- СЮДА ВСТАВЛЯЕШЬ ПРОКСИ
                        'https': 'http://188.245.226.105:8090/proxy_url.php?caller=https://ccxt.com&url=',
                    },
                    'timeout': 30000, # Увеличиваем таймаут, так как прокси может быть медленным
                })
                
                # Получаем ВСЕ тикеры разом
                tickers = exchange.fetch_tickers()
                
                results = []
                for symbol, ticker in tickers.items():
                    # Фильтруем только фьючерсы USDT
                    if 'USDT-SWAP' not in symbol: continue
                    
                    vol = ticker.get('quoteVolume', 0)
                    if vol is None or vol < (min_volume * 1_000_000): continue
                    
                    # Считаем изменение цены за 24ч (волатильность)
                    change_24h = ticker.get('percentage', 0)
                    
                    base_coin = symbol.replace('/USDT:USDT', '')
                    
                    # Простая логика
                    if change_24h > 0:
                        direction = "LONG (Рост)"
                        bot_type = "DCA"
                    else:
                        direction = "SHORT (Падение)"
                        bot_type = "DCA"
                        
                    reliability = "🟢 Высокая" if vol > 50_000_000 else "🟡 Средняя"

                    results.append({
                        "Монета": base_coin,
                        "Цена": ticker['last'],
                        "Объем (млн)": round(vol / 1_000_000, 1),
                        "Изм. 24ч (%)": round(change_24h, 2),
                        "Надежность": reliability,
                        "Бот": bot_type,
                        "Рекомендация": direction
                    })
                
                if results:
                    # Сортируем по объему (самые ликвидные сверху)
                    df_res = pd.DataFrame(results).sort_values(by="Объем (млн)", ascending=False)
                    st.dataframe(df_res.head(20), use_container_width=True)
                else:
                    st.warning("Монет по фильтрам не найдено. Попробуйте уменьшить объем.")

            except Exception as e:
                st.error(f"Ошибка: {e}")
