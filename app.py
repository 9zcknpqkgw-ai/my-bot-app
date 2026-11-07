import os
import json
import math
import time
import uuid
import hmac
import html
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


# =========================================================
# CONFIG
# =========================================================

st.set_page_config(
    page_title="OKX Terminal Pro",
    page_icon="📈",
    layout="wide",
)

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

STATES = {
    "Черновик": "План",
    "Работает": "В работе",
    "Закрыт": "Завершён",
}

API = "https://www.okx.com/api/v5"


def secret(key, default=""):
    try:
        return st.secrets.get(
            key,
            os.getenv(key, default),
        )
    except Exception:
        return os.getenv(key, default)


DB_URL = str(secret("DATABASE_URL")).strip()
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
            dt = dt.replace(tzinfo=timezone.utc)

        return max(
            0,
            (
                datetime.now(timezone.utc) - dt
            ).total_seconds() / 3600,
        )
    except (TypeError, ValueError):
        return float("inf")


def short_time(value):
    if not value:
        return "Ещё не обновлялись"

    try:
        return datetime.fromisoformat(value).strftime(
            "%d.%m %H:%M UTC"
        )
    except (TypeError, ValueError):
        return str(value)


def move(page, direction=None, bot_id=None):
    st.session_state["pending"] = page

    if direction:
        st.session_state["preferred"] = direction

    if bot_id:
        st.session_state["focus_bot"] = bot_id

    if page in ("4. DCA", "5. Grid"):
        st.session_state[
            page + "mode"
        ] = "Подготовить бота"

    if page == "3. ИИ-Центр":
        st.session_state["control_strategy"] = "Все"
        st.session_state["control_state"] = "Все"

    st.rerun()


def field(
    label,
    value,
    key,
    minimum=0.0,
    maximum=None,
):
    args = dict(
        label=label,
        value=float(value),
        min_value=float(minimum),
        key=key,
    )

    if maximum is not None:
        args["max_value"] = float(maximum)

    return st.number_input(**args)


def panel(title, text, small=False):
    css = "empty-panel" if small else "hero"

    st.markdown(
        f'<div class="{css}">'
        f'<div class="panel-title">'
        f'{html.escape(title)}'
        '</div>'
        f'<div class="panel-text">'
        f'{html.escape(text)}'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )


def table(df, direction=None):
    if df.empty:
        return

    styled = df.style.set_properties(**{
        "background-color": "#ffffff",
        "color": "#172033",
    })

    if direction in df.columns:
        colors = {
            "Long": "#137333",
            "Short": "#c5223f",
            "Neutral": "#174ea6",
        }

        styled = styled.map(
            lambda value: (
                f"color:{colors.get(str(value), '#172033')};"
                "background-color:#ffffff;"
                "font-weight:700"
            ),
            subset=[direction],
        )

    formats = {
        column: (
            "{:,.6f}"
            if column in ("Цена", "Средняя")
            else "{:,.2f}"
        )
        for column in df.select_dtypes(
            include="number"
        ).columns
    }

    st.dataframe(
        styled.format(
            formats,
            na_rep="—",
        ),
        hide_index=True,
        use_container_width=True,
    )


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
            ellipse at top left,
            #102933 0,
            transparent 45%
        ),
        #070c15;
    color: #edf3ff;
}

.block-container {
    max-width: 1400px;
    padding-top: 1.5rem;
    padding-bottom: 3rem;
}

h1, h2, h3, h4 {
    color: #edf3ff !important;
    letter-spacing: -.03em;
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
}

[data-testid="stSidebar"] {
    background: #0b1320;
    border-right: 1px solid #30445e;
}

[data-testid="stMetric"] {
    background: #142134;
    border: 1px solid #30445e;
    border-radius: 16px;
    padding: 17px;
}

[data-testid="stMetricLabel"] p,
[data-testid="stMetricLabel"] span {
    color: #b6c5da !important;
}

[data-testid="stMetricValue"] div {
    color: #f1f6ff !important;
}

.stButton button,
.stFormSubmitButton button,
.stDownloadButton button {
    background: #fff !important;
    color: #172033 !important;
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

.stButton button:hover {
    background: #eaf1fb !important;
    border-color: #2563eb !important;
}

.stButton button:disabled {
    background: #e5e7eb !important;
    color: #475569 !important;
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

[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea {
    background: #fff !important;
    color: #172033 !important;
    -webkit-text-fill-color: #172033 !important;
}

[data-testid="stNumberInput"] button {
    background: #edf2f7 !important;
    color: #172033 !important;
}

[data-testid="stSelectbox"] [data-baseweb="select"] > div,
[data-testid="stMultiSelect"] [data-baseweb="select"] > div {
    background: #fff !important;
    color: #172033 !important;
}

[data-testid="stSelectbox"] [data-baseweb="select"] span,
[data-testid="stSelectbox"] input,
[data-testid="stMultiSelect"] input {
    color: #172033 !important;
    -webkit-text-fill-color: #172033 !important;
}

[role="listbox"],
[role="option"] {
    background: #fff !important;
    color: #172033 !important;
}

[role="option"]:hover {
    background: #e8f0fe !important;
}

[data-testid="stRadio"] [role="radiogroup"] > label {
    background: #fff !important;
    border: 2px solid #cbd5e1;
    border-radius: 10px;
    padding: 8px 12px !important;
    margin: 3px !important;
}

[data-testid="stRadio"] [role="radiogroup"] > label p {
    color: #172033 !important;
    font-weight: 700 !important;
}

[data-testid="stRadio"] label:has(input:checked) {
    border-color: #2563eb !important;
}

[class*="st-key-dir_DCA_"] [role="radiogroup"] > label:nth-of-type(1) p,
[class*="st-key-dir_Grid_"] [role="radiogroup"] > label:nth-of-type(1) p {
    color: #137333 !important;
}

[class*="st-key-dir_DCA_"] [role="radiogroup"] > label:nth-of-type(2) p,
[class*="st-key-dir_Grid_"] [role="radiogroup"] > label:nth-of-type(2) p {
    color: #c5223f !important;
}

[class*="st-key-dir_Grid_"] [role="radiogroup"] > label:nth-of-type(3) p {
    color: #174ea6 !important;
}

[data-testid="stCheckbox"] p,
[data-testid="stExpander"] summary p {
    color: #edf3ff !important;
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

.hero {
    background: linear-gradient(
        120deg,
        #13343a,
        #161e35
    );
    border: 1px solid #34526b;
    border-radius: 20px;
    padding: 22px;
    margin-bottom: 18px;
}

.empty-panel {
    background: #111d2d;
    border: 1px solid #2d4059;
    border-radius: 18px;
    padding: 24px;
    margin: 12px 0;
}

.panel-title {
    color: #edf3ff;
    font-size: 1.55rem;
    font-weight: 800;
    letter-spacing: -.02em;
}

.panel-text {
    color: #b6c5da;
    line-height: 1.6;
    margin-top: 9px;
    max-width: 850px;
}

.bot-heading {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px;
    margin-bottom: 8px;
}

.bot-title {
    font-size: 1.35rem;
    font-weight: 800;
    color: #edf3ff;
}

.direction {
    background: #fff;
    border-radius: 7px;
    padding: 4px 10px;
    font-size: .8rem;
    font-weight: 800;
}

.lifecycle {
    color: #c8d6e9;
    font-size: .85rem;
}

@media(max-width: 640px) {
    .block-container {
        padding: 1rem;
    }

    .empty-panel,
    .hero {
        padding: 18px;
    }
}
</style>
        """,
        unsafe_allow_html=True,
    )


# =========================================================
# LOGIN
# =========================================================

def login():
    password = str(secret("APP_PASSWORD"))

    if (
        not password
        or st.session_state.get("authenticated")
    ):
        return

    panel(
        "OKX Terminal Pro",
        "Личный торговый кабинет",
    )

    entered = st.text_input(
        "Пароль",
        type="password",
    )

    if st.button("Войти"):
        correct = hmac.compare_digest(
            entered.encode(),
            password.encode(),
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


def query(connection, statement, parameters=()):
    cursor = connection.cursor()

    cursor.execute(
        statement.replace("?", "%s")
        if DB_URL
        else statement,
        parameters,
    )

    return cursor


def init_database():
    with database() as connection:
        query(
            connection,
            """
            CREATE TABLE IF NOT EXISTS terminal_bots (
                id TEXT PRIMARY KEY,
                document TEXT NOT NULL,
                revision INTEGER NOT NULL
            )
            """,
        )

        query(
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


def record(connection, bot_id, title, details):
    query(
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


def load_bots():
    with database() as connection:
        rows = query(
            connection,
            """
            SELECT document, revision
            FROM terminal_bots
            """,
        ).fetchall()

    result = []

    for raw, revision in rows:
        bot = json.loads(raw)
        bot["_revision"] = revision
        bot.setdefault("position", {})
        bot.setdefault("lifecycle", "Черновик")
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

    raw = json.dumps(
        document,
        ensure_ascii=False,
        allow_nan=False,
    )

    with database() as connection:
        if revision is None:
            query(
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
            cursor = query(
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
                    "Карточка обновлена в другой вкладке. "
                    "Обнови страницу перед сохранением."
                )

        record(
            connection,
            document["id"],
            title,
            details,
        )


def history():
    with database() as connection:
        rows = query(
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
# PUBLIC OKX DATA
# =========================================================

def symbol(coin, market):
    return (
        f"{coin}-USDT"
        + ("-SWAP" if market == "SWAP" else "")
    )


def api(path, params):
    request = Request(
        API + path + "?" + urlencode(params),
        headers={"User-Agent": "OKX-Terminal"},
    )

    with urlopen(request, timeout=15) as response:
        data = json.load(response)

    if data.get("code") != "0":
        raise ValueError(
            "OKX не подтвердил запрос."
        )

    return data.get("data", [])


@st.cache_data(ttl=20, show_spinner=False)
def quote(coin, market):
    instrument = symbol(coin, market)

    rows = api(
        "/market/ticker",
        {"instId": instrument},
    )

    row = next(
        (
            item for item in rows
            if item.get("instId") == instrument
        ),
        None,
    )

    if (
        not row
        or num(row.get("last")) <= 0
        or num(row.get("ts")) <= 0
        or time.time() - num(row["ts"]) / 1000 > 180
    ):
        raise ValueError(
            "Свежая цена временно недоступна: "
            + instrument
        )

    price = float(row["last"])

    volume = num(
        row.get("volCcy24h")
    ) * (
        price if market == "SWAP" else 1
    )

    return price, volume


@st.cache_data(ttl=180, show_spinner=False)
def daily(coin, market):
    rows = api(
        "/market/candles",
        {
            "instId": symbol(coin, market),
            "bar": "1D",
            "limit": "120",
        },
    )

    data = [
        [
            int(row[0]),
            *map(float, row[1:5]),
        ]
        for row in rows
        if len(row) >= 9
        and str(row[8]) == "1"
    ]

    if len(data) < 40:
        raise ValueError(
            "Для анализа пока недостаточно "
            "закрытых свечей."
        )

    frame = pd.DataFrame(
        data,
        columns=[
            "ts",
            "open",
            "high",
            "low",
            "close",
        ],
    )

    frame = (
        frame.drop_duplicates("ts")
        .sort_values("ts")
        .reset_index(drop=True)
    )

    frame["time"] = pd.to_datetime(
        frame.ts,
        unit="ms",
        utc=True,
    )

    return frame


@st.cache_data(ttl=300, show_spinner=False)
def candles(coin, market, days, bar):
    cutoff = int(
        (time.time() - days * 86400) * 1000
    )

    result = {}
    after = None
    previous = None

    for _ in range(120):
        params = {
            "instId": symbol(coin, market),
            "bar": bar,
            "limit": "100",
        }

        if after is not None:
            params["after"] = str(after)

        batch = api(
            "/market/history-candles",
            params,
        )

        if not batch:
            break

        oldest = min(
            int(row[0])
            for row in batch
        )

        for row in batch:
            if (
                len(row) >= 9
                and str(row[8]) == "1"
                and int(row[0]) >= cutoff
            ):
                result[int(row[0])] = float(row[4])

        if oldest <= cutoff or oldest == previous:
            break

        previous = oldest
        after = oldest
        time.sleep(0.12)

    if len(result) < 30:
        raise ValueError(
            "Для теста недостаточно "
            "исторических данных."
        )

    frame = pd.DataFrame(
        sorted(result.items()),
        columns=["ts", "close"],
    )

    step = {
        "15m": 900000,
        "1H": 3600000,
        "4H": 14400000,
    }[bar]

    if (
        frame.ts.diff().dropna() > step
    ).any():
        raise ValueError(
            "В истории есть пропуски. "
            "Тест остановлен."
        )

    frame["time"] = pd.to_datetime(
        frame.ts,
        unit="ms",
        utc=True,
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
    delta = frame.close.diff()

    gain = wilder(
        delta.clip(lower=0)
    )

    loss = wilder(
        -delta.clip(upper=0)
    )

    rsi = 100 - 100 / (1 + gain / loss)

    rsi.loc[
        (gain == 0) & (loss == 0)
    ] = 50

    rsi.loc[
        (gain > 0) & (loss == 0)
    ] = 100

    true_range = pd.concat(
        [
            frame.high - frame.low,
            (frame.high - frame.close.shift()).abs(),
            (frame.low - frame.close.shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)

    true_range.iloc[0] = float("nan")
    atr = wilder(true_range)

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

    plus.iloc[0] = float("nan")
    minus.iloc[0] = float("nan")

    plus = wilder(plus)
    minus = wilder(minus)

    denominator = plus + minus

    dx = (
        100
        * (plus - minus).abs()
        / denominator
    )

    dx.loc[denominator == 0] = 0

    frame["RSI"] = rsi
    frame["ADX"] = wilder(dx)
    frame["ATR %"] = (
        atr / frame.close * 100
    )

    return frame


def chart(frame, title):
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
        row_heights=[0.6, 0.2, 0.2],
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
            increasing_line_color="#00e99b",
            decreasing_line_color="#ff6b86",
        ),
        row=1,
        col=1,
    )

    figure.add_trace(
        go.Scatter(
            x=frame.time,
            y=frame.RSI,
            name="RSI",
            line=dict(color="#00c2ff"),
        ),
        row=2,
        col=1,
    )

    figure.add_trace(
        go.Scatter(
            x=frame.time,
            y=frame.ADX,
            name="ADX",
            line=dict(color="#ffd166"),
        ),
        row=3,
        col=1,
    )

    figure.update_layout(
        title=title,
        template="plotly_dark",
        height=650,
        paper_bgcolor="#101827",
        plot_bgcolor="#101827",
        xaxis_rangeslider_visible=False,
    )

    st.plotly_chart(
        figure,
        use_container_width=True,
    )


# =========================================================
# DCA PLAN
# =========================================================

def dca_plan(settings, direction):
    entry = num(settings.get("entry"))
    step = num(settings.get("step"))
    count = int(settings.get("so_count", 0))

    base = num(settings.get("base_amount"))
    first = num(settings.get("first_so"))
    multiplier = num(settings.get("mart"))

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
            "Проверь цену, шаг и суммы ордеров DCA."
        )

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
            base
            if index == 0
            else first * multiplier ** (index - 1)
        )

        if price <= 0:
            raise ValueError(
                "Уменьши шаг или количество СО: "
                "один из уровней имеет цену ≤ 0."
            )

        total += amount
        quantity += amount / price

        rows.append({
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

    return rows


# =========================================================
# ASSESSMENT
# =========================================================

def assess(bot, price):
    settings = bot["settings"]
    position = bot.get("position", {})
    direction = bot["direction"]

    remaining = max(
        0,
        num(settings.get("total_budget"))
        - num(position.get("base_margin"))
        - num(position.get("added_margin")),
    )

    result = dict(
        action="Обновить позицию",
        risk="Нужны данные",
        reason="",
        pnl=None,
        remaining=remaining,
        tp=None,
        next_so=None,
        liq_distance=None,
    )

    if bot.get("lifecycle") != "Работает":
        if bot.get("lifecycle") != "Закрыт":
            result["action"] = "Проверить перед запуском"
            result["reason"] = (
                "План сохранён. "
                "После запуска на OKX внеси "
                "фактические данные позиции."
            )
        else:
            result["action"] = "Завершён"
            result["reason"] = (
                "Бот отмечен как завершённый. "
                "История и настройки сохранены."
            )

        return result

    if price is None:
        result["reason"] = (
            "Свежая цена временно недоступна. "
            "Обнови данные; расчёт "
            "по нулевой цене отключён."
        )

        return result

    reasons = []
    high = False
    exit_signal = False

    fresh = age(
        position.get("last_check")
    ) <= num(
        settings.get("stale_hours"),
        6,
    )

    average = num(position.get("avg_price"))
    quantity = num(position.get("volume"))
    liquidation = num(position.get("liq_price"))

    if (
        liquidation > 0
        and direction in ("Long", "Short")
    ):
        result["liq_distance"] = (
            side(direction)
            * (price - liquidation)
            / price
            * 100
        )

        if result["liq_distance"] <= num(
            settings.get("liq_warn"),
            10,
        ):
            high = True

            reasons.append(
                "Цена рядом с введённой ликвидацией "
                "или пересекла её. "
                "Срочно проверь позицию. "
                "Это не расчёт биржевого MMR."
            )

    if not fresh:
        reasons.append(
            "Обнови данные позиции: "
            "последняя сверка устарела "
            "или ещё не выполнена."
        )

    elif direction == "Neutral":
        reasons.append(
            "Проверь Total PnL на OKX: "
            "суммарный результат Neutral Grid "
            "здесь не моделируется."
        )

    elif average <= 0 or quantity <= 0:
        reasons.append(
            "Внеси фактический объём "
            "в базовой монете и среднюю цену."
        )

    else:
        result["pnl"] = (
            side(direction)
            * quantity
            * (price - average)
        )

    loss_limit = num(settings.get("max_loss"))

    if (
        result["pnl"] is not None
        and loss_limit > 0
        and result["pnl"] <= -loss_limit
    ):
        exit_signal = True
        high = True

        reasons.append(
            "Достигнут твой лимит убытка "
            "открытой позиции. Funding, комиссии "
            "и прошлые циклы не учтены."
        )

    stop = num(settings.get("stop_price"))

    if (
        stop > 0
        and direction in ("Long", "Short")
        and side(direction) * (price - stop) <= 0
    ):
        exit_signal = True
        high = True

        reasons.append(
            "Достигнута сигнальная стоп-цена. "
            "Приложение не отправляло "
            "биржевой ордер."
        )

    if bot["strategy"] == "DCA":
        rows = dca_plan(
            settings,
            direction,
        )

        executed = max(
            0,
            min(
                int(position.get("executed_so", 0)),
                len(rows) - 1,
            ),
        )

        if executed + 1 < len(rows):
            result["next_so"] = (
                rows[executed + 1]["Цена"]
            )

            if (
                side(direction)
                * (price - result["next_so"])
                <= 0
            ):
                reasons.append(
                    "Цена достигла следующего СО. "
                    "Проверь исполнение "
                    "и обнови среднюю/объём."
                )

        if fresh and average > 0:
            result["tp"] = average * (
                1
                + side(direction)
                * num(settings.get("tp"), 1.5)
                / 100
            )

            if (
                side(direction)
                * (price - result["tp"])
                >= 0
            ):
                reasons.append(
                    "Цена достигла модельного TP цикла. "
                    "Это движение цены от средней, "
                    "не ROI маржи. "
                    "Проверь исполнение на OKX."
                )

    else:
        lower = num(settings.get("lower"))
        upper = num(settings.get("upper"))

        if lower <= 0 or upper <= lower:
            reasons.append(
                "Проверь сохранённые границы Grid."
            )

        elif not lower <= price <= upper:
            reasons.append(
                "Цена вышла из диапазона Grid. "
                "Проверь ордера и остаточную позицию: "
                "это не подтверждение закрытия."
            )

        elif (
            min(price - lower, upper - price)
            / (upper - lower)
            <= 0.1
        ):
            reasons.append(
                "Цена приблизилась к границе Grid — "
                "находится в крайних 10% диапазона."
            )

        target = num(settings.get("target_price"))

        if (
            target > 0
            and direction in ("Long", "Short")
            and side(direction) * (price - target) >= 0
        ):
            reasons.append(
                "Достигнута твоя целевая цена Grid. "
                "Проверь условие завершения."
            )

    if remaining <= 0:
        reasons.append(
            "Резерв исчерпан. "
            "Дальнейшие добавления маржи "
            "будут вне плана."
        )

    result["action"] = (
        "Выход по плану"
        if exit_signal
        else "Проверить на OKX"
        if reasons
        else "Не трогать по плану"
    )

    result["risk"] = (
        "Высокий"
        if high
        else "Требует внимания"
        if reasons
        else "Нет срабатываний"
    )

    result["reason"] = (
        "\n\n".join(reasons)
        if reasons
        else (
            "Условия вмешательства не сработали. "
            "Это не прогноз "
            "и не гарантия безопасности."
        )
    )

    return result


# =========================================================
# TELEGRAM
# =========================================================

def telegram(text):
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
            "Добавь Telegram Token "
            "и Chat ID в Secrets."
        )

    payload = json.dumps(
        dict(
            chat_id=chat_id,
            text=text[:4000],
        )
    ).encode()

    request = Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={
            "Content-Type": "application/json",
        },
    )

    with urlopen(request, timeout=15) as response:
        result = json.load(response)

    if not result.get("ok"):
        raise ValueError(
            "Telegram не подтвердил отправку."
        )


# =========================================================
# LIMITED SIMULATION
# =========================================================

def simulation(
    frame,
    settings,
    strategy,
    direction,
    fee,
):
    capital = settings["base_margin"]
    wallet = capital

    quantity = 0.0
    average = 0.0
    entry = 0.0
    executed = 0
    fees = 0.0
    cycles = 0

    curve = []
    peak = capital
    drawdown = 0.0
    lots = {}

    prices = frame.close.tolist()

    if strategy == "Grid":
        intervals = int(settings["grids"])

        levels = [
            settings["lower"]
            + (
                settings["upper"]
                - settings["lower"]
            )
            * index
            / intervals
            for index in range(intervals + 1)
        ]

        allocation = (
            capital / intervals / (1 + fee)
        )

    for index, price in enumerate(prices):
        if strategy == "DCA":
            direction_sign = side(direction)

            if quantity == 0:
                amount = settings["base_amount"]

                if amount * (1 + fee) > wallet:
                    raise ValueError(
                        "Недостаточно модельного капитала."
                    )

                quantity = amount / price
                average = price
                entry = price
                executed = 0

                wallet -= amount * fee
                fees += amount * fee

            elif (
                direction_sign
                * (price / average - 1)
                * 100
                >= settings["tp"]
            ):
                close_fee = (
                    quantity * price * fee
                )

                wallet += (
                    direction_sign
                    * quantity
                    * (price - average)
                    - close_fee
                )

                fees += close_fee
                quantity = 0
                cycles += 1

            elif (
                executed < settings["so_count"]
                and direction_sign
                * (price / entry - 1)
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
                    average = (
                        quantity * average + amount
                    ) / (
                        quantity + amount / price
                    )

                    quantity += amount / price
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
                    gross = (
                        lots.pop(level_index) * price
                    )

                    wallet += gross * (1 - fee)
                    fees += gross * fee
                    cycles += 1

            if index > 0:
                for level_index, level in enumerate(
                    levels[:-1]
                ):
                    cost = (
                        allocation * (1 + fee)
                    )

                    if (
                        level_index not in lots
                        and prices[index - 1] > level >= price
                        and wallet >= cost
                    ):
                        lots[level_index] = (
                            allocation / price
                        )

                        wallet -= cost
                        fees += allocation * fee

            equity = (
                wallet
                + sum(lots.values()) * price
            )

        if equity <= 0:
            raise ValueError(
                "Модельный капитал исчерпан."
            )

        peak = max(peak, equity)

        drawdown = max(
            drawdown,
            (peak - equity) / peak * 100,
        )

        curve.append(equity)

    return {
        "Итог equity": curve[-1],
        "Результат USDT": curve[-1] - capital,
        "Доходность %": (
            curve[-1] / capital - 1
        ) * 100,
        "Просадка %": drawdown,
        "Комиссии USDT": fees,
        "Циклов/лотов": cycles,
    }, curve


def backtest(
    strategy,
    direction,
    coin,
    market,
    settings,
    valid,
):
    st.subheader(
        "Сравнение вариантов"
    )

    variants = [
        ("Твой план", dict(settings)),
        ("Вариант A", dict(settings)),
        ("Вариант B", dict(settings)),
    ]

    if strategy == "DCA":
        variants[1][1]["mart"] = 1.0
        variants[2][1]["step"] *= 1.5

    else:
        middle = (
            settings["lower"]
            + settings["upper"]
        ) / 2

        width = (
            settings["upper"]
            - settings["lower"]
        ) / 2

        variants[1][1].update(
            lower=max(
                0.00000001,
                middle - width * 1.5,
            ),
            upper=middle + width * 1.5,
        )

        variants[2][1]["grids"] = max(
            2,
            settings["grids"] // 2,
        )

    display_rows = []

    for label, variant in variants:
        if strategy == "DCA":
            display_rows.append({
                "Вариант": label,
                "TP %": variant["tp"],
                "Шаг %": variant["step"],
                "СО": variant["so_count"],
                "Множитель": variant["mart"],
            })
        else:
            display_rows.append({
                "Вариант": label,
                "Нижняя граница": variant["lower"],
                "Верхняя граница": variant["upper"],
                "Интервалы": variant["grids"],
            })

    table(pd.DataFrame(display_rows))

    days = st.selectbox(
        "Период истории, дней",
        [7, 30, 90],
        key=strategy + "days",
    )

    bar = st.selectbox(
        "Свечи",
        ["15m", "1H", "4H"],
        index=1,
        key=strategy + "bar",
    )

    fee = field(
        "Комиссия за сторону, %",
        0.05,
        strategy + "fee",
        0,
        5,
    ) / 100

    if st.button(
        "Сравнить на истории",
        disabled=not valid,
        key=strategy + "test",
    ):
        if (
            settings["leverage"] != 1
            or (
                strategy == "Grid"
                and (
                    market != "SPOT"
                    or direction != "Long"
                )
            )
        ):
            st.warning(
                "Для этой модели выбери 1x. "
                "Grid-тест поддерживает только "
                "Spot Long; Futures Grid "
                "не симулируется."
            )

        else:
            st.session_state.pop(
                strategy + "result",
                None,
            )

            with st.spinner(
                "Загружаю историю "
                "и считаю варианты..."
            ):
                frame = candles(
                    coin,
                    market,
                    days,
                    bar,
                )

                rows = []
                curves = {}

                for label, variant in variants:
                    if strategy == "DCA":
                        dca_plan(
                            variant,
                            direction,
                        )

                    metrics, curve = simulation(
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

                description = (
                    f"{coin} · {market} · {bar} · "
                    f"{frame.time.iloc[0]} — "
                    f"{frame.time.iloc[-1]} · "
                    f"{len(frame)} свечей"
                )

                st.session_state[
                    strategy + "result"
                ] = (
                    rows,
                    curves,
                    description,
                )

    if strategy + "result" in st.session_state:
        rows, curves, description = (
            st.session_state[strategy + "result"]
        )

        st.caption(
            "Последний расчёт: "
            + description
            + ". После изменения "
            "параметров пересчитай."
        )

        table(pd.DataFrame(rows))
        st.line_chart(pd.DataFrame(curves))

    with st.expander(
        "Что учитывает историческая модель"
    ):
        st.write(
            "Исполнения по закрытиям свечей, "
            "комиссия за вход/выход "
            "и открытая позиция в equity. "
            "Без funding, ликвидации, "
            "очереди ордеров, проскальзывания "
            "и точных правил OKX. "
            "DCA — линейная модель, "
            "не точный Spot-кошелёк. "
            "Стопы, лимит убытка "
            "и резерв маржи в тесте "
            "не исполняются. "
            "Это не прогноз доходности."
        )


# =========================================================
# CREATOR
# =========================================================

def creator(strategy):
    preferred = st.session_state.get(
        "preferred",
        "Long",
    )

    directions = (
        ["Long", "Short"]
        if strategy == "DCA"
        else ["Long", "Short", "Neutral"]
    )

    mode = st.radio(
        "Задача",
        [
            "Подготовить новый",
            "Добавить уже запущенный",
        ],
        horizontal=True,
        key=strategy + "addmode",
    )

    if mode == "Добавить уже запущенный":
        st.caption(
            "Сохрани настройки бота, "
            "затем открой карточку "
            "и внеси фактическую позицию. "
            "Приложение не запускает его повторно."
        )

    name = st.text_input(
        "Название",
        f"Мой {strategy}",
        key=strategy + "name",
    )

    coin = st.text_input(
        "Монета",
        "BTC",
        key=strategy + "coin",
    ).strip().upper()

    market = st.radio(
        "Рынок",
        ["SWAP", "SPOT"],
        horizontal=True,
        key=strategy + "market",
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
        key="dir_" + strategy + "_" + preferred,
    )

    if market == "SPOT" and direction != "Long":
        st.warning(
            "Для Spot в этой версии выбери Long."
        )
        return

    leverage = field(
        "Плечо",
        1,
        strategy + "lev",
        1,
        100,
    )

    if market == "SPOT" and leverage != 1:
        st.warning(
            "Для Spot установи 1x."
        )
        return

    margin = field(
        "Базовая маржа / капитал Spot, USDT",
        100,
        strategy + "margin",
        0.01,
    )

    reserve = field(
        "Отдельный резерв маржи, USDT",
        50,
        strategy + "reserve",
    )

    settings = dict(
        leverage=leverage,
        base_margin=margin,
        reserve=reserve,
        total_budget=margin + reserve,
    )

    st.caption(
        f"Общий лимит выделяемых средств: "
        f"{margin + reserve:.2f} USDT. "
        "Номинал ордеров и маржа "
        "учитываются отдельно."
    )

    valid = (
        bool(name.strip())
        and coin.isalnum()
    )

    if strategy == "DCA":
        settings["entry"] = field(
            "Цена первого входа",
            100,
            strategy + "entry",
            0.00000001,
        )

        settings["tp"] = field(
            "TP: движение цены от средней, % "
            "(не ROI маржи)",
            1.5,
            strategy + "tp",
            0.01,
            99,
        )

        settings["step"] = field(
            "Шаг СО от первого входа, %",
            2,
            strategy + "step",
            0.01,
            50,
        )

        settings["so_count"] = st.number_input(
            "Количество СО",
            0,
            30,
            4,
            key=strategy + "count",
        )

        settings["base_amount"] = field(
            "Номинал первого ордера, USDT",
            10,
            strategy + "base",
            0.01,
        )

        settings["first_so"] = field(
            "Номинал первого СО, USDT",
            10,
            strategy + "first",
            0.01,
        )

        settings["mart"] = field(
            "Множитель объёма следующих СО",
            1.2,
            strategy + "mart",
            1,
            3,
        )

        try:
            plan = dca_plan(
                settings,
                direction,
            )

            table(pd.DataFrame(plan))

            required = (
                plan[-1]["Всего номинал"]
                / leverage
            )

            st.caption(
                f"Маржа по модели на все ордера: "
                f"{required:.2f} USDT, "
                "без комиссий "
                "и биржевого резерва."
            )

            if required >= margin:
                valid = False

                st.error(
                    "Увеличь базовую маржу "
                    "или уменьши номиналы: "
                    "нужен запас под ордера."
                )

        except ValueError as error:
            valid = False
            st.error(str(error))

    else:
        settings["lower"] = field(
            "Нижняя граница — точная цена",
            90,
            strategy + "low",
            0.00000001,
        )

        settings["upper"] = field(
            "Верхняя граница — точная цена",
            110,
            strategy + "upper",
            0.00000001,
        )

        settings["grids"] = st.number_input(
            "Количество интервалов "
            "(уровней N+1)",
            2,
            200,
            10,
            key=strategy + "grids",
        )

        settings["target_price"] = field(
            "Целевая цена завершения; 0 = нет",
            0,
            strategy + "target",
        )

        if settings["upper"] <= settings["lower"]:
            valid = False

            st.error(
                "Верхняя граница должна "
                "быть выше нижней."
            )

        else:
            levels = [
                settings["lower"]
                + (
                    settings["upper"]
                    - settings["lower"]
                )
                * index
                / settings["grids"]
                for index in range(
                    settings["grids"] + 1
                )
            ]

            st.line_chart(
                pd.DataFrame({
                    "Уровни Grid": levels
                })
            )

    with st.expander(
        "Риск, резерв и условия выхода",
        expanded=True,
    ):
        settings["max_loss"] = field(
            "Лимит убытка открытой позиции, USDT; "
            "0 = отключён",
            0,
            strategy + "loss",
        )

        settings["stop_price"] = field(
            "Сигнальная стоп-цена; 0 = нет",
            0,
            strategy + "stop",
        )

        settings["stale_hours"] = field(
            "Обновлять сверку не реже "
            "чем раз в часов",
            6,
            strategy + "stale",
            0.1,
            168,
        )

        settings["liq_warn"] = field(
            "Предупреждение у введённой "
            "ликвидации, %",
            10,
            strategy + "liqwarn",
            0.1,
            100,
        )

        st.caption(
            "Это сигналы, не ордера OKX. "
            "Без стопа и лимита выход "
            "по убытку не ограничен. "
            "Добавление маржи "
            "не устраняет убыток."
        )

    if st.button(
        "Сохранить и открыть бота",
        disabled=not valid,
        key=strategy + "save",
    ):
        quote(coin, market)

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
            decision="",
            created_at=now(),
        )

        save_bot(
            bot,
            "Создана карточка",
            (
                "Требуется сверка запущенного бота."
                if mode == "Добавить уже запущенный"
                else "План до запуска."
            ),
        )

        move(
            "3. ИИ-Центр",
            bot_id=bot["id"],
        )

    st.divider()

    backtest(
        strategy,
        direction,
        coin,
        market,
        settings,
        valid,
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
        )[0]
    except Exception:
        price = None

    state = assess(bot, price)

    color = {
        "Long": "#137333",
        "Short": "#c5223f",
        "Neutral": "#174ea6",
    }.get(
        bot["direction"],
        "#172033",
    )

    with st.container(border=True):
        heading = (
            '<div class="bot-heading">'
            '<span class="bot-title">'
            + html.escape(
                f"{bot['coin']} · {bot['strategy']}"
            )
            + '</span>'
            '<span class="direction" '
            'style="color:'
            + color
            + '">'
            + html.escape(bot["direction"])
            + '</span>'
            '<span class="lifecycle">'
            + STATES.get(
                bot.get("lifecycle"),
                "План",
            )
            + '</span>'
            '</div>'
        )

        st.markdown(
            heading,
            unsafe_allow_html=True,
        )

        st.caption(
            bot["name"]
            + " · "
            + bot["market"]
        )

        columns = st.columns(3)

        columns[0].metric(
            "Цена",
            fmt(price, 6),
        )

        columns[1].metric(
            "Открытый PnL ≈ USDT",
            fmt(state["pnl"]),
        )

        columns[2].metric(
            "Резерв маржи USDT",
            fmt(state["remaining"]),
        )

        st.write(
            "Сейчас: "
            + state["action"]
        )

        if state["risk"] == "Высокий":
            st.error(state["reason"])
        else:
            st.info(state["reason"])

        st.caption(
            "Внимание: "
            + state["risk"]
            + " · Данные позиции: "
            + short_time(
                position.get("last_check")
            )
        )

        if compact:
            if st.button(
                "Открыть бота",
                key=identifier + "open",
            ):
                move(
                    "3. ИИ-Центр",
                    bot_id=identifier,
                )

            return

        values = [
            ("tp", "Модельный TP"),
            ("next_so", "Следующий СО"),
            (
                "liq_distance",
                "До введённой ликвидации, %",
            ),
        ]

        for key, label in values:
            if state[key] is not None:
                st.write(
                    label
                    + ": "
                    + fmt(
                        state[key],
                        6 if key != "liq_distance" else 2,
                    )
                )

        st.caption(
            "Открытый PnL не равен "
            "результату всего бота. "
            "Объём вводится в базовой монете, "
            "не в контрактах."
        )

        needs_data = (
            bot.get("lifecycle") == "Черновик"
            or not position.get("last_check")
        )

        with st.expander(
            "Обновить позицию на основе OKX",
            expanded=needs_data,
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
                    "Состояние бота на OKX",
                    states,
                    index=states.index(
                        bot.get(
                            "lifecycle",
                            "Черновик",
                        )
                    ),
                    format_func=lambda value: STATES[value],
                )

                quantity = field(
                    "Объём в базовой монете, "
                    "НЕ контракты",
                    num(position.get("volume")),
                    identifier + "qty",
                )

                average = field(
                    "Фактическая средняя цена",
                    num(position.get("avg_price")),
                    identifier + "avg",
                )

                liquidation = field(
                    "Ликвидационная цена с OKX; "
                    "0 = неизвестна",
                    num(position.get("liq_price")),
                    identifier + "liq",
                )

                margin = field(
                    "Базовая выделенная маржа",
                    num(
                        position.get("base_margin"),
                        num(settings.get("base_margin")),
                    ),
                    identifier + "margin",
                )

                added = field(
                    "Всего добавлено маржи",
                    num(position.get("added_margin")),
                    identifier + "added",
                )

                maximum = int(
                    settings.get("so_count", 0)
                )

                if (
                    bot["strategy"] == "DCA"
                    and maximum > 0
                ):
                    executed = st.number_input(
                        "Исполнено СО текущего цикла",
                        0,
                        maximum,
                        max(
                            0,
                            min(
                                int(
                                    position.get(
                                        "executed_so",
                                        0,
                                    )
                                ),
                                maximum,
                            ),
                        ),
                        key=identifier + "executed",
                    )
                else:
                    executed = 0

                note = st.text_input(
                    "Заметка к обновлению"
                )

                confirmed = st.checkbox(
                    "Сверил значения с OKX"
                )

                if st.form_submit_button(
                    "Сохранить данные позиции"
                ):
                    invalid_position = (
                        lifecycle == "Работает"
                        and bot["direction"] != "Neutral"
                        and (
                            quantity <= 0
                            or average <= 0
                        )
                    )

                    if not confirmed or invalid_position:
                        st.error(
                            "Подтверди сверку "
                            "и заполни объём/среднюю "
                            "активной позиции."
                        )

                    else:
                        bot["position"] = dict(
                            volume=quantity,
                            avg_price=average,
                            liq_price=liquidation,
                            base_margin=margin,
                            added_margin=added,
                            executed_so=int(executed),
                            last_check=now(),
                        )

                        bot["lifecycle"] = lifecycle

                        save_bot(
                            bot,
                            "Обновлена позиция",
                            note
                            or (
                                "Значения сверены "
                                "с OKX пользователем."
                            ),
                        )

                        st.rerun()

        with st.expander(
            "План и настройки"
        ):
            table(
                pd.DataFrame([
                    {
                        "Параметр": key,
                        "Значение": str(value),
                    }
                    for key, value in settings.items()
                ])
            )

        with st.form(
            identifier + "decision"
        ):
            decision = st.radio(
                "Записать решение",
                [
                    "Не трогать",
                    "Проверить на OKX",
                    "Выход по плану",
                ],
                horizontal=True,
            )

            reason = st.text_input(
                "Почему выбрал это действие"
            )

            if st.form_submit_button(
                "Сохранить решение"
            ):
                bot["decision"] = (
                    decision
                    + " · "
                    + short_time(now())
                    + " · "
                    + reason
                )

                save_bot(
                    bot,
                    "Решение пользователя",
                    bot["decision"],
                )

                st.rerun()

        if bot.get("decision"):
            st.caption(
                "Твоё решение: "
                + bot["decision"]
            )

        st.caption(
            "Решение не отправляет торговую команду "
            "и не отключает предупреждения."
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
                f"Сейчас: {state['action']}\n"
                f"Внимание: {state['risk']}\n"
                f"Цена: {fmt(price, 6)}\n"
                f"Открытый PnL ≈ "
                f"{fmt(state['pnl'])} USDT\n"
                f"Резерв: "
                f"{fmt(state['remaining'])} USDT\n"
                f"Сверка UTC: "
                f"{position.get('last_check') or 'нет'}\n\n"
                f"{state['reason']}\n\n"
                "Торговые команды не отправлялись."
            )

            telegram(message)
            st.success("Отчёт отправлен.")


# =========================================================
# SCANNER
# =========================================================

def scanner():
    panel(
        "Сканер рынка",
        "Выбери монеты, посмотри технические сценарии "
        "и перейди к подготовке DCA или Grid.",
    )

    market = st.radio(
        "Рынок",
        ["SWAP", "SPOT"],
        horizontal=True,
        key="scanmarket",
    )

    coins = st.multiselect(
        "Монеты",
        COINS,
        default=COINS,
    )

    threshold = field(
        "Порог объёма 24H, USDT",
        10000000,
        "scanvolume",
    )

    st.caption(
        "Исходные правила RSI/ADX "
        "на закрытых дневных свечах. "
        "Их прибыльность не подтверждена."
    )

    if st.button(
        "Сканировать рынок",
        use_container_width=True,
    ):
        if not coins:
            st.warning(
                "Выбери хотя бы одну монету."
            )
            return

        rows = []
        errors = []
        charts = {}

        progress = st.progress(0.0)

        for index, coin in enumerate(coins):
            try:
                frame = indicators(
                    daily(coin, market)
                )

                last = frame.iloc[-1]

                price, volume = quote(
                    coin,
                    market,
                )

                rsi = float(last.RSI)
                adx = float(last.ADX)
                atr = float(last["ATR %"])

                if not all(
                    math.isfinite(value)
                    for value in [rsi, adx, atr]
                ):
                    raise ValueError(
                        "Индикаторы не готовы."
                    )

                if adx <= 25:
                    strategy = "Grid"
                    direction = "Не определено"
                    status = "Рассмотреть"
                    reason = "ADX ≤ 25"

                elif rsi < 40:
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

                if (
                    market == "SPOT"
                    and direction == "Short"
                ):
                    status = (
                        "Spot Short не поддерживается"
                    )

                flags = []

                if volume <= 0:
                    flags.append(
                        "Нет оценки объёма"
                    )
                elif volume < threshold:
                    flags.append(
                        "Объём ниже порога"
                    )

                if atr > 3:
                    flags.append(
                        "ATR > 3%"
                    )

                if rsi < 30 or rsi > 70:
                    flags.append(
                        "Крайний RSI"
                    )

                rows.append({
                    "Монета": coin,
                    "Цена": price,
                    "Стратегия": strategy,
                    "Направление": direction,
                    "Статус": status,
                    "RSI": rsi,
                    "ADX": adx,
                    "ATR %": atr,
                    "Объём 24H USDT ≈": volume,
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
                (index + 1) / len(coins)
            )

        st.session_state[
            "scan_result"
        ] = dict(
            rows=rows,
            errors=errors,
            charts=charts,
            market=market,
            time=now(),
        )

    result = st.session_state.get(
        "scan_result"
    )

    if not result:
        panel(
            "Рынок — перед тобой",
            "Нажми «Сканировать рынок»: "
            "появятся монеты, направления "
            "и причины выбранного сценария.",
            True,
        )
        return

    st.caption(
        f"Обновлено: "
        f"{short_time(result['time'])} · "
        f"{result['market']}"
    )

    if result["errors"]:
        st.warning(
            "Временно не удалось рассчитать: "
            + ", ".join(result["errors"])
        )

    if not result["rows"]:
        panel(
            "Не удалось загрузить рынок",
            "Повтори сканирование через некоторое время. "
            "Неудачная загрузка не влияет "
            "на сохранённых ботов.",
            True,
        )
        return

    frame = pd.DataFrame(
        result["rows"]
    )

    columns = st.columns(4)

    counters = [
        (
            columns[0],
            "DCA Long",
            frame["Направление"].eq("Long").sum(),
        ),
        (
            columns[1],
            "DCA Short",
            frame["Направление"].eq("Short").sum(),
        ),
        (
            columns[2],
            "Grid",
            frame["Стратегия"].eq("Grid").sum(),
        ),
        (
            columns[3],
            "Ждать",
            frame["Статус"].eq("Ждать").sum(),
        ),
    ]

    for column, label, count in counters:
        column.metric(
            label,
            int(count),
        )

    selected_strategy = st.radio(
        "Стратегия",
        ["Все", "DCA", "Grid"],
        horizontal=True,
        key="scan_strategy_filter",
    )

    selected_direction = st.radio(
        "Направление",
        [
            "Все",
            "Long",
            "Short",
            "Не определено",
        ],
        horizontal=True,
        key="scan_direction_filter",
    )

    visible = frame.copy()

    if selected_strategy != "Все":
        visible = visible[
            visible["Стратегия"]
            == selected_strategy
        ]

    if selected_direction != "Все":
        visible = visible[
            visible["Направление"]
            == selected_direction
        ]

    if visible.empty:
        panel(
            "Другой сценарий — тоже результат",
            "В последнем сканировании нет сочетания "
            "выбранных стратегии и направления. "
            "Открой все результаты или обнови рынок.",
            True,
        )

        if st.button(
            "Показать все сценарии"
        ):
            st.session_state[
                "reset_scan_filters"
            ] = True

            st.rerun()

        return

    table(
        visible,
        "Направление",
    )

    coin = st.selectbox(
        "Открыть монету",
        visible["Монета"].tolist(),
    )

    row = frame[
        frame["Монета"] == coin
    ].iloc[0]

    st.info(
        f"{row['Стратегия']} · "
        f"{row['Направление']} · "
        f"{row['Причина']}"
    )

    st.caption(
        row["Факторы риска"]
    )

    chart(
        result["charts"][coin],
        coin + " · цена, RSI и ADX",
    )

    columns = st.columns(3)

    actions = [
        (
            columns[0],
            "DCA Long",
            "DCA",
            "Long",
        ),
        (
            columns[1],
            "DCA Short",
            "DCA",
            "Short",
        ),
        (
            columns[2],
            "Grid",
            "Grid",
            (
                "Neutral"
                if result["market"] == "SWAP"
                else "Long"
            ),
        ),
    ]

    for column, label, strategy, direction in actions:
        disabled = (
            result["market"] != market
            or (
                result["market"] == "SPOT"
                and direction == "Short"
            )
        )

        if column.button(
            "Подготовить " + label,
            disabled=disabled,
        ):
            st.session_state[
                strategy + "coin"
            ] = coin

            st.session_state[
                strategy + "market"
            ] = result["market"]

            if strategy == "DCA":
                st.session_state[
                    strategy + "entry"
                ] = float(row["Цена"])

            move(
                "4. DCA"
                if strategy == "DCA"
                else "5. Grid",
                direction,
            )

    st.caption(
        "Направление Grid выбирается отдельно. "
        "Отсутствие флагов не означает низкий риск."
    )


# =========================================================
# IMPORT
# =========================================================

def import_bots(raws, old_events=None):
    if (
        not isinstance(raws, list)
        or len(raws) > 1000
    ):
        raise ValueError(
            "В копии должен быть список bots, "
            "не более 1000 карточек."
        )

    prepared = []

    for raw in raws:
        if not isinstance(raw, dict):
            raise ValueError(
                "Неверный формат карточки."
            )

        bot = dict(raw)

        for key in [
            "settings",
            "position",
        ]:
            value = bot.get(key, {})

            if isinstance(value, str):
                value = json.loads(value)

            if not isinstance(value, dict):
                raise ValueError(
                    "Проверь настройки "
                    "и позицию в копии."
                )

            bot[key] = value

        if (
            bot.get("strategy")
            not in ("DCA", "Grid")
            or bot.get("direction")
            not in ("Long", "Short", "Neutral")
        ):
            raise ValueError(
                "Неизвестная стратегия "
                "или направление."
            )

        if (
            bot["strategy"] == "DCA"
            and bot["direction"] == "Neutral"
        ):
            raise ValueError(
                "DCA Neutral не поддерживается."
            )

        bot["coin"] = str(
            bot.get("coin", "")
        ).strip().upper()

        if not bot["coin"].isalnum():
            raise ValueError(
                "Проверь название монеты."
            )

        bot.pop("_revision", None)
        bot["id"] = str(uuid.uuid4())

        bot["name"] = str(
            bot.get("name", bot["coin"])
        )

        old_market = str(
            bot.get("market", "SWAP")
        )

        bot["market"] = (
            "SWAP"
            if "SWAP" in old_market
            or "Фьючерсы" in old_market
            else "SPOT"
        )

        bot["lifecycle"] = "Черновик"
        bot["position"]["last_check"] = ""
        bot["updated_at"] = now()
        bot.setdefault("created_at", now())

        settings = bot["settings"]

        defaults = dict(
            leverage=1,
            stale_hours=6,
            liq_warn=10,
            max_loss=0,
            stop_price=0,
            first_so=settings.get(
                "base_amount",
                10,
            ),
            base_margin=bot["position"].get(
                "base_margin",
                0,
            ),
        )

        for key, value in defaults.items():
            settings.setdefault(
                key,
                value,
            )

        settings.setdefault(
            "total_budget",
            num(settings.get("base_margin"))
            + num(settings.get("reserve")),
        )

        if old_events:
            bot["imported_journal"] = old_events

        prepared.append(bot)

    with database() as connection:
        for bot in prepared:
            query(
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
                "Добавлена копия. Требуется сверка.",
            )

    return len(prepared)


# =========================================================
# SETTINGS
# =========================================================

def settings(bots):
    panel(
        "Настройки",
        "Подключения, доступ и резервные копии — "
        "в одном месте.",
    )

    st.write(
        "Пароль: "
        + (
            "настроен"
            if secret("APP_PASSWORD")
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

    if not secret("APP_PASSWORD"):
        st.warning(
            "Добавь APP_PASSWORD в Secrets "
            "или ограничь доступ к приложению. "
            "Не публикуй личные позиции открыто."
        )

    if not DB_URL:
        st.warning(
            "Локальный файл может потеряться "
            "при пересоздании сервера. "
            "Для постоянного внешнего хранения "
            "настрой DATABASE_URL. "
            "Скачивай резервные копии."
        )

    if st.button(
        "Проверить Telegram"
    ):
        telegram(
            "OKX Terminal Pro: "
            "соединение подтверждено. "
            "Автоматические сделки не включены."
        )

        st.success(
            "Тестовое сообщение отправлено."
        )

    backup_bots = [
        {
            key: value
            for key, value in bot.items()
            if key != "_revision"
        }
        for bot in bots
    ]

    backup = dict(
        version=9,
        created_at=now(),
        bots=backup_bots,
        events=history().to_dict("records"),
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
        "Восстановить из JSON",
        type=["json"],
    )

    confirmed = st.checkbox(
        "Добавить копии с новыми ID, "
        "не заменяя существующие карточки"
    )

    if st.button(
        "Восстановить ботов",
        disabled=(
            uploaded is None
            or not confirmed
        ),
    ):
        if uploaded.size > 5000000:
            raise ValueError(
                "Копия больше 5 MB."
            )

        source = json.loads(
            uploaded.getvalue()
        )

        if not isinstance(source, dict):
            raise ValueError(
                "Неверный формат резервной копии."
            )

        count = import_bots(
            source.get("bots"),
            source.get("events"),
        )

        st.success(
            f"Восстановлено: {count}. "
            "Открой карточки "
            "и обнови позиции."
        )

    with st.expander(
        "Перенести ботов из старого SQLite"
    ):
        st.caption(
            "Исходные записи не удаляются. "
            "Повторный перенос создаёт копии."
        )

        if st.button(
            "Перенести старую таблицу bots"
        ):
            if not os.path.isfile(DB_FILE):
                raise ValueError(
                    "Старый файл не найден "
                    "на этом сервере."
                )

            connection = sqlite3.connect(
                DB_FILE
            )

            try:
                connection.row_factory = sqlite3.Row

                exists = connection.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type='table'
                    AND name='bots'
                    """
                ).fetchone()

                if not exists:
                    raise ValueError(
                        "Старая таблица bots не найдена. "
                        "Попробуй восстановление JSON."
                    )

                rows = [
                    dict(row)
                    for row in connection.execute(
                        "SELECT * FROM bots"
                    )
                ]

            finally:
                connection.close()

            count = import_bots(rows)

            st.success(
                f"Перенесено: {count}. "
                "Проверь параметры "
                "и обнови позиции."
            )

    with st.expander(
        "Параметры Streamlit Secrets"
    ):
        st.code(
            '''
APP_PASSWORD = "ваш-длинный-пароль"

# Для постоянной внешней базы:
DATABASE_URL = "postgresql://user:password@host/database?sslmode=require"

TELEGRAM_TOKEN = "токен"
TELEGRAM_CHAT_ID = "chat-id"
'''.strip(),
            language="toml",
        )

        st.caption(
            "Не публикуй секреты в GitHub. "
            "DATABASE_URL добавляется "
            "только с реальными данными "
            "созданной базы. "
            "При переходе на другую базу "
            "перенеси карточки "
            "через экспорт/импорт."
        )

    st.caption(
        "Работа приложения: ручной контроль. "
        "Telegram — по кнопке. "
        "Фоновый сервис и автоматические сделки "
        "не включены."
    )


# =========================================================
# ACTIONS
# =========================================================

def add_actions(prefix):
    columns = st.columns(2)

    if columns[0].button(
        "Добавить DCA",
        key=prefix + "dca",
        use_container_width=True,
    ):
        move(
            "4. DCA",
            "Long",
        )

    if columns[1].button(
        "Добавить Grid",
        key=prefix + "grid",
        use_container_width=True,
    ):
        move(
            "5. Grid",
            "Neutral",
        )


def show_cards(bots, compact=False):
    for bot in bots:
        try:
            bot_card(
                bot,
                compact,
            )

        except Exception:
            st.error(
                "Карточка «"
                + str(bot.get("name", "Бот"))
                + "» не загрузилась. "
                "Обнови страницу и проверь "
                "сохранённые параметры. "
                "Данные не удалены."
            )


# =========================================================
# MAIN
# =========================================================

def main():
    design()
    login()
    init_database()

    if st.session_state.pop(
        "reset_scan_filters",
        False,
    ):
        st.session_state[
            "scan_strategy_filter"
        ] = "Все"

        st.session_state[
            "scan_direction_filter"
        ] = "Все"

    if st.session_state.pop(
        "reset_control_filters",
        False,
    ):
        st.session_state[
            "control_strategy"
        ] = "Все"

        st.session_state[
            "control_state"
        ] = "Все"

    pending = st.session_state.pop(
        "pending",
        None,
    )

    if pending in PAGES:
        st.session_state[
            "navigation"
        ] = pending

    if (
        st.session_state.get("navigation")
        not in PAGES
    ):
        st.session_state[
            "navigation"
        ] = PAGES[0]

    with st.sidebar:
        st.title(
            "OKX Terminal"
        )

        page = st.radio(
            "Раздел",
            PAGES,
            key="navigation",
            label_visibility="collapsed",
        )

        if st.button(
            "Обновить цены"
        ):
            quote.clear()
            st.rerun()

        st.caption(
            "Ручной контроль. "
            "Торговые команды не отправляются."
        )

    bots = load_bots()

    if page == "1. Главная":
        panel(
            "Твои боты — на одном экране",
            "Подготовь стратегию, "
            "внеси настройки на OKX "
            "и следи за своим планом здесь.",
        )

        if not bots:
            panel(
                "Добавь первого бота",
                "Уже запустил DCA или Grid на OKX? "
                "Перенеси его настройки. "
                "Или сначала подготовь новый план "
                "и сравни варианты на истории.",
                True,
            )

            add_actions(
                "home_empty_"
            )

            if st.button(
                "Сначала посмотреть рынок",
                use_container_width=True,
            ):
                move("2. Сканер")

        else:
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

            columns = st.columns(3)

            if columns[0].button(
                "ЛОНГ · DCA",
                key="home_long",
                use_container_width=True,
            ):
                move(
                    "4. DCA",
                    "Long",
                )

            if columns[1].button(
                "ШОРТ · DCA",
                key="home_short",
                use_container_width=True,
            ):
                move(
                    "4. DCA",
                    "Short",
                )

            if columns[2].button(
                "GRID",
                key="home_grid",
                use_container_width=True,
            ):
                move(
                    "5. Grid",
                    "Neutral",
                )

            if active:
                st.subheader(
                    "В работе"
                )

                show_cards(
                    active[:10],
                    compact=True,
                )

            if drafts:
                st.subheader(
                    "Сохранённые планы"
                )

                st.caption(
                    "Открой план, проверь параметры "
                    "и обнови позицию "
                    "после запуска на OKX."
                )

                for bot in drafts[:6]:
                    with st.container(
                        border=True
                    ):
                        st.subheader(
                            bot["name"]
                        )

                        st.caption(
                            f"{bot['coin']} · "
                            f"{bot['strategy']} "
                            f"{bot['direction']}"
                        )

                        if st.button(
                            "Открыть план",
                            key=bot["id"] + "draft",
                        ):
                            move(
                                "3. ИИ-Центр",
                                bot_id=bot["id"],
                            )

            if not active and not drafts:
                panel(
                    "История сохранена",
                    "Все твои боты отмечены "
                    "как завершённые. "
                    "Открой их в ИИ-Центре "
                    "или подготовь следующий план.",
                    True,
                )

                add_actions(
                    "home_closed_"
                )

        with st.expander(
            "Подключения и режим работы"
        ):
            st.write(
                "Хранилище: "
                + (
                    "PostgreSQL"
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
                "Цена обновляется "
                "при выполнении страницы. "
                "Telegram — по кнопке. "
                "Фоновый мониторинг не запущен."
            )

            if not DB_URL:
                st.warning(
                    "Для постоянного внешнего хранения "
                    "настрой DATABASE_URL. "
                    "Скачивай резервные копии."
                )

    elif page == "2. Сканер":
        scanner()

    elif page == "3. ИИ-Центр":
        panel(
            "Контроль ботов",
            "Что происходит, какое правило сработало "
            "и что проверить на OKX.",
        )

        st.caption(
            "ИИ-Центр использует правила твоего плана, "
            "а не прогнозирующую нейросеть."
        )

        if not bots:
            panel(
                "Перенеси своего бота сюда",
                "Выбери DCA или Grid, "
                "сохрани настройки "
                "и внеси фактическую позицию с OKX. "
                "После этого здесь появятся "
                "уровни, резерв и действия по плану.",
                True,
            )

            add_actions(
                "control_empty_"
            )

        else:
            strategy = st.radio(
                "Стратегия",
                ["Все", "DCA", "Grid"],
                horizontal=True,
                key="control_strategy",
            )

            state_filter = st.radio(
                "Состояние",
                [
                    "Все",
                    "В работе",
                    "Планы",
                    "Завершённые",
                ],
                horizontal=True,
                key="control_state",
            )

            mapping = {
                "В работе": "Работает",
                "Планы": "Черновик",
                "Завершённые": "Закрыт",
            }

            selected = [
                bot for bot in bots
                if (
                    strategy == "Все"
                    or bot["strategy"] == strategy
                )
                and (
                    state_filter == "Все"
                    or bot.get("lifecycle")
                    == mapping[state_filter]
                )
            ]

            focus = st.session_state.get(
                "focus_bot"
            )

            if focus:
                selected.sort(
                    key=lambda bot: bot["id"] != focus
                )

            if selected:
                show_cards(selected)

            else:
                panel(
                    "Посмотрим остальные боты?",
                    "Сейчас выбран фильтр, "
                    "под который не подходит "
                    "ни один сохранённый бот. "
                    "Твои остальные карточки на месте.",
                    True,
                )

                if st.button(
                    "Показать всех ботов"
                ):
                    st.session_state[
                        "reset_control_filters"
                    ] = True

                    st.rerun()

                add_actions(
                    "control_filtered_"
                )

    elif page in (
        "4. DCA",
        "5. Grid",
    ):
        strategy = (
            "DCA"
            if page == "4. DCA"
            else "Grid"
        )

        panel(
            strategy,
            (
                "Усреднение, TP и контроль цикла."
                if strategy == "DCA"
                else (
                    "Диапазон, направление "
                    "и план добавления маржи."
                )
            ),
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
            creator(strategy)

        else:
            selected = [
                bot for bot in bots
                if bot["strategy"] == strategy
            ]

            if selected:
                show_cards(selected)

            else:
                panel(
                    "Первый "
                    + strategy
                    + " — начнём с плана",
                    "Добавь уже работающего бота "
                    "или подготовь настройки "
                    "перед запуском. "
                    "Всё сохранится "
                    "в отдельной карточке.",
                    True,
                )

                if st.button(
                    "Добавить " + strategy,
                    key=strategy + "empty_add",
                ):
                    move(
                        page,
                        (
                            "Long"
                            if strategy == "DCA"
                            else "Neutral"
                        ),
                    )

    elif page == "6. Журнал решений":
        panel(
            "Журнал решений",
            "Обновления позиций, сохранённые планы "
            "и твои действия. Время UTC.",
        )

        frame = history()

        if frame.empty:
            panel(
                "История начнётся с первого действия",
                "Сохрани план или обнови позицию — "
                "запись появится здесь автоматически.",
                True,
            )

            add_actions(
                "journal_empty_"
            )

        else:
            table(frame)

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
                "не складываются "
                "как заработанная прибыль."
            )

    else:
        settings(bots)


main()
