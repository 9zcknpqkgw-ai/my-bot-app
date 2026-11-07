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
# CONFIGURATION
# =========================================================

st.set_page_config(
    page_title="OKX Terminal",
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

# TON удалён.
COINS = [
    "BTC", "ETH", "SOL", "BNB", "XRP",
    "DOGE", "ADA", "AVAX", "LINK", "DOT",
    "TRX", "LTC", "NEAR", "APT",
    "ARB", "OP", "SUI", "PEPE", "INJ",
]


def secret(name, default=""):
    try:
        return st.secrets.get(
            name,
            os.getenv(name, default),
        )
    except Exception:
        return os.getenv(name, default)


DATABASE_URL = str(secret("DATABASE_URL")).strip()
SQLITE_PATH = str(secret("SQLITE_PATH", "bots.sqlite3"))


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


def hours_since(value):
    try:
        date = datetime.fromisoformat(value)

        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)

        return max(
            0,
            (
                datetime.now(timezone.utc) - date
            ).total_seconds() / 3600,
        )
    except (ValueError, TypeError):
        return float("inf")


def numeric(
    label,
    value,
    key,
    minimum=0.0,
    maximum=None,
):
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
    st.session_state["pending_navigation"] = {
        "page": page,
        "direction": direction,
        "create": create,
    }
    st.rerun()


# =========================================================
# WHITE DESIGN
# =========================================================

def apply_design():
    st.markdown(
        """
<style>
:root {
    color-scheme: light;
    --background-color: #ffffff;
    --secondary-background-color: #f5f7fa;
    --text-color: #17212e;
    --primary-color: #198754;
}

.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stMain"] {
    background: #ffffff !important;
    color: #17212e !important;
}

.block-container {
    max-width: 1400px;
    padding-top: 1.5rem;
    padding-bottom: 3rem;
}

h1, h2, h3, h4 {
    color: #17212e !important;
    letter-spacing: -.025em;
}

[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,
[data-testid="stWidgetLabel"] p,
[data-testid="stCaptionContainer"] p {
    color: #334155 !important;
}

[data-testid="stSidebar"] {
    background: #f5f7fa !important;
    border-right: 1px solid #e0e6ed;
}

[data-testid="stSidebar"] p,
[data-testid="stSidebar"] label {
    color: #263445 !important;
}

[data-testid="stHeader"] {
    background: rgba(255,255,255,.96) !important;
}

input,
textarea {
    background: #ffffff !important;
    color: #17212e !important;
}

[data-baseweb="input"],
[data-baseweb="base-input"],
[data-baseweb="select"] > div {
    background: #ffffff !important;
    color: #17212e !important;
}

[data-testid="stMetric"] {
    background: #ffffff;
    border: 1px solid #e0e6ed;
    border-radius: 14px;
    padding: 16px;
}

[data-testid="stMetricLabel"],
[data-testid="stMetricLabel"] p {
    color: #64748b !important;
}

[data-testid="stMetricValue"],
[data-testid="stMetricValue"] div {
    color: #17212e !important;
}

.stButton button,
.stFormSubmitButton button,
.stDownloadButton button {
    background: #ffffff;
    color: #253347;
    border: 1px solid #cfd8e3;
    border-radius: 10px;
    min-height: 44px;
    font-weight: 650;
}

.stButton button:hover,
.stFormSubmitButton button:hover {
    background: #f7f9fc;
    border-color: #7f93aa;
    color: #17212e;
}

.st-key-home_long button {
    background: #ffffff !important;
    color: #16803c !important;
    border: 1px solid #cfd8e3 !important;
}

.st-key-home_short button {
    background: #ffffff !important;
    color: #cc3048 !important;
    border: 1px solid #cfd8e3 !important;
}

.st-key-home_grid button {
    background: #ffffff !important;
    color: #2563a6 !important;
    border: 1px solid #cfd8e3 !important;
}

[data-testid="stExpander"] {
    border-radius: 12px;
    background: #ffffff;
    border-color: #e0e6ed;
}

.terminal-header {
    background: #ffffff;
    border: 1px solid #e0e6ed;
    border-radius: 16px;
    padding: 20px 24px;
    margin-bottom: 20px;
}

.terminal-title {
    color: #17212e;
    font-size: clamp(1.6rem, 4vw, 2.2rem);
    font-weight: 800;
}

.terminal-subtitle {
    color: #64748b;
    line-height: 1.6;
    margin-top: 7px;
}

.white-table-wrapper {
    overflow-x: auto;
    max-height: 600px;
    overflow-y: auto;
    background: #ffffff;
    border: 1px solid #dde4ec;
    border-radius: 12px;
    margin: 12px 0 20px 0;
}

.white-table {
    border-collapse: collapse;
    width: 100%;
    background: #ffffff;
    color: #17212e;
    font-size: 14px;
}

.white-table th {
    background: #f5f7fa;
    color: #475569;
    text-align: left;
    font-weight: 650;
    padding: 12px 14px;
    border-bottom: 1px solid #dde4ec;
    white-space: nowrap;
}

.white-table td {
    background: #ffffff;
    color: #17212e;
    padding: 11px 14px;
    border-bottom: 1px solid #edf1f5;
    vertical-align: top;
}

.white-table tr:last-child td {
    border-bottom: none;
}

@media(max-width: 640px) {
    .block-container {
        padding: 1rem;
    }

    .terminal-header {
        padding: 17px;
    }
}
</style>
        """,
        unsafe_allow_html=True,
    )


def panel(title, subtitle):
    st.html(
        '<div class="terminal-header">'
        f'<div class="terminal-title">{html.escape(title)}</div>'
        f'<div class="terminal-subtitle">{html.escape(subtitle)}</div>'
        '</div>'
    )


def show_table(frame):
    if frame.empty:
        st.info("Нет данных для отображения.")
        return

    header = "".join(
        f"<th>{html.escape(str(column))}</th>"
        for column in frame.columns
    )

    body = []

    for _, row in frame.iterrows():
        cells = []

        for column, value in row.items():
            if value is None:
                text = "—"
            elif isinstance(value, float):
                if not math.isfinite(value):
                    text = "—"
                elif column in ("Цена", "Средняя", "TP", "СО"):
                    text = f"{value:,.6f}"
                else:
                    text = f"{value:,.2f}"
            else:
                text = str(value)

            color = "#17212e"

            if column == "Направление":
                if value == "Long":
                    color = "#16803c"
                elif value == "Short":
                    color = "#cc3048"
                else:
                    color = "#64748b"

            cells.append(
                f'<td style="color:{color};background:#ffffff;">'
                f'{html.escape(text)}'
                '</td>'
            )

        body.append("<tr>" + "".join(cells) + "</tr>")

    st.html(
        '<div class="white-table-wrapper">'
        '<table class="white-table">'
        '<thead><tr>'
        + header
        + '</tr></thead><tbody>'
        + "".join(body)
        + '</tbody></table></div>'
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

    panel("OKX Terminal", "Вход в личный терминал")

    entered = st.text_input("Пароль", type="password")

    if st.button("Войти"):
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
# STORAGE
# =========================================================

@contextmanager
def database():
    if DATABASE_URL:
        try:
            import psycopg2
        except ImportError as error:
            raise RuntimeError(
                "Для PostgreSQL нужен psycopg2-binary."
            ) from error

        connection = psycopg2.connect(
            DATABASE_URL,
            connect_timeout=10,
        )
    else:
        connection = sqlite3.connect(
            SQLITE_PATH,
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

    if DATABASE_URL:
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

    bots = []

    for document, revision in rows:
        bot = json.loads(document)
        bot["_revision"] = revision
        bot.setdefault("lifecycle", "Черновик")
        bot.setdefault("position", {})
        bot.setdefault("decision", "")
        bots.append(bot)

    return sorted(
        bots,
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
# OKX DATA
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
        headers={"User-Agent": "OKX-Terminal"},
    )

    with urlopen(request, timeout=15) as response:
        payload = json.load(response)

    if payload.get("code") != "0":
        raise ValueError(
            "OKX не подтвердил запрос."
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
        raise ValueError("Нет свежей цены.")

    volume = number(row.get("volCcy24h"))

    if market == "SWAP":
        volume *= price

    return {
        "price": price,
        "volume": volume,
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
        raise ValueError("Недостаточно дневных свечей.")

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
def history_candles(coin, market, days, bar):
    cutoff = int(
        (time.time() - days * 86400) * 1000
    )

    interval = {
        "15m": 900000,
        "1H": 3600000,
        "4H": 14400000,
    }[bar]

    collected = {}
    after = None
    previous = None

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

        if oldest <= cutoff or oldest == previous:
            break

        previous = oldest
        after = oldest
        time.sleep(0.12)

    if len(collected) < 30:
        raise ValueError("Недостаточно истории.")

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
        frame["ts"].diff().dropna() > interval
    ).any():
        raise ValueError(
            "В истории есть пропуски."
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

    change = frame["close"].diff()
    gains = wilder(change.clip(lower=0))
    losses = wilder(-change.clip(upper=0))

    rsi = pd.Series(
        float("nan"),
        index=frame.index,
    )

    for index in frame.index:
        gain = gains.loc[index]
        loss = losses.loc[index]

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
            increasing_line_color="#16803c",
            decreasing_line_color="#cc3048",
        ),
        row=1,
        col=1,
    )

    figure.add_trace(
        go.Scatter(
            x=frame["time"],
            y=frame["RSI"],
            name="RSI",
            line={"color": "#2563a6"},
        ),
        row=2,
        col=1,
    )

    figure.add_trace(
        go.Scatter(
            x=frame["time"],
            y=frame["ADX"],
            name="ADX",
            line={"color": "#9a6d15"},
        ),
        row=3,
        col=1,
    )

    for value in (30, 70):
        figure.add_hline(
            y=value,
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
        template="plotly_white",
        height=650,
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font={"color": "#17212e"},
        xaxis_rangeslider_visible=False,
        margin={"l": 5, "r": 5, "t": 45, "b": 5},
    )

    st.plotly_chart(
        figure,
        use_container_width=True,
        theme=None,
    )


# =========================================================
# SCANNER
# =========================================================

def scanner_page():
    panel(
        "Сканер",
        "DCA и Grid — стратегии. "
        "Long и Short — направления.",
    )

    market = st.radio(
        "Рынок",
        ["SWAP", "SPOT"],
        horizontal=True,
        key="scanner_market",
    )

    coins = st.multiselect(
        "Монеты",
        COINS,
        default=COINS,
        key="scanner_coins",
    )

    threshold = numeric(
        "Порог объёма за 24 часа, USDT",
        10_000_000,
        "scanner_threshold",
    )

    st.caption(
        "Исходные правила RSI/ADX. "
        "Закрытые дневные свечи. "
        "Это классификация, а не гарантия движения."
    )

    if st.button(
        "Сканировать",
        use_container_width=True,
    ):
        rows = []
        errors = []
        charts = {}

        progress = st.progress(0.0)

        for index, coin in enumerate(coins):
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
                        "Индикаторы не готовы."
                    )

                if adx > 25:
                    if rsi < 40:
                        strategy = "DCA"
                        direction = "Long"
                        status = "Рассмотреть"
                        reason = "ADX > 25, RSI < 40"
                    elif rsi > 50:
                        strategy = "—"
                        direction = "—"
                        status = "Ждать"
                        reason = "ADX > 25, RSI > 50"
                    else:
                        strategy = "DCA"
                        direction = "Short"
                        status = "Рассмотреть"
                        reason = "ADX > 25, RSI 40–50"
                else:
                    strategy = "Grid"
                    direction = "Не определено"
                    status = "Рассмотреть"
                    reason = "ADX ≤ 25"

                if market == "SPOT" and direction == "Short":
                    status = "Недоступно для Spot"

                volume = ticker["volume"]
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
                LOGGER.exception(
                    "Scanner failed for %s", coin
                )
                errors.append(coin)

            progress.progress(
                (index + 1) / max(1, len(coins))
            )

        st.session_state["scanner_result"] = {
            "rows": rows,
            "errors": errors,
            "charts": charts,
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

    if result["errors"]:
        st.warning(
            "Не рассчитаны: "
            + ", ".join(result["errors"])
        )

    # Убираем TON также из старого результата сессии.
    current_rows = [
        row for row in result["rows"]
        if row.get("Монета") != "TON"
    ]

    if not current_rows:
        st.info("Нет результатов.")
        return

    frame = pd.DataFrame(current_rows)

    columns = st.columns(4)

    columns[0].metric(
        "DCA Long",
        int(frame["Направление"].eq("Long").sum()),
    )
    columns[1].metric(
        "DCA Short",
        int(frame["Направление"].eq("Short").sum()),
    )
    columns[2].metric(
        "Grid",
        int(frame["Стратегия"].eq("Grid").sum()),
    )
    columns[3].metric(
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

    show_table(visible)

    if visible.empty:
        return

    coin = st.selectbox(
        "Монета для подробностей",
        visible["Монета"].tolist(),
    )

    row = frame[frame["Монета"] == coin].iloc[0]

    st.info(
        f"{row['Стратегия']} · "
        f"{row['Направление']} · "
        f"{row['Причина']}"
    )

    scanner_chart(
        result["charts"][coin],
        f"{coin} · цена, RSI и ADX",
    )

    columns = st.columns(3)

    def open_plan(strategy, direction):
        prefix = strategy.lower()

        st.session_state[prefix + "_coin"] = coin
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

    if columns[0].button("Подготовить DCA Long"):
        open_plan("DCA", "Long")

    if columns[1].button(
        "Подготовить DCA Short",
        disabled=result["market"] == "SPOT",
    ):
        open_plan("DCA", "Short")

    if columns[2].button("Подготовить Grid"):
        open_plan(
            "Grid",
            "Neutral" if result["market"] == "SWAP" else "Long",
        )

    st.caption(
        "Grid не означает автоматически Long или Short. "
        "Направление выбирается отдельно. "
        "Прибыльность правил не подтверждена."
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
        raise ValueError("Проверь параметры DCA.")

    rows = []
    total = 0.0
    quantity = 0.0

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
                "Один из уровней имеет цену ≤ 0."
            )

        total += amount
        quantity += amount / price

        rows.append({
            "Ордер": "Вход" if index == 0 else f"СО {index}",
            "Цена": price,
            "Номинал USDT": amount,
            "Всего номинал": total,
            "Средняя": total / quantity,
        })

    return rows


# =========================================================
# RISK AND EXIT PLAN
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
            "Запуск и активная позиция не подтверждены."
        )
        return state

    if price is None:
        state["reason"] = (
            "Нет свежей рыночной цены. "
            "Ноль вместо цены не используется."
        )
        return state

    fresh = hours_since(
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

        if distance <= number(settings.get("liq_warn"), 10):
            high_risk = True
            reasons.append(
                "Цена близка к введённой ликвидации "
                "или пересекла её. Срочно сверить позицию. "
                "Это не расчёт биржевого MMR."
            )

    if not fresh:
        reasons.append(
            "Сверка устарела или отсутствует."
        )
    elif direction == "Neutral":
        reasons.append(
            "Общий PnL Neutral Grid здесь "
            "не моделируется. Проверь Total PnL на OKX."
        )
    elif quantity <= 0 or average <= 0:
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
        high_risk = True
        exit_triggered = True
        reasons.append(
            "Достигнут лимит убытка открытой позиции. "
            "Комиссии, funding и прошлые циклы не учтены."
        )

    stop = number(settings.get("stop_price"))

    if (
        stop > 0
        and direction in ("Long", "Short")
        and side(direction) * (price - stop) <= 0
    ):
        high_risk = True
        exit_triggered = True
        reasons.append(
            "Достигнута сигнальная стоп-цена. "
            "Биржевой ордер приложение не выставляло."
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
            reasons.append("Проверь диапазон Grid.")
        elif price < lower or price > upper:
            reasons.append(
                "Цена вне диапазона Grid. "
                "Это не подтверждение закрытия позиции."
            )
        elif (
            min(price - lower, upper - price)
            / (upper - lower)
            <= 0.1
        ):
            reasons.append(
                "Цена в крайних 10% диапазона."
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
        state["risk"] = "Правила не сработали"

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
        LOGGER.exception("Assessment failed")

        state = {
            "action": "Проверить настройки",
            "risk": "Не оценён",
            "reason": "Проверь параметры карточки.",
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
            "Telegram не настроен в Secrets."
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
        f"Сверка UTC: "
        f"{bot.get('position', {}).get('last_check') or 'нет'}\n\n"
        "Торговые команды не отправлялись."
    )


# =========================================================
# POSITION AND BOT CARD
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
            "Ликвидационная цена; 0 = неизвестна",
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
            maximum = int(settings.get("so_count", 0))

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
                    "Нужны объём и средняя цена."
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
        direction_color = {
            "Long": "#16803c",
            "Short": "#cc3048",
            "Neutral": "#64748b",
        }.get(bot["direction"], "#17212e")

        st.html(
            '<div style="background:#ffffff;">'
            '<div style="font-size:20px;font-weight:750;">'
            f'{html.escape(bot["coin"])} · '
            f'{html.escape(bot["strategy"])} '
            f'<span style="color:{direction_color};">'
            f'{html.escape(bot["direction"])}'
            '</span></div></div>'
        )

        st.caption(
            f"{bot['name']} · "
            f"{bot.get('lifecycle', 'Черновик')} · "
            f"{bot['market']}"
        )

        columns = st.columns(3)

        columns[0].metric(
            "Цена",
            formatted(price, 6),
        )
        columns[1].metric(
            "Открытый PnL ≈ USDT",
            formatted(state["pnl"]),
        )
        columns[2].metric(
            "Остаток бюджета маржи",
            formatted(state["remaining"]),
        )

        st.write("Действие: " + state["action"])
        st.caption("Риск: " + state["risk"])

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
                key="open_" + bot["id"],
            ):
                navigate("3. ИИ-Центр")
            return

        if state["tp"] is not None:
            st.write(
                "Модельный TP: "
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
            "общему результату бота."
        )

        with st.expander(
            "Сверить позицию / отметить запуск"
        ):
            position_form(bot)

        with st.expander("Параметры плана"):
            st.json(bot["settings"])

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

            reason = st.text_input("Причина решения")

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
                "Последнее решение: " + bot["decision"]
            )

        st.caption(
            "«Не трогать» не отключает предупреждения."
        )

        if st.button(
            "Отправить статус в Telegram",
            key="telegram_" + bot["id"],
        ):
            try:
               
