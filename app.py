import html
import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from plotly.subplots import make_subplots
from ta.momentum import RSIIndicator
from ta.trend import ADXIndicator
from ta.volatility import AverageTrueRange

st.set_page_config(page_title="OKX Terminal", page_icon="⚡", layout="wide", initial_sidebar_state="auto")
API = "https://www.okx.com/api/v5"
JOURNAL = Path("journal.csv")
COINS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT", "TON", "TRX", "LTC", "NEAR", "APT", "ARB", "OP", "SUI", "PEPE", "INJ"]
TP, STEP, SO, MART, FEE = 1.5, 2.0, 4, 1.2, 0.0005
GREEN, RED, BLUE, YELLOW = "#00EFA7", "#FF5575", "#49BFFF", "#FFD166"
MARKETS = ["Спот", "Фьючерсы (SWAP)"]
BARS = {"15m": 900000, "30m": 1800000, "1H": 3600000, "4H": 14400000, "1Dutc": 86400000}
JCOLS = ["Дата UTC", "Монета", "Инструмент", "Рынок", "Направление", "Здоровье", "Статус", "Совет", "PnL, USDT", "PnL, %", "До ликвидации, %"]
for key, value in {"tg_token": "", "tg_chat": "", "auto_ai": True, "auto_scan": True, "ai_result": None, "scan_result": None, "bt_result": None}.items():
    if key not in st.session_state:
        st.session_state[key] = value

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
:root {color-scheme:dark;}
html,body,.stApp {font-family:Inter,sans-serif;}
.stApp {color:#E8EEF8;background:radial-gradient(900px 450px at 0% 0%,rgba(0,239,167,.07),transparent 65%),#060910;}
[data-testid="stHeader"] {background:#090E18!important;}
[data-testid="stSidebar"], [data-testid="stSidebar"]>div {background:#0B101B!important;opacity:1!important;}
[data-testid="stSidebar"] {border-right:1px solid #243047;}
h1,h2,h3,h4 {color:#F0F5FF!important;letter-spacing:-.025em;}
[data-testid="stMarkdownContainer"] p,[data-testid="stWidgetLabel"] p,[data-testid="stCaptionContainer"] p,[data-testid="stRadio"] p {color:#D3DDED!important;}
[data-testid="stSidebar"] [data-testid="stRadio"] label {background:#151F30!important;border:1px solid #2B3A53;border-radius:12px;padding:10px 12px;margin-bottom:6px;}
[data-testid="stSidebar"] [data-testid="stRadio"] label:hover {border-color:#00EFA7;}
[data-testid="stTextInput"] input,[data-testid="stNumberInput"] input {background:#121C2C!important;color:#F2F6FF!important;-webkit-text-fill-color:#F2F6FF!important;}
[data-testid="stNumberInput"] button {background:#1B2A40!important;color:#F2F6FF!important;}
[data-baseweb="select"]>div {background:#121C2C!important;color:#F2F6FF!important;border-color:#2B3A53!important;}
[data-baseweb="select"] span {color:#F2F6FF!important;}
.stButton>button,.stFormSubmitButton>button {min-height:46px;border:0!important;border-radius:12px!important;background:linear-gradient(110deg,#00EFA7,#3BBEFF)!important;transition:transform .18s ease,box-shadow .18s ease;}
.stButton>button p,.stFormSubmitButton>button p {color:#031019!important;font-weight:700!important;}
.stButton>button:hover,.stFormSubmitButton>button:hover {transform:translateY(-2px);box-shadow:0 8px 26px rgba(0,239,167,.2);}
.stDownloadButton>button {background:#142339!important;border:1px solid #355475!important;border-radius:12px!important;}
.stDownloadButton>button p {color:#E8EEF8!important;}
.panel,.kpi {background:linear-gradient(135deg,#152034,#0D1420);border:1px solid #27344B;border-radius:16px;padding:18px;margin-bottom:14px;}
.panel-title {color:#F2F6FF;font-size:1.1rem;font-weight:700;margin-bottom:8px;}
.panel-text,.kpi-label {color:#A9B7CE;line-height:1.6;}
.kpi-value {font-size:1.5rem;font-weight:800;overflow-wrap:anywhere;}
[data-testid="stDataFrame"] {border:1px solid #27344B;border-radius:12px;overflow:hidden;}
@media(max-width:768px){.block-container{padding:1.2rem 1rem 4rem!important;}h1{font-size:2rem!important;}.panel,.kpi{padding:15px;}.kpi-value{font-size:1.3rem;}}
</style>
""", unsafe_allow_html=True)


def panel(title, text):
    st.markdown(f'<div class="panel"><div class="panel-title">{html.escape(str(title))}</div><div class="panel-text">{html.escape(str(text))}</div></div>', unsafe_allow_html=True)


def card(label, value, color="#F1F6FF"):
    st.markdown(f'<div class="kpi"><div class="kpi-label">{html.escape(str(label))}</div><div class="kpi-value" style="color:{color}">{html.escape(str(value))}</div></div>', unsafe_allow_html=True)


def chart(fig, height=420):
    fig.update_layout(template="plotly_dark", height=height, paper_bgcolor="#0C1320", plot_bgcolor="#0C1320", font=dict(color="#DCE6F5", family="Inter,sans-serif"), margin=dict(l=15,r=15,t=50,b=25), legend=dict(orientation="h", y=1.03, x=0))
    fig.update_xaxes(gridcolor="#202C40")
    fig.update_yaxes(gridcolor="#202C40")
    st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False})


@st.cache_resource
def locks():
    return {"api": threading.Lock(), "journal": threading.RLock(), "last": [0.0]}


def api_get(endpoint, params=None):
    error = "Нет ответа OKX"
    for attempt in range(4):
        shared = locks()
        with shared["api"]:
            time.sleep(max(0, 0.17 - (time.monotonic() - shared["last"][0])))
            shared["last"][0] = time.monotonic()
        try:
            response = requests.get(API + endpoint, params=params, timeout=(8,25), headers={"User-Agent": "OKX-Terminal/3.0"})
            if response.status_code == 429:
                error = "Лимит запросов OKX"
                time.sleep(1 + attempt)
                continue
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") == "0":
                return payload.get("data", [])
            error = f"OKX {payload.get('code')}: {payload.get('msg', '')}"
        except (requests.RequestException, ValueError) as exc:
            error = str(exc)
        time.sleep(.6 * (attempt + 1))
    raise RuntimeError(error)


def inst_type(market):
    return "SPOT" if market == "Спот" else "SWAP"


@st.cache_data(ttl=3600, show_spinner=False)
def instruments(market):
    rows = api_get("/public/instruments", {"instType": inst_type(market)})
    result = {}
    for row in rows:
        symbol = row.get("instId", "")
        valid = row.get("quoteCcy") == "USDT" if market == "Спот" else row.get("settleCcy") == "USDT" and row.get("ctType") == "linear" and symbol.endswith("-USDT-SWAP")
        if valid and row.get("state") == "live":
            result[symbol] = row
    if not result:
        raise RuntimeError("Нет доступных USDT-инструментов")
    return result


@st.cache_data(ttl=45, show_spinner=False)
def tickers(market):
    return {row["instId"]: row for row in api_get("/market/tickers", {"instType": inst_type(market)})}


@st.cache_data(ttl=15, show_spinner=False)
def latest_price(symbol):
    rows = api_get("/market/ticker", {"instId": symbol})
    if not rows or float(rows[0].get("last", 0) or 0) <= 0:
        raise RuntimeError("Текущая цена недоступна")
    return float(rows[0]["last"]), rows[0].get("ts", "")


def candle_frame(rows):
    if not rows:
        raise RuntimeError("OKX не вернул свечи")
    cols = ["ts","o","h","l","c","vol","volCcy","volQuote","confirm"]
    df = pd.DataFrame(rows, columns=cols)
    for col in cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df[df["confirm"] == 1].dropna(subset=["ts","o","h","l","c"])
    df = df[(df[["o","h","l","c"]] > 0).all(axis=1)]
    df = df.drop_duplicates("ts").sort_values("ts")
    df["time"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.reset_index(drop=True)


@st.cache_data(ttl=90, show_spinner=False)
def recent(symbol, bar):
    df = candle_frame(api_get("/market/candles", {"instId":symbol,"bar":bar,"limit":"300"}))
    if len(df) < 60:
        raise RuntimeError("Нужно минимум 60 закрытых свечей")
    return df


@st.cache_data(ttl=1800, show_spinner=False)
def history(symbol, bar, start, end):
    cursor, rows = end, []
    pages = int((end-start) // BARS[bar] // 100) + 10
    for _ in range(pages):
        batch = api_get("/market/history-candles", {"instId":symbol,"bar":bar,"after":str(cursor),"limit":"100"})
        if not batch:
            break
        rows.extend(batch)
        oldest = min(int(row[0]) for row in batch)
        if oldest <= start:
            break
        if oldest >= cursor:
            raise RuntimeError("Ошибка пагинации истории OKX")
        cursor = oldest
    df = candle_frame(rows)
    df = df[(df.ts >= start) & (df.ts < end)].reset_index(drop=True)
    if len(df) < 30:
        raise RuntimeError("Мало истории для теста")
    return df


def indicators(df):
    df = df.copy()
    if len(df) < 60:
        raise RuntimeError("Мало свечей для индикаторов")
    df["RSI"] = RSIIndicator(df.c, window=14).rsi()
    adx = ADXIndicator(df.h, df.l, df.c, window=14)
    df["ADX"], df["+DI"], df["-DI"] = adx.adx(), adx.adx_pos(), adx.adx_neg()
    df["ATR"] = AverageTrueRange(df.h, df.l, df.c, window=14).average_true_range()
    return df


def price_chart(df, title):
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[.56,.22,.22], vertical_spacing=.045)
    fig.add_trace(go.Candlestick(x=df.time,open=df.o,high=df.h,low=df.l,close=df.c,name="Цена",increasing_line_color=GREEN,decreasing_line_color=RED), row=1,col=1)
    fig.add_trace(go.Scatter(x=df.time,y=df.RSI,name="RSI 14",line=dict(color=BLUE)),row=2,col=1)
    for val, color in [(30,GREEN),(70,RED)]:
        fig.add_hline(y=val,line_dash="dot",line_color=color,row=2,col=1)
    for col,color in [("ADX",YELLOW),("+DI",GREEN),("-DI",RED)]:
        fig.add_trace(go.Scatter(x=df.time,y=df[col],name=col,line=dict(color=color,width=1.6)),row=3,col=1)
    fig.add_hline(y=25,line_dash="dot",row=3,col=1)
    fig.update_yaxes(range=[0,100],row=2,col=1)
    fig.update_layout(title=title,xaxis_rangeslider_visible=False)
    chart(fig,680)


# TELEGRAM: без повторных попыток POST, чтобы не дублировать сообщение
# при неоднозначном сетевом тайм-ауте.
def credentials():
    token, chat = st.session_state.tg_token, st.session_state.tg_chat
    try:
        section = st.secrets.get("telegram", {})
        token, chat = section.get("token") or token, section.get("chat_id") or chat
    except Exception:
        pass
    return str(token).strip(), str(chat).strip()


def send_tg(message):
    token, chat = credentials()
    if not token or not chat:
        return False, "Не заданы Telegram token и chat_id"
    try:
        response = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id":chat,"text":message[:4000]},timeout=(8,15))
        payload = response.json()
        if response.ok and payload.get("ok"):
            return True, "Сообщение отправлено"
        code = payload.get("error_code", response.status_code)
        messages = {400:"Проверьте Chat ID и нажмите Start у бота",401:"Проверьте токен бота",403:"Бот заблокирован или не имеет доступа к чату",429:"Telegram ограничил частоту сообщений"}
        return False, f"Telegram {code}: {messages.get(code, 'отправка отклонена')}"
    except requests.Timeout:
        return False, "Тайм-аут Telegram: доставка неизвестна; перед повтором проверьте чат"
    except Exception:
        return False, "Не удалось связаться с Telegram; секреты в ошибку не выводятся"


def deliver(message, enabled):
    if not enabled:
        return "Не отправлялось: автоотправка выключена"
    ok, text = send_tg(message)
    return ("✅ " if ok else "⚠️ ") + text


def journal_read():
    with locks()["journal"]:
        if not JOURNAL.exists():
            return pd.DataFrame(columns=JCOLS)
        try:
            return pd.read_csv(JOURNAL)
        except pd.errors.EmptyDataError:
            return pd.DataFrame(columns=JCOLS)


def journal_save(record):
    with locks()["journal"]:
        frame = pd.concat([journal_read(),pd.DataFrame([record])],ignore_index=True)
        columns = JCOLS + [col for col in frame.columns if col not in JCOLS]
        frame = frame.reindex(columns=columns)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",newline="",suffix=".csv",dir=str(JOURNAL.parent),delete=False) as file:
                temporary = file.name
                frame.to_csv(file,index=False)
            os.replace(temporary,JOURNAL)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def dca_table(entry, base, mode):
    rows, total, qty = [], 0., 0.
    for i in range(SO+1):
        price = entry*(1-STEP/100*i) if mode=="От первого входа" else entry*(1-STEP/100)**i
        amount = base*MART**i
        total += amount
        qty += amount/price
        average = total/qty
        target = total*(1+FEE)*(1+TP/100)/(qty*(1-FEE))
        rows.append({"Ордер":"База" if i==0 else f"СО {i}","Цена":price,"Сумма, USDT":amount,"Всего, USDT":total,"Средняя цена":average,"TP с комиссиями":target})
    return pd.DataFrame(rows)


def scan_one(symbol, market, bar, info, ticker):
    df = indicators(recent(symbol,bar))
    last = df.iloc[-1]
    volume = float(ticker.get("volCcy24h",0) or 0)
    if market!="Спот":
        volume *= float(ticker.get("last",0) or 0)
    listing = int(info.get("listTime",0) or 0)
    age = (time.time()*1000-listing)/86400000 if listing else None
    rsi,adx = float(last.RSI),float(last.ADX)
    if volume<10000000:
        signal, reason = "Низкая ликвидность", "Оборот ниже 10 млн USDT"
    elif age is not None and age<180:
        signal, reason = "Ждать", "Возраст инструмента меньше 180 дней"
    elif adx<25:
        signal, reason = "Grid-кандидат", "ADX ниже 25; не гарантия бокового рынка"
    elif last["+DI"]>last["-DI"] and 35<=rsi<=55:
        signal, reason = "Long-кандидат", "+DI выше -DI, RSI в зоне фильтра"
    elif market!="Спот" and last["-DI"]>last["+DI"] and 45<=rsi<=65:
        signal, reason = "Short-кандидат", "-DI выше +DI, RSI в зоне фильтра"
    else:
        signal, reason = "Ждать", "Условия технического фильтра не выполнены"
    return {"Инструмент":symbol,"Цена":float(ticker.get("last") or last.c),"Объём 24ч, USDT":volume,"RSI":rsi,"ADX":adx,"ATR, %":float(last.ATR/last.c*100),"Сигнал":signal,"Причина":reason,"TP, %":TP}


def position_analysis(symbol, market, side, qty, entry, price, liquidation, margin, opening_fee):
    sign = 1 if side=="Long" else -1
    gross = sign*qty*(price-entry)
    net = gross-opening_fee-qty*price*FEE
    pnl_pct = net/(qty*entry)*100
    distance = None
    if market!="Спот" and liquidation>0:
        distance = sign*(price-liquidation)/price*100
    health = 100-min(45,max(0,-pnl_pct)*3)
    if distance is not None:
        if distance<=0: health=0
        elif distance<5: health=min(health,15)
        elif distance<10: health-=50
        elif distance<20: health-=30
        elif distance<35: health-=12
    health = float(np.clip(health,0,100))
    if distance is not None and distance<=0:
        status,advice = "Указанная граница достигнута", "Проверьте фактический статус позиции и правильность цены ликвидации на OKX."
    elif health<=40:
        status,advice = "Высокий риск", "Проверьте лимит убытка и возможность сокращения позиции. Не усредняйте автоматически. Добавление маржи не устраняет торговый риск."
    elif health<=70:
        status,advice = "Требует внимания", "Проверьте резерв для СО и соблюдение плана. Не увеличивайте позицию только для улучшения средней цены."
    else:
        status,advice = "Критические пороги не сработали", "Сверьте позицию с вашим планом. Это условная оценка, не прогноз и не гарантия безопасности."
    return dict(symbol=symbol,market=market,side=side,qty=qty,entry=entry,price=price,liquidation=liquidation,opening_fee=opening_fee,net=net,pnl_pct=pnl_pct,distance=distance,health=health,status=status,advice=advice,roi=net/margin*100 if margin>0 and market!="Спот" else None,time=utc_now())


def position_message(result):
    distance = "не задана / не применяется" if result["distance"] is None else f'{result["distance"]:.2f}%'
    return (f'📊 Анализ OKX\n{result["symbol"]} | {result["market"]} | {result["side"]}\n'
            f'Время UTC: {result["time"]}\nЦена: {result["price"]:.8f}\n'
            f'Количество: {result["qty"]:.8f}\nЗдоровье: {result["health"]:.0f}/100\n'
            f'PnL с оценкой комиссии выхода: {result["net"]:.4f} USDT ({result["pnl_pct"]:.2f}%)\n'
            f'До ликвидации: {distance}\n\n{result["status"]}\n{result["advice"]}')


def position_charts(result):
    health = result["health"]
    color = GREEN if health>70 else YELLOW if health>40 else RED
    fig = go.Figure(go.Indicator(mode="gauge+number",value=health,number={"suffix":"/100"},title={"text":"Условная оценка"},gauge={"axis":{"range":[0,100]},"bar":{"color":color},"steps":[{"range":[0,40],"color":"#492333"},{"range":[40,70],"color":"#4A3D24"},{"range":[70,100],"color":"#143E36"}]}))
    c1,c2 = st.columns([1,1.2])
    with c1: chart(fig,300)
    with c2:
        card("PnL после оценки комиссии выхода",f'{result["net"]:,.4f} USDT',GREEN if result["net"]>=0 else RED)
        card("PnL к номиналу входа",f'{result["pnl_pct"]:.2f}%')
        if result["distance"] is not None: card("До указанной ликвидации",f'{result["distance"]:.2f}%',YELLOW)
        if result["roi"] is not None: card("PnL / введённая маржа",f'{result["roi"]:.2f}%')
    panel(result["status"],result["advice"])
    lo,hi = min(result["entry"],result["price"])*.8,max(result["entry"],result["price"])*1.2
    if result["market"]!="Спот" and result["liquidation"]>0:
        lo,hi = min(lo,result["liquidation"]*.95),max(hi,result["liquidation"]*1.05)
    prices = np.linspace(max(lo,1e-12),hi,200)
    sign = 1 if result["side"]=="Long" else -1
    values = sign*result["qty"]*(prices-result["entry"])-result["opening_fee"]-result["qty"]*prices*FEE
    fig = go.Figure(go.Scatter(x=prices,y=values,name="Сценарный PnL",line=dict(color=BLUE,width=3)))
    fig.add_hline(y=0,line_dash="dot")
    for value,name,color in [(result["entry"],"Вход",BLUE),(result["price"],"Текущая",YELLOW)]:
        fig.add_vline(x=value,line_color=color,annotation_text=name)
    if result["market"]!="Спот" and result["liquidation"]>0:
        fig.add_vline(x=result["liquidation"],line_color=RED,annotation_text="Ликвидация")
    fig.update_layout(title="Сценарный PnL — не история доходности",xaxis_title="Цена",yaxis_title="USDT")
    chart(fig)


# БЭКТЕСТ: модель Long без плеча. Путь свечи: open -> low -> high -> close.
# Он явно задан, но не является известным фактическим порядком сделок.
def backtest(df, strategy, initial, base, mode, low_pct, high_pct, grid_count):
    cash, fees, cycles, realized = float(initial),0.,0,0.
    qty,cost,next_so = 0.,0.,1
    dca_rows, lots, curve = [],{},[]
    start_price = float(df.iloc[0].o)
    levels = np.linspace(start_price*(1-low_pct/100),start_price*(1+high_pct/100),grid_count+1)
    active = [i for i in range(grid_count) if levels[i]<start_price]
    grid_amount = initial/max(len(active),1)/(1+FEE)

    def equity(price):
        position = qty if strategy=="DCA" else sum(lot["qty"] for lot in lots.values())
        return cash+position*price*(1-FEE)

    def point(row,price,stage):
        curve.append({"Время UTC":row.time,"Этап":stage,"Equity":equity(price)})

    for _,row in df.iterrows():
        opening,low,high,closing = float(row.o),float(row.l),float(row.h),float(row.c)
        point(row,opening,"Open")
        if strategy=="DCA":
            sold_at_open = False
            if qty>0:
                target = cost*(1+TP/100)/(qty*(1-FEE))
                if opening>=target:
                    gross = qty*opening
                    fee = gross*FEE
                    net = gross-fee
                    cash+=net
                    fees+=fee
                    realized+=net-cost
                    cycles+=1
                    qty,cost=0.,0.
                    sold_at_open=True
                    point(row,opening,"TP на открытии")
            if qty==0 and not sold_at_open and base*(1+FEE)<=cash:
                fee=base*FEE
                qty,cost=base/opening,base+fee
                cash-=cost
                fees+=fee
                next_so=1
                dca_rows=dca_table(opening,base,mode).to_dict("records")
                point(row,opening,"Базовый вход")
            if qty>0:
                while next_so<=SO and low<=dca_rows[next_so]["Цена"]:
                    order=dca_rows[next_so]
                    fill=min(opening,float(order["Цена"]))
                    point(row,fill,"Перед СО")
                    amount=float(order["Сумма, USDT"])
                    fee=amount*FEE
                    if amount+fee>cash+1e-9: break
                    cash-=amount+fee
                    qty+=amount/fill
                    cost+=amount+fee
                    fees+=fee
                    next_so+=1
                    point(row,fill,"После СО")
                point(row,low,"Low")
                target=cost*(1+TP/100)/(qty*(1-FEE))
                if high>=target:
                    gross=qty*target
                    fee=gross*FEE
                    net=gross-fee
                    cash+=net
                    fees+=fee
                    realized+=net-cost
                    cycles+=1
                    qty,cost=0.,0.
                    point(row,target,"TP")
                else:
                    point(row,high,"High")
        else:
            # Существующие продажи, уже доступные на открытии.
            sold=set()
            for i,lot in list(lots.items()):
                if opening>=lot["target"]:
                    gross=lot["qty"]*lot["target"]
                    fee=gross*FEE
                    cash+=gross-fee
                    fees+=fee
                    realized+=gross-fee-lot["cost"]
                    cycles+=1
                    del lots[i]
                    sold.add(i)
            point(row,opening,"После продаж на открытии")
            # Уровни покупки обрабатываются сверху вниз по пути к low.
            for i in reversed(active):
                if i in lots or i in sold or low>levels[i]: continue
                fill=min(opening,float(levels[i]))
                point(row,fill,"Перед Grid-покупкой")
                fee=grid_amount*FEE
                debit=grid_amount+fee
                if debit>cash+1e-9: continue
                cash-=debit
                fees+=fee
                lots[i]={"qty":grid_amount/fill,"cost":debit,"target":float(levels[i+1])}
                point(row,fill,"После Grid-покупки")
            point(row,low,"Low")
            # На выбранном пути high происходит после low.
            for i in sorted(list(lots)):
                lot=lots[i]
                if high>=lot["target"]:
                    gross=lot["qty"]*lot["target"]
                    fee=gross*FEE
                    cash+=gross-fee
                    fees+=fee
                    realized+=gross-fee-lot["cost"]
                    cycles+=1
                    del lots[i]
                    point(row,lot["target"],"Grid-продажа")
            point(row,high,"High")
        point(row,closing,"Close")
    curve=pd.DataFrame(curve)
    peaks=curve.Equity.cummax().clip(lower=initial)
    dd=peaks-curve.Equity
    final=float(curve.Equity.iloc[-1])
    metrics={"Циклов":cycles,"Итоговая equity, USDT":round(final,2),"Общий PnL, USDT":round(final-initial,2),"Реализованный PnL, USDT":round(realized,2),"Доходность, %":round((final/initial-1)*100,2),"Макс. просадка, USDT":round(float(dd.max()),2),"Макс. просадка, %":round(float((dd/peaks*100).max()),2),"Уплаченные комиссии, USDT":round(fees,4)}
    return metrics,curve


with st.sidebar:
    st.markdown("## ⚡ OKX Terminal")
    st.caption("Аналитика • правила • Telegram")
    page=st.radio("Раздел",["Главная","Сканер","ИИ-Центр","DCA","Grid","Бэктест","Журнал решений","Настройки"],label_visibility="collapsed")
    st.divider()
    st.checkbox("Telegram после анализа",key="auto_ai")
    st.checkbox("Telegram после сканирования",key="auto_scan")
    st.caption("Отправка сразу после действия. Фонового мониторинга нет.")
    st.caption("DCA: 1.5% / 2% / 4 СО / ×1.2")
st.title(page)

if page=="Главная":
    panel("Терминал аналитики OKX","Реальные свечи, индикаторы, расчёты и журнал. Автоотправка отчётов в Telegram включена по умолчанию.")
    c1,c2,c3=st.columns(3)
    with c1: card("Режим","Аналитика",BLUE)
    with c2: card("Приватный API","Не подключён",YELLOW)
    with c3: card("DCA","База + 4 СО",GREEN)
    st.info("Приложение не размещает ордера и не отслеживает фактические исполнения ботов. Баланс аккаунта не запрашивается.")
    panel("Уведомления","Анализ позиции отправляется сразу после расчёта. Сканер отправляет один сводный отчёт после завершения. Настройки Telegram берутся из Secrets.")

elif page=="Сканер":
    market=st.radio("Рынок",MARKETS,horizontal=True)
    bar=st.selectbox("Таймфрейм",list(BARS),index=4)
    st.caption("Индикаторы по закрытым свечам. Сигналы — технические кандидаты, не торговые команды. TP всегда 1.5%.")
    if st.button("Сканировать и отправить отчёт",use_container_width=True):
        try:
            info,ticker_map=instruments(market),tickers(market)
            wanted=[f"{coin}-USDT"+("-SWAP" if market!="Спот" else "") for coin in COINS]
            symbols=[s for s in wanted if s in info and s in ticker_map]
            rows,errors=[],[]
            progress=st.progress(0.)
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures={pool.submit(scan_one,s,market,bar,info[s],ticker_map[s]):s for s in symbols}
                for i,future in enumerate(as_completed(futures),1):
                    try: rows.append(future.result())
                    except Exception as exc: errors.append(f"{futures[future]}: {exc}")
                    progress.progress(i/max(len(symbols),1))
            progress.empty()
            rows.sort(key=lambda r:r["Объём 24ч, USDT"],reverse=True)
            stamp=utc_now()
            saved=dict(rows=rows,errors=errors,missing=[s for s in wanted if s not in symbols],market=market,bar=bar,time=stamp,tg="Нет результатов — отчёт не отправлялся")
            if rows:
                lines=[f"📡 Сканер OKX | {market} | {bar}",f"UTC: {stamp}",f"Успешно: {len(rows)} из {len(wanted)}"]
                for row in rows:
                    lines.append(f'{row["Инструмент"]}: {row["Сигнал"]} | RSI {row["RSI"]:.0f}, ADX {row["ADX"]:.0f}')
                lines.append("DCA: TP 1.5%, шаг 2%, база + 4 СО, ×1.2. Не торговая команда.")
                saved["message"]="\n".join(lines)
                saved["tg"]=deliver(saved["message"],st.session_state.auto_scan)
            st.session_state.scan_result=saved
        except Exception as exc: st.error(str(exc))
    saved=st.session_state.scan_result
    if saved:
        st.caption(f'{saved["market"]} · {saved["bar"]} · {saved["time"]}')
        st.info(saved["tg"])
        if saved["missing"]: st.warning("Недоступны: "+", ".join(saved["missing"]))
        if saved["errors"]:
            with st.expander("Ошибки инструментов"): st.write("\n".join(saved["errors"]))
        if saved["rows"]:
            frame=pd.DataFrame(saved["rows"])
            st.dataframe(frame.style.format({"Цена":"{:,.8f}","Объём 24ч, USDT":"{:,.0f}","RSI":"{:.1f}","ADX":"{:.1f}","ATR, %":"{:.2f}"}),use_container_width=True,hide_index=True)
            symbol=st.selectbox("График",frame["Инструмент"].tolist())
            try: price_chart(indicators(recent(symbol,saved["bar"])),f'{symbol} · {saved["bar"]}')
            except Exception as exc: st.error(str(exc))
            if st.button("Повторно отправить сводку"):
                saved["tg"]=deliver(saved["message"],True)
                st.info(saved["tg"])

elif page=="ИИ-Центр":
    panel("Анализ позиции по правилам","После расчёта результат сразу записывается в журнал и отправляется в Telegram, если автоотправка включена. Это анализатор по формулам, не языковая модель.")
    market=st.radio("Рынок позиции",MARKETS,horizontal=True,key="ai_market")
    try:
        info=instruments(market)
        options=sorted(info)
        default="BTC-USDT"+("-SWAP" if market!="Спот" else "")
        symbol=st.selectbox("Инструмент",options,index=options.index(default) if default in options else 0,key=f"ai_symbol_{market}")
    except Exception as exc:
        st.error(str(exc)); st.stop()
    side="Long" if market=="Спот" else st.radio("Направление",["Long","Short"],horizontal=True)
    source=st.radio("Цена для анализа",["Автоматически с OKX","Вручную"],horizontal=True)
    manual_price=0.
    if source=="Вручную":
        manual_price=st.number_input("Текущая цена",min_value=0.,value=0.,format="%.8f",key=f"manual_{symbol}")
    with st.form(f"position_{symbol}"):
        c1,c2=st.columns(2)
        qty=c1.number_input("Количество базовой монеты",min_value=0.,value=.001,format="%.8f",help="Для SWAP вводите эквивалент в монетах, не число контрактов.")
        entry=c2.number_input("Средняя цена входа",min_value=0.,value=0.,format="%.8f")
        liquidation,margin=0.,0.
        if market!="Спот":
            c3,c4=st.columns(2)
            liquidation=c3.number_input("Ликвидация из OKX, 0 — неизвестна",min_value=0.,format="%.8f")
            margin=c4.number_input("Текущая маржа, USDT",min_value=0.,value=0.)
        opening_fee=st.number_input("Уплаченные комиссии входа, USDT",min_value=0.,value=0.,format="%.6f")
        submitted=st.form_submit_button("Анализировать → журнал + Telegram",use_container_width=True)
    if submitted:
        if qty<=0 or entry<=0: st.error("Введите положительные количество и цену входа.")
        else:
            try:
                price=latest_price(symbol)[0] if source=="Автоматически с OKX" else manual_price
                if price<=0: raise ValueError("Текущая цена должна быть больше нуля")
                result=position_analysis(symbol,market,side,qty,entry,price,liquidation,margin,opening_fee)
                result["price_source"]=source
                record={"Дата UTC":result["time"],"Монета":symbol.split("-")[0],"Инструмент":symbol,"Рынок":market,"Направление":side,"Здоровье":round(result["health"],1),"Статус":result["status"],"Совет":result["advice"],"PnL, USDT":round(result["net"],6),"PnL, %":round(result["pnl_pct"],3),"До ликвидации, %":result["distance"]}
                # Ошибка CSV не блокирует Telegram и наоборот.
                try:
                    journal_save(record)
                    result["journal_status"]="✅ Анализ записан в журнал"
                except Exception as exc:
                    result["journal_status"]=f"⚠️ Журнал не записан: {exc}"
                result["message"]=position_message(result)
                result["tg"]=deliver(result["message"],st.session_state.auto_ai)
                st.session_state.ai_result=result
            except Exception as exc: st.error(str(exc))
    result=st.session_state.ai_result
    if result:
        st.divider()
        st.caption(f'Последний расчёт: {result["symbol"]} · {result["market"]} · {result["side"]} · {result["time"]} UTC. После изменения полей выполните новый анализ.')
        st.info(result["journal_status"])
        st.info(result["tg"])
        position_charts(result)
        st.caption("PnL не включает funding и реализованные сделки бота. Выход оценён с комиссией 0.05%. Здоровье — условная шкала, не вероятность успеха.")
        if st.button("Повторно отправить этот анализ"):
            result["tg"]=deliver(result["message"],True)
            st.info(result["tg"])
        with st.expander("Реальные свечи и индикаторы позиции"):
            bar=st.selectbox("Таймфрейм графика позиции",list(BARS),index=2)
            try: price_chart(indicators(recent(result["symbol"],bar)),f'{result["symbol"]} · {bar}')
            except Exception as exc: st.error(str(exc))

elif page=="DCA":
    panel("Ваши параметры DCA","TP 1.5%, шаг 2%, базовый ордер + 4 СО. Каждый следующий ордер в 1.2 раза больше предыдущего.")
    entry=st.number_input("Цена первого входа",min_value=.00000001,value=100.,format="%.8f")
    base=st.number_input("Базовый ордер, USDT",min_value=1.,value=10.)
    mode=st.radio("Как считать шаг",["От первого входа","От предыдущего ордера"],horizontal=True)
    table=dca_table(entry,base,mode)
    st.dataframe(table.style.format({col:"{:,.8f}" for col in table.columns if col!="Ордер"}),hide_index=True,use_container_width=True)
    card("Резерв с комиссиями входа",f'{table["Всего, USDT"].iloc[-1]*(1+FEE):.4f} USDT',GREEN)
    st.caption("Средняя цена = общие суммы покупки / общее количество монет. TP с комиссиями даёт чистые +1.5% к затратам на вход. Калькулятор показывает Long-сетку.")
    fig=go.Figure(go.Bar(x=table["Ордер"],y=table["Цена"],marker_color=GREEN,name="Цена",text=table["Сумма, USDT"].map(lambda v:f"{v:.2f} USDT")))
    fig.update_layout(title="Уровни и размеры ордеров DCA")
    chart(fig)

elif page=="Grid":
    panel("Арифметическая Grid-сетка","10 интервалов — это 11 уровней. Процент шага зависит от цены уровня.")
    c1,c2,c3=st.columns(3)
    low=c1.number_input("Нижняя граница",min_value=.00000001,value=90.,format="%.8f")
    high=c2.number_input("Верхняя граница",min_value=.00000001,value=110.,format="%.8f")
    count=c3.number_input("Интервалов",min_value=2,max_value=100,value=10)
    if high<=low: st.error("Верхняя граница должна быть выше нижней")
    else:
        levels=np.linspace(low,high,int(count)+1)
        table=pd.DataFrame({"Уровень":np.arange(len(levels)),"Цена":levels})
        st.dataframe(table,hide_index=True,use_container_width=True)
        card("Шаг в цене",f"{(high-low)/count:.8f}",BLUE)
        fig=go.Figure(go.Scatter(x=table["Уровень"],y=table["Цена"],mode="lines+markers",line=dict(color=BLUE)))
        fig.update_layout(title="Уровни Grid")
        chart(fig)

elif page=="Бэктест":
    st.warning("Модель Long без плеча. SWAP — только ценовая история: funding, маржа и ликвидация не моделируются. Внутри свечи принят путь open → low → high → close. Он не известен из OHLC и влияет на результат; это не тиковый тест.")
    market=st.radio("Рынок истории",MARKETS,horizontal=True,key="bt_market")
    try:
        info=instruments(market)
        wanted=[f"{coin}-USDT"+("-SWAP" if market!="Спот" else "") for coin in COINS]
        options=[s for s in wanted if s in info]
        if not options: raise RuntimeError("Нет инструментов для теста")
    except Exception as exc:
        st.error(str(exc)); st.stop()
    selected=st.multiselect("Инструменты",options,default=options[:1])
    strategy=st.radio("Стратегия",["DCA","Grid"],horizontal=True)
    c1,c2,c3=st.columns(3)
    bar=c1.selectbox("Таймфрейм",list(BARS))
    days=c2.number_input("Дней истории",min_value=1,max_value=180,value=30)
    initial=c3.number_input("Начальная сумма, USDT",min_value=10.,value=1000.)
    base,mode,lp,hp,gc=10.,"От первого входа",10.,10.,10
    if strategy=="DCA":
        st.caption("TP 1.5%, шаг 2%, 4 СО, ×1.2. Вход нового цикла на открытии свечи; сигналы Сканера не используются. TP учитывает обе комиссии.")
        base=st.number_input("Базовый ордер, USDT",min_value=1.,value=10.,key="bt_base")
        mode=st.radio("Шаг СО",["От первого входа","От предыдущего ордера"],horizontal=True,key="bt_mode")
    else:
        c1,c2,c3=st.columns(3)
        lp=c1.number_input("Нижняя граница от старта, %",min_value=.1,max_value=90.,value=10.)
        hp=c2.number_input("Верхняя граница от старта, %",min_value=.1,max_value=200.,value=10.)
        gc=int(c3.number_input("Интервалов сетки",min_value=2,max_value=100,value=10))
        st.caption("Старт в USDT, без начального запаса монет. Активны buy-уровни ниже стартовой цены. Пары уровней фиксированы; сетка не перестраивается.")
    expected=int(days*86400000/BARS[bar])
    st.caption(f"Около {expected:,} свечей на монету. Загрузка многих монет на 15m может занять несколько минут.")
    if st.button("Запустить бэктест",use_container_width=True):
        reserve=base*sum(MART**i for i in range(SO+1))*(1+FEE)
        if not selected: st.error("Выберите инструмент")
        elif strategy=="DCA" and reserve>initial: st.error("Не хватает резерва на базу и все 4 СО с комиссиями")
        else:
            end=int(time.time()*1000)//BARS[bar]*BARS[bar]
            start=end-int(days)*86400000
            rows,curves,errors=[],{},[]
            progress=st.progress(0.)
            for index,symbol in enumerate(selected,1):
                try:
                    with st.spinner(f"Загрузка и расчёт {symbol}"):
                        df=history(symbol,bar,start,end)
                        metrics,curve=backtest(df,strategy,initial,base,mode,lp,hp,gc)
                        rows.append({"Инструмент":symbol,**metrics,"Свечей":len(df),"Покрытие, %":round(min(100,len(df)/max(expected,1)*100),1),"Начало UTC":str(df.iloc[0].time),"Последняя свеча UTC":str(df.iloc[-1].time),"Пропуски":"Да" if (df.ts.diff().dropna()!=BARS[bar]).any() else "Нет"})
                        curves[symbol]=curve
                except Exception as exc: errors.append(f"{symbol}: {exc}")
                progress.progress(index/len(selected))
            progress.empty()
            st.session_state.bt_result=dict(rows=rows,curves=curves,errors=errors,title=f"{strategy} · {market} · {bar}")
    saved=st.session_state.bt_result
    if saved:
        st.caption(saved["title"])
        if saved["errors"]:
            with st.expander("Ошибки теста"): st.write("\n".join(saved["errors"]))
        if saved["rows"]:
            table=pd.DataFrame(saved["rows"])
            st.dataframe(table,hide_index=True,use_container_width=True)
            symbol=st.selectbox("Кривая капитала",list(saved["curves"]))
            curve=saved["curves"][symbol]
            fig=go.Figure(go.Scatter(x=curve["Время UTC"],y=curve.Equity,name="Equity",line=dict(color=GREEN,width=2)))
            fig.update_layout(title=f"{symbol}: equity с открытой позицией",yaxis_title="USDT")
            chart(fig)
            st.caption("Equity: денежный остаток + позиция после оценки комиссии выхода. Просадка измеряется от предыдущего пика equity. Уплаченные комиссии не включают ещё не совершённое закрытие. Отдельный тест каждой монеты использует весь указанный капитал — это не портфельный тест.")
            st.download_button("Скачать результаты",table.to_csv(index=False).encode("utf-8-sig"),file_name="backtest.csv",mime="text/csv",use_container_width=True)

elif page=="Журнал решений":
    panel("История анализов","Каждое нажатие анализа сохраняет отдельную запись. Изменение полей без анализа запись не создаёт. Время — UTC.")
    try:
        table=journal_read()
        if table.empty: st.info("Журнал пуст")
        else:
            if "Монета" in table:
                chosen=st.multiselect("Фильтр монет",sorted(table["Монета"].dropna().astype(str).unique()))
                if chosen: table=table[table["Монета"].astype(str).isin(chosen)]
            card("Записей в выборке",len(table))
            st.dataframe(table.iloc[::-1],hide_index=True,use_container_width=True)
            st.caption("PnL записей не суммируется: это могут быть повторные снимки одной позиции.")
            st.download_button("Скачать журнал CSV",table.to_csv(index=False).encode("utf-8-sig"),file_name="journal.csv",mime="text/csv",use_container_width=True)
    except Exception as exc: st.error(f"Ошибка чтения журнала: {exc}")
    st.warning("Локальный journal.csv не является гарантированным постоянным хранилищем в облаке. Делайте выгрузки. Журнал общий для экземпляра приложения; для персональных журналов нужны авторизация и база данных.")

elif page=="Настройки":
    panel("Telegram","Токен и Chat ID из Secrets имеют приоритет. Данные ниже — только для текущей сессии, если Secrets отсутствуют.")
    has_secrets=False
    try:
        section=st.secrets.get("telegram",{})
        has_secrets=bool(section.get("token") and section.get("chat_id"))
    except Exception: pass
    if has_secrets: st.success("Telegram token и chat_id найдены в Secrets")
    else:
        st.text_input("Bot Token",type="password",key="tg_token")
        st.text_input("Chat ID",key="tg_chat")
    st.caption("Автоотправка после анализа и сканирования включается переключателями слева. Новое нажатие анализа создаёт новый отчёт; обычное переключение страниц сообщений не отправляет.")
    if st.button("Тест Telegram",use_container_width=True):
        ok,text=send_tg("✅ OKX Terminal: Telegram подключён. Анализ и сканирование отправляют отчёты после нажатия соответствующих кнопок.")
        if ok: st.success(text)
        else: st.error(text)
    st.code('[telegram]\ntoken = "ВАШ_ТОКЕН"\nchat_id = "ВАШ_CHAT_ID"',language="toml")
    st.caption("Этот блок вводится в Secrets приложения, а не публикуется в GitHub. Бот должен быть запущен кнопкой Start в Telegram.")
    panel("Ограничения","Нет фонового мониторинга, приватного подключения аккаунта, слежения за исполнениями TP/СО. Анализатор использует введённые параметры позиции. Комиссия модели 0.05% может отличаться от вашего тарифа.")
