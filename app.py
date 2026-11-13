import os
import json
import time
import math
import uuid
import hmac
import html
import copy
import sqlite3

from contextlib import contextmanager
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

import numpy as np
import pandas as pd
import requests
import streamlit as st
import plotly.graph_objects as go

from plotly.subplots import make_subplots


# =========================================================
# КОНФИГУРАЦИЯ
# =========================================================

st.set_page_config(
    page_title="OKX Terminal Pro",
    layout="wide",
    initial_sidebar_state="expanded",
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
    "TRX", "LTC", "NEAR", "APT", "ARB",
    "OP", "SUI", "PEPE", "INJ",
]

API = "https://www.okx.com/api/v5"
HOUR = 3_600_000
DAY = 24 * HOUR
DB_READY = False

CASES = {
    "Базовый": {
        "fee_mult": 1.0,
        "half_spread": 0.0002,
        "slippage": 0.0003,
        "synthetic_funding": 0.0001,
    },
    "Стресс": {
        "fee_mult": 1.5,
        "half_spread": 0.0005,
        "slippage": 0.0009,
        "synthetic_funding": 0.0002,
    },
    "Кризис": {
        "fee_mult": 2.0,
        "half_spread": 0.0010,
        "slippage": 0.0030,
        "synthetic_funding": 0.0003,
    },
}

DEFAULT_DCA = {
    "tp": 1.5,
    "step": 2.0,
    "so_count": 4,
    "mart": 1.2,
    "leverage": 3.0,
}


# =========================================================
# ОБЩИЕ ФУНКЦИИ
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
    secret("DATABASE_URL", secret("DB_URL", ""))
).strip()

DB_FILE = str(
    secret("SQLITE_PATH", "bots.sqlite3")
)


def now():
    return datetime.now(timezone.utc).isoformat()


def number_value(value, default=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except (ValueError, TypeError):
        return default


def fmt(value, digits=2):
    return "—" if value is None else f"{value:,.{digits}f}"


def direction_sign(value):
    return {"Long": 1, "Short": -1, "Neutral": 0}.get(value, 0)


def canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
    )


def age_hours(value):
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return max(
            0.0,
            (
                datetime.now(timezone.utc) - dt
            ).total_seconds() / 3600,
        )
    except (ValueError, TypeError):
        return float("inf")


def ni(label, value, key, low=0.0, high=None, integer=False):
    cast = int if integer else float
    args = {"label": label, "key": key}

    if key not in st.session_state:
        args["value"] = cast(value)

    if low is not None:
        args["min_value"] = cast(low)

    if high is not None:
        args["max_value"] = cast(high)

    if integer:
        args["step"] = 1

    return st.number_input(**args)


def route(page, direction=None, template=None, focus=None):
    st.session_state["_route"] = {
        "page": page,
        "direction": direction,
        "template": template or {},
        "focus": focus,
    }
    st.rerun()


def apply_route():
    request = st.session_state.pop("_route", None)

    if request:
        page = request["page"]
        st.session_state["page"] = page

        if page in ("DCA", "Grid"):
            st.session_state[page + "mode"] = (
                "Мои боты" if request["focus"] else "Добавить бота"
            )

            if request["direction"]:
                st.session_state[
                    page + "direction"
                ] = request["direction"]

            for key, value in request["template"].items():
                st.session_state[page + key] = value

        if request["focus"]:
            st.session_state["focus"] = request["focus"]

    if st.session_state.get("page") not in PAGES:
        st.session_state["page"] = "Главная"


# =========================================================
# ИНТЕРФЕЙС
# =========================================================

def design():
    st.markdown(
        """
<style>
.stApp {
    background:
        radial-gradient(
            1000px 600px at 8% -10%,
            rgba(0,255,157,.08),
            transparent 60%
        ),
        #070b13 !important;
    color: #e8ecf4;
    color-scheme: dark;
}
.block-container {
    max-width: 1400px;
    padding-top: 1.5rem;
}
h1,h2,h3,h4 {
    color: #edf3ff !important;
}
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,
[data-testid="stWidgetLabel"] p,
[data-testid="stCheckbox"] p,
[data-testid="stExpander"] summary p {
    color: #e8ecf4 !important;
}
[data-testid="stCaptionContainer"] p {
    color: #b7c4d8 !important;
}
[data-testid="stSidebar"] {
    background: #0b1220 !important;
    border-right: 1px solid #29384f;
}
[data-testid="stMetric"] {
    background: #121c2c;
    border: 1px solid #2b3a50;
    border-radius: 14px;
    padding: 15px;
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
    border-radius: 10px;
    min-height: 44px;
    font-weight: 700;
}
.stButton button p,
.stFormSubmitButton button p,
.stDownloadButton button p {
    color: inherit !important;
}
.stButton button:disabled,
.stFormSubmitButton button:disabled {
    background: #cbd5e1 !important;
    color: #475569 !important;
    opacity: 1 !important;
}
[class*="st-key-action_"][class*="_long"] button {
    background: #166534 !important;
    color: white !important;
    border: 2px solid #4ade80 !important;
}
[class*="st-key-action_"][class*="_short"] button {
    background: #991b1b !important;
    color: white !important;
    border: 2px solid #f87171 !important;
}
[class*="st-key-action_"][class*="_neutral"] button {
    background: #facc15 !important;
    color: #302500 !important;
    border: 2px solid #eab308 !important;
}
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea {
    background: white !important;
    color: #172033 !important;
    -webkit-text-fill-color: #172033 !important;
}
[data-testid="stSelectbox"] [data-baseweb="select"]>div,
[role="listbox"],
[role="option"] {
    background: white !important;
    color: #172033 !important;
}
[data-testid="stSelectbox"] span,
[data-testid="stSelectbox"] input {
    color: #172033 !important;
    -webkit-text-fill-color: #172033 !important;
}
[data-testid="stRadio"] [role="radiogroup"]>label {
    background: white !important;
    border: 2px solid #cbd5e1;
    border-radius: 10px;
    padding: 8px 11px !important;
    margin: 3px !important;
}
[data-testid="stRadio"] [role="radiogroup"]>label p {
    color: #172033 !important;
}
[data-testid="stAlert"] {
    background: #eef4ff !important;
    border: 1px solid #b6c9e8 !important;
}
[data-testid="stAlert"] p,
[data-testid="stAlert"] li {
    color: #172033 !important;
}
.table-wrap {
    overflow: auto;
    max-height: 650px;
    border: 1px solid #2b3a50;
    border-radius: 10px;
    margin-bottom: 12px;
}
.table-wrap table {
    width: 100%;
    border-collapse: collapse;
    background: #101827;
}
.table-wrap th {
    background: #182338 !important;
    color: #edf3ff !important;
    position: sticky;
    top: 0;
    padding: 10px;
    border: 1px solid #29384f;
    white-space: nowrap;
}
.table-wrap td {
    padding: 9px 11px;
    border: 1px solid #243249;
}
</style>
        """,
        unsafe_allow_html=True,
    )


def color_signal(value):
    value = str(value).strip().upper()

    if value in ("LONG", "ЛОНГ"):
        color = "#4ade80"
    elif value in ("SHORT", "ШОРТ"):
        color = "#fb7185"
    elif value in ("GRID", "NEUTRAL"):
        color = "#facc15"
    else:
        color = "#b8c4d8"

    return f"color:{color};background-color:#101827;font-weight:700;"


def style_df(frame, escape=False):
    formats = {
        column: "{:,.2f}"
        for column in frame.select_dtypes(
            include="number"
        ).columns
    }

    for column in ("Цена", "Средняя"):
        if column in frame:
            formats[column] = "{:,.6f}"

    for column in ("Циклов", "Стопов", "Условных ликвидаций"):
        if column in frame:
            formats[column] = "{:,.0f}"

    result = (
        frame.style
        .set_properties(**{
            "background-color": "#101827",
            "color": "#e8ecf4",
        })
        .format(
            formats,
            na_rep="—",
            escape="html" if escape else None,
        )
    )

    if escape:
        result = result.format_index(
            axis=1,
            escape="html",
        )

    for column in ("Сигнал", "Направление"):
        if column in frame:
            result = result.map(
                color_signal,
                subset=[column],
            )

    return result


def table(frame):
    if frame.empty:
        return

    rendered = (
        style_df(frame, escape=True)
        .hide(axis="index")
        .to_html()
    )

    st.markdown(
        '<div class="table-wrap">' + rendered + '</div>',
        unsafe_allow_html=True,
    )


def login():
    password = str(secret("APP_PASSWORD"))

    if not password.strip():
        st.error(
            "Задай APP_PASSWORD в Streamlit Secrets. "
            "Без пароля вход заблокирован."
        )
        st.stop()

    if st.session_state.get("_authenticated"):
        return

    st.title("OKX Terminal Pro")

    with st.form("login", clear_on_submit=True):
        entered = st.text_input("Пароль", type="password")
        submitted = st.form_submit_button(
            "Войти",
            use_container_width=True,
        )

    if submitted:
        if hmac.compare_digest(
            entered.encode(),
            password.encode(),
        ):
            st.session_state["_authenticated"] = True
            st.rerun()
        else:
            st.error("Неверный пароль.")

    st.stop()


# =========================================================
# ПОСТОЯННОЕ ХРАНЕНИЕ
# =========================================================

@contextmanager
def database():
    if not DB_URL:
        raise ValueError(
            "DATABASE_URL не настроен. "
            "Сохранение в память не используется."
        )

    import psycopg2

    connection = None

    try:
        connection = psycopg2.connect(
            DB_URL,
            connect_timeout=10,
            application_name="okx_terminal",
        )
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
    cursor.execute(
        statement.replace("?", "%s"),
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


def record(connection, bot_id, title, details):
    sql(
        connection,
        "INSERT INTO terminal_events VALUES (?, ?, ?, ?, ?)",
        (
            str(uuid.uuid4()),
            bot_id,
            now(),
            title,
            details,
        ),
    )


def normalize(raw):
    bot = json.loads(canonical(raw))

    if bot.get("strategy") not in ("DCA", "Grid"):
        raise ValueError("Неизвестная стратегия.")

    if bot.get("direction") not in ("Long", "Short", "Neutral"):
        raise ValueError("Неизвестное направление.")

    if (
        bot["strategy"] == "DCA"
        and bot["direction"] == "Neutral"
    ):
        raise ValueError("DCA Neutral не поддерживается.")

    bot["coin"] = str(
        bot.get("coin", "")
    ).strip().upper().replace("ARBITRUM", "ARB")

    if not bot["coin"].isalnum():
        raise ValueError("Неверная монета.")

    bot.setdefault("name", bot["coin"] + " " + bot["strategy"])
    bot.setdefault("market", "SWAP")
    bot.setdefault("created_at", now())
    bot.setdefault("lifecycle", "Черновик")

    if bot["lifecycle"] not in ("Черновик", "Работает", "Закрыт"):
        raise ValueError("Неизвестный статус.")

    for key in ("settings", "position"):
        if isinstance(bot.get(key), str):
            bot[key] = json.loads(bot[key])
        bot.setdefault(key, {})

    defaults = {
        "entry": 0,
        "tp": 1.5,
        "step": 2.0,
        "so_count": 4,
        "mart": 1.2,
        "base_amount": 10,
        "first_so": 10,
        "base_margin": 100,
        "reserve": 50,
        "leverage": 3,
        "lower": 0,
        "upper": 0,
        "grids": 10,
        "target_price": 0,
        "stop_price": 0,
        "stop_lower": 0,
        "stop_upper": 0,
        "max_loss": 0,
        "danger_pct": 3,
        "stale_hours": 6,
        "liq_warn": 10,
    }

    settings = bot["settings"]

    for key, default in defaults.items():
        value = float(settings.get(key, default))

        if not math.isfinite(value):
            raise ValueError("Неверный параметр: " + key)

        settings[key] = (
            int(value)
            if key in ("so_count", "grids")
            else value
        )

    settings.setdefault(
        "total_budget",
        settings["base_margin"] + settings["reserve"],
    )

    bot["position"].setdefault(
        "realized_pnl",
        number_value(settings.get("realized_pnl")),
    )

    return bot


def load_bots():
    with database() as connection:
        rows = sql(
            connection,
            "SELECT document, revision FROM terminal_bots",
        ).fetchall()

    bots = []

    for raw, revision in rows:
        bot = normalize(json.loads(raw))
        bot["_revision"] = revision
        bots.append(bot)

    return sorted(
        bots,
        key=lambda item: item.get("updated_at", ""),
        reverse=True,
    )


def save_bot(bot, title, details):
    document = normalize(bot)
    revision = document.pop("_revision", None)
    document["updated_at"] = now()
    raw = canonical(document)

    with database() as connection:
        if revision is None:
            result = sql(
                connection,
                """
                INSERT INTO terminal_bots VALUES (?, ?, 1)
                ON CONFLICT (id) DO NOTHING
                RETURNING revision
                """,
                (document["id"], raw),
            ).fetchone()
        else:
            result = sql(
                connection,
                """
                UPDATE terminal_bots
                SET document=?, revision=revision+1
                WHERE id=? AND revision=?
                RETURNING revision
                """,
                (raw, document["id"], revision),
            ).fetchone()

        if result is None:
            raise ValueError(
                "Карточка уже сохранена или изменена "
                "в другой вкладке. Обнови список."
            )

        new_revision = result[0]

        record(
            connection,
            document["id"],
            title,
            details,
        )

    with database() as connection:
        saved = sql(
            connection,
            """
            SELECT document, revision
            FROM terminal_bots WHERE id=?
            """,
            (document["id"],),
        ).fetchone()

    if not saved or saved != (raw, new_revision):
        raise ValueError(
            "Запись отправлена, но проверка не совпала. "
            "Обнови список перед повтором."
        )


def load_events():
    with database() as connection:
        rows = sql(
            connection,
            """
            SELECT bot_id, created_at, title, details
            FROM terminal_events
            ORDER BY created_at DESC LIMIT 5000
            """,
        ).fetchall()

    return pd.DataFrame(
        rows,
        columns=["Бот ID", "Дата UTC", "Событие", "Подробности"],
    )


def export_backup():
    with database() as connection:
        sql(
            connection,
            """
            SET TRANSACTION ISOLATION LEVEL
            REPEATABLE READ READ ONLY
            """,
        )

        bots = [
            json.loads(row[0])
            for row in sql(
                connection,
                "SELECT document FROM terminal_bots",
            ).fetchall()
        ]

        events = [
            {
                "bot_id": row[0],
                "created_at": row[1],
                "title": row[2],
                "details": row[3],
            }
            for row in sql(
                connection,
                """
                SELECT bot_id, created_at, title, details
                FROM terminal_events ORDER BY created_at
                """,
            ).fetchall()
        ]

    return json.dumps(
        {
            "version": 18,
            "created_at": now(),
            "bots": bots,
            "events": events,
        },
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")


def import_backup(payload):
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("bots"), list)
        or len(payload["bots"]) > 1000
    ):
        raise ValueError("Неверный формат копии.")

    prepared = []
    mapping = {}

    for raw in payload["bots"]:
        bot = normalize(raw)
        old_id = str(bot.get("id", ""))

        if old_id and old_id in mapping:
            raise ValueError("В копии повторяются ID.")

        bot.pop("_revision", None)
        bot["id"] = str(uuid.uuid4())
        bot["lifecycle"] = "Черновик"
        bot["updated_at"] = now()
        bot["position"]["last_check"] = ""

        if old_id:
            mapping[old_id] = bot["id"]

        prepared.append(bot)

    events = payload.get("events", [])

    if not isinstance(events, list):
        raise ValueError("Неверный журнал копии.")

    with database() as connection:
        for bot in prepared:
            sql(
                connection,
                "INSERT INTO terminal_bots VALUES (?, ?, 1)",
                (bot["id"], canonical(bot)),
            )
            record(
                connection,
                bot["id"],
                "Импорт",
                "Добавлена копия. Нужна сверка.",
            )

        for event in events:
            if not isinstance(event, dict):
                raise ValueError("Неверное событие.")

            old_id = str(
                event.get(
                    "bot_id",
                    event.get("Бот ID", ""),
                )
            )
            new_id = mapping.get(old_id)

            if new_id:
                record(
                    connection,
                    new_id,
                    "Импорт: " + str(
                        event.get(
                            "title",
                            event.get("Событие", ""),
                        )
                    ),
                    str(
                        event.get(
                            "created_at",
                            event.get("Дата UTC", ""),
                        )
                    )
                    + " · "
                    + str(
                        event.get(
                            "details",
                            event.get("Подробности", ""),
                        )
                    ),
                )

    return len(prepared)


# =========================================================
# HTTP И РЫНОЧНЫЕ ДАННЫЕ
# =========================================================

class RateLimiter:
    def __init__(self, interval=0.25):
        self.interval = interval
        self.lock = Lock()
        self.next_at = 0.0

    def wait(self):
        with self.lock:
            delay = self.next_at - time.monotonic()

            if delay > 0:
                time.sleep(delay)

            self.next_at = time.monotonic() + self.interval


LIMITER = RateLimiter()


def okx_get(path, params, limiter=None):
    limiter = limiter or LIMITER
    last_error = None

    for attempt in range(3):
        limiter.wait()

        try:
            response = requests.get(
                API + path,
                params=params,
                timeout=(5, 20),
            )
            response.raise_for_status()
            payload = response.json()

            if str(payload.get("code")) != "0":
                raise ValueError(
                    "OKX не подтвердил запрос."
                )

            return payload.get("data", [])

        except (
            requests.RequestException,
            ValueError,
        ) as exc:
            last_error = exc
            time.sleep(0.4 * (attempt + 1))

    raise ValueError(
        "Запрос OKX не выполнен: "
        + type(last_error).__name__
    ) from last_error


def instrument(coin, market="SWAP"):
    return (
        f"{coin}-USDT"
        + ("-SWAP" if market == "SWAP" else "")
    )


@st.cache_data(ttl=20, show_spinner=False)
def quote(coin, market="SWAP"):
    rows = okx_get(
        "/market/ticker",
        {"instId": instrument(coin, market)},
    )

    if not rows:
        raise ValueError("Инструмент не найден.")

    row = rows[0]
    price = number_value(row.get("last"))
    timestamp = number_value(row.get("ts"))

    if (
        price <= 0
        or timestamp <= 0
        or abs(time.time() - timestamp / 1000) > 180
    ):
        raise ValueError("Нет свежей цены.")

    return {
        "price": price,
        "ts": timestamp,
        "volume": (
            number_value(row.get("volCcy24h"))
            * (price if market == "SWAP" else 1)
        ),
    }


def parse_candles(rows):
    values = []

    for row in rows:
        if len(row) >= 9:
            confirmed = str(row[8]) == "1"
        elif len(row) >= 6:
            confirmed = str(row[5]) == "1"
        else:
            continue

        if confirmed:
            values.append([
                int(row[0]),
                *map(float, row[1:5]),
            ])

    frame = (
        pd.DataFrame(
            values,
            columns=["ts", "open", "high", "low", "close"],
        )
        .drop_duplicates("ts")
        .sort_values("ts")
        .reset_index(drop=True)
    )

    columns = ["open", "high", "low", "close"]

    if (
        frame.empty
        or not np.isfinite(
            frame[columns].to_numpy()
        ).all()
        or (frame[columns] <= 0).any().any()
    ):
        raise ValueError("Нет корректных закрытых свечей.")

    frame["time"] = pd.to_datetime(
        frame.ts,
        unit="ms",
        utc=True,
    )

    return frame


def history_candles(
    coin,
    start,
    end,
    bar="1H",
    mark=False,
    limiter=None,
):
    interval = {
        "1H": HOUR,
        "15m": 15 * 60_000,
        "1m": 60_000,
    }[bar]

    path = (
        "/market/history-mark-price-candles"
        if mark
        else "/market/history-candles"
    )

    after = end
    raw = []
    page_limit = int(
        math.ceil((end - start) / interval / 100)
    ) + 10

    for _ in range(page_limit):
        batch = okx_get(
            path,
            {
                "instId": instrument(coin),
                "bar": bar,
                "limit": "100",
                "after": str(after),
            },
            limiter,
        )

        if not batch:
            break

        raw.extend(batch)
        oldest = min(int(row[0]) for row in batch)

        if oldest <= start:
            break

        if oldest >= after:
            raise ValueError(
                "Пагинация истории не продвигается."
            )

        after = oldest

    frame = parse_candles(raw)
    frame = frame[
        (frame.ts >= start)
        & (frame.ts < end)
    ].reset_index(drop=True)

    expected = np.arange(
        start,
        end,
        interval,
        dtype=np.int64,
    )

    if (
        len(frame) != len(expected)
        or not np.array_equal(
            frame.ts.to_numpy(),
            expected,
        )
    ):
        kind = "Mark Price" if mark else "торговых"
        raise ValueError(
            f"{coin}: неполная история {kind} свечей."
        )

    return frame


# =========================================================
# ИНДИКАТОРЫ И ИСТОРИЧЕСКИЕ СИГНАЛЫ
# =========================================================

def rma(series, period=14):
    output = pd.Series(
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
            seed.append(float(value))

            if len(seed) == period:
                previous = sum(seed) / period
                output.loc[index] = previous
        else:
            previous = (
                previous * (period - 1) + float(value)
            ) / period
            output.loc[index] = previous

    return output


def indicators(frame):
    frame = frame.copy()
    difference = frame.close.diff()

    gain = rma(difference.clip(lower=0))
    loss = rma(-difference.clip(upper=0))

    rsi = 100 - 100 / (1 + gain / loss)
    rsi.loc[(gain == 0) & (loss == 0)] = 50
    rsi.loc[(gain > 0) & (loss == 0)] = 100

    tr = pd.concat(
        [
            frame.high - frame.low,
            (frame.high - frame.close.shift()).abs(),
            (frame.low - frame.close.shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    tr.iloc[0] = np.nan

    atr = rma(tr)
    up = frame.high.diff()
    down = -frame.low.diff()

    plus = up.where((up > down) & (up > 0), 0.0)
    minus = down.where((down > up) & (down > 0), 0.0)
    plus.iloc[0] = np.nan
    minus.iloc[0] = np.nan

    plus = rma(plus)
    minus = rma(minus)

    total = plus + minus
    dx = 100 * (plus - minus).abs() / total
    dx.loc[total == 0] = 0

    frame["RSI"] = rsi
    frame["ATR %"] = atr / frame.close * 100
    frame["+DI"] = 100 * plus / atr
    frame["-DI"] = 100 * minus / atr
    frame["ADX"] = rma(dx)
    frame["EMA50"] = frame.close.ewm(
        span=50,
        adjust=False,
        min_periods=50,
    ).mean()

    frame.loc[
        atr == 0,
        ["+DI", "-DI"],
    ] = 0

    return frame


def daily_from_hours(hours):
    indexed = hours.set_index("time")

    daily = indexed.resample("1D").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
    })

    counts = indexed.close.resample("1D").count()
    daily = daily[counts == 24].copy()

    return indicators(daily)


def signal_daily(daily):
    output = daily.copy()
    output["signal"] = 0

    long_mask = (
        (output.ADX >= 25)
        & (output["+DI"] > output["-DI"])
        & (output.close > output.EMA50)
    )
    short_mask = (
        (output.ADX >= 25)
        & (output["-DI"] > output["+DI"])
        & (output.close < output.EMA50)
    )

    output.loc[long_mask, "signal"] = 1
    output.loc[short_mask, "signal"] = -1

    slope = output.EMA50.diff()

    output["regime"] = "Боковой"
    output.loc[
        (output.close > output.EMA50) & (slope > 0),
        "regime",
    ] = "Рост"
    output.loc[
        (output.close < output.EMA50) & (slope < 0),
        "regime",
    ] = "Падение"

    # Строка дня D содержит решение по полностью
    # завершившемуся дню D-1.
    return output[["signal", "regime"]].shift(1)


# =========================================================
# FUNDING
# =========================================================

def parse_funding_csv(text, coin):
    frame = pd.read_csv(
        __import__("io").StringIO(text)
    )

    required = {"coin", "fundingTime", "fundingRate"}

    if not required.issubset(frame.columns):
        raise ValueError(
            "CSV funding: нужны coin, fundingTime, fundingRate."
        )

    frame = frame[
        frame.coin.astype(str).str.upper() == coin.upper()
    ].copy()

    if frame.empty:
        raise ValueError(
            f"В CSV нет funding для {coin}."
        )

    frame["fundingTime"] = pd.to_numeric(
        frame.fundingTime,
        errors="raise",
    ).astype("int64")

    frame["fundingRate"] = pd.to_numeric(
        frame.fundingRate,
        errors="raise",
    )

    return frame[["fundingTime", "fundingRate"]]


def funding_history(coin, start, end, limiter=None):
    rows = []
    after = end

    for _ in range(30):
        batch = okx_get(
            "/public/funding-rate-history",
            {
                "instId": instrument(coin),
                "limit": "100",
                "after": str(after),
            },
            limiter,
        )

        if not batch:
            break

        rows.extend(batch)
        oldest = min(
            int(row["fundingTime"])
            for row in batch
        )

        if oldest <= start - 9 * HOUR:
            break

        if oldest >= after:
            break

        after = oldest

    if not rows:
        raise ValueError("История funding отсутствует.")

    return pd.DataFrame({
        "fundingTime": [
            int(row["fundingTime"])
            for row in rows
        ],
        "fundingRate": [
            float(row["fundingRate"])
            for row in rows
        ],
    })


def validate_funding(frame, start, end):
    frame = (
        frame.drop_duplicates("fundingTime")
        .sort_values("fundingTime")
        .reset_index(drop=True)
    )

    if (
        frame.empty
        or not np.isfinite(
            frame.fundingRate.to_numpy()
        ).all()
    ):
        raise ValueError("Некорректная история funding.")

    times = frame.fundingTime.to_numpy(dtype=np.int64)

    if (
        times[0] > start
        or times[-1] < end - 9 * HOUR
    ):
        raise ValueError(
            "Funding не покрывает период. "
            "Загрузи полный CSV либо явно выбери "
            "сценарный funding."
        )

    relevant = frame[
        (frame.fundingTime >= start - 9 * HOUR)
        & (frame.fundingTime < end)
    ].copy()

    if (
        len(relevant) > 1
        and relevant.fundingTime.diff().dropna().max()
        > 9 * HOUR
    ):
        raise ValueError(
            "В funding обнаружен большой временной разрыв."
        )

    if (relevant.fundingTime % HOUR != 0).any():
        raise ValueError(
            "События funding не на границе часа. "
            "Для этой реализации нужен отдельный "
            "событийный архив, а не округление времени."
        )

    return relevant


# =========================================================
# ПОДГОТОВКА ДАННЫХ ИССЛЕДОВАНИЯ
# =========================================================

def research_bundle(
    coin,
    days,
    end,
    bar,
    funding_mode,
    funding_csv,
    limiter=None,
):
    start = end - days * DAY
    warm_start = start - 70 * DAY

    hours = history_candles(
        coin,
        warm_start,
        end,
        "1H",
        False,
        limiter,
    )

    daily = daily_from_hours(hours)
    historical_signals = signal_daily(daily)

    if bar == "1H":
        trade = hours[
            hours.ts >= start
        ].copy().reset_index(drop=True)
    else:
        trade = history_candles(
            coin,
            start,
            end,
            bar,
            False,
            limiter,
        )

    mark = history_candles(
        coin,
        start,
        end,
        bar,
        True,
        limiter,
    ).rename(columns={
        "open": "mark_open",
        "high": "mark_high",
        "low": "mark_low",
        "close": "mark_close",
    })

    data = trade.merge(
        mark[
            [
                "ts",
                "mark_open",
                "mark_high",
                "mark_low",
                "mark_close",
            ]
        ],
        on="ts",
        how="left",
        validate="one_to_one",
    )

    day_index = data.time.dt.floor("D")

    data["signal"] = (
        day_index.map(historical_signals.signal)
        .fillna(0)
        .astype(int)
    )
    data["regime"] = (
        day_index.map(historical_signals.regime)
        .fillna("Не определено")
    )
    data["funding_rate"] = 0.0

    if funding_mode == "Фактический":
        if funding_csv.strip():
            funding = parse_funding_csv(
                funding_csv,
                coin,
            )
        else:
            funding = funding_history(
                coin,
                start,
                end,
                limiter,
            )

        funding = validate_funding(
            funding,
            start,
            end,
        )

        rate_map = (
            funding.groupby("fundingTime")
            .fundingRate.sum()
        )

        data["funding_rate"] = (
            data.ts.map(rate_map).fillna(0.0)
        )

    if data[
        [
            "mark_open",
            "mark_high",
            "mark_low",
            "mark_close",
        ]
    ].isna().any().any():
        raise ValueError("В Mark Price есть пропуски.")

    return data


@st.cache_data(
    ttl=600,
    max_entries=4,
    show_spinner=False,
)
def cached_bundle(
    coin,
    days,
    end,
    bar,
    funding_mode,
    funding_csv,
):
    return research_bundle(
        coin,
        days,
        end,
        bar,
        funding_mode,
        funding_csv,
    )


# =========================================================
# СЦЕНАРНАЯ МОДЕЛЬ ИСПОЛНЕНИЯ
# =========================================================

def fill_price(reference, side, costs, stop=False):
    adverse = (
        costs["half_spread"]
        + costs["slippage"] * (2.0 if stop else 1.0)
    )

    return reference * (1 + side * adverse)


# =========================================================
# РИСК-ДВИЖОК DCA
# =========================================================

class DCAEngine:
    """
    Отдельный условный счёт одного бота.

    Состояние не содержит историю свечей, поэтому
    копирование для двух OHLC-путей не копирует весь тест.

    MMR — постоянное введённое допущение.
    Это не полная модель ликвидации OKX.
    """

    def __init__(self, budget, config, case, risk, funding_mode):
        self.initial = float(budget)
        self.cash = float(budget)
        self.config = dict(config)

        self.costs = dict(CASES[case])
        self.fee = risk["taker_fee"] * self.costs["fee_mult"]
        self.risk = dict(risk)
        self.funding_mode = funding_mode

        self.position = None
        self.peak = float(budget)
        self.max_dd = 0.0
        self.minimum_equity = float(budget)

        self.day = None
        self.day_start = float(budget)
        self.day_blocked = False
        self.halted = False
        self.cooldown_until = 0

        self.cycles = 0
        self.stops = 0
        self.liquidations = 0
        self.blocked_orders = 0
        self.fees = 0.0
        self.funding_cash = 0.0
        self.max_margin = 0.0
        self.max_notional = 0.0
        self.max_cycle_hours = 0.0
        self.breakdown = {}

        self.last_price = None
        self.last_mark = None

    def open_pnl(self, mark):
        p = self.position

        if not p:
            return 0.0

        return p["side"] * p["qty"] * (mark - p["avg"])

    def equity_mark(self, mark):
        return self.cash + self.open_pnl(mark)

    def equity_exit(self, price, stop=True):
        p = self.position

        if not p:
            return self.cash

        execution = fill_price(
            price,
            -p["side"],
            self.costs,
            stop=stop,
        )

        return (
            self.cash
            + p["side"] * p["qty"] * (execution - p["avg"])
            - p["qty"] * execution * self.fee
        )

    def observe(self, price, mark):
        self.last_price = price
        self.last_mark = mark

        equity = min(
            self.equity_mark(mark),
            self.equity_exit(price),
        )

        self.peak = max(self.peak, equity)
        self.minimum_equity = min(
            self.minimum_equity,
            equity,
        )
        self.max_dd = max(
            self.max_dd,
            (self.peak - equity) / self.peak,
        )

        if self.position:
            self.max_notional = max(
                self.max_notional,
                self.position["qty"] * mark,
            )
            self.max_margin = max(
                self.max_margin,
                self.position["margin"],
            )

    def cycle_limit(self):
        limit = self.initial * self.risk["cycle_loss"]

        if self.risk["account_capital"] > 0:
            limit = min(
                limit,
                self.risk["account_capital"] * 0.01,
            )

        return limit

    def size_first_order(self, price, side, cfg):
        weights = [1.0] + [
            cfg["mart"] ** i
            for i in range(cfg["so_count"])
        ]

        first_fill = fill_price(
            price,
            side,
            self.costs,
        )

        stop_reference = first_fill * (
            1 - side * self.risk["outer_stop"]
        )

        if stop_reference <= 0:
            return 0.0

        stop_execution = fill_price(
            stop_reference,
            -side,
            self.costs,
            stop=True,
        )

        qty_unit = 0.0
        cost_unit = 0.0
        opening_fees = 0.0
        worst_loss = 0.0

        for index, weight in enumerate(weights):
            reference = (
                price
                if index == 0
                else first_fill * (
                    1 - side * cfg["step"] * index / 100
                )
            )

            if reference <= 0:
                return 0.0

            if side * (reference - stop_reference) <= 0:
                break

            execution = fill_price(
                reference,
                side,
                self.costs,
            )

            quantity = weight / execution
            qty_unit += quantity
            cost_unit += weight
            opening_fees += weight * self.fee

            pnl = side * (
                qty_unit * stop_execution - cost_unit
            )

            exit_fee = (
                qty_unit * stop_execution * self.fee
            )

            funding_reserve = (
                cost_unit
                * self.costs["synthetic_funding"]
                * 9
            )

            loss = (
                -pnl
                + opening_fees
                + exit_fee
                + funding_reserve
            )

            worst_loss = max(worst_loss, loss)

        if worst_loss <= 0:
            return 0.0

        total_weight = sum(weights)

        by_risk = self.cycle_limit() / worst_loss
        by_budget = max(0.0, self.cash) / (
            total_weight / cfg["leverage"]
            + worst_loss
            + total_weight * self.fee
        )

        return max(0.0, min(by_risk, by_budget))

    def enter(self, price, mark, timestamp, signal, regime):
        if (
            self.position
            or self.halted
            or self.day_blocked
            or timestamp < self.cooldown_until
            or signal not in (-1, 1)
        ):
            return

        cfg = dict(self.config)

        nominal = self.size_first_order(
            price,
            signal,
            cfg,
        )

        if nominal <= 0:
            self.blocked_orders += 1
            return

        execution = fill_price(
            price,
            signal,
            self.costs,
        )
        fee = nominal * self.fee
        margin = nominal / cfg["leverage"]

        if self.cash < margin + fee:
            self.blocked_orders += 1
            return

        start_cash = self.cash
        self.cash -= fee
        self.fees += fee

        self.position = {
            "side": signal,
            "qty": nominal / execution,
            "avg": execution,
            "entry": execution,
            "base_nominal": nominal,
            "margin": margin,
            "so": 0,
            "so_disabled": False,
            "opened": timestamp,
            "cycle_start_cash": start_cash,
            "risk_limit": self.cycle_limit(),
            "cfg": cfg,
            "regime": regime,
        }

        self.observe(price, mark)

    def close(self, price, mark, timestamp, reason):
        p = self.position

        if not p:
            return

        stop_execution = reason != "TP"

        execution = fill_price(
            price,
            -p["side"],
            self.costs,
            stop=stop_execution,
        )

        gross = (
            p["side"]
            * p["qty"]
            * (execution - p["avg"])
        )
        fee = p["qty"] * execution * self.fee

        self.cash += gross - fee
        self.fees += fee
        self.cycles += 1

        hours = (timestamp - p["opened"]) / HOUR
        self.max_cycle_hours = max(
            self.max_cycle_hours,
            hours,
        )

        side_name = "Long" if p["side"] == 1 else "Short"
        key = side_name + " / " + p["regime"]

        item = self.breakdown.setdefault(
            key,
            {"pnl": 0.0, "cycles": 0},
        )

        item["pnl"] += self.cash - p["cycle_start_cash"]
        item["cycles"] += 1

        if reason != "TP":
            self.stops += 1
            self.cooldown_until = (
                timestamp + self.risk["cooldown_hours"] * HOUR
            )

        if reason == "MMR":
            self.liquidations += 1
            self.halted = True

        if reason == "ACCOUNT_DD":
            self.halted = True

        if reason == "DAY":
            self.day_blocked = True

        self.position = None
        self.observe(price, mark)

    def equity_threshold_price(self, target):
        p = self.position

        if not p:
            return None

        side = p["side"]

        kappa = 1 - side * (
            self.costs["half_spread"]
            + 2 * self.costs["slippage"]
        )

        denominator = p["qty"] * kappa * (side - self.fee)

        if abs(denominator) < 1e-12:
            return None

        return (
            target
            - self.cash
            + side * p["qty"] * p["avg"]
        ) / denominator

    def mmr_price(self):
        p = self.position

        if not p:
            return None

        denominator = p["qty"] * (
            p["side"] - self.risk["mmr"] - self.fee
        )

        if abs(denominator) < 1e-12:
            return None

        return (
            p["side"] * p["qty"] * p["avg"]
            - self.cash
        ) / denominator

    def check_now(self, price, mark, timestamp):
        p = self.position

        if not p:
            self.observe(price, mark)
            return

        equity = self.equity_exit(price)
        mark_equity = self.equity_mark(mark)

        maintenance = (
            p["qty"] * mark
            * (self.risk["mmr"] + self.fee)
        )

        if mark_equity <= maintenance:
            reason = "MMR"
        elif equity <= self.peak * (1 - self.risk["account_dd"]):
            reason = "ACCOUNT_DD"
        elif equity <= self.day_start * (1 - self.risk["daily_loss"]):
            reason = "DAY"
        elif equity <= p["cycle_start_cash"] - p["risk_limit"]:
            reason = "RISK"
        elif (
            p["side"] * (
                price
                - p["entry"] * (
                    1 - p["side"] * self.risk["outer_stop"]
                )
            )
            <= 0
        ):
            reason = "PRICE"
        elif timestamp - p["opened"] >= self.risk["max_hours"] * HOUR:
            reason = "TIME"
        else:
            reason = None

        if reason:
            self.close(price, mark, timestamp, reason)
        else:
            self.observe(price, mark)

    def add_safety(self, price, mark):
        p = self.position

        if not p:
            return

        cfg = p["cfg"]
        nominal = (
            p["base_nominal"]
            * cfg["mart"] ** p["so"]
        )

        execution = fill_price(
            price,
            p["side"],
            self.costs,
        )

        fee = nominal * self.fee
        margin = nominal / cfg["leverage"]

        if (
            self.equity_mark(mark)
            < p["margin"] + margin + fee
        ):
            p["so_disabled"] = True
            self.blocked_orders += 1
            return

        old = copy.deepcopy(p)
        old_cash = self.cash

        new_quantity = nominal / execution

        p["avg"] = (
            p["qty"] * p["avg"] + nominal
        ) / (
            p["qty"] + new_quantity
        )
        p["qty"] += new_quantity
        p["margin"] += margin

        self.cash -= fee

        stop_reference = p["entry"] * (
            1 - p["side"] * self.risk["outer_stop"]
        )

        projected = self.equity_exit(
            stop_reference,
            stop=True,
        ) - p["cycle_start_cash"]

        if projected < -p["risk_limit"] - 1e-8:
            self.position = old
            self.position["so_disabled"] = True
            self.cash = old_cash
            self.blocked_orders += 1
            return

        self.fees += fee
        p["so"] += 1
        self.observe(price, mark)

    def advance(self, a, b, ma, mb, timestamp):
        price = a
        mark = ma

        self.check_now(price, mark, timestamp)

        for _ in range(20):
            p = self.position

            if not p:
                self.observe(b, mb)
                return

            delta = b - price
            mark_delta = mb - mark

            events = []

            def add_price_event(level, name, priority):
                if (
                    level is None
                    or not math.isfinite(level)
                    or level <= 0
                    or abs(delta) < 1e-12
                ):
                    return

                fraction = (level - price) / delta

                if 1e-9 < fraction <= 1 + 1e-9:
                    events.append((
                        min(1.0, fraction),
                        priority,
                        name,
                        level,
                    ))

            cfg = p["cfg"]

            target = p["avg"] * (
                1 + p["side"] * cfg["tp"] / 100
            )

            add_price_event(target, "TP", 5)

            outer = p["entry"] * (
                1 - p["side"] * self.risk["outer_stop"]
            )
            add_price_event(outer, "PRICE", 1)

            limits = [
                (
                    p["cycle_start_cash"] - p["risk_limit"],
                    "RISK",
                ),
                (
                    self.peak * (1 - self.risk["account_dd"]),
                    "ACCOUNT_DD",
                ),
                (
                    self.day_start * (1 - self.risk["daily_loss"]),
                    "DAY",
                ),
            ]

            for target_equity, reason in limits:
                level = self.equity_threshold_price(
                    target_equity
                )

                if (
                    level is not None
                    and p["side"] * delta < 0
                ):
                    add_price_event(level, reason, 0)

            if (
                not p["so_disabled"]
                and p["so"] < cfg["so_count"]
                and p["side"] * delta < 0
            ):
                level = p["entry"] * (
                    1
                    - p["side"]
                    * cfg["step"]
                    * (p["so"] + 1)
                    / 100
                )
                add_price_event(level, "SO", 4)

            liquidation_mark = self.mmr_price()

            if (
                liquidation_mark is not None
                and abs(mark_delta) > 1e-12
                and p["side"] * mark_delta < 0
            ):
                fraction = (
                    liquidation_mark - mark
                ) / mark_delta

                if 1e-9 < fraction <= 1 + 1e-9:
                    events.append((
                        min(1.0, fraction),
                        -1,
                        "MMR",
                        price + delta * fraction,
                    ))

            if not events:
                self.check_now(b, mb, timestamp)
                return

            fraction, _, reason, event_price = min(events)

            event_mark = mark + mark_delta * fraction

            price = event_price
            mark = event_mark

            if reason == "SO":
                self.add_safety(price, mark)
                self.check_now(price, mark, timestamp)
            else:
                self.close(
                    price,
                    mark,
                    timestamp,
                    reason,
                )

        raise ValueError(
            "Превышено число событий в одном сегменте свечи."
        )

    def bar(self, row, order):
        timestamp = int(row["ts"])
        price = float(row["open"])
        mark = float(row["mark_open"])

        day = timestamp // DAY

        if day != self.day:
            self.day = day
            self.day_start = self.equity_exit(price)
            self.day_blocked = False

        if self.position:
            if self.funding_mode == "Фактический":
                funding = (
                    -self.position["side"]
                    * self.position["qty"]
                    * mark
                    * float(row["funding_rate"])
                )
            else:
                funding = (
                    -self.position["qty"]
                    * mark
                    * self.costs["synthetic_funding"]
                    if timestamp % (8 * HOUR) == 0
                    else 0.0
                )

            self.cash += funding
            self.funding_cash += funding

        self.check_now(price, mark, timestamp)

        signal = int(row["signal"])

        if (
            self.position
            and signal == -self.position["side"]
        ):
            self.close(
                price,
                mark,
                timestamp,
                "FLIP",
            )

        if not self.position:
            self.enter(
                price,
                mark,
                timestamp,
                signal,
                str(row["regime"]),
            )

        trade_nodes = [
            float(row[name])
            for name in order
        ]
        mark_nodes = [
            float(row["mark_" + name])
            for name in order
        ]

        for index in range(1, len(order)):
            self.advance(
                trade_nodes[index - 1],
                trade_nodes[index],
                mark_nodes[index - 1],
                mark_nodes[index],
                timestamp,
            )

        self.observe(
            float(row["close"]),
            float(row["mark_close"]),
        )

    def summary(self):
        if self.last_price is None:
            equity = self.cash
        else:
            equity = min(
                self.equity_mark(self.last_mark),
                self.equity_exit(self.last_price),
            )

        return {
            "Доходность %": (equity / self.initial - 1) * 100,
            "Результат USDT": equity - self.initial,
            "Equity USDT": equity,
            "Просадка %": self.max_dd * 100,
            "Циклов": self.cycles,
            "Стопов": self.stops,
            "Условных ликвидаций": self.liquidations,
            "Комиссии USDT": self.fees,
            "Funding USDT": self.funding_cash,
            "Макс. номинал": self.max_notional,
            "Макс. маржа": self.max_margin,
            "Отклонений СО": self.blocked_orders,
            "Макс. часы закрытой серии": self.max_cycle_hours,
            "Открытая серия": self.position is not None,
            "Статус": (
                "Отклонить"
                if self.liquidations
                or self.halted
                or equity <= self.initial
                else "Исследование, не допуск к запуску"
            ),
        }


def simulate_research(data, engine):
    curve = []

    for row in data.to_dict("records"):
        alternatives = []

        for order in (
            ("open", "high", "low", "close"),
            ("open", "low", "high", "close"),
        ):
            candidate = copy.deepcopy(engine)
            previous_min = candidate.minimum_equity

            candidate.bar(row, order)

            local_min = min(
                candidate.equity_exit(float(row["close"])),
                candidate.minimum_equity,
            )

            alternatives.append((
                local_min,
                candidate.equity_exit(float(row["close"])),
                candidate,
            ))

        # Это консервативный сценарий из двух путей,
        # а не восстановленная последовательность торгов.
        engine = min(
            alternatives,
            key=lambda item: (item[0], item[1]),
        )[2]

        curve.append({
            "time": row["time"],
            "equity": min(
                engine.equity_mark(float(row["mark_close"])),
                engine.equity_exit(float(row["close"])),
            ),
        })

    return engine, pd.DataFrame(curve)


# =========================================================
# WALK-FORWARD
# =========================================================

def select_train_parameters(data, budget, risk, funding_mode, optimize):
    candidates = [dict(DEFAULT_DCA)]

    if optimize:
        candidates.extend([
            {**DEFAULT_DCA, "mart": 1.0},
            {**DEFAULT_DCA, "step": 2.4},
        ])

    records = []

    for config in candidates:
        engine = DCAEngine(
            budget,
            config,
            "Базовый",
            risk,
            funding_mode,
        )

        engine, curve = simulate_research(data, engine)
        result = engine.summary()

        chunks = np.array_split(
            curve.equity.to_numpy(),
            3,
        )

        chunk_returns = []
        previous = budget

        for chunk in chunks:
            if len(chunk):
                chunk_returns.append(
                    chunk[-1] / previous - 1
                )
                previous = chunk[-1]

        score = (
            min(chunk_returns)
            - 1.5 * engine.max_dd
        )

        if engine.liquidations or engine.halted:
            score = -float("inf")

        records.append((score, config, result))

    best = max(records, key=lambda item: item[0])

    if not math.isfinite(best[0]):
        # Ничего не объявляется пригодным.
        # Базовый вариант всё равно проверяется OOS,
        # результат будет помечен ограничениями.
        return dict(DEFAULT_DCA), "Train не прошёл ограничения"

    return dict(best[1]), f"Train score: {best[0]:.4f}"


def walk_forward(
    data,
    budget,
    risk,
    funding_mode,
    folds,
    optimize,
):
    first_ts = int(data.ts.iloc[0])
    test_start = first_ts + 180 * DAY

    selected = []

    for index in range(folds):
        left = test_start + index * 30 * DAY
        right = left + 30 * DAY

        train = data[
            (data.ts >= left - 180 * DAY)
            & (data.ts < left)
        ]

        config, note = select_train_parameters(
            train,
            budget,
            risk,
            funding_mode,
            optimize,
        )

        selected.append((left, right, config, note))

    holdout_start = test_start + folds * 30 * DAY
    holdout_end = holdout_start + 90 * DAY

    final_train = data[
        (data.ts >= holdout_start - 180 * DAY)
        & (data.ts < holdout_start)
    ]

    final_config, note = select_train_parameters(
        final_train,
        budget,
        risk,
        funding_mode,
        optimize,
    )

    selected.append((
        holdout_start,
        holdout_end,
        final_config,
        "Holdout 90 дней; " + note,
    ))

    result_rows = []
    curves = {}
    final_engines = {}

    for case in CASES:
        engine = DCAEngine(
            budget,
            DEFAULT_DCA,
            case,
            risk,
            funding_mode,
        )

        pieces = []

        for index, (left, right, config, note) in enumerate(selected):
            engine.config = dict(config)

            segment = data[
                (data.ts >= left)
                & (data.ts < right)
            ]

            starting_equity = (
                engine.equity_exit(float(segment.open.iloc[0]))
                if engine.last_price is not None
                else budget
            )

            engine, curve = simulate_research(
                segment,
                engine,
            )

            ending_equity = engine.summary()["Equity USDT"]

            result_rows.append({
                "Сценарий": case,
                "Окно": (
                    "Holdout"
                    if index == len(selected) - 1
                    else f"OOS {index + 1}"
                ),
                "Начало UTC": pd.to_datetime(
                    left,
                    unit="ms",
                    utc=True,
                ).isoformat(),
                "Конец UTC": pd.to_datetime(
                    right,
                    unit="ms",
                    utc=True,
                ).isoformat(),
                "Доходность окна %": (
                    (ending_equity / starting_equity - 1) * 100
                    if starting_equity > 0
                    else np.nan
                ),
                "Equity USDT": ending_equity,
                "Параметры новых серий": canonical(config),
                "Train": note,
            })

            pieces.append(curve)

        all_curve = pd.concat(
            pieces,
            ignore_index=True,
        )

        curves[case] = all_curve.set_index("time").equity
        final_engines[case] = engine

    summaries = [
        {"Сценарий": case, **engine.summary()}
        for case, engine in final_engines.items()
    ]

    return (
        pd.DataFrame(result_rows),
        pd.DataFrame(summaries),
        pd.DataFrame(curves),
        final_engines,
    )


# =========================================================
# НАСТРОЙКИ ИССЛЕДОВАНИЯ
# =========================================================

def research_controls(prefix):
    budget = st.number_input(
        "Общий бюджет одного бота, USDT",
        min_value=100.0,
        max_value=200.0,
        value=150.0,
        step=10.0,
        key=prefix + "budget",
    )

    with st.expander("Риск и исполнение"):
        taker_fee = st.number_input(
            "Твоя taker-комиссия за сторону, %",
            min_value=0.0,
            max_value=1.0,
            value=0.05,
            step=0.01,
            key=prefix + "fee",
        ) / 100

        cycle_loss = st.number_input(
            "Предел убытка серии, % бюджета бота",
            min_value=0.1,
            max_value=10.0,
            value=3.0,
            key=prefix + "cycle",
        ) / 100

        account_capital = st.number_input(
            "Капитал аккаунта для лимита 1%; 0 = неизвестен",
            min_value=0.0,
            value=0.0,
            key=prefix + "account",
        )

        mmr = st.number_input(
            "Условный MMR, % — не таблица рисков OKX",
            min_value=0.1,
            max_value=20.0,
            value=1.0,
            key=prefix + "mmr",
        ) / 100

        bar = st.selectbox(
            "Свечи исполнения",
            ["1H", "15m", "1m"],
            key=prefix + "bar",
        )

        funding_mode = st.selectbox(
            "Funding",
            ["Сценарный", "Фактический"],
            key=prefix + "funding",
        )

        upload = st.file_uploader(
            "CSV funding: coin,fundingTime,fundingRate",
            type=["csv"],
            key=prefix + "csv",
        )

        csv_text = (
            upload.getvalue().decode("utf-8-sig")
            if upload is not None
            else ""
        )

        st.caption(
            "fundingTime — Unix milliseconds. "
            "Ставка — доля: 0.0001 означает 0.01%. "
            "CSV должен покрывать весь период."
        )

    risk = {
        "taker_fee": taker_fee,
        "cycle_loss": cycle_loss,
        "account_capital": account_capital,
        "mmr": mmr,
        "outer_stop": 0.10,
        "daily_loss": 0.05,
        "account_dd": 0.10,
        "max_hours": 72.0,
        "cooldown_hours": 24.0,
    }

    return budget, risk, bar, funding_mode, csv_text


def research_warning(bar, funding_mode):
    st.warning(
        "Это исследовательская модель, не биржевой допуск. "
        "MMR постоянный, без tier-таблиц, ADL и режимов "
        "cross/portfolio margin. Размеры не округляются "
        "по историческим lotSz/minSz. "
        "Внутри свечи проверяются два OHLC-пути; "
        "это не реальная последовательность сделок."
    )

    if bar == "1H":
        st.info(
            "1H годится для предварительного отбора. "
            "Внутрисвечные результаты и просадка остаются "
            "приближёнными. Перепроверь на мелких свечах."
        )

    if funding_mode == "Сценарный":
        st.info(
            "Funding не фактический: списывается "
            "неблагоприятная ставка каждые 8 часов "
            "для обеих сторон. Базовый/Стресс/Кризис: "
            "0.01% / 0.02% / 0.03% от текущего номинала."
        )


def show_breakdown(engines):
    rows = []

    for case, engine in engines.items():
        for key, item in engine.breakdown.items():
            side, regime = key.split(" / ", 1)
            rows.append({
                "Сценарий": case,
                "Направление": side,
                "Режим при входе": regime,
                "Закрытый PnL USDT": item["pnl"],
                "Циклов": item["cycles"],
            })

    if rows:
        table(pd.DataFrame(rows))

    st.caption(
        "Режим определяется по самому инструменту, "
        "не по BTC. Открытая серия не включена "
        "в таблицу закрытых серий, но включена в equity."
    )


def single_research(coin):
    st.subheader("Исследование исторических сигналов")

    budget, risk, bar, funding_mode, csv_text = research_controls(
        "single_"
    )

    mode = st.radio(
        "Режим",
        ["14 дней", "Walk-Forward"],
        horizontal=True,
        key="single_mode",
    )

    if mode == "Walk-Forward":
        folds = st.number_input(
            "OOS-окон по 30 дней",
            min_value=1,
            max_value=6,
            value=3,
            key="wf_folds",
        )

        optimize = st.checkbox(
            "Выбор на train из трёх заранее заданных вариантов",
            value=False,
            key="wf_optimize",
        )

        st.caption(
            "Train 180 дней → Test 30 дней. "
            "Затем holdout 90 дней. "
            "При выборе параметров: исходный шаблон, "
            "множитель 1.0, либо шаг 2.4%. "
            "Открытые серии и капитал между OOS-окнами "
            "не сбрасываются."
        )
    else:
        folds = 0
        optimize = False

    research_warning(bar, funding_mode)

    if st.button(
        "Запустить исследование",
        key="run_single_research",
        use_container_width=True,
    ):
        st.session_state.pop("single_result", None)

        end = int(time.time() // 3600) * HOUR
        days = (
            14
            if mode == "14 дней"
            else 180 + int(folds) * 30 + 90
        )

        with st.spinner(
            "Загружаю свечи, Mark Price и считаю. "
            "На мелких свечах загрузка может быть долгой..."
        ):
            data = cached_bundle(
                coin,
                days,
                end,
                bar,
                funding_mode,
                csv_text,
            )

            if mode == "Walk-Forward":
                windows, summary, curves, engines = walk_forward(
                    data,
                    budget,
                    risk,
                    funding_mode,
                    int(folds),
                    optimize,
                )
            else:
                windows = pd.DataFrame()
                summaries = []
                curves_dict = {}
                engines = {}

                for case in CASES:
                    engine = DCAEngine(
                        budget,
                        DEFAULT_DCA,
                        case,
                        risk,
                        funding_mode,
                    )

                    engine, curve = simulate_research(
                        data,
                        engine,
                    )
                    engines[case] = engine

                    summaries.append({
                        "Сценарий": case,
                        **engine.summary(),
                    })
                    curves_dict[case] = (
                        curve.set_index("time").equity
                    )

                summary = pd.DataFrame(summaries)
                curves = pd.DataFrame(curves_dict)

        st.session_state["single_result"] = {
            "coin": coin,
            "mode": mode,
            "windows": windows,
            "summary": summary,
            "curves": curves,
            "engines": engines,
            "funding": funding_mode,
            "bar": bar,
            "created_at": now(),
        }

    result = st.session_state.get("single_result")

    if result:
        st.caption(
            "Последний расчёт: "
            f"{result['coin']} · {result['mode']} · "
            f"{result['bar']} · funding {result['funding']} · "
            f"{result['created_at']}"
        )

        table(result["summary"])
        st.line_chart(result["curves"])

        if not result["windows"].empty:
            st.subheader("OOS-окна и holdout")
            table(result["windows"])

        st.subheader("Закрытые серии по сторонам и режимам")
        show_breakdown(result["engines"])

        st.download_button(
            "Скачать исследование CSV",
            result["summary"].to_csv(
                index=False
            ).encode("utf-8-sig"),
            "research_summary.csv",
            "text/csv",
        )


# =========================================================
# ПАКЕТНЫЙ ТЕСТ
# =========================================================

def batch_worker(
    coin,
    budget,
    risk,
    bar,
    funding_mode,
    csv_text,
    end,
    case,
    limiter,
):
    data = research_bundle(
        coin,
        14,
        end,
        bar,
        funding_mode,
        csv_text,
        limiter,
    )

    engine = DCAEngine(
        budget,
        DEFAULT_DCA,
        case,
        risk,
        funding_mode,
    )

    engine, _ = simulate_research(data, engine)

    return {
        "Монета": coin,
        "Сценарий": case,
        "Funding": funding_mode,
        **engine.summary(),
    }


def batch_research(saved):
    st.subheader("Пакетный бэктест")

    budget, risk, bar, funding_mode, csv_text = research_controls(
        "batch_"
    )

    case = st.selectbox(
        "Сценарий издержек",
        list(CASES),
        index=1,
        key="batch_case",
    )

    only_directional = st.checkbox(
        "Только текущие LONG/SHORT — условная выборка",
        value=False,
        key="batch_directional",
    )

    rows = saved.get("rows", [])

    coins = sorted({
        row["Монета"]
        for row in rows
        if not only_directional
        or row["Сигнал"] in ("LONG", "SHORT")
    })

    st.caption(
        "По умолчанию тестируются все монеты последнего "
        "сканирования, чтобы не отбирать их по сегодняшнему "
        "исходу. Внутри теста Long/Short определяются "
        "исторически. Текущее направление не переносится "
        "назад на 14 дней."
    )

    research_warning(bar, funding_mode)

    signature = canonical({
        "coins": coins,
        "scan": saved.get("timestamp"),
        "budget": budget,
        "risk": risk,
        "bar": bar,
        "funding": funding_mode,
        "case": case,
        "csv": csv_text,
    })

    if st.button(
        "🚀 Проверить ВСЕХ на истории",
        key="batch_run",
        use_container_width=True,
        disabled=not coins,
    ):
        st.session_state.pop("batch_result", None)

        end = int(time.time() // 3600) * HOUR
        limiter = RateLimiter()
        output = []

        progress = st.progress(0.0)
        status = st.empty()

        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs = {
                pool.submit(
                    batch_worker,
                    coin,
                    budget,
                    risk,
                    bar,
                    funding_mode,
                    csv_text,
                    end,
                    case,
                    limiter,
                ): coin
                for coin in coins
            }

            for index, future in enumerate(
                as_completed(jobs),
                start=1,
            ):
                coin = jobs[future]

                try:
                    output.append(future.result())
                except Exception as exc:
                    output.append({
                        "Монета": coin,
                        "Доходность %": np.nan,
                        "Статус": "Ошибка данных или модели",
                        "Ошибка": str(exc),
                    })

                progress.progress(index / len(jobs))
                status.caption(
                    f"Обработано {index}/{len(jobs)} · {coin}"
                )

        result = (
            pd.DataFrame(output)
            .sort_values(
                "Доходность %",
                ascending=False,
                na_position="last",
            )
            .reset_index(drop=True)
        )

        st.session_state["batch_result"] = {
            "signature": signature,
            "data": result,
            "timestamp": now(),
        }

    saved_result = st.session_state.get("batch_result")

    if saved_result:
        if saved_result["signature"] != signature:
            st.info(
                "Параметры изменились. "
                "Пересчитай пакетный тест."
            )
        else:
            st.caption(saved_result["timestamp"])

            st.dataframe(
                style_df(saved_result["data"]),
                hide_index=True,
                use_container_width=True,
            )

            st.download_button(
                "Скачать пакетный тест",
                saved_result["data"].to_csv(
                    index=False
                ).encode("utf-8-sig"),
                "batch_research.csv",
                "text/csv",
            )


# =========================================================
# СКАНЕР
# =========================================================

@st.cache_data(ttl=180, show_spinner=False)
def scanner_coin(coin):
    end = int(time.time() // 3600) * HOUR

    hours = history_candles(
        coin,
        end - 70 * DAY,
        end,
        "1H",
    )

    daily = daily_from_hours(hours)

    if daily.empty:
        raise ValueError("Нет дневной истории.")

    last = daily.iloc[-1]
    ticker = quote(coin)

    if not np.isfinite([
        last.RSI,
        last.ADX,
        last.EMA50,
        last["+DI"],
        last["-DI"],
    ]).all():
        raise ValueError("Недостаточно данных индикаторов.")

    if last.ADX < 25:
        signal_value = "GRID"
    elif (
        last["+DI"] > last["-DI"]
        and last.close > last.EMA50
    ):
        signal_value = "LONG"
    elif (
        last["-DI"] > last["+DI"]
        and last.close < last.EMA50
    ):
        signal_value = "SHORT"
    else:
        signal_value = "Не определено"

    return {
        "Монета": coin,
        "Цена": ticker["price"],
        "Сигнал": signal_value,
        "RSI": last.RSI,
        "ADX": last.ADX,
        "ATR %": last["ATR %"],
        "Объём 24H ≈ USDT": ticker["volume"],
    }


def market_chart(frame, title):
    figure = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.6, 0.2, 0.2],
        vertical_spacing=0.04,
    )

    figure.add_trace(
        go.Candlestick(
            x=frame.index,
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
            x=frame.index,
            y=frame.RSI,
            name="RSI",
        ),
        row=2,
        col=1,
    )
    figure.add_trace(
        go.Scatter(
            x=frame.index,
            y=frame.ADX,
            name="ADX",
        ),
        row=3,
        col=1,
    )

    figure.update_layout(
        title=title,
        template="plotly_dark",
        height=650,
        xaxis_rangeslider_visible=False,
    )

    st.plotly_chart(
        figure,
        use_container_width=True,
    )


def scanner():
    st.title("2. Сканер рынка")

    st.caption(
        "SWAP · дневные закрытые свечи UTC · "
        "симметричные Long/Short · EMA50 и ADX/DI."
    )

    if st.button(
        "Сканировать монеты",
        use_container_width=True,
    ):
        rows = []
        errors = []
        progress = st.progress(0.0)

        # Здесь сканирование последовательное:
        # cached-функции Streamlit не вызываются
        # из пользовательских потоков.
        for index, coin in enumerate(COINS, start=1):
            try:
                rows.append(scanner_coin(coin))
            except Exception as exc:
                errors.append(
                    coin + ": " + type(exc).__name__
                )

            progress.progress(index / len(COINS))

        st.session_state["scan"] = {
            "rows": rows,
            "errors": errors,
            "timestamp": now(),
            "market": "SWAP",
        }

    saved = st.session_state.get("scan")

    if not saved:
        st.info("Запусти сканирование.")
        return

    st.caption(saved["timestamp"])

    if saved["errors"]:
        st.warning("; ".join(saved["errors"]))

    if not saved["rows"]:
        return

    table(pd.DataFrame(saved["rows"]))

    batch_research(saved)

    coin = st.selectbox(
        "Монета для графика и Walk-Forward",
        [row["Монета"] for row in saved["rows"]],
    )

    end = int(time.time() // 3600) * HOUR

    hours = history_candles(
        coin,
        end - 70 * DAY,
        end,
        "1H",
    )

    market_chart(
        daily_from_hours(hours),
        coin + " · дневные свечи",
    )

    columns = st.columns(3)

    for column, label, strategy, direction, suffix in [
        (columns[0], "🟢 DCA Long", "DCA", "Long", "long"),
        (columns[1], "🔴 DCA Short", "DCA", "Short", "short"),
        (columns[2], "🟡 Grid", "Grid", "Neutral", "neutral"),
    ]:
        if column.button(
            label,
            key="action_scanner_" + suffix,
        ):
            route(
                strategy,
                direction,
                {
                    "coin": coin,
                    "entry": quote(coin)["price"],
                },
            )

    single_research(coin)


# =========================================================
# ПЛАН DCA И ДОБАВЛЕНИЕ КАРТОЧКИ
# =========================================================

def dca_plan(settings, direction):
    entry = settings["entry"]

    if (
        entry <= 0
        or settings["step"] <= 0
        or settings["base_amount"] <= 0
        or settings["first_so"] <= 0
        or settings["mart"] < 1
    ):
        raise ValueError("Проверь параметры DCA.")

    total = 0.0
    quantity = 0.0
    rows = []

    for index in range(int(settings["so_count"]) + 1):
        price = entry * (
            1
            - direction_sign(direction)
            * settings["step"]
            * index
            / 100
        )

        if price <= 0:
            raise ValueError("Уровень DCA имеет цену ≤ 0.")

        amount = (
            settings["base_amount"]
            if index == 0
            else settings["first_so"]
            * settings["mart"] ** (index - 1)
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


def creator(kind):
    task = st.radio(
        "Задача",
        ["Подготовить новый", "Добавить уже работающий"],
        horizontal=True,
        key=kind + "task",
    )

    name = st.text_input(
        "Название",
        value="Мой " + kind,
        key=kind + "name",
    )

    args = {"label": "Монета", "key": kind + "coin"}

    if kind + "coin" not in st.session_state:
        args["value"] = "BTC"

    coin = st.text_input(**args).strip().upper()

    if coin == "TON":
        st.warning(
            "Монета исключена из новых карточек. "
            "Существующие карточки не удаляются."
        )
        return

    market = st.selectbox(
        "Рынок",
        ["SWAP", "SPOT"],
        key=kind + "market",
    )

    direction = st.radio(
        "Направление",
        (
            ["Long", "Short"]
            if kind == "DCA"
            else ["Long", "Short", "Neutral"]
        ),
        horizontal=True,
        key=kind + "direction",
    )

    if market == "SPOT" and direction != "Long":
        st.warning("Spot здесь поддерживает Long.")
        return

    settings = {
        "base_margin": ni(
            "Базовая маржа / капитал Spot, USDT",
            100,
            kind + "margin",
            0.01,
        ),
    }

    if kind == "DCA":
        settings["entry"] = ni(
            "Цена первого входа",
            0,
            kind + "entry",
        )
        settings["tp"] = ni(
            "TP от средней цены, %",
            1.5,
            kind + "tp",
            0.01,
            99,
        )
    else:
        settings["lower"] = ni(
            "Нижняя граница",
            0,
            kind + "lower",
        )
        settings["upper"] = ni(
            "Верхняя граница",
            0,
            kind + "upper",
        )
        settings["grids"] = ni(
            "Количество интервалов",
            10,
            kind + "grids",
            2,
            200,
            integer=True,
        )

    with st.expander("Расширенные настройки"):
        settings["leverage"] = ni(
            "Плечо; Spot — 1",
            3 if market == "SWAP" else 1,
            kind + "leverage",
            1,
            100,
        )
        settings["reserve"] = ni(
            "Отдельный резерв маржи",
            50,
            kind + "reserve",
        )
        settings["total_budget"] = (
            settings["base_margin"]
            + settings["reserve"]
        )

        if kind == "DCA":
            settings["step"] = ni(
                "Шаг от первого входа, %",
                2,
                kind + "step",
                0.01,
                50,
            )
            settings["so_count"] = ni(
                "Количество СО",
                4,
                kind + "so",
                0,
                30,
                integer=True,
            )
            settings["base_amount"] = ni(
                "Номинал первого ордера",
                10,
                kind + "base",
                0.01,
            )
            settings["first_so"] = ni(
                "Номинал первого СО",
                10,
                kind + "first",
                0.01,
            )
            settings["mart"] = ni(
                "Множитель объёма СО",
                1.2,
                kind + "mart",
                1,
                3,
            )
        else:
            settings["target_price"] = ni(
                "Целевая цена Long/Short; 0 = нет",
                0,
                kind + "target",
            )

        settings["stop_price"] = ni(
            "Сигнальная стоп-цена Long/Short",
            0,
            kind + "stop",
        )
        settings["stop_lower"] = ni(
            "Нижний стоп Neutral",
            0,
            kind + "stoplower",
        )
        settings["stop_upper"] = ni(
            "Верхний стоп Neutral",
            0,
            kind + "stopupper",
        )
        settings["max_loss"] = ni(
            "Лимит убытка открытой позиции, USDT",
            0,
            kind + "loss",
        )
        settings["stale_hours"] = ni(
            "Актуальность сверки, часов",
            6,
            kind + "stale",
            0.1,
            168,
        )

    valid = bool(name.strip()) and coin.isalnum()

    if market == "SPOT" and settings["leverage"] != 1:
        valid = False
        st.warning("Для Spot установи плечо 1.")

    if kind == "DCA":
        try:
            plan = dca_plan(settings, direction)
            table(pd.DataFrame(plan))
        except ValueError as exc:
            valid = False
            st.info(str(exc))
    else:
        valid = (
            valid
            and 0 < settings["lower"] < settings["upper"]
        )
        if valid:
            st.line_chart(pd.DataFrame({
                "Уровни": np.linspace(
                    settings["lower"],
                    settings["upper"],
                    int(settings["grids"]) + 1,
                )
            }))

        st.caption(
            "Это план уровней и ручное сопровождение Grid. "
            "Исследовательский движок выше предназначен "
            "для DCA и не выдаёт Grid за точную "
            "копию исполнения OKX."
        )

    pending_key = kind + "pending"

    if pending_key not in st.session_state:
        st.session_state[pending_key] = {
            "id": str(uuid.uuid4()),
            "created_at": now(),
        }

    if st.button(
        "Сохранить карточку",
        disabled=not valid or not DB_READY,
        key=kind + "save",
        use_container_width=True,
    ):
        quote(coin, market)
        pending = st.session_state[pending_key]

        bot = {
            "id": pending["id"],
            "created_at": pending["created_at"],
            "name": name.strip(),
            "coin": coin,
            "market": market,
            "strategy": kind,
            "direction": direction,
            "settings": settings,
            "position": {},
            "lifecycle": "Черновик",
        }

        save_bot(bot, "Создана карточка", task)

        st.session_state.pop(pending_key, None)
        st.session_state["_flash"] = (
            "Карточка записана и проверена. "
            "Внеси фактическую позицию."
        )

        route(kind, focus=bot["id"])

    if st.button(
        "Начать другую карточку с новым ID",
        key=kind + "new",
    ):
        st.session_state[pending_key] = {
            "id": str(uuid.uuid4()),
            "created_at": now(),
        }
        st.info(
            "Новый ID назначен. После неопределённой "
            "ошибки записи сначала проверь список, "
            "чтобы не создать копию."
        )

    if not DB_READY:
        st.warning(
            "Сохранение заблокировано: "
            "PostgreSQL не подключена."
        )

    if kind == "DCA" and coin.isalnum():
        st.markdown("---")
        single_research(coin)


# =========================================================
# СОПРОВОЖДЕНИЕ СОХРАНЁННЫХ БОТОВ
# =========================================================

def assess(bot, price):
    s = bot["settings"]
    p = bot["position"]
    side = direction_sign(bot["direction"])

    realized = (
        number_value(p.get("realized_pnl"))
        if bot["strategy"] == "DCA"
        else 0.0
    )

    result = {
        "title": "Нужна сверка",
        "reason": "",
        "tone": "info",
        "pnl": None,
        "floating": None,
        "realized": realized,
        "tp": None,
        "next_so": None,
        "reserve": max(
            0,
            number_value(s["total_budget"])
            - number_value(
                p.get("base_margin"),
                s["base_margin"],
            )
            - number_value(p.get("added_margin")),
        ),
    }

    if bot["lifecycle"] != "Работает":
        result["title"] = (
            "План сохранён"
            if bot["lifecycle"] == "Черновик"
            else "Бот отмечен завершённым"
        )
        result["reason"] = (
            "Статус задаётся вручную. "
            "Для работающего бота сверь позицию на OKX."
        )
        return result

    if price is None:
        result["reason"] = "Нет свежей рыночной цены."
        return result

    stop_hit = (
        side
        and s["stop_price"] > 0
        and side * (price - s["stop_price"]) <= 0
    ) or (
        not side
        and (
            (
                s["stop_lower"] > 0
                and price <= s["stop_lower"]
            )
            or (
                s["stop_upper"] > 0
                and price >= s["stop_upper"]
            )
        )
    )

    if stop_hit:
        result.update(
            title="Достигнут сигнальный стоп",
            reason=(
                "Срочно сверь позицию и выполни "
                "выход по плану на OKX. "
                "Приложение ордер не отправляло."
            ),
            tone="error",
        )
        return result

    if age_hours(p.get("last_check")) > s["stale_hours"]:
        result["reason"] = (
            "Сверка устарела. Обнови позицию на OKX."
        )
        return result

    if not side:
        result["title"] = (
            "Цена внутри диапазона"
            if s["lower"] <= price <= s["upper"]
            else "Цена вне диапазона Grid"
        )
        result["reason"] = (
            "Проверь обе стороны, ордера и Total PnL. "
            "Показан ручной снимок, не онлайн-PnL."
        )
        result["pnl"] = p.get("total_pnl_manual")
        return result

    qty = number_value(p.get("volume"))
    avg = number_value(p.get("avg_price"))

    if qty <= 0:
        result.update(
            title="По сверке открытой позиции нет",
            reason="Проверь ожидание следующего цикла.",
            pnl=realized,
            floating=0.0,
        )
        return result

    if avg <= 0:
        result["reason"] = "Нужна фактическая средняя цена."
        return result

    floating = side * qty * (price - avg)

    result.update(
        floating=floating,
        pnl=realized + floating,
    )

    if (
        s["max_loss"] > 0
        and floating <= -s["max_loss"]
    ):
        result.update(
            title="Достигнут лимит убытка открытой позиции",
            reason=(
                "Проверь ручной выход по плану. "
                "Прибыль прошлых циклов "
                "не отменяет этот лимит."
            ),
            tone="error",
        )
        return result

    liq = number_value(p.get("liq_price"))

    if liq > 0:
        distance = side * (price - liq) / price * 100
        if distance <= s["liq_warn"]:
            result.update(
                title="Цена близко к введённой ликвидации",
                reason=(
                    "Сверь Mark Price, MMR и риск на OKX. "
                    "Здесь последняя цена и ручной уровень."
                ),
                tone="error",
            )
            return result

    if bot["strategy"] == "DCA":
        result["tp"] = avg * (
            1 + side * s["tp"] / 100
        )

        if s["entry"] > 0:
            plan = dca_plan(s, bot["direction"])
            count = max(
                0,
                min(
                    int(p.get("executed_so", 0)),
                    len(plan) - 1,
                ),
            )
            if count + 1 < len(plan):
                result["next_so"] = plan[count + 1]["Цена"]
    else:
        result["tp"] = s["target_price"] or None

    if (
        result["tp"]
        and side * (price - result["tp"]) >= 0
    ):
        result.update(
            title="Достигнут модельный TP",
            reason=(
                "Проверь исполнение. "
                "TP цикла не означает остановку бота."
            ),
            tone="success",
        )
    elif (
        bot["strategy"] == "Grid"
        and not s["lower"] <= price <= s["upper"]
    ):
        result.update(
            title="Цена вне Grid",
            reason=(
                "Проверь остаточную позицию и план выхода."
            ),
            tone="warning",
        )
    elif (
        max(0, -side * (price / avg - 1) * 100)
        >= s["danger_pct"]
    ):
        result.update(
            title="Заданная зона внимания",
            reason=(
                "Проверь риск по плану. "
                "Это не прогноз разворота."
            ),
            tone="warning",
        )
    else:
        result.update(
            title="Контроль по плану",
            reason=(
                "Жёсткие условия по введённым данным "
                "не сработали. Это не гарантия безопасности."
            ),
            tone="success" if floating > 0 else "info",
        )

    return result


def send_telegram(text):
    token = str(secret("TELEGRAM_TOKEN"))
    chat = str(secret("TELEGRAM_CHAT_ID"))

    try:
        token = token or str(
            st.secrets["telegram"]["token"]
        )
        chat = chat or str(
            st.secrets["telegram"]["chat_id"]
        )
    except Exception:
        pass

    token = token or st.session_state.get("tg_token", "")
    chat = chat or st.session_state.get("tg_chat", "")

    if not token or not chat:
        raise ValueError("Настрой Telegram.")

    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat,
            "text": text[:4000],
        },
        timeout=15,
    )
    response.raise_for_status()

    if not response.json().get("ok"):
        raise ValueError("Telegram не подтвердил отправку.")


def bot_card(bot, compact=False):
    try:
        price = quote(
            bot["coin"],
            bot["market"],
        )["price"]
    except Exception:
        price = None

    result = assess(bot, price)
    p = bot["position"]
    s = bot["settings"]
    key = bot["id"] + "_" + str(bot["_revision"])

    icon = {
        "Long": "🟢",
        "Short": "🔴",
        "Neutral": "🟡",
    }[bot["direction"]]

    with st.container(border=True):
        st.subheader(
            f"{icon} {bot['coin']} · "
            f"{bot['strategy']} {bot['direction']}"
        )
        st.caption(
            bot["name"] + " · "
            + bot["lifecycle"] + " · "
            + bot["market"]
        )

        columns = st.columns(3)
        columns[0].metric("Цена", fmt(price, 6))
        columns[1].metric("PnL ≈ USDT", fmt(result["pnl"]))
        columns[2].metric(
            "Остаток бюджета маржи",
            fmt(result["reserve"]),
        )

        getattr(st, result["tone"])(
            result["title"] + ". " + result["reason"]
        )

        st.caption(
            "Сверка UTC: "
            + (p.get("last_check") or "не выполнена")
        )

        if compact:
            if st.button(
                "Открыть карточку",
                key=key + "open",
            ):
                route(
                    bot["strategy"],
                    focus=bot["id"],
                )
            return

        with st.expander(
            "Сверить позицию с OKX",
            expanded=not p.get("last_check"),
        ):
            with st.form(key + "position"):
                statuses = ["Черновик", "Работает", "Закрыт"]
                lifecycle = st.selectbox(
                    "Статус",
                    statuses,
                    index=statuses.index(bot["lifecycle"]),
                )

                neutral = bot["direction"] == "Neutral"

                if neutral:
                    known = st.checkbox(
                        "Внести Total PnL с OKX",
                        value=p.get("total_pnl_manual") is not None,
                    )
                    total_manual = ni(
                        "Total PnL: снимок с OKX",
                        number_value(p.get("total_pnl_manual")),
                        key + "total",
                        low=None,
                    )
                    qty = 0.0
                    avg = 0.0
                    liq = 0.0
                    realized = 0.0
                    executed = 0

                    st.caption(
                        "Перед статусом «Закрыт» проверь "
                        "остатки обеих сторон и ордера."
                    )
                else:
                    known = False
                    total_manual = None

                    qty = ni(
                        "Объём в базовой монете, не контракты",
                        number_value(p.get("volume")),
                        key + "qty",
                    )
                    avg = ni(
                        "Фактическая средняя",
                        number_value(p.get("avg_price")),
                        key + "avg",
                    )
                    liq = ni(
                        "Ликвидационная цена; 0 = неизвестна",
                        number_value(p.get("liq_price")),
                        key + "liq",
                    )

                    if bot["strategy"] == "DCA":
                        realized = ni(
                            "PnL закрытых циклов, не Total PnL",
                            number_value(p.get("realized_pnl")),
                            key + "realized",
                            low=None,
                        )
                        maximum = int(s["so_count"])
                        executed = (
                            ni(
                                "Исполнено СО текущего цикла",
                                min(
                                    maximum,
                                    max(
                                        0,
                                        int(p.get("executed_so", 0)),
                                    ),
                                ),
                                key + "so",
                                0,
                                maximum,
                                integer=True,
                            )
                            if maximum > 0 else 0
                        )
                    else:
                        realized = 0.0
                        executed = 0

                base = ni(
                    "Базовая выделенная маржа",
                    number_value(
                        p.get("base_margin"),
                        s["base_margin"],
                    ),
                    key + "margin",
                )
                added = ni(
                    "Всего добавлено маржи",
                    number_value(p.get("added_margin")),
                    key + "added",
                )
                confirmed = st.checkbox(
                    "Сверил с OKX; для завершения проверил "
                    "отсутствие остатков и ордеров"
                )

                if st.form_submit_button(
                    "Сохранить сверку",
                    disabled=not DB_READY,
                ):
                    if (
                        not confirmed
                        or (qty > 0 and avg <= 0)
                        or (lifecycle == "Закрыт" and qty > 0)
                    ):
                        st.error("Проверь данные и подтверждение.")
                    else:
                        bot["lifecycle"] = lifecycle
                        bot["position"] = {
                            "volume": qty,
                            "avg_price": avg,
                            "liq_price": liq,
                            "realized_pnl": realized,
                            "executed_so": int(executed),
                            "base_margin": base,
                            "added_margin": added,
                            "total_pnl_manual": (
                                total_manual if known else None
                            ),
                            "last_check": now(),
                        }
                        save_bot(
                            bot,
                            "Сверка позиции",
                            "Пользователь сверил данные с OKX.",
                        )
                        st.session_state["_flash"] = (
                            "Позиция записана и проверена."
                        )
                        st.rerun()

        with st.expander("Изменить план сопровождения"):
            with st.form(key + "plan"):
                updated = dict(s)

                if bot["strategy"] == "DCA":
                    updated["tp"] = ni(
                        "TP от средней, %",
                        s["tp"],
                        key + "tp",
                        0.01,
                        99,
                    )
                else:
                    updated["lower"] = ni(
                        "Нижняя граница",
                        s["lower"],
                        key + "lower",
                    )
                    updated["upper"] = ni(
                        "Верхняя граница",
                        s["upper"],
                        key + "upper",
                    )
                    updated["target_price"] = ni(
                        "Целевая цена Long/Short",
                        s["target_price"],
                        key + "target",
                    )

                for field, label in [
                    ("stop_price", "Сигнальный стоп Long/Short"),
                    ("stop_lower", "Нижний стоп Neutral"),
                    ("stop_upper", "Верхний стоп Neutral"),
                    ("max_loss", "Лимит открытого убытка USDT"),
                    ("total_budget", "Общий бюджет маржи"),
                ]:
                    updated[field] = ni(
                        label,
                        s[field],
                        key + field,
                    )

                updated["stale_hours"] = ni(
                    "Актуальность сверки, часов",
                    s["stale_hours"],
                    key + "stale",
                    0.1,
                    168,
                )

                if st.form_submit_button(
                    "Сохранить план",
                    disabled=not DB_READY,
                ):
                    if (
                        bot["strategy"] == "Grid"
                        and not (
                            0
                            < updated["lower"]
                            < updated["upper"]
                        )
                    ):
                        st.error("Неверный диапазон.")
                    else:
                        bot["settings"] = updated
                        save_bot(
                            bot,
                            "Изменён план",
                            canonical(updated),
                        )
                        st.rerun()

        with st.expander("Уровни и настройки"):
            st.write("Модельный TP:", fmt(result["tp"], 6))
            st.write(
                "Следующий СО:",
                fmt(result["next_so"], 6),
            )
            table(pd.DataFrame([
                {"Параметр": name, "Значение": str(value)}
                for name, value in s.items()
            ]))

        with st.form(key + "decision"):
            decision = st.radio(
                "Моё решение",
                ["Не трогать", "Проверить на OKX", "Выход по плану"],
                horizontal=True,
            )
            reason = st.text_input("Причина")
            hours = st.number_input(
                "Перепроверить через часов",
                min_value=0.1,
                max_value=168.0,
                value=6.0,
            )

            if st.form_submit_button(
                "Записать решение",
                disabled=not DB_READY,
            ):
                if not reason.strip():
                    st.error("Укажи причину.")
                else:
                    bot["decision"] = {
                        "action": decision,
                        "reason": reason.strip(),
                        "created_at": now(),
                        "valid_hours": hours,
                    }
                    save_bot(
                        bot,
                        "Решение",
                        canonical(bot["decision"]),
                    )
                    st.rerun()

        decision = bot.get("decision")

        if isinstance(decision, dict):
            st.caption(
                str(decision.get("action", ""))
                + " · "
                + str(decision.get("reason", ""))
            )

            if (
                age_hours(decision.get("created_at"))
                >= number_value(
                    decision.get("valid_hours"),
                    6,
                )
            ):
                st.warning("Срок решения истёк.")
        elif decision:
            st.caption(str(decision))

        if st.button(
            "Отправить отчёт в Telegram",
            key=key + "telegram",
        ):
            stamp_key = bot["id"] + "_last_telegram"
            last = st.session_state.get(stamp_key, 0.0)

            if time.time() - last < 60:
                st.info("Повторная отправка доступна через минуту.")
            else:
                send_telegram(
                    f"{bot['name']}\n"
                    f"{bot['coin']} · {bot['strategy']} "
                    f"{bot['direction']}\n\n"
                    f"{result['title']}\n"
                    f"{result['reason']}\n\n"
                    f"Цена: {fmt(price, 6)}\n"
                    f"PnL ≈ {fmt(result['pnl'])} USDT\n"
                    f"Сверка: {p.get('last_check') or 'нет'}\n\n"
                    "Торговая команда не отправлялась."
                )
                st.session_state[stamp_key] = time.time()
                st.success("Отчёт отправлен.")

        st.caption(
            "Расчёты карточки приблизительные. "
            "Комиссии и funding открытой позиции "
            "отдельно не учтены. "
            "Решение «Не трогать» не отключает стоп."
        )


def list_bots(bots, prefix, compact=False):
    status = st.radio(
        "Показывать",
        ["Все", "Работает", "Черновик", "Закрыт"],
        horizontal=True,
        key=prefix + "filter",
    )

    selected = [
        bot for bot in bots
        if status == "Все"
        or bot["lifecycle"] == status
    ]
    selected.sort(
        key=lambda bot: (
            bot["id"] != st.session_state.get("focus")
        )
    )

    if not selected:
        st.info("Нет карточек для этого фильтра.")

    for bot in selected:
        try:
            bot_card(bot, compact)
        except ValueError as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(
                "Действие по карточке не подтверждено: "
                + type(exc).__name__
                + ". Обнови список перед повтором."
            )


def action_buttons(prefix):
    columns = st.columns(3)

    variants = [
        ("🟢 ЛОНГ · DCA", "DCA", "Long", "long"),
        ("🔴 ШОРТ · DCA", "DCA", "Short", "short"),
        ("🟡 NEUTRAL · GRID", "Grid", "Neutral", "neutral"),
    ]

    for column, item in zip(columns, variants):
        label, kind, direction, suffix = item

        if column.button(
            label,
            key=f"action_{prefix}_{suffix}",
            use_container_width=True,
        ):
            route(kind, direction)


# =========================================================
# НАСТРОЙКИ
# =========================================================

def settings_page(bots):
    st.title("Настройки")
    st.write("Пароль: APP_PASSWORD, вход обязателен.")

    if DB_READY:
        st.success(
            "PostgreSQL доступна. "
            f"Карточек: {len(bots)}."
        )
    elif DB_URL:
        st.error(
            "Адрес задан, но чтение базы не подтверждено. "
            "Это не означает, что карточки удалены."
        )
    else:
        st.warning(
            "Задай DATABASE_URL. "
            "Без базы сохранение заблокировано."
        )

    if st.button("Проверить PostgreSQL"):
        try:
            with database() as connection:
                result = sql(
                    connection,
                    "SELECT 1",
                ).fetchone()

            if result != (1,):
                raise ValueError("Проверка не совпала.")

            st.success(
                "Соединение работает. "
                "Это не проверка резервного копирования."
            )
        except Exception as exc:
            st.error(type(exc).__name__)

    if DB_READY:
        if st.button("Подготовить резервную копию"):
            st.session_state["backup"] = {
                "data": export_backup(),
                "timestamp": now(),
            }

        backup = st.session_state.get("backup")

        if backup:
            st.caption(backup["timestamp"])
            st.download_button(
                "Скачать JSON",
                backup["data"],
                "okx_backup.json",
                "application/json",
            )

        uploaded = st.file_uploader(
            "Восстановить JSON до 5 MB",
            type=["json"],
            key="restore_json",
        )
        confirmed = st.checkbox(
            "Добавить копии с новыми ID, "
            "не заменять существующие карточки"
        )

        if st.button(
            "Восстановить",
            disabled=uploaded is None or not confirmed,
        ):
            if uploaded.size > 5_000_000:
                raise ValueError("Файл больше 5 MB.")

            count = import_backup(
                json.loads(uploaded.getvalue())
            )
            st.session_state["_flash"] = (
                f"Добавлено копий: {count}. "
                "Они требуют сверки с OKX."
            )
            st.rerun()

        with st.expander("Перенести старый локальный SQLite"):
            st.caption(
                "Только если файл ещё существует. "
                "Исходный файл открывается только для чтения."
            )
            confirm_local = st.checkbox(
                "Подтверждаю добавление копий"
            )

            if st.button(
                "Перенести локальные карточки",
                disabled=not confirm_local,
            ):
                if not os.path.isfile(DB_FILE):
                    raise ValueError(
                        "Старый файл не найден."
                    )

                connection = sqlite3.connect(
                    "file:"
                    + os.path.abspath(DB_FILE)
                    + "?mode=ro",
                    uri=True,
                )

                try:
                    connection.row_factory = sqlite3.Row
                    tables = {
                        row[0]
                        for row in connection.execute(
                            "SELECT name FROM sqlite_master "
                            "WHERE type='table'"
                        )
                    }

                    if "terminal_bots" in tables:
                        raw = [
                            json.loads(row[0])
                            for row in connection.execute(
                                "SELECT document FROM terminal_bots"
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
                            "Таблицы карточек не найдены."
                        )
                finally:
                    connection.close()

                count = import_backup({"bots": raw})
                st.session_state["_flash"] = (
                    f"Перенесено копий: {count}."
                )
                st.rerun()

    with st.expander("Telegram"):
        st.text_input(
            "Token, если нет в Secrets",
            type="password",
            key="tg_token",
        )
        st.text_input(
            "Chat ID, если нет в Secrets",
            key="tg_chat",
        )

        if st.button("Тест Telegram"):
            send_telegram(
                "OKX Terminal Pro: тест. "
                "Торговые команды не отправляются."
            )
            st.success("Отправлено.")

    with st.expander(
        "Пример Streamlit Secrets",
        expanded=not DB_URL,
    ):
        st.code(
            '''
APP_PASSWORD = "твой-пароль"
DATABASE_URL = "postgresql://USER:PASSWORD@HOST:5432/DATABASE?sslmode=require"

# Необязательно:
TELEGRAM_TOKEN = "токен"
TELEGRAM_CHAT_ID = "chat-id"
'''.strip(),
            language="toml",
        )
        st.caption(
            "Это не рабочие реквизиты. "
            "Существующий настоящий адрес базы не заменяй."
        )

    st.caption(
        "Автоматические резервные копии отдельно "
        "настраиваются у провайдера PostgreSQL. "
        "Независимого фонового мониторинга нет. "
        "Приложение не отправляет торговые команды."
    )


# =========================================================
# ГЛАВНОЕ ПРИЛОЖЕНИЕ
# =========================================================

def main():
    global DB_READY

    apply_route()
    design()
    login()

    with st.sidebar:
        st.title("OKX Terminal")

        page = st.radio(
            "Раздел",
            PAGES,
            key="page",
            label_visibility="collapsed",
            format_func=lambda value: (
                f"{PAGES.index(value) + 1}. "
                + (
                    "Сканер рынка"
                    if value == "Сканер"
                    else value
                )
            ),
        )

        if st.button("Обновить цены и список"):
            quote.clear()
            scanner_coin.clear()
            st.rerun()

        if st.button("Выйти"):
            st.session_state["_authenticated"] = False
            st.rerun()

        st.caption(
            "Ручное сопровождение. "
            "Торговые команды не отправляются."
        )

    bots = []
    DB_READY = False

    if DB_URL:
        try:
            init_database()
            bots = load_bots()
            DB_READY = True
        except Exception as exc:
            st.error(
                "Чтение PostgreSQL не подтверждено: "
                + type(exc).__name__
                + ". Не удаляй данные и не меняй адрес "
                "на новую базу. Настройки остаются доступны."
            )
    else:
        st.warning(
            "DATABASE_URL не настроен. "
            "Рынок и исследования доступны, "
            "сохранение карточек заблокировано."
        )

    flash = st.session_state.pop("_flash", None)

    if flash:
        st.success(flash)

    try:
        if page == "Главная":
            st.title("Твои боты")
            action_buttons("home")

            columns = st.columns(3)

            for column, status, label in zip(
                columns,
                ["Работает", "Черновик", "Закрыт"],
                ["В работе", "Черновики", "Завершены"],
            ):
                column.metric(
                    label,
                    (
                        sum(
                            bot["lifecycle"] == status
                            for bot in bots
                        )
                        if DB_READY else "—"
                    ),
                )

            if DB_READY:
                list_bots(
                    bots,
                    "home",
                    compact=True,
                )
            else:
                st.info(
                    "Список не прочитан. "
                    "Это не подтверждение отсутствия карточек."
                )

        elif page == "Сканер":
            scanner()

        elif page in ("DCA", "Grid"):
            st.title(page)

            mode = st.radio(
                "Режим",
                ["Мои боты", "Добавить бота"],
                horizontal=True,
                key=page + "mode",
            )

            if mode == "Добавить бота":
                creator(page)
            else:
                if st.button("Добавить " + page):
                    route(
                        page,
                        "Long" if page == "DCA" else "Neutral",
                    )

                if DB_READY:
                    list_bots(
                        [
                            bot for bot in bots
                            if bot["strategy"] == page
                        ],
                        page,
                    )
                else:
                    st.info(
                        "Подключи PostgreSQL в Настройках."
                    )

        elif page == "Открытая позиция":
            st.title("Контроль позиций")

            if DB_READY:
                list_bots(
                    bots,
                    "positions",
                )
            else:
                st.info(
                    "Не удалось прочитать позиции из базы."
                )

        elif page == "Журнал":
            st.title("Журнал решений")

            if DB_READY:
                frame = load_events()

                if frame.empty:
                    st.info("Журнал пока пуст.")
                else:
                    table(frame)
                    st.download_button(
                        "Скачать CSV",
                        frame.to_csv(
                            index=False
                        ).encode("utf-8-sig"),
                        "journal.csv",
                        "text/csv",
                    )
            else:
                st.info("Журнал не прочитан.")

            st.caption(
                "Повторные снимки PnL "
                "не суммируются как прибыль."
            )

        else:
            settings_page(bots)

    except ValueError as exc:
        st.error(str(exc))
    except Exception as exc:
        st.error(
            "Действие не подтверждено: "
            + type(exc).__name__
            + ". После ошибки записи обнови список "
            "перед повтором. Реквизиты не публикуй."
        )


main()
