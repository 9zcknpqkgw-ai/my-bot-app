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


st.set_page_config(
    page_title="OKX Terminal Pro",
    layout="wide",
)

PAGES = [
    "Главная",
    "Сканер",
    "DCA",
    "Grid",
    "Открытая позиция",
    "Журнал",
    "Настройки",
]

COINS = [
    "BTC", "ETH", "SOL", "BNB", "XRP",
    "DOGE", "ADA", "AVAX", "LINK", "DOT",
    "TON", "TRX", "LTC", "NEAR", "APT",
    "ARB", "OP", "SUI", "PEPE", "INJ",
]

API = "https://www.okx.com/api/v5"
HOUR = 3_600_000


# =========================================================
# CONFIGURATION AND HELPERS
# =========================================================

def secret(key, default=""):
    try:
        return st.secrets.get(
            key,
            os.getenv(key, default),
        )
    except Exception:
        return os.getenv(key, default)


DB_URL = str(
    secret(
        "DATABASE_URL",
        secret("DB_URL"),
    )
).strip()

DB_FILE = str(
    secret(
        "SQLITE_PATH",
        "bots.sqlite3",
    )
)

LOCAL = str(
    secret(
        "ALLOW_LOCAL_STORAGE",
        "false",
    )
).lower() in (
    "true",
    "1",
    "yes",
)

STORAGE = bool(DB_URL) or LOCAL


def now():
    return datetime.now(
        timezone.utc
    ).isoformat()


def num(value, default=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except (ValueError, TypeError):
        return default


def fmt(value, digits=2):
    return "—" if value is None else f"{value:,.{digits}f}"


def side(direction):
    return {
        "Long": 1,
        "Short": -1,
        "Neutral": 0,
    }.get(direction, 0)


def age(value):
    try:
        dt = datetime.fromisoformat(value)

        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return max(
            0,
            (
                datetime.now(timezone.utc) - dt
            ).total_seconds() / 3600,
        )

    except (ValueError, TypeError):
        return float("inf")


# =========================================================
# NAVIGATION
# =========================================================

def move(
    page,
    direction=None,
    template=None,
    focus=None,
    mode="Мои боты",
):
    st.session_state["_route"] = dict(
        page=page,
        direction=direction,
        template=template,
        focus=focus,
        mode=mode,
    )

    st.rerun()


def apply_route():
    request = st.session_state.pop(
        "_route",
        None,
    )

    if request and request.get("page") in PAGES:
        page = request["page"]

        st.session_state["page"] = page

        if page in ("DCA", "Grid"):
            st.session_state[
                page + "mode"
            ] = request["mode"]

            if request.get("direction"):
                st.session_state[
                    page + "direction"
                ] = request["direction"]

            for key, value in (
                request.get("template") or {}
            ).items():
                st.session_state[
                    page + key
                ] = value

        if request.get("focus"):
            st.session_state[
                "focus"
            ] = request["focus"]

    if st.session_state.get("page") not in PAGES:
        st.session_state["page"] = "Главная"


def number(
    label,
    value,
    key,
    minimum=0.0,
    maximum=None,
    integer=False,
):
    args = dict(
        label=label,
        key=key,
    )

    cast = int if integer else float

    if key not in st.session_state:
        args["value"] = cast(value)

    if minimum is not None:
        args["min_value"] = cast(minimum)

    if maximum is not None:
        args["max_value"] = cast(maximum)

    if integer:
        args["step"] = 1

    return st.number_input(**args)


# =========================================================
# DESIGN
# =========================================================

def design():
    st.markdown(
        """
<style>
.stApp {
    background:
        radial-gradient(
            1100px 600px at 8% -10%,
            rgba(0,255,157,.09),
            transparent 60%
        ),
        radial-gradient(
            900px 600px at 100% 0%,
            rgba(88,101,242,.12),
            transparent 55%
        ),
        #05070c;
    color: #e8ecf4;
    color-scheme: dark;
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
    color: #b7c4d8 !important;
}

[data-testid="stWidgetLabel"] p,
[data-testid="stCheckbox"] p,
[data-testid="stExpander"] summary p {
    color: #edf3ff !important;
}

[data-testid="stSidebar"] {
    background: #090f1b;
    border-right: 1px solid #29384f;
}

.glass {
    background: linear-gradient(
        130deg,
        #12272c,
        #151a2c
    );
    border: 1px solid #30465c;
    border-radius: 20px;
    padding: 22px;
    margin-bottom: 18px;
}

.glass h2 {
    margin: 0;
}

.glass p {
    color: #bac7db !important;
    margin-bottom: 0;
}

.metric-card,
[data-testid="stMetric"] {
    background: linear-gradient(
        145deg,
        #171c29,
        #0b0e16
    );
    border: 1px solid #2b3a50;
    border-radius: 16px;
    padding: 17px;
}

.metric-label {
    color: #b7c4d8;
    font-size: .85rem;
}

.metric-value {
    color: #fff;
    font-size: 1.65rem;
    font-weight: 800;
    margin-top: 6px;
}

[data-testid="stMetricLabel"] p,
[data-testid="stMetricLabel"] span {
    color: #b7c4d8 !important;
}

[data-testid="stMetricValue"] div {
    color: #edf3ff !important;
}

.stButton button,
.stFormSubmitButton button,
.stDownloadButton button {
    background: #f5f8ff !important;
    color: #142033 !important;
    border: 1px solid #b9c7da !important;
    border-radius: 11px;
    min-height: 44px;
    font-weight: 700;
}

.stButton button p,
.stFormSubmitButton button p,
.stDownloadButton button p {
    color: inherit !important;
}

.stButton button:disabled {
    background: #cbd5e1 !important;
    color: #475569 !important;
    opacity: 1 !important;
}

[class*="st-key-action_"][class*="_long"] button {
    color: #137333 !important;
    border: 2px solid #137333 !important;
}

[class*="st-key-action_"][class*="_short"] button {
    color: #c5223f !important;
    border: 2px solid #c5223f !important;
}

[class*="st-key-action_"][class*="_neutral"] button {
    background: #ffe39b !important;
    color: #5c4100 !important;
    border: 2px solid #b8860b !important;
}

[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea {
    background: #fff !important;
    color: #172033 !important;
    -webkit-text-fill-color: #172033 !important;
}

[data-testid="stNumberInput"] button {
    background: #eaf0fa !important;
    color: #172033 !important;
}

[data-testid="stSelectbox"] [data-baseweb="select"] > div {
    background: #fff !important;
    color: #172033 !important;
}

[data-testid="stSelectbox"] span,
[data-testid="stSelectbox"] input {
    color: #172033 !important;
    -webkit-text-fill-color: #172033 !important;
}

[role="listbox"],
[role="option"] {
    background: #fff !important;
    color: #172033 !important;
}

[data-testid="stRadio"] [role="radiogroup"] > label {
    background: #fff !important;
    border: 2px solid #cbd5e1;
    border-radius: 10px;
    padding: 8px 11px !important;
    margin: 3px !important;
}

[data-testid="stRadio"] [role="radiogroup"] > label p {
    color: #172033 !important;
    font-weight: 700 !important;
}

[data-testid="stRadio"] label:has(input:checked) {
    border-color: #2563eb !important;
}

.st-key-DCAdirection [role="radiogroup"] > label:nth-of-type(1) p,
.st-key-Griddirection [role="radiogroup"] > label:nth-of-type(1) p {
    color: #137333 !important;
}

.st-key-DCAdirection [role="radiogroup"] > label:nth-of-type(2) p,
.st-key-Griddirection [role="radiogroup"] > label:nth-of-type(2) p {
    color: #c5223f !important;
}

.st-key-Griddirection [role="radiogroup"] > label:nth-of-type(3) {
    background: #ffe39b !important;
}

.st-key-Griddirection [role="radiogroup"] > label:nth-of-type(3) p {
    color: #5c4100 !important;
}

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


def panel(title, subtitle):
    st.markdown(
        '<div class="glass"><h2>'
        + html.escape(title)
        + '</h2><p>'
        + html.escape(subtitle)
        + '</p></div>',
        unsafe_allow_html=True,
    )


def table(frame):
    if frame.empty:
        return

    formats = {
        column: (
            "{:,.6f}"
            if column in ("Цена", "Средняя")
            else "{:,.2f}"
        )
        for column in frame.select_dtypes(
            include="number"
        ).columns
    }

    styled = (
        frame.style
        .set_properties(**{
            "background-color": "#fff",
            "color": "#172033",
        })
        .format(
            formats,
            na_rep="—",
        )
    )

    st.dataframe(
        styled,
        hide_index=True,
        use_container_width=True,
    )


# =========================================================
# PASSWORD
# =========================================================

def login():
    password = str(
        secret("APP_PASSWORD")
    )

    if not password.strip():
        panel(
            "Вход заблокирован",
            "Добавь APP_PASSWORD в Streamlit Secrets. "
            "Без пароля терминал не открывается.",
        )
        st.stop()

    if st.session_state.get(
        "_authenticated"
    ):
        return

    panel(
        "OKX Terminal Pro",
        "Вход в личный терминал",
    )

    with st.form(
        "login",
        clear_on_submit=True,
    ):
        entered = st.text_input(
            "Пароль",
            type="password",
        )

        submitted = st.form_submit_button(
            "Войти",
            use_container_width=True,
        )

    if submitted:
        if hmac.compare_digest(
            entered.encode(),
            password.encode(),
        ):
            st.session_state[
                "_authenticated"
            ] = True

            st.rerun()
        else:
            st.error(
                "Неверный пароль."
            )

    st.stop()


# =========================================================
# STORAGE
# =========================================================

@contextmanager
def database():
    if not STORAGE:
        raise ValueError(
            "Настрой DATABASE_URL. "
            "Сохранение только в память "
            "не используется."
        )

    if DB_URL:
        import psycopg2

        connection = psycopg2.connect(
            DB_URL,
            connect_timeout=10,
        )
    else:
        connection = sqlite3.connect(
            DB_FILE,
            timeout=20,
        )

    try:
        yield connection
        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def sql(connection, statement, args=()):
    cursor = connection.cursor()

    cursor.execute(
        statement.replace("?", "%s")
        if DB_URL
        else statement,
        args,
    )

    return cursor


def init_database():
    with database() as connection:
        sql(
            connection,
            """
            CREATE TABLE IF NOT EXISTS terminal_bots (
                id TEXT PRIMARY KEY,
                document TEXT NOT NULL,
                revision INTEGER NOT NULL
            )
            """,
        )

        sql(
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


def record(
    connection,
    bot_id,
    title,
    details,
):
    sql(
        connection,
        """
        INSERT INTO terminal_events
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


def normalize(raw):
    bot = json.loads(
        json.dumps(
            raw,
            ensure_ascii=False,
        )
    )

    if (
        bot.get("strategy")
        not in ("DCA", "Grid")
        or bot.get("direction")
        not in ("Long", "Short", "Neutral")
    ):
        raise ValueError(
            "Неверная стратегия "
            "или направление карточки."
        )

    if (
        bot["strategy"] == "DCA"
        and bot["direction"] == "Neutral"
    ):
        raise ValueError(
            "DCA Neutral не поддерживается."
        )

    for key in (
        "settings",
        "position",
    ):
        if isinstance(
            bot.get(key),
            str,
        ):
            bot[key] = json.loads(
                bot[key]
            )

        bot.setdefault(key, {})

        if not isinstance(
            bot[key],
            dict,
        ):
            raise ValueError(
                "Неверные настройки или позиция."
            )

    bot["coin"] = (
        str(bot.get("coin", ""))
        .strip()
        .upper()
        .replace("ARBITRUM", "ARB")
    )

    if not bot["coin"].isalnum():
        raise ValueError(
            "Неверная монета в карточке."
        )

    market = str(
        bot.get("market", "SWAP")
    )

    bot["market"] = (
        "SWAP"
        if "SWAP" in market
        or "Фьючерсы" in market
        else "SPOT"
    )

    bot.setdefault(
        "name",
        bot["coin"] + " " + bot["strategy"],
    )

    bot.setdefault(
        "lifecycle",
        "Черновик",
    )

    bot.setdefault(
        "created_at",
        now(),
    )

    settings = bot["settings"]
    position = bot["position"]

    defaults = dict(
        leverage=1,
        base_margin=100,
        reserve=50,
        tp=1.5,
        step=2,
        so_count=4,
        mart=1.2,
        base_amount=10,
        first_so=10,
        entry=0,
        stop_price=0,
        max_loss=0,
        stale_hours=6,
        liq_warn=10,
        danger_pct=3,
        lower=0,
        upper=0,
        grids=10,
        target_price=0,
    )

    for key, value in defaults.items():
        settings.setdefault(
            key,
            value,
        )

    settings.setdefault(
        "total_budget",
        num(settings["base_margin"])
        + num(settings["reserve"]),
    )

    position.setdefault(
        "realized_pnl",
        num(settings.get("realized_pnl")),
    )

    return bot


def load_bots():
    with database() as connection:
        rows = sql(
            connection,
            """
            SELECT document, revision
            FROM terminal_bots
            """,
        ).fetchall()

    result = []

    for document, revision in rows:
        bot = normalize(
            json.loads(document)
        )

        bot["_revision"] = revision
        result.append(bot)

    return sorted(
        result,
        key=lambda bot: bot.get(
            "updated_at",
            "",
        ),
        reverse=True,
    )


def save_bot(bot, title, details):
    document = normalize(bot)

    revision = document.pop(
        "_revision",
        None,
    )

    document["updated_at"] = now()

    raw = json.dumps(
        document,
        ensure_ascii=False,
        allow_nan=False,
    )

    with database() as connection:
        if revision is None:
            sql(
                connection,
                """
                INSERT INTO terminal_bots
                VALUES (?, ?, ?)
                """,
                (
                    document["id"],
                    raw,
                    1,
                ),
            )

        else:
            cursor = sql(
                connection,
                """
                UPDATE terminal_bots
                SET document = ?, revision = revision + 1
                WHERE id = ? AND revision = ?
                """,
                (
                    raw,
                    document["id"],
                    revision,
                ),
            )

            if cursor.rowcount != 1:
                raise ValueError(
                    "Карточка изменена в другой вкладке. "
                    "Обнови страницу перед сохранением."
                )

        record(
            connection,
            document["id"],
            title,
            details,
        )


def history():
    if not STORAGE:
        return pd.DataFrame()

    with database() as connection:
        rows = sql(
            connection,
            """
            SELECT bot_id, created_at, title, details
            FROM terminal_events
            ORDER BY created_at DESC
            LIMIT 5000
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

@st.cache_data(ttl=20, show_spinner=False)
def api(path, params):
    error = None

    for attempt in range(3):
        try:
            response = requests.get(
                API + path,
                params=params,
                timeout=(5, 12),
            )

            response.raise_for_status()
            result = response.json()

            if str(
                result.get("code")
            ) != "0":
                raise ValueError(
                    "OKX не подтвердил запрос."
                )

            return result.get(
                "data",
                [],
            )

        except (
            requests.RequestException,
            ValueError,
        ) as exc:
            error = exc

            time.sleep(
                0.2 * (attempt + 1)
            )

    raise ValueError(
        "Данные OKX недоступны."
    ) from error


def instrument(coin, market):
    return (
        f"{coin}-USDT"
        + (
            "-SWAP"
            if market == "SWAP"
            else ""
        )
    )


@st.cache_data(ttl=20, show_spinner=False)
def quote(coin, market):
    rows = api(
        "/market/ticker",
        {
            "instId": instrument(
                coin,
                market,
            ),
        },
    )

    if not rows:
        raise ValueError(
            "Инструмент не найден."
        )

    row = rows[0]

    price = num(
        row.get("last")
    )

    timestamp = num(
        row.get("ts")
    )

    if (
        price <= 0
        or timestamp <= 0
        or time.time() - timestamp / 1000 > 180
    ):
        raise ValueError(
            "Нет свежей цены."
        )

    opening = num(
        row.get("open24h")
    )

    return dict(
        price=price,
        ts=timestamp,
        volume=(
            num(row.get("volCcy24h"))
            * (
                price
                if market == "SWAP"
                else 1
            )
        ),
        change=(
            (price / opening - 1) * 100
            if opening > 0
            else None
        ),
    )


def candle_frame(rows):
    values = [
        [
            int(row[0]),
            *map(
                float,
                row[1:5],
            ),
        ]
        for row in rows
        if len(row) >= 9
        and str(row[8]) == "1"
    ]

    frame = (
        pd.DataFrame(
            values,
            columns=[
                "ts",
                "open",
                "high",
                "low",
                "close",
            ],
        )
        .drop_duplicates("ts")
        .sort_values("ts")
        .reset_index(drop=True)
    )

    if (
        frame.empty
        or not np.isfinite(
            frame[
                ["open", "high", "low", "close"]
            ].to_numpy()
        ).all()
        or (frame.close <= 0).any()
    ):
        raise ValueError(
            "Нет корректных закрытых свечей."
        )

    frame["time"] = pd.to_datetime(
        frame.ts,
        unit="ms",
        utc=True,
    )

    return frame


@st.cache_data(ttl=180, show_spinner=False)
def daily(coin, market):
    frame = candle_frame(
        api(
            "/market/candles",
            {
                "instId": instrument(
                    coin,
                    market,
                ),
                "bar": "1D",
                "limit": "200",
            },
        )
    )

    if (
        len(frame) < 60
        or (
            frame.ts.diff().dropna()
            != 24 * HOUR
        ).any()
        or time.time() * 1000
        - int(frame.ts.iloc[-1])
        > 49 * HOUR
    ):
        raise ValueError(
            "Недостаточно свежей непрерывной "
            "дневной истории."
        )

    return frame


# =========================================================
# RSI / ADX / ATR
# =========================================================

def rma(series, period=14):
    result = pd.Series(
        np.nan,
        index=series.index,
        dtype=float,
    )

    seed = []
    previous = None

    for index, value in series.items():
        if pd.isna(value):
            continue

        if previous is None:
            seed.append(
                float(value)
            )

            if len(seed) == period:
                previous = (
                    sum(seed) / period
                )

                result.loc[index] = previous

        else:
            previous = (
                previous * (period - 1)
                + float(value)
            ) / period

            result.loc[index] = previous

    return result


def indicators(frame):
    frame = frame.copy()

    delta = frame.close.diff()

    gain = rma(
        delta.clip(lower=0)
    )

    loss = rma(
        -delta.clip(upper=0)
    )

    rsi = (
        100
        - 100 / (1 + gain / loss)
    )

    rsi.loc[
        (gain == 0) & (loss == 0)
    ] = 50

    rsi.loc[
        (gain > 0) & (loss == 0)
    ] = 100

    true_range = pd.concat(
        [
            frame.high - frame.low,
            (
                frame.high
                - frame.close.shift()
            ).abs(),
            (
                frame.low
                - frame.close.shift()
            ).abs(),
        ],
        axis=1,
    ).max(axis=1)

    true_range.iloc[0] = np.nan

    atr = rma(
        true_range
    )

    up = frame.high.diff()
    down = -frame.low.diff()

    plus = up.where(
        (up > down) & (up > 0),
        0.0,
    )

    minus = down.where(
        (down > up) & (down > 0),
        0.0,
    )

    plus.iloc[0] = np.nan
    minus.iloc[0] = np.nan

    plus = rma(plus)
    minus = rma(minus)

    total = plus + minus

    dx = (
        100
        * (plus - minus).abs()
        / total
    )

    dx.loc[total == 0] = 0

    frame["RSI"] = rsi
    frame["ADX"] = rma(dx)

    frame["ATR %"] = (
        atr / frame.close * 100
    )

    frame["+DI"] = (
        100 * plus / atr
    )

    frame["-DI"] = (
        100 * minus / atr
    )

    frame.loc[
        atr == 0,
        ["+DI", "-DI"],
    ] = 0

    return frame


# =========================================================
# MARKET CHART
# =========================================================

def chart(frame, title):
    figure = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        row_heights=[
            0.6,
            0.2,
            0.2,
        ],
        vertical_spacing=0.04,
    )

    figure.add_trace(
        go.Candlestick(
            x=frame.time,
            open=frame.open,
            high=frame.high,
            low=frame.low,
            close=frame.close,
            name="Цена",
            increasing_line_color="#00ff9d",
            decreasing_line_color="#ff4d6d",
        ),
        row=1,
        col=1,
    )

    figure.add_trace(
        go.Scatter(
            x=frame.time,
            y=frame.RSI,
            name="RSI",
            line=dict(
                color="#00c2ff",
            ),
        ),
        row=2,
        col=1,
    )

    figure.add_trace(
        go.Scatter(
            x=frame.time,
            y=frame.ADX,
            name="ADX",
            line=dict(
                color="#ffd166",
            ),
        ),
        row=3,
        col=1,
    )

    figure.add_hline(
        y=30,
        line_dash="dot",
        row=2,
        col=1,
    )

    figure.add_hline(
        y=70,
        line_dash="dot",
        row=2,
        col=1,
    )

    figure.add_hline(
        y=25,
        line_dash="dot",
        row=3,
        col=1,
    )

    figure.update_layout(
        title=title,
        template="plotly_dark",
        height=650,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis_rangeslider_visible=False,
    )

    st.plotly_chart(
        figure,
        use_container_width=True,
    )


# =========================================================
# SCANNER
# =========================================================

def analyze_coin(coin, market):
    frame = indicators(
        daily(
            coin,
            market,
        )
    )

    last = frame.iloc[-1]

    ticker = quote(
        coin,
        market,
    )

    if not np.isfinite([
        last.RSI,
        last.ADX,
        last["+DI"],
        last["-DI"],
        last["ATR %"],
    ]).all():
        raise ValueError(
            "Индикаторы не готовы."
        )

    if last.ADX < 25:
        signal = "GRID"

    elif last["+DI"] > last["-DI"]:
        signal = "LONG"

    elif last["-DI"] > last["+DI"]:
        signal = "SHORT"

    else:
        signal = "WAIT"

    if last["ATR %"] < 1.5:
        take = 1.0

    elif last["ATR %"] < 3:
        take = 1.5

    else:
        take = 2.0

    return {
        "Монета": coin,
        "Цена": ticker["price"],
        "Сигнал": signal,
        "RSI": last.RSI,
        "ADX": last.ADX,
        "ATR %": last["ATR %"],
        "Объём 24H ≈ USDT": ticker["volume"],
        "Тейк %": take,
        "Шаг %": 2.0,
    }


def scanner():
    panel(
        "Сканер",
        "Дневные свечи, RSI/ADX, ликвидность "
        "и переход к настройке бота.",
    )

    market = st.radio(
        "Рынок",
        ["SWAP", "SPOT"],
        horizontal=True,
        key="scanmarket",
    )

    if st.button(
        "Сканировать 20 монет",
        use_container_width=True,
    ):
        rows = []
        errors = []

        progress = st.progress(
            0.0
        )

        with ThreadPoolExecutor(
            max_workers=4
        ) as pool:
            jobs = {
                pool.submit(
                    analyze_coin,
                    coin,
                    market,
                ): coin
                for coin in COINS
            }

            for index, future in enumerate(
                as_completed(jobs)
            ):
                try:
                    rows.append(
                        future.result()
                    )
                except Exception:
                    errors.append(
                        jobs[future]
                    )

                progress.progress(
                    (index + 1) / len(jobs)
                )

        rows.sort(
            key=lambda row: COINS.index(
                row["Монета"]
            )
        )

        st.session_state["scan"] = dict(
            rows=rows,
            errors=errors,
            market=market,
            time=now(),
        )

    saved = st.session_state.get(
        "scan"
    )

    if not saved:
        st.info(
            "Запусти сканирование."
        )
        return

    st.caption(
        saved["market"]
        + " · "
        + saved["time"]
    )

    if saved["errors"]:
        st.warning(
            "Не рассчитаны: "
            + ", ".join(saved["errors"])
        )

    if not saved["rows"]:
        return

    table(
        pd.DataFrame(
            saved["rows"]
        )
    )

    coin = st.selectbox(
        "Открыть монету",
        [
            row["Монета"]
            for row in saved["rows"]
        ],
    )

    row = next(
        row
        for row in saved["rows"]
        if row["Монета"] == coin
    )

    chart(
        indicators(
            daily(
                coin,
                saved["market"],
            )
        ),
        coin + " · цена, RSI и ADX",
    )

    st.caption(
        "Сигнал — правило индикаторов, "
        "не прогноз доходности. "
        "TP по ATR — шаблон, не оптимизация."
    )

    columns = st.columns(2)

    template = dict(
        coin=coin,
        market=saved["market"],
        entry=float(row["Цена"]),
        tp=float(row["Тейк %"]),
        step=2.0,
        count=4,
        mart=1.2,
        lower=float(row["Цена"]) * 0.9,
        upper=float(row["Цена"]) * 1.1,
    )

    direction = (
        "Short"
        if row["Сигнал"] == "SHORT"
        else "Long"
    )

    if columns[0].button(
        "Создать DCA",
        disabled=(
            saved["market"] != market
            or (
                market == "SPOT"
                and direction == "Short"
            )
        ),
    ):
        move(
            "DCA",
            direction,
            template,
            mode="Подготовить бота",
        )

    if columns[1].button(
        "Создать Grid",
        disabled=(
            saved["market"] != market
        ),
    ):
        move(
            "Grid",
            "Neutral"
            if market == "SWAP"
            else "Long",
            template,
            mode="Подготовить бота",
        )


# =========================================================
# DCA PLAN
# =========================================================

def dca_plan(settings, direction):
    entry = num(settings["entry"])
    step = num(settings["step"])
    count = int(settings["so_count"])

    base = num(settings["base_amount"])
    first = num(settings["first_so"])
    multiplier = num(settings["mart"])

    if (
        entry <= 0
        or step <= 0
        or base <= 0
        or first <= 0
        or multiplier < 1
        or not 0 <= count <= 30
        or direction not in ("Long", "Short")
    ):
        raise ValueError(
            "Проверь цену и параметры DCA."
        )

    result = []
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

        if price <= 0:
            raise ValueError(
                "Один из уровней DCA "
                "имеет цену ≤ 0."
            )

        amount = (
            base
            if index == 0
            else first
            * multiplier ** (index - 1)
        )

        total += amount
        quantity += amount / price

        result.append({
            "Ордер": (
                "Вход"
                if index == 0
                else f"СО {index}"
            ),
            "Цена": price,
            "Номинал USDT": amount,
            "Всего номинал": total,
            "Средняя": total / quantity,
        })

    return result


# =========================================================
# HISTORICAL DATA
# =========================================================

@st.cache_data(ttl=300, show_spinner=False)
def history_prices(
    coin,
    market,
    days,
    end,
):
    start = (
        end - days * 24 * HOUR
    )

    after = end
    rows = []
    previous = None

    for _ in range(100):
        batch = api(
            "/market/history-candles",
            {
                "instId": instrument(
                    coin,
                    market,
                ),
                "bar": "1H",
                "limit": "100",
                "after": str(after),
            },
        )

        if not batch:
            break

        rows.extend(batch)

        oldest = min(
            int(row[0])
            for row in batch
        )

        if (
            oldest <= start
            or oldest == previous
        ):
            break

        previous = oldest
        after = oldest

        time.sleep(0.12)

    frame = candle_frame(
        rows
    )

    frame = frame[
        (frame.ts >= start)
        & (frame.ts < end)
    ].reset_index(drop=True)

    expected = np.arange(
        start,
        end,
        HOUR,
        dtype=np.int64,
    )

    if (
        len(frame) != len(expected)
        or not np.array_equal(
            frame.ts.to_numpy(),
            expected,
        )
    ):
        raise ValueError(
            "История не покрывает весь "
            "выбранный период без пропусков. "
            "Тест остановлен."
        )

    return frame


# =========================================================
# SIMULATION
# =========================================================

def simulate(
    frame,
    settings,
    strategy,
    direction,
    market,
    fee,
):
    capital = num(
        settings["base_margin"]
    )

    leverage = num(
        settings["leverage"]
    )

    if capital <= 0 or leverage < 1:
        raise ValueError(
            "Проверь капитал и плечо."
        )

    if (
        market == "SPOT"
        and (
            direction != "Long"
            or leverage != 1
        )
    ):
        raise ValueError(
            "Spot-модель поддерживает "
            "только Long 1x."
        )

    if strategy == "DCA":
        plan = dca_plan(
            settings,
            direction,
        )

        total_notional = (
            plan[-1]["Всего номинал"]
        )

        if (
            total_notional / leverage
            + total_notional * fee
            >= capital
        ):
            raise ValueError(
                "Капитала недостаточно "
                "для ордеров с запасом."
            )

    else:
        if not (
            0
            < settings["lower"]
            < settings["upper"]
        ):
            raise ValueError(
                "Проверь диапазон Grid."
            )

        levels = np.linspace(
            settings["lower"],
            settings["upper"],
            int(settings["grids"]) + 1,
        )

        allocation = (
            capital
            / int(settings["grids"])
            / (1 + leverage * fee)
        )

        middle = (
            settings["lower"]
            + settings["upper"]
        ) / 2

    wallet = capital
    quantity = 0.0
    average = 0.0
    entry = 0.0
    used = 0.0

    executed = 0
    cycles = 0
    fees = 0.0
    floating = 0.0

    lots = {}
    curve = []
    halted = False

    prices = frame.close.to_numpy(
        dtype=float
    )

    for index, price in enumerate(prices):
        if strategy == "DCA":
            sign = side(direction)

            if (
                quantity
                and sign
                * (price / average - 1)
                * 100
                >= settings["tp"]
            ):
                close_fee = (
                    quantity * price * fee
                )

                wallet += (
                    sign
                    * quantity
                    * (price - average)
                    - close_fee
                )

                fees += close_fee
                quantity = 0.0
                used = 0.0
                cycles += 1

            elif quantity == 0:
                amount = (
                    settings["base_amount"]
                )

                if (
                    wallet
                    >= amount / leverage
                    + amount * fee
                ):
                    quantity = (
                        amount / price
                    )

                    average = price
                    entry = price
                    used = amount / leverage
                    executed = 0

                    wallet -= amount * fee
                    fees += amount * fee

            elif (
                executed < settings["so_count"]
                and sign
                * (price / entry - 1)
                * 100
                <= -settings["step"] * (executed + 1)
            ):
                amount = (
                    settings["first_so"]
                    * settings["mart"] ** executed
                )

                available = (
                    wallet
                    if market == "SPOT"
                    else wallet
                    + sign
                    * quantity
                    * (price - average)
                )

                if (
                    available
                    >= used
                    + amount / leverage
                    + amount * fee
                ):
                    average = (
                        quantity * average
                        + amount
                    ) / (
                        quantity
                        + amount / price
                    )

                    quantity += amount / price
                    used += amount / leverage

                    wallet -= amount * fee
                    fees += amount * fee

                    executed += 1

            floating = (
                sign
                * quantity
                * (price - average)
                if quantity
                else 0.0
            )

            equity = (
                wallet + floating
            )

        elif market == "SPOT":
            for key in list(lots):
                lot_quantity, cost = lots[key]

                if price >= levels[key + 1]:
                    gross = (
                        lot_quantity * price
                    )

                    wallet += (
                        gross * (1 - fee)
                    )

                    fees += gross * fee

                    del lots[key]
                    cycles += 1

            if (
                index > 0
                and settings["lower"]
                <= price
                <= settings["upper"]
            ):
                for level_index, level in enumerate(
                    levels[:-1]
                ):
                    full_cost = (
                        allocation * (1 + fee)
                    )

                    if (
                        level_index not in lots
                        and prices[index - 1]
                        > level
                        >= price
                        and wallet + 1e-9 >= full_cost
                    ):
                        lots[level_index] = (
                            allocation / price,
                            allocation,
                        )

                        wallet -= full_cost
                        fees += allocation * fee

            floating = sum(
                lot_quantity * price - cost
                for lot_quantity, cost
                in lots.values()
            )

            equity = (
                wallet
                + sum(
                    lot_quantity * price
                    for lot_quantity, cost
                    in lots.values()
                )
            )

        else:
            for key in list(lots):
                (
                    sign,
                    lot_quantity,
                    opened,
                    target,
                    margin,
                ) = lots[key]

                if sign * (price - target) >= 0:
                    close_fee = (
                        lot_quantity
                        * price
                        * fee
                    )

                    wallet += (
                        sign
                        * lot_quantity
                        * (price - opened)
                        - close_fee
                    )

                    fees += close_fee

                    del lots[key]
                    cycles += 1

            floating = sum(
                sign
                * lot_quantity
                * (price - opened)
                for (
                    sign,
                    lot_quantity,
                    opened,
                    target,
                    margin,
                ) in lots.values()
            )

            used = sum(
                lot[4]
                for lot in lots.values()
            )

            if (
                index > 0
                and settings["lower"]
                <= price
                <= settings["upper"]
            ):
                for level_index, level in enumerate(
                    levels
                ):
                    if direction == "Long":
                        sign = 1

                    elif direction == "Short":
                        sign = -1

                    else:
                        sign = (
                            1
                            if level < middle
                            else -1
                        )

                    if (
                        sign == 1
                        and level_index == len(levels) - 1
                    ):
                        continue

                    if (
                        sign == -1
                        and level_index == 0
                    ):
                        continue

                    if sign == 1:
                        crossed = (
                            prices[index - 1]
                            > level
                            >= price
                        )
                    else:
                        crossed = (
                            prices[index - 1]
                            < level
                            <= price
                        )

                    key = (
                        level_index,
                        sign,
                    )

                    opening_fee = (
                        allocation
                        * leverage
                        * fee
                    )

                    if (
                        crossed
                        and key not in lots
                        and wallet + floating
                        >= used
                        + allocation
                        + opening_fee
                    ):
                        lots[key] = (
                            sign,
                            allocation * leverage / price,
                            price,
                            levels[level_index + sign],
                            allocation,
                        )

                        wallet -= opening_fee
                        fees += opening_fee
                        used += allocation

            floating = sum(
                sign
                * lot_quantity
                * (price - opened)
                for (
                    sign,
                    lot_quantity,
                    opened,
                    target,
                    margin,
                ) in lots.values()
            )

            equity = (
                wallet + floating
            )

        if equity <= 0:
            curve.append(0.0)
            halted = True
            break

        curve.append(equity)

    values = np.array(
        [capital, *curve]
    )

    peaks = np.maximum.accumulate(
        values
    )

    return dict(
        roi=(
            curve[-1] / capital - 1
        ) * 100,
        pnl=curve[-1] - capital,
        cycles=cycles,
        fees=fees,
        floating=floating,
        dd=float(
            np.max(
                (peaks - values) / peaks
            ) * 100
        ),
        halted=halted,
        curve=curve,
    )


# =========================================================
# BACKTEST AND ALTERNATIVES
# =========================================================

def backtest(
    strategy,
    coin,
    market,
    direction,
    settings,
    valid,
):
    with st.expander(
        "Бэктест и альтернативы",
        expanded=False,
    ):
        days = st.selectbox(
            "Дней истории 1H",
            [7, 14, 30, 90],
            index=1,
            key=strategy + "days",
        )

        fee = number(
            "Комиссия за сторону, % от номинала",
            0.05,
            strategy + "fee",
            0,
            5,
        ) / 100

        if st.button(
            "Сравнить мой план и 2 альтернативы",
            disabled=not valid,
            key=strategy + "test",
        ):
            st.session_state.pop(
                strategy + "test_result",
                None,
            )

            variants = [
                (
                    "Твой план",
                    dict(settings),
                ),
                (
                    "Без увеличения СО"
                    if strategy == "DCA"
                    else "Шире диапазон",
                    dict(settings),
                ),
                (
                    "Шире шаг"
                    if strategy == "DCA"
                    else "Меньше интервалов",
                    dict(settings),
                ),
            ]

            if strategy == "DCA":
                variants[1][1]["mart"] = 1.0
                variants[2][1]["step"] *= 1.5

            else:
                middle = (
                    settings["upper"]
                    + settings["lower"]
                ) / 2

                half = (
                    settings["upper"]
                    - settings["lower"]
                ) / 2

                variants[1][1].update(
                    lower=max(
                        0.00000001,
                        middle - half * 1.5,
                    ),
                    upper=middle + half * 1.5,
                )

                variants[2][1]["grids"] = max(
                    2,
                    int(settings["grids"]) // 2,
                )

            with st.spinner(
                "Загружаю историю и считаю..."
            ):
                frame = history_prices(
                    coin,
                    market,
                    days,
                    int(time.time() // 3600) * HOUR,
                )

                rows = []
                curves = {}

                for label, variant in variants:
                    result = simulate(
                        frame,
                        variant,
                        strategy,
                        direction,
                        market,
                        fee,
                    )

                    rows.append({
                        "Вариант": label,
                        "Доходность %": result["roi"],
                        "Результат USDT": result["pnl"],
                        "Просадка %": result["dd"],
                        "Циклы/лоты": result["cycles"],
                        "Комиссии USDT": result["fees"],
                        "Открытый PnL": result["floating"],
                        "Капитал исчерпан": result["halted"],
                        "Параметры": json.dumps(
                            variant,
                            ensure_ascii=False,
                        ),
                    })

                    curves[label] = (
                        result["curve"]
                        + [np.nan]
                        * (
                            len(frame)
                            - len(result["curve"])
                        )
                    )

                st.session_state[
                    strategy + "test_result"
                ] = dict(
                    rows=rows,
                    curves=pd.DataFrame(
                        curves,
                        index=frame.time,
                    ),
                    description=(
                        f"{coin} · {market} · "
                        f"{direction} · "
                        f"{frame.time.iloc[0]} — "
                        f"{frame.time.iloc[-1]} · "
                        f"{len(frame)} свечей"
                    ),
                )

        result = st.session_state.get(
            strategy + "test_result"
        )

        if result:
            st.caption(
                "Последний расчёт: "
                + result["description"]
            )

            table(
                pd.DataFrame(
                    result["rows"]
                )
            )

            st.line_chart(
                result["curves"]
            )

        st.caption(
            "Пересчитывай после изменения полей. "
            "Результат включает открытую позицию. "
            "Модель использует закрытия 1H, "
            "а не реальные исполнения. "
            "Futures Grid — приближённая модель "
            "пересечений уровней без стартовой позиции, "
            "не копия OKX. "
            "Нет funding, ликвидации, MMR, "
            "проскальзывания и внутрисвечных касаний. "
            "Стопы, резерв и лимит убытка "
            "в тесте не исполняются. "
            "Это не прогноз и не выбор "
            "гарантированно лучшего варианта."
        )


# =========================================================
# CREATE OR ADD BOT
# =========================================================

def creator(strategy):
    task = st.radio(
        "Задача",
        [
            "Подготовить новый",
            "Добавить уже работающий",
        ],
        horizontal=True,
        key=strategy + "task",
    )

    name = st.text_input(
        "Название",
        value="Мой " + strategy,
        key=strategy + "name",
    )

    coin = st.text_input(
        "Монета",
        key=strategy + "coin",
        value=(
            None
            if strategy + "coin" in st.session_state
            else "BTC"
        ),
    ).strip().upper()

    market = st.selectbox(
        "Рынок",
        ["SWAP", "SPOT"],
        key=strategy + "market",
    )

    direction = st.radio(
        "Направление",
        (
            ["Long", "Short"]
            if strategy == "DCA"
            else ["Long", "Short", "Neutral"]
        ),
        horizontal=True,
        key=strategy + "direction",
    )

    if (
        market == "SPOT"
        and direction != "Long"
    ):
        st.warning(
            "Для Spot выбери Long."
        )
        return

    margin = number(
        "Базовая маржа / капитал Spot, USDT",
        100,
        strategy + "margin",
        0.01,
    )

    settings = dict(
        base_margin=margin,
    )

    if strategy == "DCA":
        settings["entry"] = number(
            "Цена первого входа",
            0,
            strategy + "entry",
        )

        settings["tp"] = number(
            "Тейк: движение цены от средней, % "
            "(не ROI маржи)",
            1.5,
            strategy + "tp",
            0.01,
            99,
        )

    else:
        settings["entry"] = 0.0

        settings["lower"] = number(
            "Нижняя граница — точная цена",
            0,
            strategy + "lower",
        )

        settings["upper"] = number(
            "Верхняя граница — точная цена",
            0,
            strategy + "upper",
        )

        settings["grids"] = number(
            "Количество интервалов",
            10,
            strategy + "grids",
            2,
            200,
            integer=True,
        )

    with st.expander(
        "Расширенные настройки"
    ):
        settings["leverage"] = number(
            "Плечо",
            3 if market == "SWAP" else 1,
            strategy + "leverage",
            1,
            100,
        )

        settings["reserve"] = number(
            "Отдельный резерв маржи, USDT",
            50,
            strategy + "reserve",
        )

        settings["total_budget"] = (
            margin + settings["reserve"]
        )

        if strategy == "DCA":
            settings["step"] = number(
                "Шаг СО от первого входа, %",
                2,
                strategy + "step",
                0.01,
                50,
            )

            settings["so_count"] = number(
                "Количество СО",
                4,
                strategy + "count",
                0,
                30,
                integer=True,
            )

            settings["base_amount"] = number(
                "Номинал первого ордера, USDT",
                10,
                strategy + "base",
                0.01,
            )

            settings["first_so"] = number(
                "Номинал первого СО, USDT",
                10,
                strategy + "first",
                0.01,
            )

            settings["mart"] = number(
                "Множитель объёма следующих СО",
                1.2,
                strategy + "mart",
                1,
                3,
            )

        else:
            settings["target_price"] = number(
                "Целевая цена завершения; 0 = нет",
                0,
                strategy + "target",
            )

        settings["stop_price"] = number(
            "Сигнальная стоп-цена Long/Short; "
            "0 = нет",
            0,
            strategy + "stop",
        )

        settings["max_loss"] = number(
            "Лимит убытка открытой позиции, USDT; "
            "0 = нет",
            0,
            strategy + "loss",
        )

        settings["danger_pct"] = number(
            "Неблагоприятное движение "
            "для зоны внимания, %",
            3,
            strategy + "danger",
            0.1,
            100,
        )

        settings["stale_hours"] = number(
            "Сверка позиции устаревает через часов",
            6,
            strategy + "stale",
            0.1,
            168,
        )

        settings["liq_warn"] = number(
            "Предупреждение у введённой "
            "ликвидации, %",
            10,
            strategy + "liqwarn",
            0.1,
            100,
        )

        st.caption(
            "Сигнальный стоп — не биржевой ордер. "
            "Для Neutral односторонняя стоп-цена "
            "не оценивается. "
            "Добавление маржи не устраняет убыток."
        )

    valid = (
        bool(name.strip())
        and coin.isalnum()
        and not (
            market == "SPOT"
            and settings["leverage"] != 1
        )
    )

    if strategy == "DCA":
        try:
            plan = dca_plan(
                settings,
                direction,
            )

            with st.expander(
                "План ордеров"
            ):
                table(
                    pd.DataFrame(plan)
                )

                required = (
                    plan[-1]["Всего номинал"]
                    / settings["leverage"]
                )

                st.caption(
                    "Маржа на все ордера по модели: "
                    f"{required:.2f} USDT, "
                    "без комиссий."
                )

            valid = (
                valid
                and plan[-1]["Всего номинал"]
                / settings["leverage"]
                < margin
            )

        except ValueError as error:
            valid = False
            st.info(str(error))

    else:
        valid = (
            valid
            and 0
            < settings["lower"]
            < settings["upper"]
        )

        if valid:
            st.line_chart(
                pd.DataFrame({
                    "Уровни Grid": np.linspace(
                        settings["lower"],
                        settings["upper"],
                        int(settings["grids"]) + 1,
                    ),
                })
            )

    if st.button(
        "Сохранить и открыть карточку",
        disabled=not valid or not STORAGE,
        key=strategy + "save",
        use_container_width=True,
    ):
        quote(
            coin,
            market,
        )

        bot = dict(
            id=str(uuid.uuid4()),
            name=name.strip(),
            coin=coin,
            market=market,
            strategy=strategy,
            direction=direction,
            settings=settings,
            position={},
            lifecycle="Черновик",
            created_at=now(),
        )

        save_bot(
            bot,
            "Создана карточка",
            (
                "Добавлен работающий бот: "
                "нужна сверка позиции."
                if task == "Добавить уже работающий"
                else "План до запуска."
            ),
        )

        move(
            strategy,
            focus=bot["id"],
        )

    if not STORAGE:
        st.warning(
            "Сохранение заблокировано до подключения "
            "хранилища в Настройках. "
            "План не будет выдан за сохранённый "
            "только в памяти."
        )

    backtest(
        strategy,
        coin,
        market,
        direction,
        settings,
        valid,
    )


# =========================================================
# POSITION ASSESSMENT
# =========================================================

def assess(bot, price):
    settings = bot["settings"]
    position = bot.get("position", {})
    direction = bot["direction"]

    realized = (
        num(
            position.get(
                "realized_pnl",
                settings.get("realized_pnl"),
            )
        )
        if bot["strategy"] == "DCA"
        else 0.0
    )

    result = dict(
        title="Нужна сверка",
        reason="",
        severity="info",
        pnl=None,
        floating=None,
        realized=realized,
        tp=None,
        next_so=None,
        liq_distance=None,
        reserve=max(
            0,
            num(settings["total_budget"])
            - num(
                position.get("base_margin"),
                num(settings["base_margin"]),
            )
            - num(
                position.get("added_margin")
            ),
        ),
    )

    if bot.get("lifecycle") != "Работает":
        result.update(
            title=(
                "План сохранён"
                if bot.get("lifecycle") != "Закрыт"
                else "Бот завершён"
            ),
            reason=(
                "После запуска внеси фактическую "
                "позицию с OKX."
                if bot.get("lifecycle") != "Закрыт"
                else "История сохранена. "
                "Статус отмечен пользователем."
            ),
        )

        return result

    if price is None:
        result.update(
            title="Нет свежей рыночной цены",
            reason=(
                "Обнови данные. "
                "Расчёт по нулевой цене отключён."
            ),
        )

        return result

    stop = num(
        settings.get("stop_price")
    )

    if (
        stop > 0
        and side(direction)
        and side(direction) * (price - stop) <= 0
    ):
        result.update(
            title="Достигнута стоп-цена плана",
            reason=(
                "Срочно сверь текущую позицию на OKX "
                "и выполни выход, предусмотренный планом. "
                "Приложение ордер не отправляло; "
                "сохранённые данные позиции "
                "могут быть устаревшими."
            ),
            severity="error",
        )

        return result

    if age(
        position.get("last_check")
    ) > num(
        settings["stale_hours"],
        6,
    ):
        result.update(
            title="Обнови позицию с OKX",
            reason=(
                "Последняя сверка устарела "
                "или ещё не выполнена. "
                "Не выдаём уверенный совет "
                "держать или закрывать."
            ),
        )

        return result

    if direction == "Neutral":
        inside = (
            num(settings["lower"])
            <= price
            <= num(settings["upper"])
        )

        result.update(
            title=(
                "Цена внутри диапазона"
                if inside
                else "Цена вышла из диапазона Grid"
            ),
            reason=(
                "Проверь Total PnL, остаточные позиции "
                "и ордера на OKX. "
                "Суммарный PnL Neutral "
                "здесь не рассчитывается."
            ),
            severity=(
                "info"
                if inside
                else "warning"
            ),
        )

        return result

    quantity = num(
        position.get("volume")
    )

    average = num(
        position.get("avg_price")
    )

    if quantity <= 0:
        result.update(
            title="По сверке открытой позиции нет",
            reason=(
                "Проверь, ожидает ли бот "
                "следующий цикл."
            ),
            floating=0.0,
            pnl=(
                realized
                if bot["strategy"] == "DCA"
                else None
            ),
        )

        return result

    if average <= 0:
        result["reason"] = (
            "Нужна фактическая средняя цена."
        )

        return result

    floating = (
        side(direction)
        * quantity
        * (price - average)
    )

    result.update(
        floating=floating,
        pnl=floating + realized,
    )

    liquidation = num(
        position.get("liq_price")
    )

    if liquidation > 0:
        result["liq_distance"] = (
            side(direction)
            * (price - liquidation)
            / price
            * 100
        )

    if (
        num(settings["max_loss"]) > 0
        and floating
        <= -num(settings["max_loss"])
    ):
        result.update(
            title=(
                "Достигнут лимит убытка "
                "открытой позиции"
            ),
            reason=(
                "По плану требуется проверить "
                "ручной выход. "
                "Прибыль закрытых циклов "
                "не отменяет этот лимит."
            ),
            severity="error",
        )

        return result

    if (
        result["liq_distance"] is not None
        and result["liq_distance"]
        <= num(settings["liq_warn"], 10)
    ):
        result.update(
            title=(
                "Цена близко к введённой "
                "ликвидации"
            ),
            reason=(
                "Срочно проверь риск на OKX. "
                "Здесь последняя цена "
                "и ручная ликвидационная цена, "
                "не биржевой Mark Price/MMR."
            ),
            severity="error",
        )

        return result

    if bot["strategy"] == "DCA":
        result["tp"] = average * (
            1
            + side(direction)
            * num(settings["tp"])
            / 100
        )

        plan = dca_plan(
            settings,
            direction,
        )

        executed = max(
            0,
            min(
                int(
                    position.get(
                        "executed_so",
                        0,
                    )
                ),
                len(plan) - 1,
            ),
        )

        if executed + 1 < len(plan):
            result["next_so"] = (
                plan[executed + 1]["Цена"]
            )

    else:
        result["tp"] = (
            num(settings["target_price"])
            or None
        )

    if (
        result["tp"]
        and side(direction)
        * (price - result["tp"])
        >= 0
    ):
        result.update(
            title="Достигнут модельный тейк",
            reason=(
                "Проверь исполнение на OKX. "
                "TP текущего цикла DCA "
                "не означает остановку новых "
                "циклов или всего бота."
            ),
            severity="success",
        )

    elif (
        bot["strategy"] == "Grid"
        and not (
            num(settings["lower"])
            <= price
            <= num(settings["upper"])
        )
    ):
        result.update(
            title="Цена вне диапазона Grid",
            reason=(
                "Проверь ордера и остаточную позицию. "
                "Выход из диапазона — "
                "не подтверждение закрытия."
            ),
            severity="warning",
        )

    elif max(
        0,
        -side(direction)
        * (price / average - 1)
        * 100,
    ) >= num(
        settings["danger_pct"],
        3,
    ):
        result.update(
            title="Цена в заданной зоне внимания",
            reason=(
                "Движение против позиции достигло "
                "твоего порога. "
                "Проверь уменьшение риска "
                "или выход по плану; "
                "это не доказательство "
                "будущего разворота."
            ),
            severity="warning",
        )

    elif (
        result["next_so"]
        and side(direction)
        * (price - result["next_so"])
        <= 0
    ):
        result.update(
            title="Цена достигла следующего СО",
            reason=(
                "Проверь исполнение, объём "
                "и среднюю цену. "
                "Касание уровня само по себе "
                "не подтверждает исполнение."
            ),
        )

    elif floating > 0:
        result.update(
            title=(
                "Рынок благоприятнее "
                "твоей средней"
            ),
            reason=(
                "Открытая позиция в плюсе. "
                "По сохранённому плану контролируй "
                "TP и условия риска. "
                "Одно наблюдение не подтверждает "
                "рост PnL во времени."
            ),
            severity="success",
        )

    else:
        result.update(
            title="Контроль по плану",
            reason=(
                "Жёсткие условия выхода "
                "не сработали. "
                "Следи за позицией; "
                "это не обещание отскока."
            ),
        )

    if result["reserve"] <= 0:
        result["reason"] += (
            " Резерв маржи исчерпан; "
            "дальнейшие добавления вне плана."
        )

    return result


# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(text):
    token = str(
        secret("TELEGRAM_TOKEN")
    )

    chat = str(
        secret("TELEGRAM_CHAT_ID")
    )

    try:
        token = token or str(
            st.secrets["telegram"]["token"]
        )

        chat = chat or str(
            st.secrets["telegram"]["chat_id"]
        )

    except Exception:
        pass

    token = token or st.session_state.get(
        "tg_token",
        "",
    )

    chat = chat or st.session_state.get(
        "tg_chat",
        "",
    )

    if not token or not chat:
        raise ValueError(
            "Настрой Telegram в Secrets "
            "или в разделе Настройки."
        )

    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat,
            "text": text[:4000],
        },
        timeout=12,
    )

    response.raise_for_status()

    if not response.json().get("ok"):
        raise ValueError(
            "Telegram не подтвердил отправку."
        )


# =========================================================
# BOT CARD
# =========================================================

def bot_card(bot, compact=False):
    identifier = bot["id"]
    position = bot.get("position", {})
    settings = bot["settings"]

    try:
        price = quote(
            bot["coin"],
            bot["market"],
        )["price"]

    except Exception:
        price = None

    state = assess(
        bot,
        price,
    )

    with st.container(border=True):
        st.subheader(
            f"{bot['coin']} · "
            f"{bot['strategy']} "
            f"{bot['direction']}"
        )

        st.caption(
            bot["name"]
            + " · "
            + bot.get(
                "lifecycle",
                "Черновик",
            )
            + " · "
            + bot["market"]
        )

        columns = st.columns(3)

        columns[0].metric(
            "Цена",
            fmt(price, 6),
        )

        columns[1].metric(
            (
                "Общий PnL ≈ USDT"
                if bot["strategy"] == "DCA"
                else "Открытый PnL ≈ USDT"
            ),
            fmt(state["pnl"]),
        )

        columns[2].metric(
            "Резерв маржи USDT",
            fmt(state["reserve"]),
        )

        st.markdown(
            "### Анализ текущей ситуации"
        )

        getattr(
            st,
            state["severity"],
        )(
            state["title"]
            + ". "
            + state["reason"]
        )

        if bot["strategy"] == "DCA":
            st.caption(
                f"Закрытые циклы: "
                f"{fmt(state['realized'])} USDT · "
                f"Открытая позиция: "
                f"{fmt(state['floating'])} USDT"
            )

        st.caption(
            "Последняя сверка UTC: "
            + (
                position.get("last_check")
                or "не выполнена"
            )
        )

        if compact:
            if st.button(
                "Открыть карточку",
                key=identifier + "open",
            ):
                move(
                    bot["strategy"],
                    focus=identifier,
                )

            return

        with st.expander(
            "Обновить фактическую позицию с OKX",
            expanded=not position.get("last_check"),
        ):
            with st.form(
                identifier + "position"
            ):
                states = [
                    "Черновик",
                    "Работает",
                    "Закрыт",
                ]

                lifecycle = st.selectbox(
                    "Состояние",
                    states,
                    index=states.index(
                        bot.get(
                            "lifecycle",
                            "Черновик",
                        )
                    ),
                )

                quantity = number(
                    "Объём в базовой монете, "
                    "НЕ контракты; 0 = нет позиции",
                    num(position.get("volume")),
                    identifier + "qty",
                )

                average = number(
                    "Фактическая средняя цена",
                    num(position.get("avg_price")),
                    identifier + "avg",
                )

                if bot["strategy"] == "DCA":
                    realized = number(
                        "Арбитражный PnL "
                        "закрытых циклов, USDT",
                        num(
                            position.get(
                                "realized_pnl"
                            )
                        ),
                        identifier + "realized",
                        minimum=None,
                    )

                    st.caption(
                        "Накопленная прибыль закрытых циклов, "
                        "не Total PnL. "
                        "Сохранение заменяет значение, "
                        "а не прибавляет его. "
                        "Отрицательное число разрешено."
                    )

                else:
                    realized = 0.0

                liquidation = number(
                    "Ликвидационная цена с OKX; "
                    "0 = неизвестна",
                    num(position.get("liq_price")),
                    identifier + "liq",
                )

                base_margin = number(
                    "Базовая выделенная маржа",
                    num(
                        position.get("base_margin"),
                        num(settings["base_margin"]),
                    ),
                    identifier + "margin",
                )

                added = number(
                    "Всего добавлено маржи",
                    num(
                        position.get(
                            "added_margin"
                        )
                    ),
                    identifier + "added",
                )

                maximum = (
                    int(
                        settings.get(
                            "so_count",
                            0,
                        )
                    )
                    if bot["strategy"] == "DCA"
                    else 0
                )

                if maximum > 0:
                    executed = number(
                        "Исполнено СО текущего цикла",
                        min(
                            int(
                                position.get(
                                    "executed_so",
                                    0,
                                )
                            ),
                            maximum,
                        ),
                        identifier + "executed",
                        0,
                        maximum,
                        integer=True,
                    )
                else:
                    executed = 0

                confirmed = st.checkbox(
                    "Сверил значения с OKX"
                )

                if st.form_submit_button(
                    "Сохранить позицию"
                ):
                    invalid = (
                        not confirmed
                        or (
                            quantity > 0
                            and bot["direction"] != "Neutral"
                            and average <= 0
                        )
                        or (
                            lifecycle == "Закрыт"
                            and quantity > 0
                        )
                    )

                    if invalid:
                        st.error(
                            "Подтверди сверку. "
                            "Для ненулевой позиции нужна средняя; "
                            "завершённый бот должен "
                            "иметь нулевой остаток."
                        )

                    else:
                        bot["position"] = dict(
                            volume=quantity,
                            avg_price=average,
                            realized_pnl=realized,
                            liq_price=liquidation,
                            base_margin=base_margin,
                            added_margin=added,
                            executed_so=int(executed),
                            last_check=now(),
                        )

                        bot["lifecycle"] = lifecycle

                        save_bot(
                            bot,
                            "Обновлена позиция",
                            "Пользователь сверил значения "
                            "на OKX.",
                        )

                        st.rerun()

        with st.expander(
            "Уровни и настройки"
        ):
            values = [
                (
                    "tp",
                    "Модельный TP",
                ),
                (
                    "next_so",
                    "Следующий СО",
                ),
                (
                    "liq_distance",
                    "До введённой ликвидации, %",
                ),
            ]

            for key, label in values:
                st.write(
                    label
                    + ": "
                    + fmt(
                        state[key],
                        6
                        if key != "liq_distance"
                        else 2,
                    )
                )

            table(
                pd.DataFrame([
                    {
                        "Параметр": key,
                        "Значение": str(value),
                    }
                    for key, value
                    in settings.items()
                ])
            )

            if (
                num(position.get("volume")) > 0
                and num(position.get("avg_price")) > 0
                and side(bot["direction"])
                and price
            ):
                prices = np.linspace(
                    min(
                        price,
                        position["avg_price"],
                    ) * 0.85,
                    max(
                        price,
                        position["avg_price"],
                    ) * 1.15,
                    120,
                )

                pnl = (
                    side(bot["direction"])
                    * position["volume"]
                    * (
                        prices
                        - position["avg_price"]
                    )
                )

                figure = go.Figure(
                    go.Scatter(
                        x=prices,
                        y=pnl,
                        name="Открытый PnL",
                        line=dict(
                            color="#00ff9d",
                        ),
                    )
                )

                figure.add_hline(
                    y=0,
                    line_dash="dot",
                )

                figure.update_layout(
                    template="plotly_dark",
                    title=(
                        "Профиль открытой позиции "
                        "без комиссий/funding"
                    ),
                    height=330,
                )

                st.plotly_chart(
                    figure,
                    use_container_width=True,
                )

        with st.form(
            identifier + "decision"
        ):
            decision = st.radio(
                "Моё решение",
                [
                    "Не трогать",
                    "Проверить на OKX",
                    "Выход по плану",
                ],
                horizontal=True,
            )

            note = st.text_input(
                "Причина решения"
            )

            if st.form_submit_button(
                "Записать решение"
            ):
                bot["decision"] = (
                    decision
                    + " · "
                    + now()
                    + " · "
                    + note
                )

                save_bot(
                    bot,
                    "Решение пользователя",
                    bot["decision"],
                )

                st.rerun()

        if bot.get("decision"):
            st.caption(
                bot["decision"]
            )

        if st.button(
            "Отправить отчёт в Telegram",
            key=identifier + "tg",
        ):
            message = (
                f"{bot['name']}\n"
                f"{bot['coin']} · "
                f"{bot['strategy']} · "
                f"{bot['direction']}\n\n"
                f"{state['title']}\n"
                f"{state['reason']}\n\n"
                f"Цена: {fmt(price, 6)}\n"
                f"PnL ≈ {fmt(state['pnl'])} USDT\n"
                f"Закрытые циклы: "
                f"{fmt(state['realized'])} USDT\n"
                f"Открытый PnL ≈ "
                f"{fmt(state['floating'])} USDT\n"
                f"Сверка: "
                f"{position.get('last_check') or 'нет'}\n\n"
                "Торговая команда не отправлялась."
            )

            send_telegram(
                message
            )

            st.success(
                "Отчёт отправлен."
            )

        st.caption(
            "Расчёты приблизительные. "
            "Комиссии и funding открытой позиции "
            "отдельно не учтены. "
            "«Не трогать» не скрывает стоп "
            "и предупреждения. "
            "Торговая команда не отправлялась."
        )


def cards(bots, compact=False):
    for bot in bots:
        try:
            bot_card(
                bot,
                compact,
            )

        except Exception as error:
            st.error(
                f"Не удалось открыть "
                f"«{bot.get('name', 'Бот')}»: "
                f"{type(error).__name__}. "
                "Карточка не удалена. "
                "Обнови страницу "
                "и проверь настройки."
            )


def actions(prefix):
    columns = st.columns(3)

    if columns[0].button(
        "ЛОНГ · DCA",
        key="action_" + prefix + "_long",
        use_container_width=True,
    ):
        move(
            "DCA",
            "Long",
            mode="Подготовить бота",
        )

    if columns[1].button(
        "ШОРТ · DCA",
        key="action_" + prefix + "_short",
        use_container_width=True,
    ):
        move(
            "DCA",
            "Short",
            mode="Подготовить бота",
        )

    if columns[2].button(
        "НЕЙТРАЛЬНО · GRID",
        key="action_" + prefix + "_neutral",
        use_container_width=True,
    ):
        move(
            "Grid",
            "Neutral",
            mode="Подготовить бота",
        )


# =========================================================
# IMPORT / EXPORT
# =========================================================

def import_bots(raws, events=None):
    if (
        not isinstance(raws, list)
        or len(raws) > 1000
    ):
        raise ValueError(
            "В копии должен быть список bots, "
            "максимум 1000 карточек."
        )

    prepared = []

    for raw in raws:
        bot = normalize(raw)

        bot.pop(
            "_revision",
            None,
        )

        bot.update(
            id=str(uuid.uuid4()),
            lifecycle="Черновик",
            updated_at=now(),
        )

        bot["position"]["last_check"] = ""

        if events:
            bot["imported_journal"] = events

        prepared.append(bot)

    with database() as connection:
        for bot in prepared:
            sql(
                connection,
                """
                INSERT INTO terminal_bots
                VALUES (?, ?, ?)
                """,
                (
                    bot["id"],
                    json.dumps(
                        bot,
                        ensure_ascii=False,
                        allow_nan=False,
                    ),
                    1,
                ),
            )

            record(
                connection,
                bot["id"],
                "Импорт",
                "Добавлена копия. Нужна сверка; "
                "существующие карточки не заменены.",
            )

    return len(prepared)


# =========================================================
# SETTINGS
# =========================================================

def settings_page(bots):
    panel(
        "Настройки",
        "Пароль, постоянное хранилище, "
        "резервные копии и Telegram.",
    )

    st.write(
        "Пароль: включён через APP_PASSWORD "
        "в Secrets."
    )

    storage_text = (
        "внешний PostgreSQL"
        if DB_URL
        else "локальный SQLite (явно разрешён)"
        if LOCAL
        else "НЕ ПОДКЛЮЧЕНО — сохранение заблокировано"
    )

    st.write(
        "Хранилище: " + storage_text
    )

    if LOCAL:
        st.warning(
            "Локальный файл на Streamlit Cloud "
            "может исчезнуть при пересоздании сервера. "
            "Для постоянного внешнего хранения "
            "нужен DATABASE_URL."
        )

    if STORAGE:
        backup = dict(
            version=14,
            created_at=now(),
            bots=[
                {
                    key: value
                    for key, value in bot.items()
                    if key != "_revision"
                }
                for bot in bots
            ],
            events=history().to_dict(
                "records"
            ),
        )

        st.download_button(
            "Скачать резервную копию JSON",
            json.dumps(
                backup,
                ensure_ascii=False,
                indent=2,
            ),
            "okx_backup.json",
            "application/json",
        )

        uploaded = st.file_uploader(
            "Восстановить JSON",
            type=["json"],
        )

        confirm = st.checkbox(
            "Добавить копии с новыми ID, "
            "не заменяя существующие карточки"
        )

        if st.button(
            "Восстановить",
            disabled=(
                uploaded is None
                or not confirm
            ),
        ):
            if uploaded.size > 5_000_000:
                raise ValueError(
                    "Файл больше 5 MB."
                )

            source = json.loads(
                uploaded.getvalue()
            )

            if not isinstance(
                source,
                dict,
            ):
                raise ValueError(
                    "Неверный формат копии."
                )

            count = import_bots(
                source.get("bots"),
                source.get("events"),
            )

            st.success(
                f"Добавлено: {count}. "
                "Открой карточки "
                "и обнови позиции."
            )

        with st.expander(
            "Перенести оставшийся локальный файл"
        ):
            st.caption(
                "Только если старый файл ещё "
                "находится на этом сервере. "
                "Повторный перенос создаёт копии; "
                "исходник не удаляется."
            )

            if st.button(
                "Импортировать локальные карточки"
            ):
                if not os.path.isfile(
                    DB_FILE
                ):
                    raise ValueError(
                        "Старый локальный файл "
                        "не найден."
                    )

                connection = sqlite3.connect(
                    DB_FILE
                )

                try:
                    connection.row_factory = sqlite3.Row

                    tables = {
                        row[0]
                        for row in connection.execute(
                            "SELECT name "
                            "FROM sqlite_master "
                            "WHERE type='table'"
                        )
                    }

                    if "terminal_bots" in tables:
                        raw = [
                            json.loads(row[0])
                            for row in connection.execute(
                                "SELECT document "
                                "FROM terminal_bots"
                            )
                        ]

                    elif "bots" in tables:
                        raw = [
                            dict(row)
                            for row in connection.execute(
                                "SELECT * FROM bots"
                            )
                        ]

                    else:
                        raise ValueError(
                            "Таблицы карточек "
                            "не найдены."
                        )

                finally:
                    connection.close()

                count = import_bots(
                    raw
                )

                st.success(
                    f"Добавлено копий: {count}. "
                    "Требуется сверка."
                )

    with st.expander(
        "Telegram"
    ):
        st.text_input(
            "Token, если не задан в Secrets",
            type="password",
            key="tg_token",
        )

        st.text_input(
            "Chat ID, если не задан в Secrets",
            key="tg_chat",
        )

        if st.button(
            "Отправить тест Telegram"
        ):
            send_telegram(
                "OKX Terminal Pro: "
                "соединение подтверждено. "
                "Торговые команды не включены."
            )

            st.success(
                "Тестовое сообщение отправлено."
            )

    with st.expander(
        "Пример Streamlit Secrets",
        expanded=not STORAGE,
    ):
        st.code(
            '''
APP_PASSWORD = "ваш-длинный-пароль"

# Реальная строка подключения созданной внешней базы:
DATABASE_URL = "postgresql://user:password@host/database?sslmode=require"

# Необязательно:
TELEGRAM_TOKEN = "токен"
TELEGRAM_CHAT_ID = "chat-id"
'''.strip(),
            language="toml",
        )

        st.caption(
            "Если DATABASE_URL уже настроен — "
            "не заменяй его примером. "
            "Для локального запуска вместо DATABASE_URL "
            "можно явно разрешить "
            "ALLOW_LOCAL_STORAGE = true. "
            "На облаке это не решает "
            "проблему сохранности. "
            "Секреты не публикуй в GitHub."
        )

    st.caption(
        "Telegram отправляется по кнопке. "
        "Независимый фоновый мониторинг не запущен. "
        "Старые исчезнувшие данные "
        "не восстанавливаются без базы "
        "или резервной копии."
    )


# =========================================================
# MAIN APPLICATION
# =========================================================

def main():
    apply_route()
    design()
    login()

    with st.sidebar:
        st.title(
            "OKX Terminal"
        )

        page = st.radio(
            "Раздел",
            PAGES,
            key="page",
            label_visibility="collapsed",
        )

        if st.button(
            "Обновить цены"
        ):
            quote.clear()
            api.clear()
            st.rerun()

        if st.button(
            "Выйти из терминала"
        ):
            st.session_state[
                "_authenticated"
            ] = False

            st.rerun()

        st.caption(
            "Ручное сопровождение. "
            "Торговые команды не отправляются."
        )

    bots = []

    if STORAGE:
        try:
            init_database()
            bots = load_bots()

        except Exception:
            st.error(
                "Не удалось открыть хранилище. "
                "Не меняй DATABASE_URL "
                "на случайную базу "
                "и не удаляй данные. "
                "Проверь подключение, требования "
                "и журнал запуска Streamlit."
            )

            st.stop()

    else:
        st.warning(
            "Постоянное хранилище не подключено. "
            "Просмотр рынка и бэктест доступны; "
            "сохранение карточек заблокировано. "
            "Открой Настройки."
        )

    try:
        if page == "Главная":
            panel(
                "Твои боты — на одном экране",
                "Работающие позиции, сохранённые планы "
                "и действия по правилам.",
            )

            try:
                change = quote(
                    "BTC",
                    "SPOT",
                )["change"]

                if (
                    change is not None
                    and change < -2
                ):
                    st.info(
                        f"BTC за 24 часа: {change:.2f}%. "
                        "Проверь риск Long "
                        "и план фиксации Short. "
                        "Само падение BTC "
                        "не является причиной "
                        "автоматически закрывать шорт."
                    )

            except Exception:
                st.caption(
                    "Обзор BTC временно недоступен."
                )

            active = [
                bot for bot in bots
                if bot.get("lifecycle") == "Работает"
            ]

            drafts = [
                bot for bot in bots
                if bot.get("lifecycle") == "Черновик"
            ]

            columns = st.columns(3)

            columns[0].metric(
                "В работе",
                len(active),
            )

            columns[1].metric(
                "Планы",
                len(drafts),
            )

            columns[2].metric(
                "Завершены",
                sum(
                    bot.get("lifecycle") == "Закрыт"
                    for bot in bots
                ),
            )

            actions(
                "home"
            )

            cards(
                active[:10],
                compact=True,
            )

            if drafts:
                st.subheader(
                    "Сохранённые планы"
                )

                for bot in drafts[:6]:
                    with st.container(
                        border=True
                    ):
                        st.write(
                            f"{bot['name']} · "
                            f"{bot['coin']} · "
                            f"{bot['strategy']} "
                            f"{bot['direction']}"
                        )

                        if st.button(
                            "Открыть план",
                            key=bot["id"] + "draft",
                        ):
                            move(
                                bot["strategy"],
                                focus=bot["id"],
                            )

            if not bots:
                panel(
                    "Добавь первого бота",
                    "Сохрани план или перенеси "
                    "уже работающего бота с OKX. "
                    "После сохранения внеси "
                    "фактическую позицию.",
                )

        elif page == "Сканер":
            scanner()

        elif page in ("DCA", "Grid"):
            panel(
                page,
                "Мои боты, добавление работающего бота "
                "и подготовка нового плана.",
            )

            mode = st.radio(
                "Режим",
                [
                    "Мои боты",
                    "Подготовить бота",
                ],
                horizontal=True,
                key=page + "mode",
            )

            if mode == "Подготовить бота":
                creator(page)

            else:
                selected = [
                    bot for bot in bots
                    if bot["strategy"] == page
                ]

                selected.sort(
                    key=lambda bot: (
                        bot["id"]
                        != st.session_state.get("focus")
                    )
                )

                if selected:
                    cards(
                        selected
                    )

                else:
                    st.info(
                        "Пока нет сохранённых "
                        "карточек этого типа."
                    )

                    if st.button(
                        "Добавить " + page
                    ):
                        move(
                            page,
                            "Long"
                            if page == "DCA"
                            else "Neutral",
                            mode="Подготовить бота",
                        )

        elif page == "Открытая позиция":
            panel(
                "Контроль позиций",
                "Свежесть данных, текущая цена "
                "и условия вмешательства.",
            )

            selected = [
                bot for bot in bots
                if bot.get("lifecycle") == "Работает"
            ]

            if selected:
                cards(
                    selected
                )

            else:
                st.info(
                    "Работающих карточек пока нет. "
                    "Добавь бота в DCA/Grid "
                    "и сверь его позицию с OKX."
                )

                actions(
                    "positions"
                )

        elif page == "Журнал":
            panel(
                "Журнал решений",
                "Планы, ручные сверки "
                "и решения. Время UTC.",
            )

            frame = history()

            if frame.empty:
                st.info(
                    "Записи появятся после "
                    "сохранения карточки "
                    "или решения."
                )

            else:
                table(
                    frame
                )

                st.download_button(
                    "Скачать журнал CSV",
                    frame.to_csv(
                        index=False
                    ).encode("utf-8-sig"),
                    "journal.csv",
                    "text/csv",
                )

            st.caption(
                "Повторные снимки одной позиции "
                "не суммируются как прибыль."
            )

        else:
            settings_page(
                bots
            )

    except Exception as error:
        if isinstance(
            error,
            (
                ValueError,
                requests.RequestException,
            ),
        ):
            st.error(
                str(error)
            )

        else:
            st.error(
                "Действие не завершено. "
                "Тип ошибки: "
                + type(error).__name__
                + ". Проверь журнал запуска. "
                "Не удаляй базу "
                "и резервные копии."
            )


main()
