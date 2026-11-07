import os
import json
import math
import time
import uuid
import hmac
import html
import logging
import sqlite3

from contextlib import contextmanager
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlencode

import pandas as pd
import streamlit as st

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
except ImportError:
    go = None
    make_subplots = None


# =========================================================
# CONFIG
# =========================================================

st.set_page_config(
    page_title="OKX Terminal Pro",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

LOGGER = logging.getLogger("okx_terminal")

API = "https://www.okx.com/api/v5"

PAGES = [
    "1. Главная",
    "2. Сканер",
    "3. ИИ-Центр",
    "4. DCA",
    "5. Grid",
    "6. Журнал решений",
    "7. Настройки",
]

COINS = [
    "BTC", "ETH", "SOL", "BNB", "XRP",
    "DOGE", "ADA", "AVAX", "LINK", "DOT",
    "TRX", "LTC", "NEAR", "APT",
    "ARB", "OP", "SUI", "PEPE", "INJ",
]

WHITE = "#FFFFFF"
TEXT_DARK = "#172033"
LONG_COLOR = "#137333"
SHORT_COLOR = "#C5223F"
NEUTRAL_COLOR = "#174EA6"
WAIT_COLOR = "#475569"


def secret(name, default=""):
    try:
        return st.secrets.get(
            name,
            os.getenv(name, default),
        )
    except Exception:
        return os.getenv(name, default)


DB_URL = str(secret("DATABASE_URL")).strip()
DB_FILE = str(secret("SQLITE_PATH", "bots.sqlite3"))


def now():
    return datetime.now(timezone.utc).isoformat()


def number(value, default=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except (ValueError, TypeError):
        return default


def formatted(value, digits=2):
    if value is None:
        return "Нет данных"
    return f"{value:,.{digits}f}"


def side(direction):
    return {
        "Long": 1,
        "Short": -1,
        "Neutral": 0,
    }.get(direction, 0)


def age_hours(value):
    try:
        dt = datetime.fromisoformat(value)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return max(
            0,
            (
                datetime.now(timezone.utc) - dt
            ).total_seconds() / 3600,
        )
    except (ValueError, TypeError):
        return float("inf")


def numeric(label, value, key, minimum=0.0, maximum=None):
    arguments = {
        "label": label,
        "value": float(value),
        "min_value": float(minimum),
        "key": key,
    }

    if maximum is not None:
        arguments["max_value"] = float(maximum)

    return st.number_input(**arguments)


def navigate(page, direction=None, create=False):
    st.session_state["pending_page"] = page

    if direction:
        st.session_state["preferred_direction"] = direction

    if create and page == "4. DCA":
        st.session_state["DCA_page_mode"] = "Добавить / подготовить"

    if create and page == "5. Grid":
        st.session_state["Grid_page_mode"] = "Добавить / подготовить"

    st.rerun()


# =========================================================
# DESIGN
# =========================================================

def apply_design():
    st.markdown(
        """
<style>
:root {
    --terminal-bg: #05070c;
    --terminal-panel: #101827;
    --terminal-border: #2b3b54;
    --terminal-text: #edf3ff;
    --terminal-muted: #b6c5da;
}

.stApp {
    background:
        radial-gradient(
            1100px 650px at 0% -10%,
            rgba(0, 255, 157, .07),
            transparent 60%
        ),
        radial-gradient(
            900px 600px at 100% 0%,
            rgba(88, 101, 242, .10),
            transparent 60%
        ),
        linear-gradient(180deg, #05070c, #080d16);
    color: #edf3ff;
}

.block-container {
    max-width: 1400px;
    padding-top: 1.5rem;
    padding-bottom: 3rem;
}

h1, h2, h3, h4 {
    color: #edf3ff !important;
    letter-spacing: -.035em;
}

[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li {
    color: #edf3ff;
}

[data-testid="stCaptionContainer"] p {
    color: #b6c5da !important;
}

[data-testid="stWidgetLabel"] p {
    color: #edf3ff !important;
    font-weight: 600;
}

[data-testid="stSidebar"] {
    background: #080d16;
    border-right: 1px solid #2b3b54;
}

[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {
    color: #edf3ff !important;
}

.glass {
    background: linear-gradient(135deg, #142333, #11182a);
    border: 1px solid #30455e;
    border-radius: 20px;
    padding: 22px;
    margin-bottom: 18px;
}

.glass-title {
    color: #f0f5ff;
    font-size: clamp(1.5rem, 4vw, 2.2rem);
    font-weight: 800;
}

.glass-sub {
    color: #b8c8de;
    line-height: 1.6;
    margin-top: 8px;
}

.metric-card {
    background: linear-gradient(135deg, #152133, #101725);
    border: 1px solid #2a3a52;
    border-radius: 17px;
    padding: 18px;
    margin-bottom: 10px;
}

.metric-label {
    color: #b6c5da;
    font-size: .78rem;
    font-weight: 700;
    letter-spacing: .04em;
}

.metric-value {
    color: #f1f6ff;
    font-size: clamp(1.15rem, 3vw, 1.75rem);
    font-weight: 800;
    margin-top: 8px;
    overflow-wrap: anywhere;
}

.metric-value.positive {
    color: #95f2be;
}

.metric-value.negative {
    color: #ffacbd;
}

.metric-value.warning {
    color: #ffe19a;
}

[data-testid="stMetric"] {
    background: #131e2e;
    border: 1px solid #29384f;
    border-radius: 15px;
    padding: 16px;
}

[data-testid="stMetricLabel"],
[data-testid="stMetricLabel"] p,
[data-testid="stMetricLabel"] span {
    color: #b6c5da !important;
}

[data-testid="stMetricValue"],
[data-testid="stMetricValue"] div {
    color: #f3f7ff !important;
}

/* Белые поля ввода, тёмные значения. */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea {
    background: #ffffff !important;
    color: #172033 !important;
    -webkit-text-fill-color: #172033 !important;
    caret-color: #172033 !important;
}

[data-testid="stTextInput"] input::placeholder,
[data-testid="stTextArea"] textarea::placeholder {
    color: #475569 !important;
    opacity: 1 !important;
}

[data-testid="stNumberInput"] button {
    background: #eef2f7 !important;
    color: #172033 !important;
}

/* Закрытые выпадающие списки. */
[data-testid="stSelectbox"] [data-baseweb="select"] > div,
[data-testid="stMultiSelect"] [data-baseweb="select"] > div {
    background: #ffffff !important;
    color: #172033 !important;
}

[data-testid="stSelectbox"] [data-baseweb="select"] span,
[data-testid="stSelectbox"] [data-baseweb="select"] input,
[data-testid="stMultiSelect"] [data-baseweb="select"] input {
    color: #172033 !important;
    -webkit-text-fill-color: #172033 !important;
}

/* Открытые списки. */
[role="listbox"],
[role="option"] {
    background: #ffffff !important;
    color: #172033 !important;
}

[role="option"]:hover,
[role="option"][aria-selected="true"] {
    background: #e8f0fe !important;
    color: #172033 !important;
}

/* Все radio-варианты: белый фон, читаемый текст. */
[data-testid="stRadio"] [role="radiogroup"] > label {
    background: #ffffff !important;
    border: 2px solid #cbd5e1 !important;
    border-radius: 10px;
    padding: 8px 12px !important;
    margin: 3px !important;
    opacity: 1 !important;
}

[data-testid="stRadio"] [role="radiogroup"] > label p {
    color: #172033 !important;
    font-weight: 700 !important;
    opacity: 1 !important;
}

[data-testid="stRadio"] [role="radiogroup"] > label:has(input:checked) {
    border-color: #2563eb !important;
    box-shadow: 0 0 0 1px #2563eb;
}

/* Направления: цвет текста, а не цветная заливка. */
[class*="st-key-dca_direction_"] [role="radiogroup"] > label:nth-of-type(1) p,
[class*="st-key-grid_direction_"] [role="radiogroup"] > label:nth-of-type(1) p {
    color: #137333 !important;
}

[class*="st-key-dca_direction_"] [role="radiogroup"] > label:nth-of-type(2) p,
[class*="st-key-grid_direction_"] [role="radiogroup"] > label:nth-of-type(2) p {
    color: #c5223f !important;
}

[class*="st-key-grid_direction_"] [role="radiogroup"] > label:nth-of-type(3) p {
    color: #174ea6 !important;
}

/* Кнопки по умолчанию. */
.stButton button,
.stFormSubmitButton button,
.stDownloadButton button {
    background: #ffffff !important;
    color: #172033 !important;
    border: 1px solid #b9c7da !important;
    border-radius: 12px;
    min-height: 44px;
    font-weight: 700;
}

.stButton button p,
.stFormSubmitButton button p,
.stDownloadButton button p {
    color: inherit !important;
}

.stButton button:hover,
.stFormSubmitButton button:hover,
.stDownloadButton button:hover {
    background: #eaf1fb !important;
    border-color: #2563eb !important;
}

.stButton button:disabled,
.stFormSubmitButton button:disabled {
    background: #e5e7eb !important;
    color: #475569 !important;
    border-color: #cbd5e1 !important;
    opacity: 1 !important;
}

.st-key-home_long button {
    color: #137333 !important;
    border: 2px solid #137333 !important;
}

.st-key-home_short button {
    color: #c5223f !important;
    border: 2px solid #c5223f !important;
}

.st-key-home_grid button {
    color: #174ea6 !important;
    border: 2px solid #174ea6 !important;
}

/* Чекбоксы и подписи раскрывающихся блоков. */
[data-testid="stCheckbox"] p,
[data-testid="stExpander"] summary p {
    color: #edf3ff !important;
}

[data-testid="stExpander"] {
    border-radius: 13px;
    border-color: #30455e;
}

/* Сообщения: светлый фон и тёмный текст. */
[data-testid="stAlert"] {
    background: #eef4ff !important;
    border: 1px solid #b6c9e8 !important;
    border-radius: 12px;
}

[data-testid="stAlert"] p,
[data-testid="stAlert"] li,
[data-testid="stAlert"] span {
    color: #172033 !important;
}

/* Код и JSON. */
[data-testid="stCode"] pre,
[data-testid="stCode"] code {
    background: #ffffff !important;
    color: #172033 !important;
}

/* Цветные подписи не используются без названия. */
.direction-long {
    color: #137333;
    background: #ffffff;
    font-weight: 700;
}

.direction-short {
    color: #c5223f;
    background: #ffffff;
    font-weight: 700;
}

@media(max-width: 640px) {
    .block-container {
        padding: 1rem;
    }

    .glass {
        padding: 18px;
    }
}
</style>
        """,
        unsafe_allow_html=True,
    )


def metric_card(label, value, tone=""):
    if tone not in {"", "positive", "negative", "warning"}:
        tone = ""

    st.markdown(
        '<div class="metric-card">'
        f'<div class="metric-label">{html.escape(str(label))}</div>'
        f'<div class="metric-value {tone}">'
        f'{html.escape(str(value))}'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )


def panel(title, subtitle):
    st.markdown(
        '<div class="glass">'
        f'<div class="glass-title">{html.escape(str(title))}</div>'
        f'<div class="glass-sub">{html.escape(str(subtitle))}</div>'
        '</div>',
        unsafe_allow_html=True,
    )


def direction_style(value):
    colors = {
        "Long": LONG_COLOR,
        "Short": SHORT_COLOR,
        "Neutral": NEUTRAL_COLOR,
        "Не определено": TEXT_DARK,
        "—": TEXT_DARK,
    }

    color = colors.get(str(value), TEXT_DARK)

    return (
        f"color:{color};"
        "background-color:#ffffff;"
        "font-weight:700;"
    )


def show_table(frame, formats=None, direction_column=None):
    if frame.empty:
        st.info("Нет данных для отображения.")
        return

    safe_formats = {
        key: value
        for key, value in (formats or {}).items()
        if key in frame.columns
    }

    styled = (
        frame.style
        .format(safe_formats, na_rep="Нет данных")
        .set_properties(**{
            "background-color": WHITE,
            "color": TEXT_DARK,
        })
    )

    if direction_column in frame.columns:
        styled = styled.map(
            direction_style,
            subset=[direction_column],
        )

    st.dataframe(
        styled,
        hide_index=True,
        use_container_width=True,
    )


# =========================================================
# LOGIN
# =========================================================

def login():
    password = str(secret("APP_PASSWORD"))

    if not password:
        return

    if st.session_state.get("authenticated"):
        return

    panel(
        "OKX Terminal Pro",
        "Вход в личный терминал",
    )

    entered = st.text_input(
        "Пароль",
        type="password",
    )

    if st.button("Войти", type="primary"):
        correct = hmac.compare_digest(
            entered.encode("utf-8"),
            password.encode("utf-8"),
        )

        if correct:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Неверный пароль.")

    st.stop()


# =========================================================
# DATABASE
# =========================================================

@contextmanager
def database():
    if DB_URL:
        try:
            import psycopg2
        except ImportError as error:
            raise RuntimeError(
                "Для PostgreSQL нужен psycopg2-binary."
            ) from error

        connection = psycopg2.connect(
            DB_URL,
            connect_timeout=10,
        )
    else:
        connection = sqlite3.connect(
            DB_FILE,
            timeout=20,
        )
        connection.execute("PRAGMA busy_timeout=20000")

    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def execute(connection, statement, parameters=()):
    cursor = connection.cursor()

    if DB_URL:
        statement = statement.replace("?", "%s")

    cursor.execute(statement, parameters)
    return cursor


def initialize_database():
    with database() as connection:
        execute(
            connection,
            """
            CREATE TABLE IF NOT EXISTS terminal_bots (
                id TEXT PRIMARY KEY,
                document TEXT NOT NULL,
                revision INTEGER NOT NULL
            )
            """,
        )

        execute(
            connection,
            """
            CREATE TABLE IF NOT EXISTS terminal_events (
                id TEXT PRIMARY KEY,
                bot_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                title TEXT NOT NULL,
                details TEXT NOT NULL
            )
            """,
        )


def add_event(connection, bot_id, title, details):
    execute(
        connection,
        """
        INSERT INTO terminal_events
        (id, bot_id, created_at, title, details)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            bot_id,
            now(),
            title,
            details,
        ),
    )


def load_bots():
    with database() as connection:
        rows = execute(
            connection,
            "SELECT document, revision FROM terminal_bots",
        ).fetchall()

    result = []

    for document, revision in rows:
        bot = json.loads(document)
        bot["_revision"] = revision
        bot.setdefault("lifecycle", "Черновик")
        bot.setdefault("position", {})
        bot.setdefault("decision", "")
        result.append(bot)

    return sorted(
        result,
        key=lambda bot: bot.get("updated_at", ""),
        reverse=True,
    )


def save_bot(bot, title, details):
    document = dict(bot)
    revision = document.pop("_revision", None)
    document["updated_at"] = now()

    payload = json.dumps(
        document,
        ensure_ascii=False,
        allow_nan=False,
    )

    with database() as connection:
        if revision is None:
            execute(
                connection,
                """
                INSERT INTO terminal_bots
                (id, document, revision)
                VALUES (?, ?, ?)
                """,
                (document["id"], payload, 1),
            )
        else:
            cursor = execute(
                connection,
                """
                UPDATE terminal_bots
                SET document = ?, revision = revision + 1
                WHERE id = ? AND revision = ?
                """,
                (
                    payload,
                    document["id"],
                    revision,
                ),
            )

            if cursor.rowcount != 1:
                raise ValueError(
                    "Карточка изменена в другой вкладке. "
                    "Обнови страницу."
                )

        add_event(
            connection,
            document["id"],
            title,
            details,
        )


def load_events():
    with database() as connection:
        rows = execute(
            connection,
            """
            SELECT bot_id, created_at, title, details
            FROM terminal_events
            ORDER BY created_at DESC
            LIMIT 3000
            """,
        ).fetchall()

    return pd.DataFrame(
        rows,
        columns=[
            "Бот ID",
            "Дата UTC",
            "Событие",
            "Подробности",
        ],
    )


# =========================================================
# OKX PUBLIC DATA
# =========================================================

def symbol_for(coin, market):
    return (
        f"{coin}-USDT-SWAP"
        if market == "SWAP"
        else f"{coin}-USDT"
    )


def api_get(path, parameters):
    request = Request(
        API + path + "?" + urlencode(parameters),
        headers={"User-Agent": "OKX-Terminal-Pro"},
    )

    with urlopen(request, timeout=15) as response:
        payload = json.load(response)

    if payload.get("code") != "0":
        raise ValueError(
            "OKX не подтвердил запрос данных."
        )

    return payload.get("data", [])


@st.cache_data(ttl=20, show_spinner=False)
def get_quote(coin, market):
    symbol = symbol_for(coin, market)

    rows = api_get(
        "/market/ticker",
        {"instId": symbol},
    )

    row = next(
        (
            item for item in rows
            if item.get("instId") == symbol
        ),
        None,
    )

    if not row:
        raise ValueError("Инструмент не найден.")

    price = number(row.get("last"))
    timestamp = number(row.get("ts")) / 1000

    if (
        price <= 0
        or timestamp <= 0
        or time.time() - timestamp > 180
    ):
        raise ValueError(
            "Нет свежей корректной цены."
        )

    if market == "SWAP":
        volume = number(row.get("volCcy24h")) * price
    else:
        volume = number(row.get("volCcy24h"))

    return {
        "price": price,
        "timestamp": timestamp,
        "volume_usdt_estimate": volume,
    }


@st.cache_data(ttl=180, show_spinner=False)
def daily_candles(coin, market):
    raw = api_get(
        "/market/candles",
        {
            "instId": symbol_for(coin, market),
            "bar": "1D",
            "limit": "120",
        },
    )

    rows = [
        [
            int(item[0]),
            float(item[1]),
            float(item[2]),
            float(item[3]),
            float(item[4]),
        ]
        for item in raw
        if len(item) >= 9
        and str(item[8]) == "1"
    ]

    if len(rows) < 40:
        raise ValueError(
            "Недостаточно закрытых дневных свечей."
        )

    frame = pd.DataFrame(
        rows,
        columns=["ts", "open", "high", "low", "close"],
    )

    frame = (
        frame.drop_duplicates("ts")
        .sort_values("ts")
        .reset_index(drop=True)
    )

    frame["time"] = pd.to_datetime(
        frame["ts"],
        unit="ms",
        utc=True,
    )

    return frame


@st.cache_data(ttl=300, show_spinner=False)
def historical_candles(coin, market, days, bar):
    cutoff = int(
        (time.time() - days * 86400) * 1000
    )

    step_ms = {
        "15m": 900000,
        "1H": 3600000,
        "4H": 14400000,
    }[bar]

    collected = {}
    after = None
    previous_oldest = None

    for _ in range(120):
        parameters = {
            "instId": symbol_for(coin, market),
            "bar": bar,
            "limit": "100",
        }

        if after is not None:
            parameters["after"] = str(after)

        batch = api_get(
            "/market/history-candles",
            parameters,
        )

        if not batch:
            break

        oldest = min(int(item[0]) for item in batch)

        for item in batch:
            if (
                len(item) >= 9
                and str(item[8]) == "1"
                and int(item[0]) >= cutoff
            ):
                collected[int(item[0])] = [
                    int(item[0]),
                    float(item[4]),
                ]

        if (
            oldest <= cutoff
            or oldest == previous_oldest
        ):
            break

        previous_oldest = oldest
        after = oldest
        time.sleep(0.12)

    if len(collected) < 30:
        raise ValueError(
            "Недостаточно исторических свечей."
        )

    frame = pd.DataFrame(
        sorted(collected.values()),
        columns=["ts", "close"],
    )

    frame["time"] = pd.to_datetime(
        frame["ts"],
        unit="ms",
        utc=True,
    )

    if (
        frame["ts"].diff().dropna() > step_ms
    ).any():
        raise ValueError(
            "В истории есть пропуски. "
            "Сравнение остановлено."
        )

    return frame


# =========================================================
# INDICATORS
# =========================================================

def wilder(series, period=14):
    result = pd.Series(
        float("nan"),
        index=series.index,
        dtype=float,
    )

    seed = []
    previous = None

    for index, value in series.items():
        if pd.isna(value):
            continue

        value = float(value)

        if previous is None:
            seed.append(value)

            if len(seed) == period:
                previous = sum(seed) / period
                result.loc[index] = previous
        else:
            previous = (
                previous * (period - 1) + value
            ) / period

            result.loc[index] = previous

    return result


def indicators(frame):
    frame = frame.copy()
    difference = frame["close"].diff()

    average_gain = wilder(
        difference.clip(lower=0)
    )

    average_loss = wilder(
        -difference.clip(upper=0)
    )

    rsi = pd.Series(
        float("nan"),
        index=frame.index,
    )

    for index in frame.index:
        gain = average_gain.loc[index]
        loss = average_loss.loc[index]

        if pd.isna(gain) or pd.isna(loss):
            continue

        if gain == 0 and loss == 0:
            rsi.loc[index] = 50
        elif loss == 0:
            rsi.loc[index] = 100
        else:
            rsi.loc[index] = (
                100 - 100 / (1 + gain / loss)
            )

    previous_close = frame["close"].shift(1)

    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    true_range.iloc[0] = float("nan")
    atr = wilder(true_range)

    up = frame["high"].diff()
    down = -frame["low"].diff()

    plus_dm = pd.Series(0.0, index=frame.index)
    minus_dm = pd.Series(0.0, index=frame.index)

    plus_mask = (up > down) & (up > 0)
    minus_mask = (down > up) & (down > 0)

    plus_dm.loc[plus_mask] = up.loc[plus_mask]
    minus_dm.loc[minus_mask] = down.loc[minus_mask]

    plus_dm.iloc[0] = float("nan")
    minus_dm.iloc[0] = float("nan")

    smooth_plus = wilder(plus_dm)
    smooth_minus = wilder(minus_dm)

    plus_di = 100 * smooth_plus / atr
    minus_di = 100 * smooth_minus / atr

    denominator = plus_di + minus_di

    dx = (
        100
        * (plus_di - minus_di).abs()
        / denominator
    )

    flat = (
        denominator.eq(0)
        | (
            atr.eq(0)
            & smooth_plus.eq(0)
            & smooth_minus.eq(0)
        )
    )

    dx.loc[flat] = 0

    frame["RSI"] = rsi
    frame["ADX"] = wilder(dx)
    frame["ATR %"] = atr / frame["close"] * 100

    return frame


# =========================================================
# CHART
# =========================================================

def scanner_chart(frame, title):
    if go is None:
        st.line_chart(
            frame.set_index("time")[["close"]]
        )

        st.line_chart(
            frame.set_index("time")[["RSI", "ADX"]]
        )
        return

    figure = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.60, 0.20, 0.20],
        vertical_spacing=0.04,
    )

    figure.add_trace(
        go.Candlestick(
            x=frame["time"],
            open=frame["open"],
            high=frame["high"],
            low=frame["low"],
            close=frame["close"],
            name="Цена",
            increasing_line_color="#00e99b",
            decreasing_line_color="#ff6b86",
        ),
        row=1,
        col=1,
    )

    figure.add_trace(
        go.Scatter(
            x=frame["time"],
            y=frame["RSI"],
            name="RSI",
            line={"color": "#00c2ff"},
        ),
        row=2,
        col=1,
    )

    figure.add_trace(
        go.Scatter(
            x=frame["time"],
            y=frame["ADX"],
            name="ADX",
            line={"color": "#ffd166"},
        ),
        row=3,
        col=1,
    )

    figure.add_hline(
        y=30,
        row=2,
        col=1,
        line_dash="dot",
    )

    figure.add_hline(
        y=70,
        row=2,
        col=1,
        line_dash="dot",
    )

    figure.add_hline(
        y=25,
        row=3,
        col=1,
        line_dash="dot",
    )

    figure.update_layout(
        title=title,
        template="plotly_dark",
        height=670,
        paper_bgcolor="#101827",
        plot_bgcolor="#101827",
        font={"color": "#edf3ff"},
        xaxis_rangeslider_visible=False,
        margin={"l": 5, "r": 5, "t": 45, "b": 5},
    )

    st.plotly_chart(
        figure,
        use_container_width=True,
    )


# =========================================================
# SCANNER
# =========================================================

def scanner_page():
    panel(
        "Сканер рынка",
        "DCA и Grid — стратегии. "
        "Long, Short и Neutral — направления.",
    )

    market = st.radio(
        "Рынок",
        ["SWAP", "SPOT"],
        horizontal=True,
        key="scanner_market",
    )

    selected_coins = st.multiselect(
        "Монеты",
        COINS,
        default=COINS,
        key="scanner_coins",
    )

    threshold = numeric(
        "Порог объёма за 24 часа, USDT",
        10_000_000,
        "scanner_volume_threshold",
    )

    st.caption(
        "Исходные правила RSI/ADX. "
        "Закрытые дневные свечи. "
        "Прибыльность этих правил не подтверждена."
    )

    if st.button(
        "Сканировать",
        type="primary",
        use_container_width=True,
    ):
        if not selected_coins:
            st.warning("Выбери хотя бы одну монету.")
            return

        rows = []
        errors = []
        charts = {}
        progress = st.progress(0.0)

        for index, coin in enumerate(selected_coins):
            try:
                frame = indicators(
                    daily_candles(coin, market)
                )

                last = frame.iloc[-1]
                ticker = get_quote(coin, market)

                rsi = float(last["RSI"])
                adx = float(last["ADX"])
                atr = float(last["ATR %"])

                if not all(
                    math.isfinite(value)
                    for value in (rsi, adx, atr)
                ):
                    raise ValueError(
                        "Индикаторы ещё не готовы."
                    )

                if adx > 25:
                    if rsi < 40:
                        strategy = "DCA"
                        direction = "Long"
                        status = "Рассмотреть"
                        reason = "ADX > 25 и RSI < 40"
                    elif rsi > 50:
                        strategy = "—"
                        direction = "—"
                        status = "Ждать"
                        reason = "ADX > 25 и RSI > 50"
                    else:
                        strategy = "DCA"
                        direction = "Short"
                        status = "Рассмотреть"
                        reason = "ADX > 25 и RSI 40–50"
                else:
                    strategy = "Grid"
                    direction = "Не определено"
                    status = "Рассмотреть"
                    reason = "ADX ≤ 25"

                if market == "SPOT" and direction == "Short":
                    status = "Не поддерживается на Spot"
                    reason += "; Spot Short здесь недоступен"

                volume = ticker["volume_usdt_estimate"]
                flags = []

                if volume <= 0:
                    liquidity = "Нет оценки"
                    flags.append("Нет оценки объёма")
                elif volume < threshold:
                    liquidity = "Ниже порога"
                    flags.append("Объём ниже порога")
                else:
                    liquidity = "Выше порога"

                if atr > 3:
                    flags.append("ATR > 3%")

                if rsi < 30 or rsi > 70:
                    flags.append("Крайнее значение RSI")

                rows.append({
                    "Монета": coin,
                    "Цена": ticker["price"],
                    "Стратегия": strategy,
                    "Направление": direction,
                    "Статус": status,
                    "RSI": rsi,
                    "ADX": adx,
                    "ATR %": atr,
                    "Объём 24H USDT ≈": volume,
                    "Ликвидность": liquidity,
                    "Факторы риска": (
                        "; ".join(flags)
                        or "Пороговые флаги не сработали"
                    ),
                    "Причина": reason,
                })

                charts[coin] = frame

            except Exception:
                errors.append(coin)

            progress.progress(
                (index + 1) / len(selected_coins)
            )

        st.session_state["scanner_result"] = {
            "rows": rows,
            "charts": charts,
            "errors": errors,
            "market": market,
            "time": now(),
        }

    result = st.session_state.get("scanner_result")

    if not result:
        return

    st.caption(
        f"Последний расчёт: "
        f"{result['market']} · {result['time']}"
    )

    same_market = result["market"] == market

    if not same_market:
        st.warning(
            "Показаны результаты другого рынка. "
            "Запусти сканирование заново."
        )

    if result["errors"]:
        st.warning(
            "Не рассчитаны: "
            + ", ".join(result["errors"])
        )

    if not result["rows"]:
        st.info("Нет результатов.")
        return

    frame = pd.DataFrame(result["rows"])

    columns = st.columns(4)

    with columns[0]:
        metric_card(
            "DCA Long",
            int(frame["Направление"].eq("Long").sum()),
            "positive",
        )

    with columns[1]:
        metric_card(
            "DCA Short",
            int(frame["Направление"].eq("Short").sum()),
            "negative",
        )

    with columns[2]:
        metric_card(
            "Grid",
            int(frame["Стратегия"].eq("Grid").sum()),
        )

    with columns[3]:
        metric_card(
            "Ждать",
            int(frame["Статус"].eq("Ждать").sum()),
        )

    strategy_filter = st.radio(
        "Стратегия",
        ["Все", "DCA", "Grid"],
        horizontal=True,
    )

    direction_filter = st.radio(
        "Направление",
        ["Все", "Long", "Short", "Не определено"],
        horizontal=True,
    )

    visible = frame.copy()

    if strategy_filter != "Все":
        visible = visible[
            visible["Стратегия"] == strategy_filter
        ]

    if direction_filter != "Все":
        visible = visible[
            visible["Направление"] == direction_filter
        ]

    show_table(
        visible,
        {
            "Цена": "{:,.6f}",
            "RSI": "{:.1f}",
            "ADX": "{:.1f}",
            "ATR %": "{:.2f}",
            "Объём 24H USDT ≈": "{:,.0f}",
        },
        "Направление",
    )

    if visible.empty:
        return

    selected = st.selectbox(
        "Монета для подробностей",
        visible["Монета"].tolist(),
    )

    row = frame[frame["Монета"] == selected].iloc[0]

    st.info(
        f"{row['Стратегия']} · "
        f"{row['Направление']} · "
        f"{row['Причина']}"
    )

    st.caption(row["Факторы риска"])

    scanner_chart(
        result["charts"][selected],
        f"{selected} · цена, RSI и ADX",
    )

    columns = st.columns(3)

    def open_creator(strategy, direction):
        prefix = strategy.lower()

        st.session_state[prefix + "_coin"] = selected
        st.session_state[prefix + "_market"] = result["market"]

        if strategy == "DCA":
            st.session_state[prefix + "_entry"] = float(
                row["Цена"]
            )

        navigate(
            "4. DCA" if strategy == "DCA" else "5. Grid",
            direction,
            create=True,
        )

    if columns[0].button(
        "Подготовить DCA Long",
        disabled=not same_market,
        use_container_width=True,
    ):
        open_creator("DCA", "Long")

    if columns[1].button(
        "Подготовить DCA Short",
        disabled=(
            not same_market
            or result["market"] == "SPOT"
        ),
        use_container_width=True,
    ):
        open_creator("DCA", "Short")

    if columns[2].button(
        "Подготовить Grid",
        disabled=not same_market,
        use_container_width=True,
    ):
        open_creator(
            "Grid",
            "Neutral" if result["market"] == "SWAP" else "Long",
        )

    st.caption(
        "Направление Grid автоматически не придумано. "
        "Выбери его при подготовке. "
        "Отсутствие флагов не означает низкий риск."
    )


# =========================================================
# DCA PLAN
# =========================================================

def dca_plan(settings, direction):
    entry = number(settings.get("entry"))
    step = number(settings.get("step"))
    count = int(settings.get("so_count", 0))
    first = number(settings.get("base_amount"))
    first_so = number(settings.get("first_so"))
    multiplier = number(settings.get("mart"))

    if (
        entry <= 0
        or step <= 0
        or first <= 0
        or first_so <= 0
        or multiplier < 1
        or not 0 <= count <= 30
        or direction not in ("Long", "Short")
    ):
        raise ValueError("Некорректные параметры DCA.")

    rows = []
    total_notional = 0.0
    total_quantity = 0.0

    for index in range(count + 1):
        price = entry * (
            1
            - side(direction)
            * step
            * index
            / 100
        )

        amount = (
            first
            if index == 0
            else first_so * multiplier ** (index - 1)
        )

        if price <= 0:
            raise ValueError(
                "Один из уровней СО имеет цену ≤ 0."
            )

        total_notional += amount
        total_quantity += amount / price

        rows.append({
            "Ордер": "Вход" if index == 0 else f"СО {index}",
            "Цена": price,
            "Номинал USDT": amount,
            "Всего номинал": total_notional,
            "Модельная средняя": (
                total_notional / total_quantity
            ),
        })

    return rows


# =========================================================
# LIMITED BACKTEST
# =========================================================

def simulate(frame, settings, strategy, direction, fee):
    capital = settings["base_margin"]
    wallet = capital
    quantity = 0.0
    average = 0.0
    cycle_entry = 0.0
    executed = 0
    fees = 0.0
    cycles = 0
    curve = []
    peak = capital
    max_drawdown = 0.0
    lots = {}

    prices = frame["close"].tolist()

    if strategy == "Grid":
        count = int(settings["grids"])

        levels = [
            settings["lower"]
            + (
                settings["upper"] - settings["lower"]
            ) * index / count
            for index in range(count + 1)
        ]

        allocation = capital / count / (1 + fee)

    for index, price in enumerate(prices):
        if strategy == "DCA":
            direction_sign = side(direction)

            if quantity == 0:
                amount = settings["base_amount"]

                if amount * (1 + fee) > wallet:
                    raise ValueError(
                        "Недостаточно модельного капитала."
                    )

                cycle_entry = price
                average = price
                quantity = amount / price
                executed = 0
                wallet -= amount * fee
                fees += amount * fee

            elif (
                direction_sign
                * (price / average - 1)
                * 100
                >= settings["tp"]
            ):
                close_fee = quantity * price * fee

                wallet += (
                    direction_sign
                    * quantity
                    * (price - average)
                    - close_fee
                )

                fees += close_fee
                quantity = 0.0
                cycles += 1

            elif (
                executed < settings["so_count"]
                and direction_sign
                * (price / cycle_entry - 1)
                * 100
                <= -settings["step"] * (executed + 1)
            ):
                amount = (
                    settings["first_so"]
                    * settings["mart"] ** executed
                )

                equity_before = (
                    wallet
                    + direction_sign
                    * quantity
                    * (price - average)
                )

                if (
                    quantity * average + amount <= capital
                    and equity_before > amount * fee
                ):
                    added_quantity = amount / price

                    average = (
                        quantity * average + amount
                    ) / (
                        quantity + added_quantity
                    )

                    quantity += added_quantity
                    wallet -= amount * fee
                    fees += amount * fee
                    executed += 1

            equity = (
                wallet
                + direction_sign
                * quantity
                * (price - average)
            )

        else:
            for level_index in list(lots):
                if price >= levels[level_index + 1]:
                    units = lots.pop(level_index)
                    gross = units * price
                    wallet += gross * (1 - fee)
                    fees += gross * fee
                    cycles += 1

            if index > 0:
                previous_price = prices[index - 1]

                for level_index, level in enumerate(levels[:-1]):
                    cost = allocation * (1 + fee)

                    if (
                        level_index not in lots
                        and previous_price > level >= price
                        and wallet >= cost
                    ):
                        lots[level_index] = allocation / price
                        wallet -= cost
                        fees += allocation * fee

            equity = wallet + sum(lots.values()) * price

        if equity <= 0:
            raise ValueError(
                "Модельный капитал исчерпан."
            )

        peak = max(peak, equity)

        max_drawdown = max(
            max_drawdown,
            (peak - equity) / peak * 100,
        )

        curve.append(equity)

    return {
        "Итоговая equity": curve[-1],
        "Результат USDT": curve[-1] - capital,
        "Доходность %": (curve[-1] / capital - 1) * 100,
        "Просадка %": max_drawdown,
        "Комиссии USDT": fees,
        "Закрытых циклов / лотов": cycles,
    }, curve


def alternatives_panel(
    strategy,
    direction,
    coin,
    market,
    settings,
    valid,
):
    prefix = strategy.lower()

    variants = [
        ("Исходный план", dict(settings)),
        ("Альтернатива A", dict(settings)),
        ("Альтернатива B", dict(settings)),
    ]

    if strategy == "DCA":
        variants[1][1]["mart"] = 1.0
        variants[2][1]["step"] *= 1.5
    else:
        middle = (
            settings["lower"] + settings["upper"]
        ) / 2

        half_width = (
            settings["upper"] - settings["lower"]
        ) / 2

        variants[1][1]["lower"] = max(
            0.00000001,
            middle - half_width * 1.5,
        )

        variants[1][1]["upper"] = (
            middle + half_width * 1.5
        )

        variants[2][1]["grids"] = max(
            2,
            settings["grids"] // 2,
        )

    st.subheader("Альтернативы")

    show_table(
        pd.DataFrame([
            {
                "Вариант": label,
                "Параметры": json.dumps(
                    variant,
                    ensure_ascii=False,
                ),
            }
            for label, variant in variants
        ])
    )

    st.subheader("Исторический тест")

    days = st.selectbox(
        "Запрошенная история, дней",
        [7, 30, 90],
        key=prefix + "_test_days",
    )

    bar = st.selectbox(
        "Таймфрейм",
        ["15m", "1H", "4H"],
        index=1,
        key=prefix + "_test_bar",
    )

    fee = numeric(
        "Комиссия за одну сторону, %",
        0.05,
        prefix + "_test_fee",
        0,
        5,
    ) / 100

    if st.button(
        "Сравнить варианты на истории",
        disabled=not valid,
        key=prefix + "_run_test",
        use_container_width=True,
    ):
        allowed = (
            settings["leverage"] == 1
            and (
                strategy == "DCA"
                or (
                    market == "SPOT"
                    and direction == "Long"
                )
            )
        )

        if not allowed:
            st.warning(
                "Тест доступен при плече 1x. "
                "Для Grid — только Spot Long. "
                "Futures Grid здесь не симулируется."
            )
        else:
            try:
                with st.spinner("Загружаю и считаю историю..."):
                    frame = historical_candles(
                        coin,
                        market,
                        days,
                        bar,
                    )

                    rows = []
                    curves = {}

                    for label, variant in variants:
                        if strategy == "DCA":
                            dca_plan(variant, direction)

                        metrics, curve = simulate(
                            frame,
                            variant,
                            strategy,
                            direction,
                            fee,
                        )

                        rows.append({
                            "Вариант": label,
                            **metrics,
                        })

                        curves[label] = curve

                    st.session_state[
                        prefix + "_backtest"
                    ] = {
                        "rows": rows,
                        "curves": curves,
                        "description": (
                            f"{coin} · {market} · {bar} · "
                            f"{frame['time'].iloc[0]} — "
                            f"{frame['time'].iloc[-1]} · "
                            f"{len(frame)} закрытых свечей"
                        ),
                    }

            except Exception as error:
                st.session_state.pop(
                    prefix + "_backtest",
                    None,
                )

                LOGGER.exception("Backtest failed")
                st.error(str(error))

    result = st.session_state.get(
        prefix + "_backtest"
    )

    if result:
        st.caption(
            "Последний расчёт: "
            + result["description"]
            + ". После изменения полей пересчитай."
        )

        show_table(
            pd.DataFrame(result["rows"]),
            {
                "Итоговая equity": "{:,.2f}",
                "Результат USDT": "{:,.2f}",
                "Доходность %": "{:.2f}",
                "Просадка %": "{:.2f}",
                "Комиссии USDT": "{:,.2f}",
            },
        )

        st.line_chart(
            pd.DataFrame(result["curves"])
        )

    st.caption(
        "Ограничения: исполнения по закрытиям свечей; "
        "без funding, проскальзывания, очереди ордеров, "
        "ликвидации и точных правил OKX. "
        "DCA — линейная модель 1x, не точный Spot-кошелёк. "
        "Открытая позиция включена в equity. "
        "Стопы, лимит убытка и резерв маржи "
        "в этом тесте не исполняются."
    )


# =========================================================
# BOT ASSESSMENT
# =========================================================

def assess(bot, price):
    settings = bot["settings"]
    position = bot.get("position", {})
    direction = bot["direction"]

    used_margin = (
        number(position.get("base_margin"))
        + number(position.get("added_margin"))
    )

    state = {
        "action": "Проверить на OKX",
        "risk": "Не оценён",
        "reason": "",
        "pnl": None,
        "remaining": max(
            0,
            number(settings.get("total_budget")) - used_margin,
        ),
        "tp": None,
        "next_so": None,
        "liq_distance": None,
    }

    if bot.get("lifecycle") != "Работает":
        state["reason"] = (
            "Активная позиция не подтверждена. "
            "Сверь данные и отметь фактический запуск."
        )
        return state

    if price is None:
        state["reason"] = (
            "Нет свежей рыночной цены. "
            "Расчёты по нулевой цене отключены."
        )
        return state

    fresh = age_hours(
        position.get("last_check")
    ) <= number(
        settings.get("stale_hours"),
        6,
    )

    average = number(position.get("avg_price"))
    quantity = number(position.get("volume"))
    liquidation = number(position.get("liq_price"))

    reasons = []
    high_risk = False
    exit_triggered = False

    if liquidation > 0 and direction in ("Long", "Short"):
        distance = (
            side(direction)
            * (price - liquidation)
            / price
            * 100
        )

        state["liq_distance"] = distance

        if distance <= number(
            settings.get("liq_warn"),
            10,
        ):
            high_risk = True

            reasons.append(
                "Цена близка к введённой ликвидации "
                "или пересекла её. Срочно сверить позицию. "
                "Это не расчёт биржевого MMR."
            )

    if not fresh:
        reasons.append(
            "Сверка устарела или отсутствует. "
            "Рекомендация продолжать недостоверна."
        )

    elif direction == "Neutral":
        reasons.append(
            "Для Neutral общий PnL Grid "
            "не моделируется. Проверь Total PnL на OKX."
        )

    elif average <= 0 or quantity <= 0:
        reasons.append(
            "Нужны фактические объём и средняя цена."
        )

    else:
        state["pnl"] = (
            side(direction)
            * quantity
            * (price - average)
        )

    loss_limit = number(settings.get("max_loss"))

    if (
        state["pnl"] is not None
        and loss_limit > 0
        and state["pnl"] <= -loss_limit
    ):
        exit_triggered = True
        high_risk = True

        reasons.append(
            "Достигнут лимит убытка открытой позиции. "
            "Funding, комиссии и прошлые циклы не учтены."
        )

    stop = number(settings.get("stop_price"))

    if (
        stop > 0
        and direction in ("Long", "Short")
        and side(direction) * (price - stop) <= 0
    ):
        exit_triggered = True
        high_risk = True

        reasons.append(
            "Достигнута сигнальная стоп-цена. "
            "Приложение не выставляло ордер на бирже."
        )

    if bot["strategy"] == "DCA":
        plan = dca_plan(settings, direction)

        executed = max(
            0,
            min(
                int(position.get("executed_so", 0)),
                len(plan) - 1,
            ),
        )

        if executed + 1 < len(plan):
            state["next_so"] = plan[executed + 1]["Цена"]

            if (
                side(direction)
                * (price - state["next_so"])
                <= 0
            ):
                reasons.append(
                    f"Достигнут уровень СО {executed + 1}. "
                    "Проверь исполнение и обнови сверку."
                )

        if fresh and average > 0:
            state["tp"] = average * (
                1
                + side(direction)
                * number(settings.get("tp"), 1.5)
                / 100
            )

            if side(direction) * (price - state["tp"]) >= 0:
                reasons.append(
                    "Достигнут модельный TP цикла. "
                    "Это движение цены от средней, "
                    "не ROI на маржу. Проверь исполнение."
                )

    else:
        lower = number(settings.get("lower"))
        upper = number(settings.get("upper"))

        if lower <= 0 or upper <= lower:
            reasons.append(
                "Проверь сохранённый диапазон."
            )

        elif price < lower or price > upper:
            reasons.append(
                "Цена вне диапазона Grid. "
                "Позиция от этого не считается закрытой."
            )

        elif (
            min(price - lower, upper - price)
            / (upper - lower)
            <= 0.1
        ):
            reasons.append(
                "Цена в крайних 10% диапазона Grid."
            )

        target = number(settings.get("target_price"))

        if (
            target > 0
            and direction in ("Long", "Short")
            and side(direction) * (price - target) >= 0
        ):
            reasons.append(
                "Достигнута целевая цена Grid. "
                "Проверь правило завершения."
            )

    if state["remaining"] <= 0:
        reasons.append(
            "Лимит маржи исчерпан. "
            "Дальнейшие добавления вне плана."
        )

    if exit_triggered:
        state["action"] = "Выход по плану"
    elif not reasons:
        state["action"] = "Не трогать по плану"

    if high_risk:
        state["risk"] = "Высокий"
    elif reasons:
        state["risk"] = "Требует проверки"
    else:
        state["risk"] = (
            "Без срабатывания проверяемых правил"
        )

    state["reason"] = (
        "\n\n".join(reasons)
        if reasons
        else (
            "Проверяемые условия не сработали. "
            "Это не гарантия безопасности."
        )
    )

    return state


def safe_assessment(bot):
    try:
        price = get_quote(
            bot["coin"],
            bot["market"],
        )["price"]
    except Exception:
        price = None

    try:
        state = assess(bot, price)
    except Exception:
        LOGGER.exception("Bot assessment failed")

        state = {
            "action": "Проверить настройки",
            "risk": "Не оценён",
            "reason": "Проверь параметры сохранённой карточки.",
            "pnl": None,
            "remaining": None,
            "tp": None,
            "next_so": None,
            "liq_distance": None,
        }

    return price, state


# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(text):
    token = str(secret("TELEGRAM_TOKEN"))
    chat_id = str(secret("TELEGRAM_CHAT_ID"))

    try:
        token = token or str(
            st.secrets["telegram"]["token"]
        )
        chat_id = chat_id or str(
            st.secrets["telegram"]["chat_id"]
        )
    except Exception:
        pass

    if not token or not chat_id:
        raise ValueError(
            "Настрой Telegram Token и Chat ID в Secrets."
        )

    payload = json.dumps({
        "chat_id": chat_id,
        "text": text[:4000],
    }).encode("utf-8")

    request = Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    with urlopen(request, timeout=15) as response:
        result = json.load(response)

    if not result.get("ok"):
        raise ValueError(
            "Telegram не подтвердил отправку."
        )


def make_report(bot, price, state):
    return (
        f"{bot['name']}\n"
        f"{bot['coin']} · {bot['strategy']} · "
        f"{bot['direction']}\n\n"
        f"Действие: {state['action']}\n"
        f"Риск: {state['risk']}\n"
        f"Цена: {formatted(price, 6)}\n"
        f"Открытый PnL, оценка: "
        f"{formatted(state['pnl'])} USDT\n"
        f"Остаток бюджета маржи: "
        f"{formatted(state['remaining'])} USDT\n\n"
        f"{state['reason']}\n\n"
        f"Последняя сверка UTC: "
        f"{bot.get('position', {}).get('last_check') or 'нет'}\n\n"
        "Торговые команды не отправлялись. "
        "Действия подтверждаются на OKX."
    )


# =========================================================
# POSITION AND BOT CARDS
# =========================================================

def position_form(bot):
    identifier = bot["id"]
    settings = bot["settings"]
    position = bot.get("position", {})

    states = ["Черновик", "Работает", "Закрыт"]
    current = bot.get("lifecycle", "Черновик")

    with st.form("position_" + identifier):
        lifecycle = st.selectbox(
            "Фактическое состояние на OKX",
            states,
            index=states.index(
                current if current in states else "Черновик"
            ),
        )

        quantity = numeric(
            "Объём в базовой монете, НЕ контракты",
            number(position.get("volume")),
            identifier + "_quantity",
        )

        average = numeric(
            "Фактическая средняя цена",
            number(position.get("avg_price")),
            identifier + "_average",
        )

        liquidation = numeric(
            "Ликвидационная цена с OKX; 0 = неизвестна",
            number(position.get("liq_price")),
            identifier + "_liq",
        )

        margin = numeric(
            "Базовая выделенная маржа",
            number(
                position.get("base_margin"),
                number(settings.get("base_margin")),
            ),
            identifier + "_margin",
        )

        added = numeric(
            "Всего добавлено маржи",
            number(position.get("added_margin")),
            identifier + "_added",
        )

        if bot["strategy"] == "DCA":
            maximum = int(
                settings.get("so_count", 0)
            )

            executed = st.number_input(
                "Исполнено СО текущего цикла",
                min_value=0,
                max_value=maximum,
                value=max(
                    0,
                    min(
                        int(position.get("executed_so", 0)),
                        maximum,
                    ),
                ),
                key=identifier + "_executed",
            )
        else:
            executed = 0

        note = st.text_input("Комментарий")

        confirmed = st.checkbox(
            "Проверил значения на OKX. "
            "Это ручной снимок позиции."
        )

        if st.form_submit_button("Сохранить сверку"):
            if not confirmed:
                st.error("Подтверди сверку.")

            elif (
                lifecycle == "Работает"
                and bot["direction"] != "Neutral"
                and (quantity <= 0 or average <= 0)
            ):
                st.error(
                    "Нужны фактические объём и средняя цена."
                )

            else:
                bot["position"] = {
                    "volume": quantity,
                    "avg_price": average,
                    "liq_price": liquidation,
                    "base_margin": margin,
                    "added_margin": added,
                    "executed_so": int(executed),
                    "last_check": now(),
                }

                bot["lifecycle"] = lifecycle

                save_bot(
                    bot,
                    "Ручная сверка",
                    note or "Позиция проверена пользователем.",
                )

                st.rerun()


def bot_card(bot, compact=False):
    price, state = safe_assessment(bot)

    with st.container(border=True):
        st.subheader(
            f"{bot['coin']} · "
            f"{bot['strategy']} {bot['direction']}"
        )

        st.caption(
            f"{bot['name']} · "
            f"{bot.get('lifecycle', 'Черновик')} · "
            f"{bot['market']}"
        )

        columns = st.columns(3)

        with columns[0]:
            metric_card(
                "Цена",
                formatted(price, 6),
            )

        with columns[1]:
            tone = ""

            if state["pnl"] is not None:
                tone = (
                    "positive"
                    if state["pnl"] >= 0
                    else "negative"
                )

            metric_card(
                "Открытый PnL ≈ USDT",
                formatted(state["pnl"]),
                tone,
            )

        with columns[2]:
            metric_card(
                "Остаток бюджета маржи",
                formatted(state["remaining"]),
            )

        st.write(
            "Действие: " + state["action"]
        )

        st.caption(
            "Риск: " + state["risk"]
        )

        if state["risk"] == "Высокий":
            st.error(state["reason"])
        else:
            st.info(state["reason"])

        st.caption(
            "Сверка UTC: "
            + (
                bot.get("position", {}).get("last_check")
                or "нет"
            )
        )

        if compact:
            if st.button(
                "Открыть контроль",
                key="open_control_" + bot["id"],
            ):
                navigate("3. ИИ-Центр")
            return

        if state["tp"] is not None:
            st.write(
                "Модельный TP цикла: "
                + formatted(state["tp"], 6)
            )

        if state["next_so"] is not None:
            st.write(
                "Следующий СО: "
                + formatted(state["next_so"], 6)
            )

        if state["liq_distance"] is not None:
            st.write(
                "До введённой ликвидации, %: "
                + formatted(state["liq_distance"])
            )

        st.caption(
            "PnL открытой позиции не равен "
            "общему результату бота. "
            "Объём вводится в базовой монете."
        )

        with st.expander(
            "Сверить позицию / подтвердить запуск"
        ):
            position_form(bot)

        with st.expander("Сохранённый план"):
            settings_frame = pd.DataFrame([
                {
                    "Параметр": key,
                    "Значение": str(value),
                }
                for key, value in bot["settings"].items()
            ])

            show_table(settings_frame)

        with st.form("decision_" + bot["id"]):
            decision = st.radio(
                "Моё решение — не торговая команда",
                [
                    "Не трогать",
                    "Проверить на OKX",
                    "Выход по плану",
                ],
                horizontal=True,
            )

            reason = st.text_input(
                "Причина решения"
            )

            if st.form_submit_button("Записать решение"):
                bot["decision"] = (
                    decision + " · " + now() + " · " + reason
                )

                save_bot(
                    bot,
                    "Решение пользователя",
                    bot["decision"],
                )

                st.rerun()

        if bot.get("decision"):
            st.caption(
                "Последнее решение: "
                + bot["decision"]
            )

        st.caption(
            "«Не трогать» не отключает предупреждения "
            "и не отменяет лимиты."
        )

        if st.button(
            "Отправить статус в Telegram",
            key="telegram_" + bot["id"],
            use_container_width=True,
        ):
            try:
                send_telegram(
                    make_report(bot, price, state)
                )
                st.success(
                    "Telegram подтвердил отправку."
                )
            except Exception:
                LOGGER.exception("Telegram send failed")
                st.error(
                    "Отправка не подтверждена. "
                    "Проверь Telegram в Secrets."
                )


# =========================================================
# PLAN CREATOR
# =========================================================

def creator(strategy):
    prefix = strategy.lower()

    preferred = st.session_state.get(
        "preferred_direction",
        "Long",
    )

    directions = (
        ["Long", "Short"]
        if strategy == "DCA"
        else ["Long", "Short", "Neutral"]
    )

    mode = st.radio(
        "Что добавляем",
        [
            "План нового бота",
            "Уже работает на OKX",
        ],
        horizontal=True,
        key=prefix + "_mode",
    )

    name = st.text_input(
        "Название",
        value=f"Мой {strategy}",
        key=prefix + "_name",
    )

    coin = st.text_input(
        "Монета",
        value="BTC",
        key=prefix + "_coin",
    ).strip().upper()

    market = st.radio(
        "Рынок",
        ["SWAP", "SPOT"],
        horizontal=True,
        key=prefix + "_market",
    )

    direction = st.radio(
        "Направление",
        directions,
        index=(
            directions.index(preferred)
            if preferred in directions
            else 0
        ),
        horizontal=True,
        key=prefix + "_direction_" + preferred,
    )

    if market == "SPOT" and direction != "Long":
        st.warning(
            "Для Spot здесь поддерживается Long."
        )
        return

    leverage = numeric(
        "Плечо",
        1,
        prefix + "_leverage",
        1,
        100,
    )

    if market == "SPOT" and leverage != 1:
        st.warning("Для Spot установи 1x.")
        return

    columns = st.columns(2)

    with columns[0]:
        margin = numeric(
            "Базовая маржа / капитал Spot, USDT",
            100,
            prefix + "_margin",
            0.01,
        )

    with columns[1]:
        reserve = numeric(
            "Отдельный резерв маржи, USDT",
            50,
            prefix + "_reserve",
        )

    settings = {
        "leverage": leverage,
        "base_margin": margin,
        "reserve": reserve,
        "total_budget": margin + reserve,
        "stale_hours": 6.0,
        "liq_warn": 10.0,
    }

    st.caption(
        f"Лимит выделяемых средств: "
        f"{margin + reserve:.2f} USDT. "
        "Номинал ордеров и маржа — разные величины."
    )

    valid = bool(name.strip()) and coin.isalnum()

    if strategy == "DCA":
        columns = st.columns(2)

        with columns[0]:
            settings["entry"] = numeric(
                "Цена первого входа",
                100,
                prefix + "_entry",
                0.00000001,
            )

            settings["tp"] = numeric(
                "TP по движению цены от средней, %",
                1.5,
                prefix + "_tp",
                0.01,
                99,
            )

            settings["step"] = numeric(
                "Шаг СО от первого входа, %",
                2,
                prefix + "_step",
                0.01,
                50,
            )

            settings["so_count"] = st.number_input(
                "Количество СО",
                min_value=0,
                max_value=30,
                value=4,
                key=prefix + "_count",
            )

        with columns[1]:
            settings["base_amount"] = numeric(
                "Номинал первого ордера, USDT",
                10,
                prefix + "_amount",
                0.01,
            )

            settings["first_so"] = numeric(
                "Номинал первого СО, USDT",
                10,
                prefix + "_first_so",
                0.01,
            )

            settings["mart"] = numeric(
                "Множитель объёма следующих СО",
                1.2,
                prefix + "_mart",
                1,
                3,
            )

        try:
            plan = dca_plan(
                settings,
                direction,
            )

            show_table(
                pd.DataFrame(plan),
                {
                    "Цена": "{:,.6f}",
                    "Номинал USDT": "{:,.2f}",
                    "Всего номинал": "{:,.2f}",
                    "Модельная средняя": "{:,.6f}",
                },
            )

            required_margin = (
                plan[-1]["Всего номинал"] / leverage
            )

            st.caption(
                f"Модельная маржа под все ордера: "
                f"{required_margin:.2f} USDT "
                "без комиссий и биржевого резерва."
            )

            if required_margin >= margin:
                valid = False
                st.error(
                    "Базовой маржи недостаточно "
                    "для всех ордеров с запасом."
                )

        except Exception as error:
            valid = False
            st.error(str(error))

    else:
        columns = st.columns(2)

        with columns[0]:
            settings["lower"] = numeric(
                "Нижняя граница — точная цена",
                90,
                prefix + "_lower",
                0.00000001,
            )

        with columns[1]:
            settings["upper"] = numeric(
                "Верхняя граница — точная цена",
                110,
                prefix + "_upper",
                0.00000001,
            )

        settings["grids"] = st.number_input(
            "Количество интервалов; уровней N + 1",
            min_value=2,
            max_value=200,
            value=10,
            key=prefix + "_grids",
        )

        settings["target_price"] = numeric(
            "Целевая цена завершения; 0 = не задана",
            0,
            prefix + "_target",
        )

        if settings["upper"] <= settings["lower"]:
            valid = False
            st.error(
                "Верхняя граница должна быть выше нижней."
            )

        if valid:
            levels = [
                settings["lower"]
                + (
                    settings["upper"] - settings["lower"]
                ) * index / settings["grids"]
                for index in range(settings["grids"] + 1)
            ]

            st.line_chart(
                pd.DataFrame({"Уровни Grid": levels})
            )

    with st.expander(
        "Правила риска и выхода",
        expanded=True,
    ):
        settings["max_loss"] = numeric(
            "Лимит убытка открытой позиции, USDT; "
            "0 = сигнал отключён",
            0,
            prefix + "_loss",
        )

        settings["stop_price"] = numeric(
            "Сигнальная стоп-цена; 0 = нет",
            0,
            prefix + "_stop",
        )

        settings["stale_hours"] = numeric(
            "Сверка устаревает через часов",
            6,
            prefix + "_stale",
            0.1,
            168,
        )

        settings["liq_warn"] = numeric(
            "Предупреждение у введённой ликвидации, %",
            10,
            prefix + "_liqwarn",
            0.1,
            100,
        )

        st.caption(
            "Это сигнальные правила, не биржевые ордера. "
            "Без стопа и лимита убытка "
            "выход по убытку заранее не ограничен. "
            "Добавление маржи не устраняет убыток."
        )

    if st.button(
        "Сохранить карточку",
        type="primary",
        disabled=not valid,
        use_container_width=True,
        key=prefix + "_save",
    ):
        try:
            get_quote(coin, market)

            bot = {
                "id": str(uuid.uuid4()),
                "name": name.strip(),
                "coin": coin,
                "market": market,
                "strategy": strategy,
                "direction": direction,
                "settings": settings,
                "position": {},
                "lifecycle": "Черновик",
                "decision": "",
                "created_at": now(),
            }

            save_bot(
                bot,
                "Создана карточка",
                (
                    "Требуется сверка работающего бота."
                    if mode == "Уже работает на OKX"
                    else "План до запуска на OKX."
                ),
            )

            navigate("3. ИИ-Центр")

        except Exception as error:
            LOGGER.exception("Saving bot failed")
            st.error(
                "Не сохранено: " + str(error)
            )

    st.divider()

    alternatives_panel(
        strategy,
        direction,
        coin,
        market,
        settings,
        valid,
    )


def strategy_page(strategy, bots):
    panel(
        strategy,
        (
            "Планы усреднения, TP и контроль цикла."
            if strategy == "DCA"
            else "Диапазон, направление, маржа и резерв."
        ),
    )

    action = st.radio(
        "Режим",
        [
            "Мои боты",
            "Добавить / подготовить",
        ],
        horizontal=True,
        key=strategy + "_page_mode",
    )

    if action == "Добавить / подготовить":
        creator(strategy)
        return

    selected = [
        bot for bot in bots
        if bot["strategy"] == strategy
    ]

    if not selected:
        st.info(
            "Пока нет карточек. "
            "Выбери «Добавить / подготовить»."
        )

    for bot in selected:
        bot_card(bot)


# =========================================================
# BACKUP / IMPORT
# =========================================================

def normalize_import(raw):
    if not isinstance(raw, dict):
        raise ValueError("Неверная карточка.")

    document = dict(raw)

    for field in ("settings", "position"):
        value = document.get(field, {})

        if isinstance(value, str):
            value = json.loads(value)

        if not isinstance(value, dict):
            raise ValueError(
                "Неверные настройки или позиция."
            )

        document[field] = value

    if document.get("strategy") not in ("DCA", "Grid"):
        raise ValueError("Неизвестная стратегия.")

    direction = document.get("direction")

    if direction not in ("Long", "Short", "Neutral"):
        raise ValueError("Неизвестное направление.")

    if document["strategy"] == "DCA" and direction == "Neutral":
        raise ValueError("DCA Neutral не поддерживается.")

    coin = str(document.get("coin", "")).strip().upper()

    if not coin or not coin.isalnum():
        raise ValueError("Неверная монета.")

    document.pop("_revision", None)

    document["id"] = str(uuid.uuid4())
    document["coin"] = coin
    document["name"] = str(
        document.get("name", coin)
    ).strip()

    previous_market = str(
        document.get("market", "SWAP")
    )

    document["market"] = (
        "SWAP"
        if "SWAP" in previous_market
        or "Фьючерсы" in previous_market
        else "SPOT"
    )

    document["lifecycle"] = "Черновик"
    document["position"]["last_check"] = ""
    document["updated_at"] = now()
    document.setdefault("created_at", now())
    document.setdefault("decision", "")

    settings = document["settings"]

    settings.setdefault("leverage", 1.0)
    settings.setdefault("stale_hours", 6.0)
    settings.setdefault("liq_warn", 10.0)
    settings.setdefault("stop_price", 0.0)
    settings.setdefault("max_loss", 0.0)

    settings.setdefault(
        "first_so",
        settings.get("base_amount", 10.0),
    )

    settings.setdefault(
        "base_margin",
        document["position"].get("base_margin", 0.0),
    )

    settings.setdefault(
        "total_budget",
        number(settings.get("base_margin"))
        + number(settings.get("reserve")),
    )

    return document


def import_documents(documents, previous_events=None):
    if (
        not isinstance(documents, list)
        or len(documents) > 1000
    ):
        raise ValueError("Неверный список bots.")

    prepared = [
        normalize_import(document)
        for document in documents
    ]

    with database() as connection:
        for document in prepared:
            if previous_events:
                document["imported_journal"] = previous_events

            execute(
                connection,
                """
                INSERT INTO terminal_bots
                (id, document, revision)
                VALUES (?, ?, ?)
                """,
                (
                    document["id"],
                    json.dumps(
                        document,
                        ensure_ascii=False,
                        allow_nan=False,
                    ),
                    1,
                ),
            )

            add_event(
                connection,
                document["id"],
                "Импорт",
                "Добавлена копия. Требуется сверка.",
            )

    return len(prepared)


# =========================================================
# SETTINGS
# =========================================================

def settings_page(bots):
    panel(
        "Настройки",
        "Вход, Telegram, хранилище и резервные копии.",
    )

    password_ready = bool(
        secret("APP_PASSWORD")
    )

    st.write(
        "Пароль: "
        + (
            "настроен"
            if password_ready
            else "не настроен"
        )
    )

    st.write(
        "Хранилище: "
        + (
            "внешний PostgreSQL"
            if DB_URL
            else "локальный SQLite"
        )
    )

    if not password_ready:
        st.warning(
            "Настрой APP_PASSWORD в Secrets "
            "или ограничь доступ к приложению. "
            "Личные позиции не должны быть публичными."
        )

    if not DB_URL:
        st.warning(
            "Локальный файл может потеряться "
            "при пересоздании облачного сервера. "
            "Для постоянного внешнего хранения "
            "настрой DATABASE_URL."
        )

    if st.button("Тест Telegram"):
        try:
            send_telegram(
                "OKX Terminal Pro: соединение подтверждено. "
                "Автоматические сделки не включены."
            )
            st.success("Сообщение отправлено.")
        except Exception:
            LOGGER.exception("Telegram test failed")
            st.error(
                "Проверь Telegram Secrets и соединение."
            )

    clean_bots = []

    for bot in bots:
        document = dict(bot)
        document.pop("_revision", None)
        clean_bots.append(document)

    backup = {
        "version": 7,
        "created_at": now(),
        "bots": clean_bots,
        "events": load_events().to_dict("records"),
    }

    st.download_button(
        "Скачать планы и журнал JSON",
        json.dumps(
            backup,
            ensure_ascii=False,
            indent=2,
        ),
        "okx_backup.json",
        "application/json",
        use_container_width=True,
    )

    uploaded = st.file_uploader(
        "Восстановить JSON",
        type=["json"],
    )

    confirmed = st.checkbox(
        "Добавить копии с новыми ID, "
        "не заменяя существующие карточки."
    )

    if st.button(
        "Импортировать",
        disabled=uploaded is None or not confirmed,
    ):
        try:
            if uploaded.size > 5_000_000:
                raise ValueError("Файл больше 5 MB.")

            source = json.loads(
                uploaded.getvalue()
            )

            if not isinstance(source, dict):
                raise ValueError("Неверная копия.")

            count = import_documents(
                source.get("bots"),
                source.get("events"),
            )

            st.success(
                f"Добавлено: {count}. "
                "Перед контролем проведи сверку."
            )

        except Exception as error:
            LOGGER.exception("Import failed")
            st.error(str(error))

    with st.expander(
        "Импорт из старой таблицы SQLite"
    ):
        st.caption(
            "Старые записи не удаляются. "
            "Повторный импорт создаёт копии."
        )

        if st.button("Перенести старую таблицу bots"):
            old_connection = None

            try:
                if not os.path.isfile(DB_FILE):
                    raise ValueError(
                        "Старый локальный файл не найден."
                    )

                old_connection = sqlite3.connect(DB_FILE)
                old_connection.row_factory = sqlite3.Row

                exists = old_connection.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name='bots'
                    """
                ).fetchone()

                if not exists:
                    raise ValueError(
                        "Старая таблица bots не найдена."
                    )

                rows = [
                    dict(row)
                    for row in old_connection.execute(
                        "SELECT * FROM bots"
                    )
                ]

                old_connection.close()
                old_connection = None

                count = import_documents(rows)

                st.success(
                    f"Добавлено: {count}. "
                    "Проверь единицы и суммы."
                )

            except Exception as error:
                LOGGER.exception("Legacy import failed")
                st.error(str(error))

            finally:
                if old_connection is not None:
                    old_connection.close()

    st.subheader("Пример Streamlit Secrets")

    st.code(
        '''
APP_PASSWORD = "ваш-длинный-пароль"

# Для внешнего постоянного хранилища:
DATABASE_URL = "postgresql://user:password@host/database?sslmode=require"

# Если нужен Telegram:
TELEGRAM_TOKEN = "токен"
TELEGRAM_CHAT_ID = "chat-id"
'''.strip(),
        language="toml",
    )

    st.caption(
        "Не публикуй Secrets в GitHub. "
        "При смене локальной базы на внешнюю "
        "перенеси карточки через экспорт/импорт."
    )


# =========================================================
# HOME / CONTROL
# =========================================================

def home_page(bots):
    panel(
        "OKX Terminal Pro",
        "Сканер, подготовка DCA и Grid, "
        "контроль позиции и решения по твоему плану.",
    )

    active = [
        bot for bot in bots
        if bot.get("lifecycle") == "Работает"
    ]

    columns = st.columns(4)

    with columns[0]:
        metric_card(
            "Работают по сверке",
            len(active),
            "positive",
        )

    with columns[1]:
        metric_card(
            "DCA",
            sum(
                bot["strategy"] == "DCA"
                for bot in bots
            ),
        )

    with columns[2]:
        metric_card(
            "Grid",
            sum(
                bot["strategy"] == "Grid"
                for bot in bots
            ),
        )

    with columns[3]:
        metric_card(
            "Режим",
            "Ручной контроль",
            "warning",
        )

    columns = st.columns(3)

    if columns[0].button(
        "ЛОНГ · DCA",
        key="home_long",
        use_container_width=True,
    ):
        navigate(
            "4. DCA",
            "Long",
            create=True,
        )

    if columns[1].button(
        "ШОРТ · DCA",
        key="home_short",
        use_container_width=True,
    ):
        navigate(
            "4. DCA",
            "Short",
            create=True,
        )

    if columns[2].button(
        "GRID",
        key="home_grid",
        use_container_width=True,
    ):
        navigate(
            "5. Grid",
            "Neutral",
            create=True,
        )

    columns = st.columns(2)

    if columns[0].button(
        "Открыть сканер",
        use_container_width=True,
    ):
        navigate("2. Сканер")

    if columns[1].button(
        "Контроль ботов",
        use_container_width=True,
    ):
        navigate("3. ИИ-Центр")

    st.subheader("Работающие боты")

    if not active:
        st.info(
            "Пока нет подтверждённых работающих ботов. "
            "Создай карточку DCA или Grid, "
            "затем сверь фактическую позицию."
        )

    for bot in active[:10]:
        bot_card(bot, compact=True)

    with st.expander("Статус системы"):
        st.write(
            "Хранилище: "
            + (
                "внешний PostgreSQL"
                if DB_URL
                else "локальный SQLite"
            )
        )

        st.write(
            "Пароль: "
            + (
                "настроен"
                if secret("APP_PASSWORD")
                else "не настроен"
            )
        )

        st.caption(
            "Цена обновляется при выполнении страницы "
            "и по кнопке. Фоновый сервис не запущен. "
            "Telegram отправляется по кнопке. "
            "Торговых команд нет."
        )

        if not DB_URL:
            st.warning(
                "Для сохранности при пересоздании сервера "
                "нужна внешняя база или резервные копии."
            )


def control_page(bots):
    panel(
        "ИИ-Центр",
        "Контроль по правилам твоего плана. "
        "Это не прогнозирующая нейросеть.",
    )

    filter_strategy = st.radio(
        "Стратегия",
        ["Все", "DCA", "Grid"],
        horizontal=True,
    )

    filter_state = st.radio(
        "Состояние",
        ["Все", "Работает", "Черновик", "Закрыт"],
        horizontal=True,
    )

    selected = [
        bot for bot in bots
        if (
            filter_strategy == "Все"
            or bot["strategy"] == filter_strategy
        )
        and (
            filter_state == "Все"
            or bot.get("lifecycle") == filter_state
        )
    ]

    if not selected:
        st.info(
            "Нет карточек для этих фильтров. "
            "Добавь бота в DCA или Grid."
        )

    for bot in selected:
        bot_card(bot)


# =========================================================
# MAIN
# =========================================================

def main():
    apply_design()
    login()
    initialize_database()

    pending = st.session_state.pop(
        "pending_page",
        None,
    )

    if pending in PAGES:
        st.session_state["navigation"] = pending

    if st.session_state.get("navigation") not in PAGES:
        st.session_state["navigation"] = PAGES[0]

    with st.sidebar:
        st.title("OKX Terminal")
        st.caption("Анализ, подготовка и контроль")

        page = st.radio(
            "Раздел",
            PAGES,
            key="navigation",
            label_visibility="collapsed",
        )

        if st.button(
            "Обновить рыночные цены",
            use_container_width=True,
        ):
            get_quote.clear()
            st.rerun()

        st.caption(
            "Без приватного торгового API. "
            "Действия выполняются вручную на OKX."
        )

    bots = load_bots()

    if page == "1. Главная":
        home_page(bots)

    elif page == "2. Сканер":
        scanner_page()

    elif page == "3. ИИ-Центр":
        control_page(bots)

    elif page == "4. DCA":
        strategy_page("DCA", bots)

    elif page == "5. Grid":
        strategy_page("Grid", bots)

    elif page == "6. Журнал решений":
        panel(
            "Журнал решений",
            "История карточек, сверок и решений. Время UTC.",
        )

        frame = load_events()

        show_table(frame)

        st.download_button(
            "Скачать журнал CSV",
            frame.to_csv(index=False).encode("utf-8-sig"),
            "journal.csv",
            "text/csv",
        )

        st.caption(
            "Повторные снимки PnL одной позиции "
            "не складываются как заработанная прибыль."
        )

    elif page == "7. Настройки":
        settings_page(bots)


try:
    main()

except Exception as error:
    LOGGER.exception("Application operation failed")

    st.error(
        "Операция не завершена: "
        + type(error).__name__
        + "."
    )

    st.info(
        "Проверь зависимости, введённые параметры "
        "и подключение к базе. "
        "Секреты подключения здесь не отображаются. "
        "При ошибке PostgreSQL приложение "
        "не переключается на пустую локальную базу."
    )
