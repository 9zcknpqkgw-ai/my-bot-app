import os
import json
import time
import math
import uuid
import hmac
import html
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import requests
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(page_title="OKX Terminal Pro", layout="wide")
PAGES = ["Главная", "Сканер", "DCA", "Grid", "Открытая позиция", "Журнал", "Настройки"]
COINS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT", "TRX", "LTC", "NEAR", "APT", "ARB", "OP", "SUI", "PEPE", "INJ"]
API = "https://www.okx.com/api/v5"
HOUR = 3_600_000
DB_READY = False


def secret(key, default=""):
    try:
        return st.secrets.get(key, os.getenv(key, default))
    except Exception:
        return os.getenv(key, default)


DB_URL = str(secret("DATABASE_URL", secret("DB_URL", ""))).strip()
DB_FILE = str(secret("SQLITE_PATH", "bots.sqlite3"))


def now():
    return datetime.now(timezone.utc).isoformat()


def num(value, default=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


def fmt(value, digits=2):
    return "—" if value is None else f"{value:,.{digits}f}"


def sign(direction):
    return {"Long": 1, "Short": -1, "Neutral": 0}.get(direction, 0)


def age(value):
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600)
    except (ValueError, TypeError):
        return float("inf")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def design():
    st.markdown("""<style>
    .stApp{background:radial-gradient(1000px 600px at 8% -10%,rgba(0,255,157,.09),transparent 60%),radial-gradient(900px 600px at 100% 0%,rgba(88,101,242,.12),transparent 55%),#05070c!important;color:#e8ecf4;color-scheme:dark}
    .block-container{max-width:1400px;padding-top:1.4rem;padding-bottom:3rem}
    h1,h2,h3,h4{color:#edf3ff!important;letter-spacing:-.035em}
    [data-testid="stMarkdownContainer"] p,[data-testid="stMarkdownContainer"] li{color:#edf3ff}
    [data-testid="stCaptionContainer"] p{color:#b7c4d8!important}
    [data-testid="stWidgetLabel"] p,[data-testid="stCheckbox"] p,[data-testid="stExpander"] summary p{color:#edf3ff!important}
    [data-testid="stSidebar"]{background:#090f1b!important;border-right:1px solid #29384f}
    .glass{background:linear-gradient(130deg,#12272c,#151a2c);border:1px solid #30465c;border-radius:20px;padding:22px;margin-bottom:18px}
    .glass h2{margin:0}.glass p{color:#bac7db!important;margin-bottom:0}
    [data-testid="stMetric"]{background:linear-gradient(145deg,#171c29,#0b0e16);border:1px solid #2b3a50;border-radius:16px;padding:16px}
    [data-testid="stMetricLabel"] p,[data-testid="stMetricLabel"] span{color:#b7c4d8!important}
    [data-testid="stMetricValue"] div{color:#edf3ff!important}
    .stButton button,.stFormSubmitButton button,.stDownloadButton button{background:#f5f8ff!important;color:#142033!important;border:1px solid #b9c7da!important;border-radius:11px;min-height:44px;font-weight:700}
    .stButton button p,.stFormSubmitButton button p,.stDownloadButton button p{color:inherit!important}
    .stButton button:disabled,.stFormSubmitButton button:disabled{background:#cbd5e1!important;color:#475569!important;opacity:1!important}
    [class*="st-key-action_"][class*="_long"] button{background:#166534!important;color:white!important;border:2px solid #4ade80!important}
    [class*="st-key-action_"][class*="_short"] button{background:#991b1b!important;color:white!important;border:2px solid #f87171!important}
    [class*="st-key-action_"][class*="_neutral"] button{background:#facc15!important;color:#302500!important;border:2px solid #eab308!important}
    [data-testid="stTextInput"] input,[data-testid="stNumberInput"] input,[data-testid="stTextArea"] textarea{background:white!important;color:#172033!important;-webkit-text-fill-color:#172033!important}
    [data-testid="stNumberInput"] button{background:#eaf0fa!important;color:#172033!important}
    [data-testid="stSelectbox"] [data-baseweb="select"]>div{background:white!important;color:#172033!important}
    [data-testid="stSelectbox"] span,[data-testid="stSelectbox"] input{color:#172033!important;-webkit-text-fill-color:#172033!important}
    [role="listbox"],[role="option"]{background:white!important;color:#172033!important}
    [data-testid="stRadio"] [role="radiogroup"]>label{background:white!important;border:2px solid #cbd5e1;border-radius:10px;padding:8px 11px!important;margin:3px!important}
    [data-testid="stRadio"] [role="radiogroup"]>label p{color:#172033!important;font-weight:700!important}
    [data-testid="stRadio"] label:has(input:checked){border-color:#2563eb!important}
    .st-key-DCAdirection [role="radiogroup"]>label:nth-of-type(1),.st-key-Griddirection [role="radiogroup"]>label:nth-of-type(1){background:#dcfce7!important;border-color:#16a34a!important}
    .st-key-DCAdirection [role="radiogroup"]>label:nth-of-type(2),.st-key-Griddirection [role="radiogroup"]>label:nth-of-type(2){background:#fee2e2!important;border-color:#dc2626!important}
    .st-key-Griddirection [role="radiogroup"]>label:nth-of-type(3){background:#fef08a!important;border-color:#ca8a04!important}
    [data-testid="stAlert"]{background:#eef4ff!important;border:1px solid #b6c9e8!important;border-radius:12px}
    [data-testid="stAlert"] p,[data-testid="stAlert"] li,[data-testid="stAlert"] span{color:#172033!important}
    @media(max-width:640px){.block-container{padding:1rem}.glass{padding:16px}}
    </style>""", unsafe_allow_html=True)


def panel(title, text):
    st.markdown('<div class="glass"><h2>' + html.escape(title) + '</h2><p>' + html.escape(text) + '</p></div>', unsafe_allow_html=True)


def table(df):
    if df.empty:
        return
    formats = {c: "{:,.6f}" if c in ("Цена", "Средняя") else "{:,.2f}" for c in df.select_dtypes(include="number").columns}
    st.dataframe(df.style.set_properties(**{"background-color": "#ffffff", "color": "#172033"}).format(formats, na_rep="—"), use_container_width=True, hide_index=True)


def number(label, value, key, minimum=0.0, maximum=None, integer=False):
    cast = int if integer else float
    args = dict(label=label, key=key)
    if key not in st.session_state:
        args["value"] = cast(value)
    if minimum is not None:
        args["min_value"] = cast(minimum)
    if maximum is not None:
        args["max_value"] = cast(maximum)
    if integer:
        args["step"] = 1
    return st.number_input(**args)


def move(page, direction=None, template=None, focus=None, mode="Мои боты"):
    st.session_state["_route"] = dict(page=page, direction=direction, template=template or {}, focus=focus, mode=mode)
    st.rerun()


def apply_route():
    request = st.session_state.pop("_route", None)
    if request and request["page"] in PAGES:
        page = request["page"]
        st.session_state["page"] = page
        if page in ("DCA", "Grid"):
            st.session_state[page + "mode"] = request["mode"]
            if request["direction"]:
                st.session_state[page + "direction"] = request["direction"]
            for key, value in request["template"].items():
                st.session_state[page + key] = value
        if request["focus"]:
            st.session_state["focus"] = request["focus"]
    if st.session_state.get("page") not in PAGES:
        st.session_state["page"] = "Главная"


def login():
    password = str(secret("APP_PASSWORD"))
    if not password.strip():
        panel("Вход заблокирован", "Задай APP_PASSWORD в Streamlit Secrets. Без пароля терминал не открывается.")
        st.stop()
    if st.session_state.get("_authenticated"):
        return
    panel("OKX Terminal Pro", "Вход в личный терминал")
    with st.form("login", clear_on_submit=True):
        entered = st.text_input("Пароль", type="password")
        submitted = st.form_submit_button("Войти", use_container_width=True)
    if submitted:
        if hmac.compare_digest(entered.encode("utf-8"), password.encode("utf-8")):
            st.session_state["_authenticated"] = True
            st.rerun()
        else:
            st.error("Неверный пароль.")
    st.stop()


@contextmanager
def database():
    if not DB_URL:
        raise ValueError("DATABASE_URL не настроен. Сохранение в память или локальный файл не используется.")
    import psycopg2
    connection = None
    try:
        connection = psycopg2.connect(dsn=DB_URL, connect_timeout=10, application_name="okx_terminal")
        connection.autocommit = False
        yield connection
        connection.commit()
    except Exception:
        if connection is not None:
            connection.rollback()
        raise
    finally:
        if connection is not None:
            connection.close()


def sql(connection, statement, args=()):
    cursor = connection.cursor()
    cursor.execute(statement.replace("?", "%s"), args)
    return cursor


def init_database():
    with database() as c:
        sql(c, "CREATE TABLE IF NOT EXISTS terminal_bots (id TEXT PRIMARY KEY, document TEXT NOT NULL, revision INTEGER NOT NULL)")
        sql(c, "CREATE TABLE IF NOT EXISTS terminal_events (id TEXT PRIMARY KEY, bot_id TEXT NOT NULL, created_at TEXT NOT NULL, title TEXT NOT NULL, details TEXT NOT NULL)")


def check_postgres():
    with database() as c:
        if sql(c, "SELECT 1").fetchone() != (1,):
            raise ValueError("База не подтвердила проверку.")


def record(c, bot_id, title, details):
    sql(c, "INSERT INTO terminal_events VALUES (?, ?, ?, ?, ?)", (str(uuid.uuid4()), bot_id, now(), title, details))


def normalize(raw):
    if not isinstance(raw, dict):
        raise ValueError("Карточка должна быть объектом JSON.")
    b = json.loads(canonical(raw))
    if b.get("strategy") not in ("DCA", "Grid") or b.get("direction") not in ("Long", "Short", "Neutral"):
        raise ValueError("Неизвестная стратегия или направление карточки.")
    if b["strategy"] == "DCA" and b["direction"] == "Neutral":
        raise ValueError("DCA Neutral не поддерживается.")
    b["coin"] = str(b.get("coin", "")).strip().upper().replace("ARBITRUM", "ARB")
    if not b["coin"].isalnum():
        raise ValueError("Неверная монета в карточке.")
    market = str(b.get("market", "SWAP"))
    b["market"] = "SWAP" if "SWAP" in market or "Фьючерсы" in market else "SPOT"
    b.setdefault("name", b["coin"] + " " + b["strategy"])
    b.setdefault("created_at", now())
    b.setdefault("lifecycle", "Черновик")
    if b["lifecycle"] not in ("Черновик", "Работает", "Закрыт"):
        raise ValueError("Неизвестный статус карточки.")
    for key in ("settings", "position"):
        if isinstance(b.get(key), str):
            b[key] = json.loads(b[key])
        b.setdefault(key, {})
        if not isinstance(b[key], dict):
            raise ValueError("Неверные настройки позиции.")
    s, p = b["settings"], b["position"]
    defaults = dict(entry=0, tp=1.5, step=2, so_count=4, mart=1.2, base_amount=10, first_so=10, base_margin=100, reserve=50, leverage=1, lower=0, upper=0, grids=10, target_price=0, stop_price=0, stop_lower=0, stop_upper=0, max_loss=0, danger_pct=3, liq_warn=10, stale_hours=6)
    for key, default in defaults.items():
        value = s.get(key, default)
        try:
            converted = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Нечисловой параметр: " + key) from exc
        if not math.isfinite(converted):
            raise ValueError("Неверный параметр: " + key)
        if key in ("so_count", "grids") and converted != int(converted):
            raise ValueError("Нужно целое число: " + key)
        s[key] = int(converted) if key in ("so_count", "grids") else converted
    s["total_budget"] = num(s.get("total_budget"), s["base_margin"] + s["reserve"])
    p.setdefault("realized_pnl", num(s.get("realized_pnl")))
    return b


def load_bots():
    with database() as c:
        rows = sql(c, "SELECT document, revision FROM terminal_bots").fetchall()
    result = []
    for raw, revision in rows:
        b = normalize(json.loads(raw))
        b["_revision"] = revision
        result.append(b)
    return sorted(result, key=lambda b: b.get("updated_at", ""), reverse=True)


def save_bot(bot, title, details):
    b = normalize(bot)
    revision = b.pop("_revision", None)
    if not b.get("id"):
        raise ValueError("У карточки нет ID.")
    b["updated_at"] = now()
    raw = canonical(b)
    with database() as c:
        if revision is None:
            row = sql(c, "INSERT INTO terminal_bots VALUES (?, ?, 1) ON CONFLICT (id) DO NOTHING RETURNING revision", (b["id"], raw)).fetchone()
            if row is None:
                raise ValueError("Карточка с этим ID уже есть. Обнови список: предыдущая попытка могла сохраниться.")
        else:
            row = sql(c, "UPDATE terminal_bots SET document=?, revision=revision+1 WHERE id=? AND revision=? RETURNING revision", (raw, b["id"], revision)).fetchone()
            if row is None:
                raise ValueError("Карточка изменена в другой вкладке. Обнови страницу перед повторным редактированием.")
        new_revision = row[0]
        record(c, b["id"], title, details)
    with database() as c:
        saved = sql(c, "SELECT document, revision FROM terminal_bots WHERE id=?", (b["id"],)).fetchone()
    if not saved or saved[0] != raw or saved[1] != new_revision:
        raise ValueError("Запись отправлена, но повторная проверка версии не совпала. Обнови список, не создавай дубликат.")
    return new_revision


def history():
    with database() as c:
        rows = sql(c, "SELECT bot_id, created_at, title, details FROM terminal_events ORDER BY created_at DESC LIMIT 5000").fetchall()
    return pd.DataFrame(rows, columns=["Бот ID", "Дата UTC", "Событие", "Подробности"])


def backup_bytes():
    with database() as c:
        sql(c, "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        bots = [json.loads(row[0]) for row in sql(c, "SELECT document FROM terminal_bots").fetchall()]
        events = [dict(bot_id=r[0], created_at=r[1], title=r[2], details=r[3]) for r in sql(c, "SELECT bot_id, created_at, title, details FROM terminal_events ORDER BY created_at").fetchall()]
    return json.dumps(dict(version=15, created_at=now(), bots=bots, events=events), ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")


def import_backup(source):
    if not isinstance(source, dict) or not isinstance(source.get("bots"), list) or len(source["bots"]) > 1000:
        raise ValueError("Нужен JSON с массивом bots, не более 1000 карточек.")
    events = source.get("events", [])
    if not isinstance(events, list) or len(events) > 20000:
        raise ValueError("Неверный журнал резервной копии или больше 20000 событий.")
    prepared, mapping = [], {}
    for raw in source["bots"]:
        b = normalize(raw)
        old_id = str(b.get("id", ""))
        if old_id and old_id in mapping:
            raise ValueError("В копии повторяются ID.")
        b.pop("_revision", None)
        b.update(id=str(uuid.uuid4()), lifecycle="Черновик", updated_at=now())
        b["position"]["last_check"] = ""
        if old_id:
            mapping[old_id] = b["id"]
        prepared.append(b)
    with database() as c:
        for b in prepared:
            sql(c, "INSERT INTO terminal_bots VALUES (?, ?, 1)", (b["id"], canonical(b)))
            record(c, b["id"], "Импорт", "Копия добавлена без замены существующей карточки. Нужна сверка с OKX.")
        for event in events:
            if not isinstance(event, dict):
                raise ValueError("Неверное событие журнала.")
            target = mapping.get(str(event.get("bot_id", event.get("Бот ID", ""))))
            if target:
                original_date = str(event.get("created_at", event.get("Дата UTC", "")))
                title = str(event.get("title", event.get("Событие", "Событие")))
                details = str(event.get("details", event.get("Подробности", "")))
                record(c, target, "Импорт: " + title, original_date + " · " + details)
    with database() as c:
        for b in prepared:
            if not sql(c, "SELECT id FROM terminal_bots WHERE id=?", (b["id"],)).fetchone():
                raise ValueError("Импорт отправлен, но проверка не завершена. Обнови список.")
    return len(prepared)


@st.cache_data(ttl=20, max_entries=256, show_spinner=False)
def api(path, params):
    error = None
    for attempt in range(3):
        try:
            response = requests.get(API + path, params=params, timeout=(5, 12))
            response.raise_for_status()
            result = response.json()
            if str(result.get("code")) != "0":
                raise ValueError("OKX не подтвердил запрос.")
            return result.get("data", [])
        except (requests.RequestException, ValueError) as exc:
            error = exc
            time.sleep(.2 * (attempt + 1))
    raise ValueError("Данные OKX недоступны. Проверь доступность инструмента и повтори запрос.") from error


def instrument(coin, market):
    return f"{coin}-USDT" + ("-SWAP" if market == "SWAP" else "")


@st.cache_data(ttl=20, max_entries=100, show_spinner=False)
def quote(coin, market):
    rows = api("/market/ticker", {"instId": instrument(coin, market)})
    if not rows:
        raise ValueError("Инструмент не найден на OKX.")
    row = rows[0]
    price, ts = num(row.get("last")), num(row.get("ts"))
    if price <= 0 or ts <= 0 or abs(time.time() - ts / 1000) > 180:
        raise ValueError("Нет свежей рыночной цены.")
    opening = num(row.get("open24h"))
    return dict(price=price, ts=ts, volume=num(row.get("volCcy24h")) * (price if market == "SWAP" else 1), change=(price / opening - 1) * 100 if opening > 0 else None)


def candle_frame(rows):
    data = [[int(r[0]), *map(float, r[1:5])] for r in rows if len(r) >= 9 and str(r[8]) == "1"]
    df = pd.DataFrame(data, columns=["ts", "open", "high", "low", "close"]).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    if df.empty or not np.isfinite(df[["open", "high", "low", "close"]].to_numpy()).all() or (df[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("Нет корректных закрытых свечей.")
    df["time"] = pd.to_datetime(df.ts, unit="ms", utc=True)
    return df


@st.cache_data(ttl=180, max_entries=100, show_spinner=False)
def daily(coin, market):
    df = candle_frame(api("/market/candles", {"instId": instrument(coin, market), "bar": "1D", "limit": "200"}))
    if len(df) < 60 or (df.ts.diff().dropna() != 24 * HOUR).any() or time.time() * 1000 - df.ts.iloc[-1] > 49 * HOUR:
        raise ValueError("Недостаточно непрерывной свежей дневной истории.")
    return df


def rma(series, period=14):
    result = pd.Series(np.nan, index=series.index, dtype=float)
    seed, previous = [], None
    for index, value in series.items():
        if pd.isna(value):
            continue
        if previous is None:
            seed.append(float(value))
            if len(seed) == period:
                previous = sum(seed) / period
                result.loc[index] = previous
        else:
            previous = (previous * (period - 1) + float(value)) / period
            result.loc[index] = previous
    return result


def indicators(df):
    df = df.copy()
    delta = df.close.diff()
    gain, loss = rma(delta.clip(lower=0)), rma(-delta.clip(upper=0))
    rsi = 100 - 100 / (1 + gain / loss)
    rsi.loc[(gain == 0) & (loss == 0)] = 50
    rsi.loc[(gain > 0) & (loss == 0)] = 100
    tr = pd.concat([df.high - df.low, (df.high - df.close.shift()).abs(), (df.low - df.close.shift()).abs()], axis=1).max(axis=1)
    tr.iloc[0] = np.nan
    atr = rma(tr)
    up, down = df.high.diff(), -df.low.diff()
    plus, minus = up.where((up > down) & (up > 0), 0.0), down.where((down > up) & (down > 0), 0.0)
    plus.iloc[0] = minus.iloc[0] = np.nan
    plus, minus = rma(plus), rma(minus)
    total = plus + minus
    dx = 100 * (plus - minus).abs() / total
    dx.loc[total == 0] = 0
    df["RSI"], df["ADX"], df["ATR %"] = rsi, rma(dx), atr / df.close * 100
    df["+DI"], df["-DI"] = 100 * plus / atr, 100 * minus / atr
    df.loc[atr == 0, ["+DI", "-DI"]] = 0
    return df


def market_chart(df, title):
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[.6, .2, .2], vertical_spacing=.04)
    fig.add_trace(go.Candlestick(x=df.time, open=df.open, high=df.high, low=df.low, close=df.close, name="Цена", increasing_line_color="#00ff9d", decreasing_line_color="#ff4d6d"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.time, y=df.RSI, name="RSI", line=dict(color="#00c2ff")), row=2, col=1)
    fig.add_trace(go.Scatter(x=df.time, y=df.ADX, name="ADX", line=dict(color="#ffd166")), row=3, col=1)
    for y in (30, 70):
        fig.add_hline(y=y, line_dash="dot", row=2, col=1)
    fig.add_hline(y=25, line_dash="dot", row=3, col=1)
    fig.update_layout(title=title, template="plotly_dark", height=650, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", xaxis_rangeslider_visible=False)
    st.plotly_chart(fig, use_container_width=True)


def analyze_coin(coin, market):
    df, q = indicators(daily(coin, market)), quote(coin, market)
    last = df.iloc[-1]
    if not np.isfinite([last.RSI, last.ADX, last["ATR %"], last["+DI"], last["-DI"]]).all():
        raise ValueError("Индикаторы не готовы.")
    signal = "GRID" if last.ADX < 25 else "LONG" if last["+DI"] > last["-DI"] else "SHORT" if last["-DI"] > last["+DI"] else "WAIT"
    return {"Монета": coin, "Цена": q["price"], "Сигнал": signal, "RSI": last.RSI, "ADX": last.ADX, "ATR %": last["ATR %"], "Объём 24H ≈ USDT": q["volume"], "Тейк %": 1.0 if last["ATR %"] < 1.5 else 1.5 if last["ATR %"] < 3 else 2.0}


def actions(prefix):
    cols = st.columns(3)
    for column, label, strategy, direction, suffix in zip(cols, ["🟢 ЛОНГ · DCA", "🔴 ШОРТ · DCA", "🟡 NEUTRAL · GRID"], ["DCA", "DCA", "Grid"], ["Long", "Short", "Neutral"], ["long", "short", "neutral"]):
        if column.button(label, key="action_" + prefix + "_" + suffix, use_container_width=True):
            move(strategy, direction, mode="Добавить бота")


def scanner():
    panel("Сканер", "Закрытые дневные свечи, RSI/ADX и переход к настройке. TON исключён из списка.")
    market = st.radio("Рынок", ["SWAP", "SPOT"], horizontal=True, key="scanmarket")
    if st.button("Сканировать монеты", use_container_width=True):
        rows, errors = [], []
        progress = st.progress(0.0)
        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs = {pool.submit(analyze_coin, coin, market): coin for coin in COINS}
            for i, future in enumerate(as_completed(jobs)):
                try:
                    rows.append(future.result())
                except Exception:
                    errors.append(jobs[future])
                progress.progress((i + 1) / len(jobs))
        rows.sort(key=lambda row: COINS.index(row["Монета"]))
        st.session_state["scan"] = dict(rows=rows, errors=errors, market=market, timestamp=now())
    saved = st.session_state.get("scan")
    if not saved:
        st.info("Запусти сканирование.")
        return
    st.caption(saved["market"] + " · " + saved["timestamp"])
    if saved["errors"]:
        st.warning("Нет корректных данных: " + ", ".join(saved["errors"]))
    if not saved["rows"]:
        return
    table(pd.DataFrame(saved["rows"]))
    coin = st.selectbox("Открыть монету", [r["Монета"] for r in saved["rows"]])
    row = next(r for r in saved["rows"] if r["Монета"] == coin)
    market_chart(indicators(daily(coin, saved["market"])), coin + " · цена / RSI / ADX")
    st.caption("Сигнал — правило индикаторов, не прогноз. TP по ATR — черновой шаблон, не оптимизация.")
    template = dict(coin=coin, market=saved["market"], entry=float(row["Цена"]), tp=float(row["Тейк %"]), step=2.0, count=4, mart=1.2)
    cols = st.columns(3)
    for column, label, strategy, direction, suffix in zip(cols, ["🟢 DCA Long", "🔴 DCA Short", "🟡 Grid"], ["DCA", "DCA", "Grid"], ["Long", "Short", "Neutral" if market == "SWAP" else "Long"], ["long", "short", "neutral"]):
        if column.button(label, key="action_scan_" + suffix, disabled=saved["market"] != market or (market == "SPOT" and direction == "Short")):
            move(strategy, direction, template, mode="Добавить бота")


def dca_plan(s, direction):
    entry, step, count = num(s["entry"]), num(s["step"]), int(s["so_count"])
    base, first, mult = num(s["base_amount"]), num(s["first_so"]), num(s["mart"])
    if entry <= 0 or step <= 0 or base <= 0 or first <= 0 or mult < 1 or not 0 <= count <= 30 or direction not in ("Long", "Short"):
        raise ValueError("Проверь цену входа и параметры DCA.")
    rows, total, qty = [], 0.0, 0.0
    for i in range(count + 1):
        price = entry * (1 - sign(direction) * step * i / 100)
        if price <= 0:
            raise ValueError("Один из уровней DCA имеет цену ≤ 0.")
        amount = base if i == 0 else first * mult ** (i - 1)
        total += amount
        qty += amount / price
        rows.append({"Ордер": "Вход" if i == 0 else f"СО {i}", "Цена": price, "Номинал USDT": amount, "Всего номинал": total, "Средняя": total / qty})
    return rows


@st.cache_data(ttl=300, max_entries=20, show_spinner=False)
def history_prices(coin, market, days, end):
    start, after, rows, previous = end - days * 24 * HOUR, end, [], None
    for _ in range(100):
        batch = api("/market/history-candles", {"instId": instrument(coin, market), "bar": "1H", "limit": "100", "after": str(after)})
        if not batch:
            break
        rows.extend(batch)
        oldest = min(int(r[0]) for r in batch)
        if oldest <= start or oldest == previous:
            break
        previous, after = oldest, oldest
        time.sleep(.12)
    df = candle_frame(rows)
    df = df[(df.ts >= start) & (df.ts < end)].reset_index(drop=True)
    expected = np.arange(start, end, HOUR, dtype=np.int64)
    if len(df) != len(expected) or not np.array_equal(df.ts.to_numpy(), expected):
        raise ValueError("История не покрывает весь период без пропусков. Тест не выполнен.")
    return df


def simulate(df, s, strategy, direction, market, fee):
    capital, leverage = num(s["base_margin"]), num(s["leverage"])
    if capital <= 0 or leverage < 1 or df.empty:
        raise ValueError("Проверь капитал, плечо и историю.")
    if market == "SPOT" and (direction != "Long" or leverage != 1):
        raise ValueError("Spot поддерживает только Long 1x.")
    if strategy == "DCA":
        plan = dca_plan(s, direction)
        if plan[-1]["Всего номинал"] / leverage + plan[-1]["Всего номинал"] * fee >= capital:
            raise ValueError("Капитала не хватает на все ордера с комиссиями.")
    else:
        if not 0 < s["lower"] < s["upper"] or int(s["grids"]) < 2:
            raise ValueError("Проверь диапазон и число интервалов Grid.")
        levels = np.linspace(s["lower"], s["upper"], int(s["grids"]) + 1)
        allocation = capital / int(s["grids"]) / (1 + leverage * fee)
        middle = (s["lower"] + s["upper"]) / 2
    wallet, qty, avg, entry, used = capital, 0.0, 0.0, 0.0, 0.0
    executed, cycles, fees, floating = 0, 0, 0.0, 0.0
    lots, curve, halted = {}, [], False
    prices = df.close.to_numpy(dtype=float)
    for i, price in enumerate(prices):
        if strategy == "DCA":
            sg = sign(direction)
            if qty and sg * (price / avg - 1) * 100 >= s["tp"]:
                close_fee = qty * price * fee
                wallet += sg * qty * (price - avg) - close_fee
                fees += close_fee
                qty, used = 0.0, 0.0
                cycles += 1
            elif qty == 0:
                amount = s["base_amount"]
                if wallet >= amount / leverage + amount * fee:
                    qty, avg, entry, used, executed = amount / price, price, price, amount / leverage, 0
                    wallet -= amount * fee
                    fees += amount * fee
            elif executed < s["so_count"] and sg * (price / entry - 1) * 100 <= -s["step"] * (executed + 1):
                amount = s["first_so"] * s["mart"] ** executed
                available = wallet if market == "SPOT" else wallet + sg * qty * (price - avg)
                if available >= used + amount / leverage + amount * fee:
                    avg = (qty * avg + amount) / (qty + amount / price)
                    qty += amount / price
                    used += amount / leverage
                    wallet -= amount * fee
                    fees += amount * fee
                    executed += 1
            floating = sg * qty * (price - avg) if qty else 0.0
            equity = wallet + floating
        elif market == "SPOT":
            for key in list(lots):
                quantity, cost = lots[key]
                if price >= levels[key + 1]:
                    gross = quantity * price
                    wallet += gross * (1 - fee)
                    fees += gross * fee
                    del lots[key]
                    cycles += 1
            if i > 0 and s["lower"] <= price <= s["upper"]:
                for j, level in enumerate(levels[:-1]):
                    if j not in lots and prices[i - 1] > level >= price and wallet + 1e-9 >= allocation * (1 + fee):
                        lots[j] = (allocation / price, allocation)
                        wallet -= allocation * (1 + fee)
                        fees += allocation * fee
            floating = sum(quantity * price - cost for quantity, cost in lots.values())
            equity = wallet + sum(quantity * price for quantity, cost in lots.values())
        else:
            for key in list(lots):
                sg, quantity, opened, target, margin = lots[key]
                if sg * (price - target) >= 0:
                    close_fee = quantity * price * fee
                    wallet += sg * quantity * (price - opened) - close_fee
                    fees += close_fee
                    del lots[key]
                    cycles += 1
            floating = sum(sg * quantity * (price - opened) for sg, quantity, opened, target, margin in lots.values())
            used = sum(lot[4] for lot in lots.values())
            if i > 0 and s["lower"] <= price <= s["upper"]:
                for j, level in enumerate(levels):
                    sg = 1 if direction == "Long" else -1 if direction == "Short" else 1 if level < middle else -1
                    if (sg == 1 and j == len(levels) - 1) or (sg == -1 and j == 0):
                        continue
                    crossed = prices[i - 1] > level >= price if sg == 1 else prices[i - 1] < level <= price
                    key = (j, sg)
                    opening_fee = allocation * leverage * fee
                    if crossed and key not in lots and wallet + floating >= used + allocation + opening_fee:
                        lots[key] = (sg, allocation * leverage / price, price, levels[j + sg], allocation)
                        wallet -= opening_fee
                        fees += opening_fee
                        used += allocation
            floating = sum(sg * quantity * (price - opened) for sg, quantity, opened, target, margin in lots.values())
            equity = wallet + floating
        if equity <= 0:
            curve.append(0.0)
            halted = True
            break
        curve.append(equity)
    values = np.array([capital, *curve])
    peaks = np.maximum.accumulate(values)
    return dict(roi=(curve[-1] / capital - 1) * 100, pnl=curve[-1] - capital, cycles=cycles, fees=fees, floating=floating, dd=float(np.max((peaks - values) / peaks) * 100), halted=halted, curve=curve)


def backtest(kind, coin, market, direction, s, valid):
    with st.expander("Бэктест и сравнение альтернатив"):
        days = st.selectbox("Дней истории 1H", [7, 14, 30, 90], index=1, key=kind + "days")
        fee = number("Комиссия за сторону, % от номинала", .05, kind + "fee", 0, 5) / 100
        if st.button("Рассчитать мой план и две альтернативы", disabled=not valid, key=kind + "test"):
            st.session_state.pop(kind + "result", None)
            variants = [("Мой план", dict(s)), ("Без увеличения СО" if kind == "DCA" else "Шире диапазон", dict(s)), ("Шире шаг" if kind == "DCA" else "Меньше интервалов", dict(s))]
            if kind == "DCA":
                variants[1][1]["mart"] = 1.0
                variants[2][1]["step"] *= 1.5
            else:
                mid, half = (s["upper"] + s["lower"]) / 2, (s["upper"] - s["lower"]) / 2
                variants[1][1].update(lower=max(.00000001, mid - half * 1.5), upper=mid + half * 1.5)
                variants[2][1]["grids"] = max(2, int(s["grids"]) // 2)
            with st.spinner("Загружаю свечи и считаю..."):
                df = history_prices(coin, market, days, int(time.time() // 3600) * HOUR)
                rows, curves = [], {}
                for label, variant in variants:
                    try:
                        result = simulate(df, variant, kind, direction, market, fee)
                        rows.append({"Вариант": label, "Результат USDT": result["pnl"], "Доходность %": result["roi"], "Просадка %": result["dd"], "Циклы/лоты": result["cycles"], "Комиссии USDT": result["fees"], "Открытый PnL": result["floating"], "Капитал исчерпан": str(result["halted"]), "Параметры": canonical(variant)})
                        curves[label] = result["curve"] + [np.nan] * (len(df) - len(result["curve"]))
                    except ValueError as exc:
                        rows.append({"Вариант": label, "Ошибка модели": str(exc), "Параметры": canonical(variant)})
                st.session_state[kind + "result"] = dict(rows=rows, curves=pd.DataFrame(curves, index=df.time), caption=f"{coin} · {market} · {direction} · {df.time.iloc[0]} — {df.time.iloc[-1]} · {len(df)} свечей")
        result = st.session_state.get(kind + "result")
        if result:
            st.caption("Последний расчёт, не обязательно текущие поля: " + result["caption"])
            table(pd.DataFrame(result["rows"]))
            if not result["curves"].empty:
                st.line_chart(result["curves"])
        st.caption("Модель по закрытиям 1H. Открытая позиция включена в итоговый капитал. Futures Grid — приближённая модель пересечений уровней без стартовой позиции, не копия OKX. Нет funding, ликвидации, MMR, проскальзывания и внутрисвечных исполнений. Стопы, лимит убытка и резерв в тесте не исполняются. Одного периода недостаточно для выбора лучшего варианта.")


def creator(kind):
    task = st.radio("Задача", ["Подготовить новый", "Добавить уже работающий"], horizontal=True, key=kind + "task")
    name = st.text_input("Название", value="Мой " + kind, key=kind + "name")
    args = dict(label="Монета", key=kind + "coin")
    if kind + "coin" not in st.session_state:
        args["value"] = "BTC"
    coin = st.text_input(**args).strip().upper()
    if coin == "TON":
        st.warning("TON исключён из добавления новых ботов. Старые карточки при этом не удаляются.")
        return
    market = st.selectbox("Рынок", ["SWAP", "SPOT"], key=kind + "market")
    direction = st.radio("Направление", ["Long", "Short"] if kind == "DCA" else ["Long", "Short", "Neutral"], horizontal=True, key=kind + "direction")
    if market == "SPOT" and direction != "Long":
        st.warning("Spot: выбери Long. Short и Neutral здесь предназначены для SWAP.")
        return
    s = dict(base_margin=number("Базовая маржа / капитал Spot, USDT", 100, kind + "margin", .01))
    if kind == "DCA":
        s["entry"] = number("Цена первого входа", 0, kind + "entry")
        s["tp"] = number("TP: движение цены от средней, % (не ROI маржи)", 1.5, kind + "tp", .01, 99)
    else:
        s["entry"] = 0.0
        s["lower"] = number("Нижняя граница — точная цена", 0, kind + "lower")
        s["upper"] = number("Верхняя граница — точная цена", 0, kind + "upper")
        s["grids"] = number("Количество интервалов", 10, kind + "grids", 2, 200, integer=True)
    with st.expander("Расширенные настройки"):
        s["leverage"] = number("Плечо; для Spot нужно 1", 3 if market == "SWAP" else 1, kind + "leverage", 1, 100)
        s["reserve"] = number("Отдельный резерв маржи, USDT", 50, kind + "reserve")
        s["total_budget"] = s["base_margin"] + s["reserve"]
        if kind == "DCA":
            s["step"] = number("Шаг СО от первого входа, %", 2, kind + "step", .01, 50)
            s["so_count"] = number("Количество СО", 4, kind + "count", 0, 30, integer=True)
            s["base_amount"] = number("Номинал первого ордера, USDT", 10, kind + "base", .01)
            s["first_so"] = number("Номинал первого СО, USDT", 10, kind + "first", .01)
            s["mart"] = number("Множитель номинала последующих СО", 1.2, kind + "mart", 1, 3)
        else:
            s["target_price"] = number("Целевая цена завершения Long/Short; 0 = нет", 0, kind + "target")
        if direction == "Neutral":
            s["stop_lower"] = number("Нижняя сигнальная стоп-цена; 0 = нет", 0, kind + "stoplower")
            s["stop_upper"] = number("Верхняя сигнальная стоп-цена; 0 = нет", 0, kind + "stopupper")
        else:
            s["stop_price"] = number("Сигнальная стоп-цена; 0 = нет", 0, kind + "stop")
        s["max_loss"] = number("Лимит убытка открытой позиции Long/Short, USDT; 0 = нет", 0, kind + "loss")
        s["danger_pct"] = number("Неблагоприятное движение для зоны внимания, %", 3, kind + "danger", .1, 100)
        s["stale_hours"] = number("Сверка устаревает через часов", 6, kind + "stale", .1, 168)
        s["liq_warn"] = number("Предупреждение у введённой ликвидации, %", 10, kind + "liqwarn", .1, 100)
        st.caption("Стопы здесь — условия уведомления, а не биржевые ордера. Множитель изменяет объём СО, не расстояние между уровнями.")
    valid = bool(name.strip()) and coin.isalnum() and not (market == "SPOT" and s["leverage"] != 1)
    if market == "SPOT" and s["leverage"] != 1:
        st.warning("В расширенных настройках установи плечо 1 для Spot.")
    if kind == "DCA":
        try:
            plan = dca_plan(s, direction)
            with st.expander("План ордеров"):
                table(pd.DataFrame(plan))
                st.caption(f"Маржа на все ордера ≈ {plan[-1]['Всего номинал'] / s['leverage']:.2f} USDT, без комиссий.")
            if plan[-1]["Всего номинал"] / s["leverage"] >= s["base_margin"]:
                valid = False
                st.warning("Базовой маржи не хватает на план ордеров с запасом.")
        except ValueError as exc:
            valid = False
            st.info(str(exc))
    else:
        valid = valid and 0 < s["lower"] < s["upper"]
        if valid:
            st.line_chart(pd.DataFrame({"Уровни Grid": np.linspace(s["lower"], s["upper"], int(s["grids"]) + 1)}))
    pending = kind + "pending_id"
    if pending not in st.session_state:
        st.session_state[pending] = dict(id=str(uuid.uuid4()), created_at=now())
    if st.button("Сохранить карточку в PostgreSQL", disabled=not valid or not DB_READY, key=kind + "save", use_container_width=True):
        quote(coin, market)
        draft = st.session_state[pending]
        b = dict(id=draft["id"], created_at=draft["created_at"], name=name.strip(), coin=coin, market=market, direction=direction, strategy=kind, settings=s, position={}, lifecycle="Черновик")
        save_bot(b, "Создана карточка", "Добавлен работающий бот: нужна фактическая сверка." if task == "Добавить уже работающий" else "Сохранён план до запуска.")
        st.session_state.pop(pending, None)
        st.session_state["_flash"] = "Карточка записана и повторно прочитана из PostgreSQL. Внеси фактическую позицию и статус."
        move(kind, focus=b["id"])
    if not DB_READY:
        st.warning("Сохранение заблокировано: PostgreSQL не подключена или недоступна. Сохранение в память не подменяет запись в базу.")
    backtest(kind, coin, market, direction, s, valid)


def assess(b, price):
    s, p, direction = b["settings"], b.get("position", {}), b["direction"]
    realized = num(p.get("realized_pnl")) if b["strategy"] == "DCA" else 0.0
    r = dict(title="Нужна сверка", reason="", tone="info", pnl=None, floating=None, realized=realized, tp=None, next_so=None, liq_distance=None, reserve=max(0, num(s["total_budget"]) - num(p.get("base_margin"), s["base_margin"]) - num(p.get("added_margin"))))
    if b["lifecycle"] != "Работает":
        r.update(title="План сохранён" if b["lifecycle"] == "Черновик" else "Бот отмечен завершённым", reason="Для работающего бота внеси фактическую позицию и выбери статус «Работает»." if b["lifecycle"] == "Черновик" else "Карточка и история остаются в базе. Статус отмечен пользователем.")
        return r
    if price is None:
        r.update(title="Нет свежей цены", reason="Расчёт по нулевой цене отключён. Обнови данные.")
        return r
    stop = s["stop_price"]
    hit = (direction != "Neutral" and stop > 0 and sign(direction) * (price - stop) <= 0) or (direction == "Neutral" and ((s["stop_lower"] > 0 and price <= s["stop_lower"]) or (s["stop_upper"] > 0 and price >= s["stop_upper"])))
    if hit:
        r.update(title="Достигнута сигнальная стоп-цена плана", reason="Срочно сверь позицию на OKX и выполни предусмотренный планом выход. Свежесть позиции не отменяет этот сигнал. Торговая команда не отправлялась.", tone="error")
        return r
    if age(p.get("last_check")) > s["stale_hours"]:
        r.update(title="Сверка устарела или не выполнена", reason="Обнови фактическую позицию на OKX. Не выдаём уверенное указание держать или закрывать по устаревшим данным.")
        return r
    if direction == "Neutral":
        inside = s["lower"] <= price <= s["upper"]
        r.update(title="Цена внутри диапазона Grid" if inside else "Цена вне диапазона Grid", reason="Проверь остаточные позиции, ордера и Total PnL на OKX. Введённый вручную Total PnL — снимок сверки, а не онлайн-расчёт.", tone="info" if inside else "warning")
        if p.get("total_pnl_manual") is not None:
            r["pnl"] = num(p["total_pnl_manual"])
        return r
    qty, avg = num(p.get("volume")), num(p.get("avg_price"))
    if qty <= 0:
        r.update(title="По сверке открытой позиции нет", reason="Проверь, ожидает ли бот следующий цикл.", floating=0.0, pnl=realized if b["strategy"] == "DCA" else None)
        return r
    if avg <= 0:
        r["reason"] = "Нужна фактическая средняя цена."
        return r
    floating = sign(direction) * qty * (price - avg)
    r.update(pnl=floating + realized, floating=floating)
    liquidation = num(p.get("liq_price"))
    if liquidation > 0:
        r["liq_distance"] = sign(direction) * (price - liquidation) / price * 100
    if s["max_loss"] > 0 and floating <= -s["max_loss"]:
        r.update(title="Достигнут лимит убытка открытой позиции", reason="Проверь ручной выход по плану. Прибыль прошлых циклов не отменяет этот лимит.", tone="error")
        return r
    if r["liq_distance"] is not None and r["liq_distance"] <= s["liq_warn"]:
        r.update(title="Цена близко к введённой ликвидации", reason="Срочно сверь риск на OKX. Здесь последняя цена, не Mark Price; ликвидация введена вручную, MMR не рассчитан.", tone="error")
        return r
    if b["strategy"] == "DCA":
        r["tp"] = avg * (1 + sign(direction) * s["tp"] / 100)
        if s["entry"] > 0:
            plan = dca_plan(s, direction)
            executed = max(0, min(int(p.get("executed_so", 0)), len(plan) - 1))
            if executed + 1 < len(plan):
                r["next_so"] = plan[executed + 1]["Цена"]
    else:
        r["tp"] = s["target_price"] or None
    if r["tp"] and sign(direction) * (price - r["tp"]) >= 0:
        r.update(title="Достигнут модельный тейк", reason="Проверь исполнение на OKX. TP цикла, остановка новых циклов и полная остановка бота — разные действия.", tone="success")
    elif b["strategy"] == "Grid" and not s["lower"] <= price <= s["upper"]:
        r.update(title="Цена вне диапазона Grid", reason="Проверь остаточную позицию и план выхода. Выход из диапазона не означает закрытие.", tone="warning")
    elif max(0, -sign(direction) * (price / avg - 1) * 100) >= s["danger_pct"]:
        r.update(title="Цена в заданной зоне внимания", reason="Движение против позиции достигло твоего порога. Проверь уменьшение риска или выход по плану. Это не прогноз разворота.", tone="warning")
    elif r["next_so"] and sign(direction) * (price - r["next_so"]) <= 0:
        r.update(title="Достигнут уровень следующего СО", reason="Проверь исполнение, объём и среднюю. Касание уровня не подтверждает исполнение.")
    elif floating > 0:
        r.update(title="Открытая позиция в плюсе", reason="Контролируй TP и условия риска. Один снимок не подтверждает рост прибыли во времени.", tone="success")
    else:
        r.update(title="Контроль по плану", reason="Жёсткие условия выхода по введённым данным не сработали. Это не обещание отскока.")
    if r["reserve"] <= 0:
        r["reason"] += " Резерв маржи исчерпан; дальнейшее добавление выходит за бюджет."
    return r


def telegram_credentials():
    token, chat = str(secret("TELEGRAM_TOKEN")), str(secret("TELEGRAM_CHAT_ID"))
    try:
        token = token or str(st.secrets["telegram"]["token"])
        chat = chat or str(st.secrets["telegram"]["chat_id"])
    except Exception:
        pass
    return token or st.session_state.get("tg_token", ""), chat or st.session_state.get("tg_chat", "")


def send_telegram(text):
    token, chat = telegram_credentials()
    if not token or not chat:
        raise ValueError("Настрой Telegram в Secrets или в Настройках.")
    response = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat, "text": text[:4000]}, timeout=12)
    response.raise_for_status()
    if not response.json().get("ok"):
        raise ValueError("Telegram не подтвердил отправку.")


def position_form(b):
    p, s = b["position"], b["settings"]
    key = b["id"] + "_" + str(b["_revision"])
    with st.expander("Сверить фактическую позицию с OKX", expanded=not p.get("last_check")):
        with st.form(key + "position"):
            lifecycle = st.selectbox("Статус", ["Черновик", "Работает", "Закрыт"], index=["Черновик", "Работает", "Закрыт"].index(b["lifecycle"]))
            neutral = b["direction"] == "Neutral"
            if neutral:
                known = st.checkbox("Ввести фактический Total PnL с OKX", value=p.get("total_pnl_manual") is not None)
                total_manual = number("Total PnL с OKX, USDT — снимок на момент сверки", num(p.get("total_pnl_manual")), key + "total", minimum=None)
                quantity, average, realized, liquidation, executed = 0.0, 0.0, 0.0, 0.0, 0
                st.caption("Нулевой объём здесь не утверждает отсутствие обеих сторон Neutral. Перед отметкой завершения проверь все остаточные позиции и ордера на OKX.")
            else:
                known, total_manual = False, None
                quantity = number("Объём в базовой монете, НЕ контракты; 0 = нет позиции", num(p.get("volume")), key + "qty")
                average = number("Фактическая средняя цена", num(p.get("avg_price")), key + "avg")
                liquidation = number("Ликвидационная цена с OKX; 0 = неизвестна", num(p.get("liq_price")), key + "liq")
                if b["strategy"] == "DCA":
                    realized = number("PnL закрытых циклов, USDT; не Total PnL", num(p.get("realized_pnl")), key + "realized", minimum=None)
                    st.caption("Накопленное значение заменяется, а не прибавляется. Убыток можно вводить отрицательным числом.")
                    maximum = int(s["so_count"])
                    executed = number("Исполнено СО текущего цикла", min(max(0, int(p.get("executed_so", 0))), maximum), key + "executed", 0, maximum, integer=True) if maximum > 0 else 0
                else:
                    realized, executed = 0.0, 0
            base = number("Фактически выделенная базовая маржа", num(p.get("base_margin"), s["base_margin"]), key + "base")
            added = number("Всего добавлено маржи", num(p.get("added_margin")), key + "added")
            confirmed = st.checkbox("Сверил значения с OKX; для статуса «Закрыт» проверил отсутствие остаточных позиций и ордеров")
            if st.form_submit_button("Сохранить сверку", disabled=not DB_READY):
                if not confirmed or (quantity > 0 and average <= 0) or (lifecycle == "Закрыт" and quantity > 0):
                    st.error("Подтверди сверку. Ненулевой позиции нужна средняя; завершённой карточке — нулевой остаток.")
                else:
                    b["lifecycle"] = lifecycle
                    b["position"] = dict(volume=quantity, avg_price=average, realized_pnl=realized, liq_price=liquidation, executed_so=int(executed), base_margin=base, added_margin=added, total_pnl_manual=total_manual if known else None, last_check=now())
                    save_bot(b, "Сверка позиции", "Данные и статус подтверждены пользователем на OKX.")
                    st.session_state["_flash"] = "Сверка записана и проверена в PostgreSQL."
                    st.rerun()


def plan_form(b):
    s = b["settings"]
    key = b["id"] + "_" + str(b["_revision"]) + "plan"
    with st.expander("Изменить план сопровождения"):
        with st.form(key):
            updated = dict(s)
            if b["strategy"] == "DCA":
                updated["tp"] = number("TP от средней, %", s["tp"], key + "tp", .01, 99)
            else:
                updated["lower"] = number("Нижняя граница", s["lower"], key + "lower")
                updated["upper"] = number("Верхняя граница", s["upper"], key + "upper")
                updated["target_price"] = number("Целевая цена Long/Short; 0 = нет", s["target_price"], key + "target")
            if b["direction"] == "Neutral":
                updated["stop_lower"] = number("Нижний сигнальный стоп; 0 = нет", s["stop_lower"], key + "stoplower")
                updated["stop_upper"] = number("Верхний сигнальный стоп; 0 = нет", s["stop_upper"], key + "stopupper")
            else:
                updated["stop_price"] = number("Сигнальная стоп-цена; 0 = нет", s["stop_price"], key + "stop")
            updated["max_loss"] = number("Лимит убытка открытой позиции Long/Short, USDT", s["max_loss"], key + "loss")
            updated["danger_pct"] = number("Зона внимания: движение против позиции, %", s["danger_pct"], key + "danger", .1, 100)
            updated["total_budget"] = number("Общий бюджет маржи, включая резерв", s["total_budget"], key + "budget", .01)
            updated["stale_hours"] = number("Срок актуальности сверки, часов", s["stale_hours"], key + "stale", .1, 168)
            if st.form_submit_button("Сохранить изменения плана", disabled=not DB_READY):
                if b["strategy"] == "Grid" and not 0 < updated["lower"] < updated["upper"]:
                    st.error("Проверь диапазон.")
                else:
                    b["settings"] = updated
                    save_bot(b, "Изменён план", canonical(updated))
                    st.session_state["_flash"] = "План обновлён и прочитан из PostgreSQL."
                    st.rerun()


def bot_card(b, compact=False):
    try:
        q = quote(b["coin"], b["market"])
        price = q["price"]
    except Exception:
        q, price = None, None
    r = assess(b, price)
    key, p = b["id"], b["position"]
    icon = {"Long": "🟢", "Short": "🔴", "Neutral": "🟡"}[b["direction"]]
    with st.container(border=True):
        st.subheader(f"{icon} {b['coin']} · {b['strategy']} {b['direction']}")
        st.caption(b["name"] + " · " + b["lifecycle"] + " · " + b["market"])
        cols = st.columns(3)
        cols[0].metric("Последняя цена", fmt(price, 6))
        label = "PnL с OKX: снимок" if b["direction"] == "Neutral" else "Общий PnL ≈ USDT" if b["strategy"] == "DCA" else "Открытый PnL ≈ USDT"
        cols[1].metric(label, fmt(r["pnl"]))
        cols[2].metric("Резерв маржи USDT", fmt(r["reserve"]))
        st.markdown("### Анализ текущей ситуации")
        getattr(st, r["tone"])(r["title"] + ". " + r["reason"])
        if b["strategy"] == "DCA":
            st.caption(f"Закрытые циклы: {fmt(r['realized'])} USDT · Открытый PnL: {fmt(r['floating'])} USDT")
        st.caption("Сверка позиции UTC: " + (p.get("last_check") or "не выполнена"))
        if q:
            st.caption("Время рыночной цены UTC: " + datetime.fromtimestamp(q["ts"] / 1000, timezone.utc).isoformat())
        if compact:
            if st.button("Открыть карточку", key=key + "open"):
                move(b["strategy"], focus=key)
            return
        position_form(b)
        plan_form(b)
        with st.expander("Уровни и полные настройки"):
            for field, label in [("tp", "Модельный TP"), ("next_so", "Следующий СО"), ("liq_distance", "До введённой ликвидации, %")]:
                st.write(label + ": " + fmt(r[field], 6 if field != "liq_distance" else 2))
            table(pd.DataFrame([{"Параметр": k, "Значение": str(v)} for k, v in b["settings"].items()]))
            qty, avg = num(p.get("volume")), num(p.get("avg_price"))
            if qty > 0 and avg > 0 and sign(b["direction"]) and price:
                prices = np.linspace(min(price, avg) * .85, max(price, avg) * 1.15, 120)
                fig = go.Figure(go.Scatter(x=prices, y=sign(b["direction"]) * qty * (prices - avg), name="Открытый PnL", line=dict(color="#00ff9d")))
                fig.add_hline(y=0, line_dash="dot")
                fig.update_layout(template="plotly_dark", title="Профиль позиции без комиссий и funding", height=330)
                st.plotly_chart(fig, use_container_width=True)
        with st.form(key + "decision"):
            decision = st.radio("Моё решение", ["Не трогать", "Проверить на OKX", "Выход по плану"], horizontal=True)
            note = st.text_input("Причина")
            hours = st.number_input("Перепроверить через часов", min_value=.1, max_value=168., value=6.)
            if st.form_submit_button("Записать решение", disabled=not DB_READY):
                if not note.strip():
                    st.error("Укажи причину решения.")
                else:
                    b["decision"] = dict(action=decision, reason=note.strip(), created_at=now(), valid_hours=hours)
                    save_bot(b, "Решение пользователя", canonical(b["decision"]))
                    st.rerun()
        decision = b.get("decision")
        if isinstance(decision, dict):
            st.caption("Последнее решение: " + str(decision.get("action", "")) + " · " + str(decision.get("reason", "")))
            if age(decision.get("created_at")) >= num(decision.get("valid_hours"), 6):
                st.warning("Срок решения истёк: перепроверь позицию и план.")
        elif decision:
            st.caption(str(decision))
        if st.button("Отправить отчёт в Telegram", key=key + "telegram"):
            event_key = key + "_telegram_last"
            payload = canonical(dict(title=r["title"], check=p.get("last_check"), pnl=round(r["pnl"], 2) if r["pnl"] is not None else None))
            previous = st.session_state.get(event_key, {})
            if previous.get("payload") == payload and time.time() - previous.get("ts", 0) < 60:
                st.info("Такой отчёт уже отправлен менее минуты назад.")
            else:
                text = f"{b['name']}\n{b['coin']} · {b['strategy']} · {b['direction']}\n\n{r['title']}\n{r['reason']}\n\nЦена: {fmt(price, 6)}\nPnL: {fmt(r['pnl'])} USDT\nСверка UTC: {p.get('last_check') or 'нет'}\n\nПроверь исполнение и действуй по своему плану на OKX. Торговая команда не отправлялась."
                send_telegram(text)
                st.session_state[event_key] = dict(payload=payload, ts=time.time())
                st.success("Отчёт отправлен. Защита от повторов действует в текущей сессии.")
        st.caption("Комиссии и funding открытой позиции отдельно не учтены. «Не трогать» не отключает стоп и предупреждения. Автоматического закрытия сделок нет.")


def cards(bots, compact=False):
    for b in bots:
        try:
            bot_card(b, compact)
        except Exception as exc:
            if isinstance(exc, ValueError):
                st.error(str(exc))
            else:
                st.error(f"Действие по карточке «{b.get('name', 'Бот')}» не подтверждено: {type(exc).__name__}. Обнови список перед повтором. Данные не удаляются.")


def list_bots(bots, prefix, compact=False):
    status = st.radio("Показывать", ["Все", "Работает", "Черновик", "Закрыт"], horizontal=True, key=prefix + "filter")
    selected = [b for b in bots if status == "Все" or b["lifecycle"] == status]
    selected.sort(key=lambda b: b["id"] != st.session_state.get("focus"))
    if not selected:
        st.info("Нет карточек для выбранного фильтра.")
    cards(selected, compact)


def settings_page(bots):
    panel("Настройки", "PostgreSQL, проверка подключения, резервные копии и Telegram.")
    st.write("Пароль: включён через APP_PASSWORD.")
    if DB_READY:
        st.success("PostgreSQL доступна. Карточки прочитаны из базы.")
    elif DB_URL:
        st.error("Адрес базы задан, но чтение карточек не подтверждено. Пустой список не означает, что данные удалены.")
    else:
        st.warning("DATABASE_URL не настроен. Сохранение заблокировано.")
    if st.button("Проверить PostgreSQL"):
        try:
            check_postgres()
            st.success("SELECT 1 выполнен. Это проверка соединения, не резервного копирования и не права записи.")
        except Exception as exc:
            st.error("Проверка не пройдена: " + type(exc).__name__ + ". Проверь реальный адрес базы и параметры доступа.")
    if DB_READY:
        st.caption(f"Всего карточек в этой базе: {len(bots)}. Поддерживаются прежние terminal_bots и terminal_events.")
        if st.button("Подготовить резервную копию JSON"):
            st.session_state["backup"] = dict(data=backup_bytes(), timestamp=now())
        backup = st.session_state.get("backup")
        if backup:
            st.caption("Копия сформирована UTC: " + backup["timestamp"])
            st.download_button("Скачать подготовленную копию", backup["data"], "okx_backup.json", "application/json")
        uploaded = st.file_uploader("Восстановить JSON, до 5 MB", type=["json"])
        confirmed = st.checkbox("Добавить копии с новыми ID. Не заменять существующие карточки. После импорта сверить позиции.")
        if st.button("Восстановить копии", disabled=uploaded is None or not confirmed):
            if uploaded.size > 5_000_000:
                raise ValueError("Файл больше 5 MB.")
            count = import_backup(json.loads(uploaded.getvalue()))
            st.session_state["_flash"] = f"Импортировано карточек: {count}. Они видны как черновики; сверь позиции перед статусом «Работает»."
            st.rerun()
        with st.expander("Перенести оставшийся локальный SQLite"):
            st.caption("Только если старый файл ещё есть на этом сервере. Чтение без изменения исходника. Повторный импорт создаёт копии.")
            confirm_sqlite = st.checkbox("Подтверждаю перенос копий без удаления оригинала")
            if st.button("Перенести локальные карточки в PostgreSQL", disabled=not confirm_sqlite):
                if not os.path.isfile(DB_FILE):
                    raise ValueError("Старый файл не найден. Исчезнувший файл без копии восстановить нельзя.")
                c = sqlite3.connect("file:" + os.path.abspath(DB_FILE) + "?mode=ro", uri=True)
                try:
                    c.row_factory = sqlite3.Row
                    tables = {row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    if "terminal_bots" in tables:
                        raw = [json.loads(row[0]) for row in c.execute("SELECT document FROM terminal_bots")]
                    elif "bots" in tables:
                        raw = [dict(row) for row in c.execute("SELECT * FROM bots")]
                    else:
                        raise ValueError("Таблицы карточек не найдены.")
                finally:
                    c.close()
                count = import_backup(dict(bots=raw))
                st.session_state["_flash"] = f"Перенесено копий: {count}. Обнови фактические позиции."
                st.rerun()
    with st.expander("Telegram"):
        st.text_input("Token, если нет в Secrets", type="password", key="tg_token")
        st.text_input("Chat ID, если нет в Secrets", key="tg_chat")
        if st.button("Тест Telegram"):
            send_telegram("OKX Terminal Pro: тест подключения. Торговые команды не отправляются.")
            st.success("Тест отправлен.")
    with st.expander("Что указать в Streamlit Secrets", expanded=not DB_URL):
        st.code('APP_PASSWORD = "твой-длинный-пароль"\nDATABASE_URL = "postgresql://USER:PASSWORD@HOST:5432/DATABASE?sslmode=require"\n\n# Необязательно:\nTELEGRAM_TOKEN = "токен"\nTELEGRAM_CHAT_ID = "chat-id"', language="toml")
        st.caption("Это пример, не рабочие реквизиты. Вставь строку подключения своей PostgreSQL. Существующий настоящий DATABASE_URL не заменяй примером. Секреты не публикуй в GitHub.")
    st.caption("Автоматические резервные копии нужно отдельно включить и проверить у провайдера базы. Здесь есть ручной экспорт/импорт. Независимого фонового мониторинга нет; Telegram отправляется по кнопке.")


def main():
    global DB_READY
    apply_route()
    design()
    login()
    with st.sidebar:
        st.title("OKX Terminal")
        page = st.radio("Раздел", PAGES, key="page", label_visibility="collapsed")
        if st.button("Обновить цены и список"):
            quote.clear()
            api.clear()
            st.rerun()
        if st.button("Выйти"):
            st.session_state["_authenticated"] = False
            st.rerun()
        st.caption("Ручное сопровождение. Приватный торговый API не используется.")
    bots = []
    DB_READY = False
    if DB_URL:
        try:
            init_database()
            bots = load_bots()
            DB_READY = True
        except Exception as exc:
            st.error("Чтение PostgreSQL не подтверждено: " + type(exc).__name__ + ". Не удаляй данные и не меняй адрес на новую базу. Открой Настройки. Пустой экран не подтверждает потерю карточек.")
    else:
        st.warning("Нужен DATABASE_URL внешней PostgreSQL. Сканер и расчёты доступны, сохранение карточек пока заблокировано.")
    flash = st.session_state.pop("_flash", None)
    if flash:
        st.success(flash)
    try:
        if page == "Главная":
            panel("Твои боты", "Все сохранённые карточки, понятные статусы и действия по плану.")
            actions("home")
            cols = st.columns(3)
            for column, status, label in zip(cols, ["Работает", "Черновик", "Закрыт"], ["В работе", "Черновики", "Завершены"]):
                column.metric(label, sum(b["lifecycle"] == status for b in bots) if DB_READY else "—")
            if DB_READY:
                list_bots(bots, "home", compact=True)
            else:
                st.info("Список не прочитан. Это не утверждение, что карточек нет.")
        elif page == "Сканер":
            scanner()
        elif page in ("DCA", "Grid"):
            panel(page, "Мои боты и добавление нового или уже работающего бота.")
            mode = st.radio("Режим", ["Мои боты", "Добавить бота"], horizontal=True, key=page + "mode")
            if mode == "Добавить бота":
                creator(page)
            else:
                if st.button("Добавить " + page):
                    move(page, "Long" if page == "DCA" else "Neutral", mode="Добавить бота")
                if DB_READY:
                    list_bots([b for b in bots if b["strategy"] == page], page)
                else:
                    st.info("Подключи или восстанови доступ к PostgreSQL в Настройках.")
        elif page == "Открытая позиция":
            panel("Контроль позиций", "Позиции и планы видны явно. «Черновик» не означает потерю карточки.")
            if DB_READY:
                list_bots(bots, "positions")
            else:
                st.info("Не удалось прочитать карточки из базы.")
        elif page == "Журнал":
            panel("Журнал", "Создание карточек, изменения планов, сверки и решения. Время UTC.")
            if DB_READY:
                df = history()
                if df.empty:
                    st.info("В этой базе журнал пока пуст.")
                else:
                    table(df)
                    st.download_button("Скачать журнал CSV", df.to_csv(index=False).encode("utf-8-sig"), "journal.csv", "text/csv")
            else:
                st.info("Журнал не прочитан: нет подтверждённого подключения к базе.")
            st.caption("Снимки PnL одной позиции не суммируются как прибыль.")
        else:
            settings_page(bots)
    except Exception as exc:
        if isinstance(exc, ValueError):
            st.error(str(exc))
        else:
            st.error("Действие не подтверждено: " + type(exc).__name__ + ". После ошибки записи обнови список перед повтором. Адрес базы и токены не публикуй.")


main()
