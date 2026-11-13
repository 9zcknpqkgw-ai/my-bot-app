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

DB_READY = False


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
        secret("DB_URL", ""),
    )
).strip()

# Только для импорта оставшегося старого SQLite.
# Новые карточки сохраняются исключительно в PostgreSQL.
DB_FILE = str(
    secret("SQLITE_PATH", "bots.sqlite3")
)


# =========================================================
# ОБЩИЕ ФУНКЦИИ
# =========================================================

def now():
    return datetime.now(timezone.utc).isoformat()


def num(value, default=0.0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def fmt(value, digits=2):
    return "—" if value is None else f"{value:,.{digits}f}"


def sign(direction):
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
    except (ValueError, TypeError):
        return float("inf")


def canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
    )


def number(
    label,
    value,
    key,
    minimum=0.0,
    maximum=None,
    integer=False,
):
    cast = int if integer else float

    args = {
        "label": label,
        "key": key,
    }

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
# НАВИГАЦИЯ
# =========================================================

def move(
    page,
    direction=None,
    template=None,
    focus=None,
    mode="Мои боты",
):
    st.session_state["_route"] = {
        "page": page,
        "direction": direction,
        "template": template or {},
        "focus": focus,
        "mode": mode,
    }

    st.rerun()


def apply_route():
    request = st.session_state.pop("_route", None)

    if request and request["page"] in PAGES:
        page = request["page"]
        st.session_state["page"] = page

        if page in ("DCA", "Grid"):
            st.session_state[page + "mode"] = request["mode"]

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
# ОФОРМЛЕНИЕ
# =========================================================

def design():
    st.markdown(
        """
<style>
.stApp {
    background:
        radial-gradient(
            1000px 600px at 8% -10%,
            rgba(0,255,157,.09),
            transparent 60%
        ),
        radial-gradient(
            900px 600px at 100% 0%,
            rgba(88,101,242,.12),
            transparent 55%
        ),
        #05070c !important;
    color: #e8ecf4;
    color-scheme: dark;
}

.block-container {
    max-width: 1400px;
    padding-top: 1.4rem;
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
    background: #090f1b !important;
    border-right: 1px solid #29384f;
}

.glass {
    background: linear-gradient(130deg, #12272c, #151a2c);
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

[data-testid="stMetric"] {
    background: linear-gradient(145deg, #171c29, #0b0e16);
    border: 1px solid #2b3a50;
    border-radius: 16px;
    padding: 16px;
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

[data-testid="stNumberInput"] button {
    background: #eaf0fa !important;
    color: #172033 !important;
}

[data-testid="stSelectbox"] [data-baseweb="select"] > div {
    background: white !important;
    color: #172033 !important;
}

[data-testid="stSelectbox"] span,
[data-testid="stSelectbox"] input {
    color: #172033 !important;
    -webkit-text-fill-color: #172033 !important;
}

[role="listbox"],
[role="option"] {
    background: white !important;
    color: #172033 !important;
}

[data-testid="stRadio"] [role="radiogroup"] > label {
    background: white !important;
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

.st-key-DCAdirection [role="radiogroup"] > label:nth-of-type(1),
.st-key-Griddirection [role="radiogroup"] > label:nth-of-type(1) {
    background: #dcfce7 !important;
    border-color: #16a34a !important;
}

.st-key-DCAdirection [role="radiogroup"] > label:nth-of-type(2),
.st-key-Griddirection [role="radiogroup"] > label:nth-of-type(2) {
    background: #fee2e2 !important;
    border-color: #dc2626 !important;
}

.st-key-Griddirection [role="radiogroup"] > label:nth-of-type(3) {
    background: #fef08a !important;
    border-color: #ca8a04 !important;
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

.terminal-table-wrap {
    width: 100%;
    overflow-x: auto;
    max-height: 650px;
    overflow-y: auto;
    border: 1px solid #2b3a50;
    border-radius: 12px;
    margin-bottom: 12px;
    background: #101827;
}

.terminal-table-wrap table {
    width: 100%;
    border-collapse: collapse;
    background: #101827 !important;
    color: #e8ecf4 !important;
    font-size: .88rem;
}

.terminal-table-wrap th {
    background: #182338 !important;
    color: #edf3ff !important;
    border: 1px solid #2b3a50 !important;
    padding: 10px 12px !important;
    text-align: left !important;
    position: sticky;
    top: 0;
    z-index: 1;
    white-space: nowrap;
}

.terminal-table-wrap td {
    border: 1px solid #243249 !important;
    padding: 9px 12px !important;
    vertical-align: top;
}

@media(max-width: 640px) {
    .block-container {
        padding: 1rem;
    }

    .glass {
        padding: 16px;
    }
}
</style>
        """,
        unsafe_allow_html=True,
    )


def panel(title, text):
    st.markdown(
        '<div class="glass"><h2>'
        + html.escape(title)
        + '</h2><p>'
        + html.escape(text)
        + '</p></div>',
        unsafe_allow_html=True,
    )


def signal_style(value):
    text = str(value).strip().upper()

    if text in ("LONG", "ЛОНГ", "DCA LONG"):
        color = "#4ade80"
    elif text in ("SHORT", "ШОРТ", "DCA SHORT"):
        color = "#fb7185"
    elif text in (
        "NEUTRAL",
        "НЕЙТРАЛЬНО",
        "НЕЙТРАЛЬНЫЙ",
        "GRID",
    ):
        color = "#facc15"
    else:
        color = "#b8c4d8"

    return (
        "background-color: #101827;"
        f"color: {color};"
        "font-weight: 800;"
    )


def recommendation_style(value):
    color = {
        "Запускать": "#4ade80",
        "Пропустить": "#fb7185",
        "Проверить": "#facc15",
        "Нет данных": "#b8c4d8",
    }.get(str(value), "#e8ecf4")

    return (
        "background-color: #101827;"
        f"color: {color};"
        "font-weight: 700;"
    )


def styled_frame(frame):
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

    for column in ("Циклов", "Циклы/лоты"):
        if column in frame.columns:
            formats[column] = "{:,.0f}"

    styled = (
        frame.style
        .set_properties(**{
            "background-color": "#101827",
            "color": "#e8ecf4",
        })
        .format(
            formats,
            na_rep="—",
            escape="html",
        )
        .format_index(
            escape="html",
            axis=1,
        )
    )

    direction_columns = [
        column
        for column in ("Сигнал", "Направление")
        if column in frame.columns
    ]

    if direction_columns:
        styled = styled.map(
            signal_style,
            subset=direction_columns,
        )

    if "Рекомендация" in frame.columns:
        styled = styled.map(
            recommendation_style,
            subset=["Рекомендация"],
        )

    return styled


def table(frame):
    if frame.empty:
        return

    styled = styled_frame(frame).hide(axis="index")

    st.markdown(
        '<div class="terminal-table-wrap">'
        + styled.to_html()
        + '</div>',
        unsafe_allow_html=True,
    )


# =========================================================
# ПАРОЛЬ
# =========================================================

def login():
    password = str(secret("APP_PASSWORD"))

    if not password.strip():
        panel(
            "Вход заблокирован",
            "Задай APP_PASSWORD в Streamlit Secrets. "
            "Без пароля терминал не открывается.",
        )
        st.stop()

    if st.session_state.get("_authenticated"):
        return

    panel(
        "OKX Terminal Pro",
        "Вход в личный терминал",
    )

    with st.form("login", clear_on_submit=True):
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
            entered.encode("utf-8"),
            password.encode("utf-8"),
        ):
            st.session_state["_authenticated"] = True
            st.rerun()
        else:
            st.error("Неверный пароль.")

    st.stop()


# =========================================================
# POSTGRESQL
# =========================================================

@contextmanager
def database():
    if not DB_URL:
        raise ValueError(
            "DATABASE_URL не настроен. "
            "Сохранение в память или локальный файл "
            "не используется."
        )

    import psycopg2

    connection = None

    try:
        connection = psycopg2.connect(
            dsn=DB_URL,
            connect_timeout=10,
            application_name="okx_terminal",
        )

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

    # Используется только с фиксированными запросами приложения.
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


def check_postgres():
    with database() as connection:
        result = sql(
            connection,
            "SELECT 1",
        ).fetchone()

        if result != (1,):
            raise ValueError(
                "База не подтвердила проверку."
            )


def record(connection, bot_id, title, details):
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
    if not isinstance(raw, dict):
        raise ValueError(
            "Карточка должна быть объектом JSON."
        )

    bot = json.loads(canonical(raw))

    if (
        bot.get("strategy") not in ("DCA", "Grid")
        or bot.get("direction")
        not in ("Long", "Short", "Neutral")
    ):
        raise ValueError(
            "Неизвестная стратегия "
            "или направление карточки."
        )

    if (
        bot["strategy"] == "DCA"
        and bot["direction"] == "Neutral"
    ):
        raise ValueError(
            "DCA Neutral не поддерживается."
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

    market = str(bot.get("market", "SWAP"))

    bot["market"] = (
        "SWAP"
        if "SWAP" in market or "Фьючерсы" in market
        else "SPOT"
    )

    bot.setdefault(
        "name",
        bot["coin"] + " " + bot["strategy"],
    )

    bot.setdefault("created_at", now())
    bot.setdefault("lifecycle", "Черновик")

    if bot["lifecycle"] not in (
        "Черновик",
        "Работает",
        "Закрыт",
    ):
        raise ValueError(
            "Неизвестный статус карточки."
        )

    for key in ("settings", "position"):
        if isinstance(bot.get(key), str):
            bot[key] = json.loads(bot[key])

        bot.setdefault(key, {})

        if not isinstance(bot[key], dict):
            raise ValueError(
                "Неверные настройки позиции."
            )

    settings = bot["settings"]
    position = bot["position"]

    defaults = {
        "entry": 0,
        "tp": 1.5,
        "step": 2,
        "so_count": 4,
        "mart": 1.2,
        "base_amount": 10,
        "first_so": 10,
        "base_margin": 100,
        "reserve": 50,
        "leverage": 1,
        "lower": 0,
        "upper": 0,
        "grids": 10,
        "target_price": 0,
        "stop_price": 0,
        "stop_lower": 0,
        "stop_upper": 0,
        "max_loss": 0,
        "danger_pct": 3,
        "liq_warn": 10,
        "stale_hours": 6,
    }

    for key, default in defaults.items():
        value = settings.get(key, default)

        try:
            converted = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Нечисловой параметр: " + key
            ) from exc

        if not math.isfinite(converted):
            raise ValueError(
                "Неверный параметр: " + key
            )

        if (
            key in ("so_count", "grids")
            and converted != int(converted)
        ):
            raise ValueError(
                "Нужно целое число: " + key
            )

        settings[key] = (
            int(converted)
            if key in ("so_count", "grids")
            else converted
        )

    settings["total_budget"] = num(
        settings.get("total_budget"),
        settings["base_margin"] + settings["reserve"],
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

    for raw, revision in rows:
        bot = normalize(json.loads(raw))
        bot["_revision"] = revision
        result.append(bot)

    return sorted(
        result,
        key=lambda bot: bot.get("updated_at", ""),
        reverse=True,
    )


def save_bot(bot, title, details):
    document = normalize(bot)

    revision = document.pop("_revision", None)

    if not document.get("id"):
        raise ValueError("У карточки нет ID.")

    document["updated_at"] = now()

    raw = canonical(document)

    with database() as connection:
        if revision is None:
            row = sql(
                connection,
                """
                INSERT INTO terminal_bots
                VALUES (?, ?, 1)
                ON CONFLICT (id) DO NOTHING
                RETURNING revision
                """,
                (
                    document["id"],
                    raw,
                ),
            ).fetchone()

            if row is None:
                raise ValueError(
                    "Карточка с этим ID уже есть. "
                    "Обнови список: предыдущая попытка "
                    "могла сохраниться."
                )

        else:
            row = sql(
                connection,
                """
                UPDATE terminal_bots
                SET document = ?,
                    revision = revision + 1
                WHERE id = ?
                  AND revision = ?
                RETURNING revision
                """,
                (
                    raw,
                    document["id"],
                    revision,
                ),
            ).fetchone()

            if row is None:
                raise ValueError(
                    "Карточка изменена в другой вкладке. "
                    "Обнови страницу перед повторным "
                    "редактированием."
                )

        new_revision = row[0]

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
            FROM terminal_bots
            WHERE id = ?
            """,
            (document["id"],),
        ).fetchone()

    if (
        not saved
        or saved[0] != raw
        or saved[1] != new_revision
    ):
        raise ValueError(
            "Запись отправлена, но повторная "
            "проверка версии не совпала. "
            "Обнови список, не создавай дубликат."
        )

    return new_revision


def history():
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
# РЕЗЕРВНЫЕ КОПИИ
# =========================================================

def backup_bytes():
    with database() as connection:
        sql(
            connection,
            """
            SET TRANSACTION
            ISOLATION LEVEL REPEATABLE READ
            READ ONLY
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
                FROM terminal_events
                ORDER BY created_at
                """,
            ).fetchall()
        ]

    return json.dumps(
        {
            "version": 17,
            "created_at": now(),
            "bots": bots,
            "events": events,
        },
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    ).encode("utf-8")


def import_backup(source):
    if (
        not isinstance(source, dict)
        or not isinstance(source.get("bots"), list)
        or len(source["bots"]) > 1000
    ):
        raise ValueError(
            "Нужен JSON с массивом bots, "
            "не более 1000 карточек."
        )

    events = source.get("events", [])

    if (
        not isinstance(events, list)
        or len(events) > 20000
    ):
        raise ValueError(
            "Неверный журнал копии "
            "или больше 20000 событий."
        )

    prepared = []
    mapping = {}

    for raw in source["bots"]:
        bot = normalize(raw)
        old_id = str(bot.get("id", ""))

        if old_id and old_id in mapping:
            raise ValueError(
                "В копии повторяются ID."
            )

        bot.pop("_revision", None)

        bot.update(
            id=str(uuid.uuid4()),
            lifecycle="Черновик",
            updated_at=now(),
        )

        bot["position"]["last_check"] = ""

        if old_id:
            mapping[old_id] = bot["id"]

        prepared.append(bot)

    with database() as connection:
        for bot in prepared:
            sql(
                connection,
                """
                INSERT INTO terminal_bots
                VALUES (?, ?, 1)
                """,
                (
                    bot["id"],
                    canonical(bot),
                ),
            )

            record(
                connection,
                bot["id"],
                "Импорт",
                "Копия добавлена без замены "
                "существующей карточки. "
                "Нужна сверка с OKX.",
            )

        for event in events:
            if not isinstance(event, dict):
                raise ValueError(
                    "Неверное событие журнала."
                )

            old_bot_id = str(
                event.get(
                    "bot_id",
                    event.get("Бот ID", ""),
                )
            )

            target = mapping.get(old_bot_id)

            if not target:
                continue

            original_date = str(
                event.get(
                    "created_at",
                    event.get("Дата UTC", ""),
                )
            )

            title = str(
                event.get(
                    "title",
                    event.get("Событие", "Событие"),
                )
            )

            details = str(
                event.get(
                    "details",
                    event.get("Подробности", ""),
                )
            )

            record(
                connection,
                target,
                "Импорт: " + title,
                original_date + " · " + details,
            )

    with database() as connection:
        for bot in prepared:
            saved = sql(
                connection,
                """
                SELECT id
                FROM terminal_bots
                WHERE id = ?
                """,
                (bot["id"],),
            ).fetchone()

            if not saved:
                raise ValueError(
                    "Импорт отправлен, но проверка "
                    "не завершена. Обнови список."
                )

    return len(prepared)


# =========================================================
# ПУБЛИЧНЫЕ ДАННЫЕ OKX
# =========================================================

@st.cache_data(
    ttl=20,
    max_entries=256,
    show_spinner=False,
)
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

            if str(result.get("code")) != "0":
                raise ValueError(
                    "OKX не подтвердил запрос."
                )

            return result.get("data", [])

        except (
            requests.RequestException,
            ValueError,
        ) as exc:
            error = exc
            time.sleep(0.2 * (attempt + 1))

    raise ValueError(
        "Данные OKX недоступны. "
        "Проверь доступность инструмента "
        "и повтори запрос."
    ) from error


def instrument(coin, market):
    return (
        f"{coin}-USDT"
        + ("-SWAP" if market == "SWAP" else "")
    )


@st.cache_data(
    ttl=20,
    max_entries=100,
    show_spinner=False,
)
def quote(coin, market):
    rows = api(
        "/market/ticker",
        {"instId": instrument(coin, market)},
    )

    if not rows:
        raise ValueError(
            "Инструмент не найден на OKX."
        )

    row = rows[0]

    price = num(row.get("last"))
    timestamp = num(row.get("ts"))

    if (
        price <= 0
        or timestamp <= 0
        or abs(time.time() - timestamp / 1000) > 180
    ):
        raise ValueError(
            "Нет свежей рыночной цены."
        )

    opening = num(row.get("open24h"))

    return {
        "price": price,
        "ts": timestamp,
        "volume": (
            num(row.get("volCcy24h"))
            * (price if market == "SWAP" else 1)
        ),
        "change": (
            (price / opening - 1) * 100
            if opening > 0
            else None
        ),
    }


def candle_frame(rows):
    data = [
        [
            int(row[0]),
            *map(float, row[1:5]),
        ]
        for row in rows
        if len(row) >= 9
        and str(row[8]) == "1"
    ]

    frame = (
        pd.DataFrame(
            data,
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

    columns = ["open", "high", "low", "close"]

    if (
        frame.empty
        or not np.isfinite(
            frame[columns].to_numpy()
        ).all()
        or (frame[columns] <= 0).any().any()
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


@st.cache_data(
    ttl=180,
    max_entries=100,
    show_spinner=False,
)
def daily(coin, market):
    frame = candle_frame(
        api(
            "/market/candles",
            {
                "instId": instrument(coin, market),
                "bar": "1D",
                "limit": "200",
            },
        )
    )

    if (
        len(frame) < 60
        or (
            frame.ts.diff().dropna() != 24 * HOUR
        ).any()
        or (
            time.time() * 1000 - frame.ts.iloc[-1]
            > 49 * HOUR
        )
    ):
        raise ValueError(
            "Недостаточно непрерывной "
            "свежей дневной истории."
        )

    return frame


# =========================================================
# ИНДИКАТОРЫ
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
            seed.append(float(value))

            if len(seed) == period:
                previous = sum(seed) / period
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

    gain = rma(delta.clip(lower=0))
    loss = rma(-delta.clip(upper=0))

    rsi = 100 - 100 / (1 + gain / loss)

    rsi.loc[(gain == 0) & (loss == 0)] = 50
    rsi.loc[(gain > 0) & (loss == 0)] = 100

    true_range = pd.concat(
        [
            frame.high - frame.low,
            (frame.high - frame.close.shift()).abs(),
            (frame.low - frame.close.shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)

    true_range.iloc[0] = np.nan

    atr = rma(true_range)

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

    dx = 100 * (plus - minus).abs() / total
    dx.loc[total == 0] = 0

    frame["RSI"] = rsi
    frame["ADX"] = rma(dx)
    frame["ATR %"] = atr / frame.close * 100

    frame["+DI"] = 100 * plus / atr
    frame["-DI"] = 100 * minus / atr

    frame.loc[
        atr == 0,
        ["+DI", "-DI"],
    ] = 0

    return frame


# =========================================================
# ГРАФИК РЫНКА
# =========================================================

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
            line={"color": "#00c2ff"},
        ),
        row=2,
        col=1,
    )

    figure.add_trace(
        go.Scatter(
            x=frame.time,
            y=frame.ADX,
            name="ADX",
            line={"color": "#ffd166"},
        ),
        row=3,
        col=1,
    )

    for value in (30, 70):
        figure.add_hline(
            y=value,
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
# КНОПКИ НАПРАВЛЕНИЯ
# =========================================================

def actions(prefix):
    columns = st.columns(3)

    variants = [
        ("🟢 ЛОНГ · DCA", "DCA", "Long", "long"),
        ("🔴 ШОРТ · DCA", "DCA", "Short", "short"),
        ("🟡 NEUTRAL · GRID", "Grid", "Neutral", "neutral"),
    ]

    for column, variant in zip(columns, variants):
        label, strategy, direction, suffix = variant

        if column.button(
            label,
            key=f"action_{prefix}_{suffix}",
            use_container_width=True,
        ):
            move(
                strategy,
                direction,
                mode="Добавить бота",
            )


# =========================================================
# ПЛАН DCA
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
            "Проверь цену входа и параметры DCA."
        )

    rows = []
    total = 0.0
    quantity = 0.0

    for index in range(count + 1):
        price = entry * (
            1 - sign(direction) * step * index / 100
        )

        if price <= 0:
            raise ValueError(
                "Один из уровней DCA имеет цену ≤ 0."
            )

        amount = (
            base
            if index == 0
            else first * multiplier ** (index - 1)
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
# ИСТОРИЯ ДЛЯ ОБЫЧНОГО БЭКТЕСТА
# =========================================================

@st.cache_data(
    ttl=300,
    max_entries=20,
    show_spinner=False,
)
def history_prices(coin, market, days, end):
    start = end - days * 24 * HOUR

    after = end
    rows = []
    previous = None

    for _ in range(100):
        batch = api(
            "/market/history-candles",
            {
                "instId": instrument(coin, market),
                "bar": "1H",
                "limit": "100",
                "after": str(after),
            },
        )

        if not batch:
            break

        rows.extend(batch)

        oldest = min(int(row[0]) for row in batch)

        if oldest <= start or oldest == previous:
            break

        previous = oldest
        after = oldest

        time.sleep(0.12)

    frame = candle_frame(rows)

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
            "История не покрывает весь период "
            "без пропусков. Тест не выполнен."
        )

    return frame


# =========================================================
# РАСЧЁТНЫЙ МОДУЛЬ БЭКТЕСТА
# =========================================================

def simulate(
    frame,
    settings,
    strategy,
    direction,
    market,
    fee,
):
    capital = num(settings["base_margin"])
    leverage = num(settings["leverage"])

    if (
        capital <= 0
        or leverage < 1
        or frame.empty
    ):
        raise ValueError(
            "Проверь капитал, плечо и историю."
        )

    if (
        market == "SPOT"
        and (
            direction != "Long"
            or leverage != 1
        )
    ):
        raise ValueError(
            "Spot поддерживает только Long 1x."
        )

    if strategy == "DCA":
        plan = dca_plan(settings, direction)
        total_notional = plan[-1]["Всего номинал"]

        if (
            total_notional / leverage
            + total_notional * fee
            >= capital
        ):
            raise ValueError(
                "Капитала не хватает "
                "на все ордера с комиссиями."
            )

    elif strategy == "Grid":
        if (
            not 0 < settings["lower"] < settings["upper"]
            or int(settings["grids"]) < 2
        ):
            raise ValueError(
                "Проверь диапазон "
                "и число интервалов Grid."
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
            settings["lower"] + settings["upper"]
        ) / 2

    else:
        raise ValueError(
            "Неизвестная стратегия теста."
        )

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
    blocked_orders = 0

    prices = frame.close.to_numpy(dtype=float)

    for index, price in enumerate(prices):
        if strategy == "DCA":
            direction_sign = sign(direction)

            reached_take = (
                quantity
                and direction_sign
                * (price / average - 1)
                * 100
                >= settings["tp"]
            )

            if reached_take:
                close_fee = quantity * price * fee

                wallet += (
                    direction_sign
                    * quantity
                    * (price - average)
                    - close_fee
                )

                fees += close_fee

                quantity = 0.0
                used = 0.0
                cycles += 1

            elif quantity == 0:
                amount = settings["base_amount"]

                if (
                    wallet
                    >= amount / leverage + amount * fee
                ):
                    quantity = amount / price
                    average = price
                    entry = price
                    used = amount / leverage
                    executed = 0

                    wallet -= amount * fee
                    fees += amount * fee
                else:
                    blocked_orders += 1

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

                available = (
                    wallet
                    if market == "SPOT"
                    else wallet
                    + direction_sign
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
                        quantity * average + amount
                    ) / (
                        quantity + amount / price
                    )

                    quantity += amount / price
                    used += amount / leverage

                    wallet -= amount * fee
                    fees += amount * fee

                    executed += 1
                else:
                    # Это число попыток на свечах,
                    # а не количество уникальных СО.
                    blocked_orders += 1

            floating = (
                direction_sign
                * quantity
                * (price - average)
                if quantity
                else 0.0
            )

            equity = wallet + floating

        elif market == "SPOT":
            for key in list(lots):
                lot_quantity, cost = lots[key]

                if price >= levels[key + 1]:
                    gross = lot_quantity * price

                    wallet += gross * (1 - fee)
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
                    full_cost = allocation * (1 + fee)

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
                for lot_quantity, cost in lots.values()
            )

            equity = wallet + sum(
                lot_quantity * price
                for lot_quantity, cost in lots.values()
            )

        else:
            for key in list(lots):
                (
                    lot_sign,
                    lot_quantity,
                    opened,
                    target,
                    margin,
                ) = lots[key]

                if lot_sign * (price - target) >= 0:
                    close_fee = lot_quantity * price * fee

                    wallet += (
                        lot_sign
                        * lot_quantity
                        * (price - opened)
                        - close_fee
                    )

                    fees += close_fee

                    del lots[key]
                    cycles += 1

            floating = sum(
                lot_sign
                * lot_quantity
                * (price - opened)
                for (
                    lot_sign,
                    lot_quantity,
                    opened,
                    target,
                    margin,
                ) in lots.values()
            )

            used = sum(lot[4] for lot in lots.values())

            if (
                index > 0
                and settings["lower"]
                <= price
                <= settings["upper"]
            ):
                for level_index, level in enumerate(levels):
                    if direction == "Long":
                        lot_sign = 1
                    elif direction == "Short":
                        lot_sign = -1
                    else:
                        lot_sign = (
                            1 if level < middle else -1
                        )

                    if (
                        lot_sign == 1
                        and level_index == len(levels) - 1
                    ):
                        continue

                    if lot_sign == -1 and level_index == 0:
                        continue

                    crossed = (
                        prices[index - 1] > level >= price
                        if lot_sign == 1
                        else prices[index - 1] < level <= price
                    )

                    key = (level_index, lot_sign)

                    opening_fee = (
                        allocation * leverage * fee
                    )

                    if (
                        crossed
                        and key not in lots
                        and wallet + floating
                        >= used + allocation + opening_fee
                    ):
                        lots[key] = (
                            lot_sign,
                            allocation * leverage / price,
                            price,
                            levels[level_index + lot_sign],
                            allocation,
                        )

                        wallet -= opening_fee
                        fees += opening_fee
                        used += allocation

            floating = sum(
                lot_sign
                * lot_quantity
                * (price - opened)
                for (
                    lot_sign,
                    lot_quantity,
                    opened,
                    target,
                    margin,
                ) in lots.values()
            )

            equity = wallet + floating

        if equity <= 0:
            curve.append(0.0)
            halted = True
            break

        curve.append(equity)

    values = np.array([capital, *curve])
    peaks = np.maximum.accumulate(values)

    return {
        "roi": (curve[-1] / capital - 1) * 100,
        "pnl": curve[-1] - capital,
        "cycles": cycles,
        "fees": fees,
        "floating": floating,
        "dd": float(
            np.max((peaks - values) / peaks) * 100
        ),
        "halted": halted,
        "blocked_orders": blocked_orders,
        "curve": curve,
    }


# =========================================================
# ОБЫЧНЫЙ БЭКТЕСТ И АЛЬТЕРНАТИВЫ
# =========================================================

def backtest(
    kind,
    coin,
    market,
    direction,
    settings,
    valid,
):
    with st.expander(
        "Бэктест и сравнение альтернатив"
    ):
        days = st.selectbox(
            "Дней истории 1H",
            [7, 14, 30, 90],
            index=1,
            key=kind + "days",
        )

        fee = number(
            "Комиссия за сторону, % от номинала",
            0.05,
            kind + "fee",
            0,
            5,
        ) / 100

        if st.button(
            "Рассчитать мой план и две альтернативы",
            disabled=not valid,
            key=kind + "test",
        ):
            st.session_state.pop(
                kind + "result",
                None,
            )

            variants = [
                ("Мой план", dict(settings)),
                (
                    "Без увеличения СО"
                    if kind == "DCA"
                    else "Шире диапазон",
                    dict(settings),
                ),
                (
                    "Шире шаг"
                    if kind == "DCA"
                    else "Меньше интервалов",
                    dict(settings),
                ),
            ]

            if kind == "DCA":
                variants[1][1]["mart"] = 1.0
                variants[2][1]["step"] *= 1.5

            else:
                middle = (
                    settings["upper"] + settings["lower"]
                ) / 2

                half = (
                    settings["upper"] - settings["lower"]
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
                "Загружаю свечи и считаю..."
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
                    try:
                        result = simulate(
                            frame,
                            variant,
                            kind,
                            direction,
                            market,
                            fee,
                        )

                        rows.append({
                            "Вариант": label,
                            "Результат USDT": result["pnl"],
                            "Доходность %": result["roi"],
                            "Просадка %": result["dd"],
                            "Циклы/лоты": result["cycles"],
                            "Комиссии USDT": result["fees"],
                            "Открытый PnL": result["floating"],
                            "Капитал исчерпан": str(
                                result["halted"]
                            ),
                            "Свечей с нехваткой средств": (
                                result["blocked_orders"]
                            ),
                            "Параметры": canonical(variant),
                        })

                        curves[label] = (
                            result["curve"]
                            + [np.nan]
                            * (
                                len(frame)
                                - len(result["curve"])
                            )
                        )

                    except ValueError as exc:
                        rows.append({
                            "Вариант": label,
                            "Ошибка модели": str(exc),
                            "Параметры": canonical(variant),
                        })

                st.session_state[kind + "result"] = {
                    "rows": rows,
                    "curves": pd.DataFrame(
                        curves,
                        index=frame.time,
                    ),
                    "caption": (
                        f"{coin} · {market} · {direction} · "
                        f"{frame.time.iloc[0]} — "
                        f"{frame.time.iloc[-1]} · "
                        f"{len(frame)} свечей"
                    ),
                }

        result = st.session_state.get(kind + "result")

        if result:
            st.caption(
                "Последний расчёт, "
                "не обязательно текущие поля: "
                + result["caption"]
            )

            table(pd.DataFrame(result["rows"]))

            if not result["curves"].empty:
                st.line_chart(result["curves"])

        st.caption(
            "Модель по закрытиям 1H. "
            "Открытая позиция включена в итоговый капитал "
            "без гипотетической комиссии её закрытия. "
            "Futures Grid — приближённая модель пересечений "
            "уровней без стартовой позиции, не копия OKX. "
            "Нет funding, ликвидации, MMR, проскальзывания "
            "и внутрисвечных исполнений. "
            "Стопы, лимит убытка и отдельный резерв "
            "в тесте не исполняются. "
            "Одного периода недостаточно "
            "для выбора лучшего варианта."
        )


# =========================================================
# ПАКЕТНЫЙ БЭКТЕСТ
# =========================================================

def _batch_load_history(
    coin,
    end_ms,
    request_lock,
    next_request_at,
):
    start_ms = end_ms - 14 * 24 * HOUR

    url = API + "/market/history-candles"
    instrument_id = f"{coin}-USDT-SWAP"

    after = end_ms
    raw_rows = []

    def reserve_request_slot():
        with request_lock:
            delay = (
                next_request_at[0] - time.monotonic()
            )

            if delay > 0:
                time.sleep(delay)

            next_request_at[0] = (
                time.monotonic() + 0.25
            )

    with requests.Session() as session:
        for _ in range(8):
            batch = None
            last_error = None

            for attempt in range(3):
                reserve_request_slot()

                try:
                    response = session.get(
                        url,
                        params={
                            "instId": instrument_id,
                            "bar": "1H",
                            "limit": "100",
                            "after": str(after),
                        },
                        timeout=(5, 15),
                    )

                    response.raise_for_status()
                    payload = response.json()

                    if str(payload.get("code")) != "0":
                        raise ValueError(
                            "OKX не подтвердил "
                            "запрос истории."
                        )

                    batch = payload.get("data", [])

                    if not isinstance(batch, list):
                        raise ValueError(
                            "Неверный формат истории."
                        )

                    break

                except (
                    requests.RequestException,
                    ValueError,
                ) as exc:
                    last_error = exc

                    if attempt < 2:
                        time.sleep(
                            0.5 * (attempt + 1)
                        )

            if batch is None:
                raise ValueError(
                    f"{coin}: история не загружена "
                    "после трёх попыток "
                    f"({type(last_error).__name__})."
                )

            if not batch:
                break

            raw_rows.extend(batch)

            oldest_ms = min(
                int(row[0]) for row in batch
            )

            if oldest_ms <= start_ms:
                break

            if oldest_ms >= after:
                raise ValueError(
                    f"{coin}: загрузка истории "
                    "не продвигается."
                )

            after = oldest_ms

    frame = candle_frame(raw_rows)

    frame = frame[
        (frame["ts"] >= start_ms)
        & (frame["ts"] < end_ms)
    ].reset_index(drop=True)

    expected = np.arange(
        start_ms,
        end_ms,
        HOUR,
        dtype=np.int64,
    )

    if (
        len(frame) != len(expected)
        or not np.array_equal(
            frame["ts"].to_numpy(dtype=np.int64),
            expected,
        )
    ):
        raise ValueError(
            f"{coin}: история неполная. "
            "Нужны 336 последовательных "
            "закрытых свечей 1H."
        )

    return frame


def _batch_dca_settings(budget, first_price):
    budget = float(budget)
    first_price = float(first_price)

    if not 100.0 <= budget <= 200.0:
        raise ValueError(
            "Бюджет бота должен быть "
            "от 100 до 200 USDT."
        )

    if (
        not np.isfinite(first_price)
        or first_price <= 0
    ):
        raise ValueError(
            "Некорректная первая цена."
        )

    leverage = 3.0
    safety_orders = 4
    multiplier = 1.2

    take_pct = 1.5
    fee_rate = 0.0005

    # Вход 1; СО: 1, 1.2, 1.44, 1.728.
    total_weight = 1.0 + sum(
        multiplier ** index
        for index in range(safety_orders)
    )

    # Маржа и расчётные комиссии находятся
    # внутри выбранного общего бюджета.
    cost_per_nominal = (
        1.0 / leverage
        + fee_rate
        + fee_rate * (1.0 + take_pct / 100.0)
    )

    first_nominal = (
        budget
        / (total_weight * cost_per_nominal)
    )

    return {
        "entry": first_price,
        "base_margin": budget,
        "leverage": leverage,
        "base_amount": first_nominal,
        "first_so": first_nominal,
        "so_count": safety_orders,
        "mart": multiplier,
        "step": 2.0,
        "tp": take_pct,
    }


def _batch_backtest_one(
    coin,
    direction,
    budget,
    end_ms,
    request_lock,
    next_request_at,
):
    if direction not in ("Long", "Short"):
        raise ValueError(
            "Поддерживаются только Long и Short."
        )

    frame = _batch_load_history(
        coin,
        end_ms,
        request_lock,
        next_request_at,
    )

    settings = _batch_dca_settings(
        budget,
        frame["close"].iloc[0],
    )

    result = simulate(
        frame=frame,
        settings=settings,
        strategy="DCA",
        direction=direction,
        market="SWAP",
        fee=0.0005,
    )

    profitability = float(result["roi"])

    if result["halted"]:
        recommendation = "Пропустить"
    elif profitability > 5:
        recommendation = "Запускать"
    elif profitability < 0:
        recommendation = "Пропустить"
    else:
        recommendation = "Проверить"

    return {
        "Монета": coin,
        "Направление": direction,
        "Бюджет USDT": float(budget),
        "Доходность %": profitability,
        "Циклов": int(result["cycles"]),
        "Просадка %": float(result["dd"]),
        "Результат USDT": float(result["pnl"]),
        "Комиссии USDT": float(result["fees"]),
        "Открытый PnL USDT": float(result["floating"]),
        "Свечей с нехваткой средств": int(
            result["blocked_orders"]
        ),
        "Рекомендация": recommendation,
        "Статус": (
            "Капитал исчерпан"
            if result["halted"]
            else "Готово"
        ),
        "Ошибка": "",
    }


def render_batch_backtest(saved_scan):
    st.markdown("### Пакетный бэктест")

    budget = st.number_input(
        "Общий бюджет одного бота, USDT",
        min_value=100.0,
        max_value=200.0,
        value=150.0,
        step=10.0,
        key="scanner_batch_budget",
    )

    st.caption(
        "Весь бюджет — на одного бота. "
        "Плечо 3× · TP 1,5% · шаг 2% · "
        "4 СО · множитель объёма ×1,2. "
        "Вход и СО размещаются внутри бюджета."
    )

    with st.expander(
        "Как распределяется выбранный бюджет"
    ):
        preview = _batch_dca_settings(
            budget,
            first_price=1.0,
        )

        first_nominal = preview["base_amount"]
        leverage = preview["leverage"]

        rows = [{
            "Ордер": "Вход",
            "Номинал USDT": first_nominal,
            "Маржа без комиссии": (
                first_nominal / leverage
            ),
        }]

        for index in range(4):
            nominal = (
                first_nominal * 1.2 ** index
            )

            rows.append({
                "Ордер": f"СО {index + 1}",
                "Номинал USDT": nominal,
                "Маржа без комиссии": nominal / leverage,
            })

        table(pd.DataFrame(rows))

        st.caption(
            "Остаток бюджета предусмотрен "
            "для расчётных комиссий. "
            "При убытке доступной маржи "
            "может не хватить на очередной СО: "
            "модель не добавляет деньги извне."
        )

    market = str(
        saved_scan.get("market", "SWAP")
    ).strip().upper()

    targets = set()

    for row in saved_scan.get("rows", []):
        signal_value = str(
            row.get("Сигнал", "")
        ).strip().upper()

        if signal_value not in ("LONG", "SHORT"):
            continue

        coin = str(
            row.get("Монета", "")
        ).strip().upper()

        if not coin or not coin.isalnum():
            continue

        direction = (
            "Long"
            if signal_value == "LONG"
            else "Short"
        )

        targets.add((coin, direction))

    targets = sorted(targets)

    scan_timestamp = str(
        saved_scan.get(
            "timestamp",
            saved_scan.get("time", ""),
        )
    )

    signature = (
        "DCA_BATCH_1_2_V1",
        market,
        scan_timestamp,
        float(budget),
        tuple(targets),
    )

    st.caption(
        "Монет LONG/SHORT в последнем сканировании: "
        f"{len(targets)}. "
        "GRID и неопределённые сигналы пропускаются."
    )

    if market != "SWAP":
        st.info(
            "Пакетный тест с плечом 3× работает "
            "для SWAP. Выполни сканирование SWAP."
        )

    if not targets:
        st.info(
            "В последнем сканировании "
            "нет сигналов LONG/SHORT."
        )

    run = st.button(
        "🚀 Проверить ВСЕХ на истории",
        key="scanner_batch_backtest_run",
        use_container_width=True,
        disabled=not targets or market != "SWAP",
    )

    if run:
        st.session_state.pop(
            "scanner_batch_backtest_result",
            None,
        )

        end_ms = (
            int(time.time() * 1000)
            // HOUR
            * HOUR
        )

        start_ms = end_ms - 14 * 24 * HOUR

        request_lock = Lock()
        next_request_at = [0.0]

        rows = []

        progress = st.progress(0.0)
        status = st.empty()

        with ThreadPoolExecutor(
            max_workers=min(4, len(targets))
        ) as executor:
            futures = {
                executor.submit(
                    _batch_backtest_one,
                    coin,
                    direction,
                    float(budget),
                    end_ms,
                    request_lock,
                    next_request_at,
                ): (coin, direction)
                for coin, direction in targets
            }

            for completed, future in enumerate(
                as_completed(futures),
                start=1,
            ):
                coin, direction = futures[future]

                try:
                    rows.append(future.result())

                except Exception as exc:
                    rows.append({
                        "Монета": coin,
                        "Направление": direction,
                        "Бюджет USDT": float(budget),
                        "Доходность %": np.nan,
                        "Циклов": np.nan,
                        "Просадка %": np.nan,
                        "Результат USDT": np.nan,
                        "Комиссии USDT": np.nan,
                        "Открытый PnL USDT": np.nan,
                        "Свечей с нехваткой средств": np.nan,
                        "Рекомендация": "Нет данных",
                        "Статус": "Ошибка",
                        "Ошибка": str(exc),
                    })

                progress.progress(
                    completed / len(targets)
                )

                status.caption(
                    f"Обработано: {completed}/{len(targets)} "
                    f"· последняя монета: {coin}"
                )

        result_frame = (
            pd.DataFrame(rows)
            .sort_values(
                by="Доходность %",
                ascending=False,
                na_position="last",
                kind="mergesort",
            )
            .reset_index(drop=True)
        )

        st.session_state[
            "scanner_batch_backtest_result"
        ] = {
            "signature": signature,
            "frame": result_frame,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "budget": float(budget),
        }

    saved_result = st.session_state.get(
        "scanner_batch_backtest_result"
    )

    if not saved_result:
        return

    if saved_result["signature"] != signature:
        st.info(
            "Бюджет или сканирование изменились. "
            "Нажми кнопку для нового расчёта."
        )
        return

    result_frame = saved_result["frame"]

    start_text = pd.to_datetime(
        saved_result["start_ms"],
        unit="ms",
        utc=True,
    ).strftime("%d.%m.%Y %H:%M UTC")

    end_text = pd.to_datetime(
        saved_result["end_ms"],
        unit="ms",
        utc=True,
    ).strftime("%d.%m.%Y %H:%M UTC")

    st.caption(
        f"Период: {start_text} — {end_text}. "
        "Правая граница не включена. "
        "336 закрытых свечей 1H на монету. "
        f"Бюджет: {saved_result['budget']:.2f} USDT."
    )

    st.dataframe(
        styled_frame(result_frame),
        use_container_width=True,
        hide_index=True,
    )

    errors_count = int(
        (result_frame["Статус"] == "Ошибка").sum()
    )

    if errors_count:
        st.warning(
            f"Не рассчитано монет: {errors_count}. "
            "Причины указаны в колонке «Ошибка»."
        )

    st.download_button(
        "Скачать пакетный тест CSV",
        result_frame.to_csv(
            index=False
        ).encode("utf-8-sig"),
        "batch_backtest.csv",
        "text/csv",
        key="scanner_batch_download",
    )

    st.caption(
        "Доходность считается от всего бюджета бота. "
        "Пропорции ордеров: 1 : 1 : 1,2 : 1,44 : 1,728. "
        "Комиссия — 0,05% от номинала за сторону. "
        "Открытая конечная позиция включена в результат "
        "без гипотетической комиссии её закрытия."
    )

    st.caption(
        "«Запускать» — метка доходности > 5% "
        "на этом периоде, не торговая команда "
        "и не прогноз. "
        "Модель использует закрытия 1H; "
        "не учитывает funding, ликвидацию, "
        "MMR, проскальзывание и исполнения внутри свечи. "
        "Карточки работающих ботов не изменяются."
    )


# =========================================================
# СКАНЕР РЫНКА
# =========================================================

def analyze_coin(coin, market):
    frame = indicators(daily(coin, market))
    ticker = quote(coin, market)

    last = frame.iloc[-1]

    if not np.isfinite([
        last.RSI,
        last.ADX,
        last["ATR %"],
        last["+DI"],
        last["-DI"],
    ]).all():
        raise ValueError(
            "Индикаторы не готовы."
        )

    if last.ADX < 25:
        signal_value = "GRID"
    elif last["+DI"] > last["-DI"]:
        signal_value = "LONG"
    elif last["-DI"] > last["+DI"]:
        signal_value = "SHORT"
    else:
        signal_value = "Не определено"

    take = (
        1.0
        if last["ATR %"] < 1.5
        else 1.5
        if last["ATR %"] < 3
        else 2.0
    )

    return {
        "Монета": coin,
        "Цена": ticker["price"],
        "Сигнал": signal_value,
        "RSI": last.RSI,
        "ADX": last.ADX,
        "ATR %": last["ATR %"],
        "Объём 24H ≈ USDT": ticker["volume"],
        "Тейк %": take,
    }


def scanner():
    panel(
        "2. Сканер рынка",
        "Закрытые дневные свечи, RSI/ADX, "
        "пакетная проверка истории "
        "и переход к настройке бота.",
    )

    market = st.radio(
        "Рынок",
        ["SWAP", "SPOT"],
        horizontal=True,
        key="scanmarket",
    )

    if st.button(
        "Сканировать монеты",
        use_container_width=True,
    ):
        rows = []
        errors = []

        progress = st.progress(0.0)

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
                    rows.append(future.result())
                except Exception:
                    errors.append(jobs[future])

                progress.progress(
                    (index + 1) / len(jobs)
                )

        rows.sort(
            key=lambda row: COINS.index(
                row["Монета"]
            )
        )

        st.session_state["scan"] = {
            "rows": rows,
            "errors": errors,
            "market": market,
            "timestamp": now(),
        }

    saved = st.session_state.get("scan")

    if not saved:
        st.info("Запусти сканирование.")
        return

    st.caption(
        saved["market"] + " · " + saved["timestamp"]
    )

    st.caption(
        "Long — зелёный; Short — красный; "
        "Grid — жёлтый; неопределённый сигнал — серый."
    )

    if saved["errors"]:
        st.warning(
            "Нет корректных данных: "
            + ", ".join(saved["errors"])
        )

    if not saved["rows"]:
        return

    table(pd.DataFrame(saved["rows"]))

    # Пакетный тест встроен непосредственно
    # после таблицы последнего сканирования.
    render_batch_backtest(saved)

    st.markdown("---")

    coin = st.selectbox(
        "Открыть монету",
        [row["Монета"] for row in saved["rows"]],
    )

    row = next(
        row
        for row in saved["rows"]
        if row["Монета"] == coin
    )

    market_chart(
        indicators(daily(coin, saved["market"])),
        coin + " · цена / RSI / ADX",
    )

    st.caption(
        "Сигнал — правило индикаторов, не прогноз. "
        "TP по ATR — черновой шаблон, не оптимизация. "
        "GRID обозначает режим по индикаторам, "
        "а не подтверждённую позицию Neutral."
    )

    template = {
        "coin": coin,
        "market": saved["market"],
        "entry": float(row["Цена"]),
        "tp": float(row["Тейк %"]),
        "step": 2.0,
        "count": 4,
        "mart": 1.2,
    }

    columns = st.columns(3)

    variants = [
        ("🟢 DCA Long", "DCA", "Long", "long"),
        ("🔴 DCA Short", "DCA", "Short", "short"),
        (
            "🟡 Grid",
            "Grid",
            "Neutral" if saved["market"] == "SWAP" else "Long",
            "neutral",
        ),
    ]

    for column, variant in zip(columns, variants):
        label, strategy, direction, suffix = variant

        disabled = (
            saved["market"] != market
            or (
                saved["market"] == "SPOT"
                and direction == "Short"
            )
        )

        if column.button(
            label,
            key="action_scan_" + suffix,
            disabled=disabled,
        ):
            move(
                strategy,
                direction,
                template,
                mode="Добавить бота",
            )


# =========================================================
# ДОБАВЛЕНИЕ БОТА
# =========================================================

def creator(kind):
    task = st.radio(
        "Задача",
        [
            "Подготовить новый",
            "Добавить уже работающий",
        ],
        horizontal=True,
        key=kind + "task",
    )

    name = st.text_input(
        "Название",
        value="Мой " + kind,
        key=kind + "name",
    )

    coin_args = {
        "label": "Монета",
        "key": kind + "coin",
    }

    if kind + "coin" not in st.session_state:
        coin_args["value"] = "BTC"

    coin = (
        st.text_input(**coin_args)
        .strip()
        .upper()
    )

    if coin == "TON":
        st.warning(
            "Эта монета исключена из добавления "
            "новых ботов. Старые карточки не удаляются."
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
        st.warning(
            "Spot: выбери Long. "
            "Short и Neutral предназначены для SWAP."
        )
        return

    settings = {
        "base_margin": number(
            "Базовая маржа / капитал Spot, USDT",
            100,
            kind + "margin",
            0.01,
        ),
    }

    if kind == "DCA":
        settings["entry"] = number(
            "Цена первого входа",
            0,
            kind + "entry",
        )

        settings["tp"] = number(
            "TP: движение цены от средней, % "
            "(не ROI маржи)",
            1.5,
            kind + "tp",
            0.01,
            99,
        )

    else:
        settings["entry"] = 0.0

        settings["lower"] = number(
            "Нижняя граница — точная цена",
            0,
            kind + "lower",
        )

        settings["upper"] = number(
            "Верхняя граница — точная цена",
            0,
            kind + "upper",
        )

        settings["grids"] = number(
            "Количество интервалов",
            10,
            kind + "grids",
            2,
            200,
            integer=True,
        )

    with st.expander("Расширенные настройки"):
        settings["leverage"] = number(
            "Плечо; для Spot нужно 1",
            3 if market == "SWAP" else 1,
            kind + "leverage",
            1,
            100,
        )

        settings["reserve"] = number(
            "Отдельный резерв маржи, USDT",
            50,
            kind + "reserve",
        )

        settings["total_budget"] = (
            settings["base_margin"]
            + settings["reserve"]
        )

        if kind == "DCA":
            settings["step"] = number(
                "Шаг СО от первого входа, %",
                2,
                kind + "step",
                0.01,
                50,
            )

            settings["so_count"] = number(
                "Количество СО",
                4,
                kind + "count",
                0,
                30,
                integer=True,
            )

            settings["base_amount"] = number(
                "Номинал первого ордера, USDT",
                10,
                kind + "base",
                0.01,
            )

            settings["first_so"] = number(
                "Номинал первого СО, USDT",
                10,
                kind + "first",
                0.01,
            )

            settings["mart"] = number(
                "Множитель номинала последующих СО",
                1.2,
                kind + "mart",
                1,
                3,
            )

        else:
            settings["target_price"] = number(
                "Целевая цена завершения Long/Short; "
                "0 = нет",
                0,
                kind + "target",
            )

        if direction == "Neutral":
            settings["stop_lower"] = number(
                "Нижняя сигнальная стоп-цена; 0 = нет",
                0,
                kind + "stoplower",
            )

            settings["stop_upper"] = number(
                "Верхняя сигнальная стоп-цена; 0 = нет",
                0,
                kind + "stopupper",
            )

        else:
            settings["stop_price"] = number(
                "Сигнальная стоп-цена; 0 = нет",
                0,
                kind + "stop",
            )

        settings["max_loss"] = number(
            "Лимит убытка открытой позиции "
            "Long/Short, USDT; 0 = нет",
            0,
            kind + "loss",
        )

        settings["danger_pct"] = number(
            "Неблагоприятное движение "
            "для зоны внимания, %",
            3,
            kind + "danger",
            0.1,
            100,
        )

        settings["stale_hours"] = number(
            "Сверка устаревает через часов",
            6,
            kind + "stale",
            0.1,
            168,
        )

        settings["liq_warn"] = number(
            "Предупреждение у введённой ликвидации, %",
            10,
            kind + "liqwarn",
            0.1,
            100,
        )

        st.caption(
            "Стопы здесь — условия уведомления, "
            "а не биржевые ордера. "
            "Множитель изменяет объём СО, "
            "не расстояние между уровнями."
        )

    valid = (
        bool(name.strip())
        and coin.isalnum()
        and not (
            market == "SPOT"
            and settings["leverage"] != 1
        )
    )

    if (
        market == "SPOT"
        and settings["leverage"] != 1
    ):
        st.warning(
            "В расширенных настройках "
            "установи плечо 1 для Spot."
        )

    if kind == "DCA":
        try:
            plan = dca_plan(settings, direction)

            with st.expander("План ордеров"):
                table(pd.DataFrame(plan))

                required_margin = (
                    plan[-1]["Всего номинал"]
                    / settings["leverage"]
                )

                st.caption(
                    "Маржа на все ордера ≈ "
                    f"{required_margin:.2f} USDT, "
                    "без комиссий."
                )

            if (
                plan[-1]["Всего номинал"]
                / settings["leverage"]
                >= settings["base_margin"]
            ):
                valid = False

                st.warning(
                    "Базовой маржи не хватает "
                    "на план ордеров с запасом."
                )

        except ValueError as exc:
            valid = False
            st.info(str(exc))

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

    pending_key = kind + "pending_id"

    if pending_key not in st.session_state:
        st.session_state[pending_key] = {
            "id": str(uuid.uuid4()),
            "created_at": now(),
        }

    if st.button(
        "Сохранить карточку в PostgreSQL",
        disabled=not valid or not DB_READY,
        key=kind + "save",
        use_container_width=True,
    ):
        quote(coin, market)

        draft = st.session_state[pending_key]

        bot = {
            "id": draft["id"],
            "created_at": draft["created_at"],
            "name": name.strip(),
            "coin": coin,
            "market": market,
            "direction": direction,
            "strategy": kind,
            "settings": settings,
            "position": {},
            "lifecycle": "Черновик",
        }

        save_bot(
            bot,
            "Создана карточка",
            (
                "Добавлен работающий бот: "
                "нужна фактическая сверка."
                if task == "Добавить уже работающий"
                else "Сохранён план до запуска."
            ),
        )

        st.session_state.pop(pending_key, None)

        st.session_state["_flash"] = (
            "Карточка записана и повторно прочитана "
            "из PostgreSQL. "
            "Внеси фактическую позицию и статус."
        )

        move(kind, focus=bot["id"])

    if st.button(
        "Начать другую карточку с новым ID",
        key=kind + "new_id",
    ):
        st.session_state[pending_key] = {
            "id": str(uuid.uuid4()),
            "created_at": now(),
        }

        st.info(
            "Назначен новый ID. "
            "Если предыдущая запись не была подтверждена, "
            "сначала проверь список, "
            "чтобы не создать копию."
        )

    if not DB_READY:
        st.warning(
            "Сохранение заблокировано: PostgreSQL "
            "не подключена или недоступна. "
            "Сохранение в память "
            "не подменяет запись в базу."
        )

    backtest(
        kind,
        coin,
        market,
        direction,
        settings,
        valid,
    )


# =========================================================
# ОЦЕНКА СОСТОЯНИЯ ПОЗИЦИИ
# =========================================================

def assess(bot, price):
    settings = bot["settings"]
    position = bot.get("position", {})
    direction = bot["direction"]

    realized = (
        num(position.get("realized_pnl"))
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
        "liq_distance": None,
        "reserve": max(
            0,
            num(settings["total_budget"])
            - num(
                position.get("base_margin"),
                settings["base_margin"],
            )
            - num(position.get("added_margin")),
        ),
    }

    if bot["lifecycle"] != "Работает":
        if bot["lifecycle"] == "Черновик":
            result.update(
                title="План сохранён",
                reason=(
                    "Для работающего бота внеси "
                    "фактическую позицию "
                    "и выбери статус «Работает»."
                ),
            )
        else:
            result.update(
                title="Бот отмечен завершённым",
                reason=(
                    "Карточка и история остаются в базе. "
                    "Статус отмечен пользователем."
                ),
            )

        return result

    if price is None:
        result.update(
            title="Нет свежей цены",
            reason=(
                "Расчёт по нулевой цене отключён. "
                "Обнови данные."
            ),
        )
        return result

    stop = settings["stop_price"]

    directional_stop = (
        direction != "Neutral"
        and stop > 0
        and sign(direction) * (price - stop) <= 0
    )

    neutral_stop = (
        direction == "Neutral"
        and (
            (
                settings["stop_lower"] > 0
                and price <= settings["stop_lower"]
            )
            or (
                settings["stop_upper"] > 0
                and price >= settings["stop_upper"]
            )
        )
    )

    if directional_stop or neutral_stop:
        result.update(
            title="Достигнута сигнальная стоп-цена плана",
            reason=(
                "Срочно сверь позицию на OKX "
                "и выполни предусмотренный планом выход. "
                "Свежесть позиции не отменяет этот сигнал. "
                "Торговая команда не отправлялась."
            ),
            tone="error",
        )
        return result

    if (
        age(position.get("last_check"))
        > settings["stale_hours"]
    ):
        result.update(
            title="Сверка устарела или не выполнена",
            reason=(
                "Обнови фактическую позицию на OKX. "
                "Не выдаём уверенное указание "
                "держать или закрывать "
                "по устаревшим данным."
            ),
        )
        return result

    if direction == "Neutral":
        inside = (
            settings["lower"]
            <= price
            <= settings["upper"]
        )

        result.update(
            title=(
                "Цена внутри диапазона Grid"
                if inside
                else "Цена вне диапазона Grid"
            ),
            reason=(
                "Проверь остаточные позиции, "
                "ордера и Total PnL на OKX. "
                "Введённый вручную Total PnL — "
                "снимок сверки, а не онлайн-расчёт."
            ),
            tone="info" if inside else "warning",
        )

        if position.get("total_pnl_manual") is not None:
            result["pnl"] = num(
                position["total_pnl_manual"]
            )

        return result

    quantity = num(position.get("volume"))
    average = num(position.get("avg_price"))

    if quantity <= 0:
        result.update(
            title="По сверке открытой позиции нет",
            reason=(
                "Проверь, ожидает ли бот следующий цикл."
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
        sign(direction)
        * quantity
        * (price - average)
    )

    result.update(
        pnl=floating + realized,
        floating=floating,
    )

    liquidation = num(
        position.get("liq_price")
    )

    if liquidation > 0:
        result["liq_distance"] = (
            sign(direction)
            * (price - liquidation)
            / price
            * 100
        )

    if (
        settings["max_loss"] > 0
        and floating <= -settings["max_loss"]
    ):
        result.update(
            title=(
                "Достигнут лимит убытка "
                "открытой позиции"
            ),
            reason=(
                "Проверь ручной выход по плану. "
                "Прибыль прошлых циклов "
                "не отменяет этот лимит."
            ),
            tone="error",
        )
        return result

    if (
        result["liq_distance"] is not None
        and result["liq_distance"]
        <= settings["liq_warn"]
    ):
        result.update(
            title=(
                "Цена близко к введённой ликвидации"
            ),
            reason=(
                "Срочно сверь риск на OKX. "
                "Здесь последняя цена, не Mark Price; "
                "ликвидация введена вручную, "
                "MMR не рассчитан."
            ),
            tone="error",
        )
        return result

    if bot["strategy"] == "DCA":
        result["tp"] = average * (
            1 + sign(direction) * settings["tp"] / 100
        )

        if settings["entry"] > 0:
            plan = dca_plan(settings, direction)

            executed = max(
                0,
                min(
                    int(position.get("executed_so", 0)),
                    len(plan) - 1,
                ),
            )

            if executed + 1 < len(plan):
                result["next_so"] = (
                    plan[executed + 1]["Цена"]
                )

    else:
        result["tp"] = (
            settings["target_price"] or None
        )

    if (
        result["tp"]
        and sign(direction)
        * (price - result["tp"])
        >= 0
    ):
        result.update(
            title="Достигнут модельный тейк",
            reason=(
                "Проверь исполнение на OKX. "
                "TP цикла, остановка новых циклов "
                "и полная остановка бота — "
                "разные действия."
            ),
            tone="success",
        )

    elif (
        bot["strategy"] == "Grid"
        and not (
            settings["lower"]
            <= price
            <= settings["upper"]
        )
    ):
        result.update(
            title="Цена вне диапазона Grid",
            reason=(
                "Проверь остаточную позицию "
                "и план выхода. "
                "Выход из диапазона "
                "не означает закрытие."
            ),
            tone="warning",
        )

    elif (
        max(
            0,
            -sign(direction)
            * (price / average - 1)
            * 100,
        )
        >= settings["danger_pct"]
    ):
        result.update(
            title="Цена в заданной зоне внимания",
            reason=(
                "Движение против позиции достигло "
                "твоего порога. "
                "Проверь уменьшение риска "
                "или выход по плану. "
                "Это не прогноз разворота."
            ),
            tone="warning",
        )

    elif (
        result["next_so"]
        and sign(direction)
        * (price - result["next_so"])
        <= 0
    ):
        result.update(
            title="Достигнут уровень следующего СО",
            reason=(
                "Проверь исполнение, объём и среднюю. "
                "Касание уровня "
                "не подтверждает исполнение."
            ),
        )

    elif floating > 0:
        result.update(
            title="Открытая позиция в плюсе",
            reason=(
                "Контролируй TP и условия риска. "
                "Один снимок не подтверждает "
                "рост прибыли во времени."
            ),
            tone="success",
        )

    else:
        result.update(
            title="Контроль по плану",
            reason=(
                "Жёсткие условия выхода "
                "по введённым данным не сработали. "
                "Это не обещание отскока."
            ),
        )

    if result["reserve"] <= 0:
        result["reason"] += (
            " Резерв маржи исчерпан; "
            "дальнейшее добавление "
            "выходит за бюджет."
        )

    return result


# =========================================================
# TELEGRAM
# =========================================================

def telegram_credentials():
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

    token = token or st.session_state.get(
        "tg_token",
        "",
    )

    chat = chat or st.session_state.get(
        "tg_chat",
        "",
    )

    return token, chat


def send_telegram(text):
    token, chat = telegram_credentials()

    if not token or not chat:
        raise ValueError(
            "Настрой Telegram в Secrets "
            "или в Настройках."
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
# СВЕРКА ФАКТИЧЕСКОЙ ПОЗИЦИИ
# =========================================================

def position_form(bot):
    position = bot["position"]
    settings = bot["settings"]

    key = (
        bot["id"]
        + "_"
        + str(bot["_revision"])
    )

    with st.expander(
        "Сверить фактическую позицию с OKX",
        expanded=not position.get("last_check"),
    ):
        with st.form(key + "position"):
            statuses = [
                "Черновик",
                "Работает",
                "Закрыт",
            ]

            lifecycle = st.selectbox(
                "Статус",
                statuses,
                index=statuses.index(bot["lifecycle"]),
            )

            neutral = (
                bot["direction"] == "Neutral"
            )

            if neutral:
                known = st.checkbox(
                    "Ввести фактический Total PnL с OKX",
                    value=(
                        position.get("total_pnl_manual")
                        is not None
                    ),
                )

                total_manual = number(
                    "Total PnL с OKX, USDT — "
                    "снимок на момент сверки",
                    num(position.get("total_pnl_manual")),
                    key + "total",
                    minimum=None,
                )

                quantity = 0.0
                average = 0.0
                realized = 0.0
                liquidation = 0.0
                executed = 0

                st.caption(
                    "Нулевой объём здесь не утверждает "
                    "отсутствие обеих сторон Neutral. "
                    "Перед отметкой завершения проверь "
                    "все остаточные позиции "
                    "и ордера на OKX."
                )

            else:
                known = False
                total_manual = None

                quantity = number(
                    "Объём в базовой монете, "
                    "НЕ контракты; 0 = нет позиции",
                    num(position.get("volume")),
                    key + "qty",
                )

                average = number(
                    "Фактическая средняя цена",
                    num(position.get("avg_price")),
                    key + "avg",
                )

                liquidation = number(
                    "Ликвидационная цена с OKX; "
                    "0 = неизвестна",
                    num(position.get("liq_price")),
                    key + "liq",
                )

                if bot["strategy"] == "DCA":
                    realized = number(
                        "PnL закрытых циклов, USDT; "
                        "не Total PnL",
                        num(position.get("realized_pnl")),
                        key + "realized",
                        minimum=None,
                    )

                    st.caption(
                        "Накопленное значение заменяется, "
                        "а не прибавляется. "
                        "Убыток можно вводить "
                        "отрицательным числом."
                    )

                    maximum = int(settings["so_count"])

                    executed = (
                        number(
                            "Исполнено СО текущего цикла",
                            min(
                                max(
                                    0,
                                    int(
                                        position.get(
                                            "executed_so",
                                            0,
                                        )
                                    ),
                                ),
                                maximum,
                            ),
                            key + "executed",
                            0,
                            maximum,
                            integer=True,
                        )
                        if maximum > 0
                        else 0
                    )

                else:
                    realized = 0.0
                    executed = 0

            base = number(
                "Фактически выделенная базовая маржа",
                num(
                    position.get("base_margin"),
                    settings["base_margin"],
                ),
                key + "base",
            )

            added = number(
                "Всего добавлено маржи",
                num(position.get("added_margin")),
                key + "added",
            )

            confirmed = st.checkbox(
                "Сверил значения с OKX; "
                "для статуса «Закрыт» проверил "
                "отсутствие остаточных позиций "
                "и ордеров"
            )

            if st.form_submit_button(
                "Сохранить сверку",
                disabled=not DB_READY,
            ):
                invalid = (
                    not confirmed
                    or (
                        quantity > 0
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
                        "Ненулевой позиции нужна средняя; "
                        "завершённой карточке — "
                        "нулевой остаток."
                    )

                else:
                    bot["lifecycle"] = lifecycle

                    bot["position"] = {
                        "volume": quantity,
                        "avg_price": average,
                        "realized_pnl": realized,
                        "liq_price": liquidation,
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
                        "Данные и статус подтверждены "
                        "пользователем на OKX.",
                    )

                    st.session_state["_flash"] = (
                        "Сверка записана и проверена "
                        "в PostgreSQL."
                    )

                    st.rerun()


# =========================================================
# РЕДАКТИРОВАНИЕ ПЛАНА
# =========================================================

def plan_form(bot):
    settings = bot["settings"]

    key = (
        bot["id"]
        + "_"
        + str(bot["_revision"])
        + "plan"
    )

    with st.expander(
        "Изменить план сопровождения"
    ):
        with st.form(key):
            updated = dict(settings)

            if bot["strategy"] == "DCA":
                updated["tp"] = number(
                    "TP от средней, %",
                    settings["tp"],
                    key + "tp",
                    0.01,
                    99,
                )

            else:
                updated["lower"] = number(
                    "Нижняя граница",
                    settings["lower"],
                    key + "lower",
                )

                updated["upper"] = number(
                    "Верхняя граница",
                    settings["upper"],
                    key + "upper",
                )

                updated["target_price"] = number(
                    "Целевая цена Long/Short; 0 = нет",
                    settings["target_price"],
                    key + "target",
                )

            if bot["direction"] == "Neutral":
                updated["stop_lower"] = number(
                    "Нижний сигнальный стоп; 0 = нет",
                    settings["stop_lower"],
                    key + "stoplower",
                )

                updated["stop_upper"] = number(
                    "Верхний сигнальный стоп; 0 = нет",
                    settings["stop_upper"],
                    key + "stopupper",
                )

            else:
                updated["stop_price"] = number(
                    "Сигнальная стоп-цена; 0 = нет",
                    settings["stop_price"],
                    key + "stop",
                )

            updated["max_loss"] = number(
                "Лимит убытка открытой позиции "
                "Long/Short, USDT",
                settings["max_loss"],
                key + "loss",
            )

            updated["danger_pct"] = number(
                "Зона внимания: движение "
                "против позиции, %",
                settings["danger_pct"],
                key + "danger",
                0.1,
                100,
            )

            updated["total_budget"] = number(
                "Общий бюджет маржи, включая резерв",
                settings["total_budget"],
                key + "budget",
                0.01,
            )

            updated["stale_hours"] = number(
                "Срок актуальности сверки, часов",
                settings["stale_hours"],
                key + "stale",
                0.1,
                168,
            )

            if st.form_submit_button(
                "Сохранить изменения плана",
                disabled=not DB_READY,
            ):
                invalid_grid = (
                    bot["strategy"] == "Grid"
                    and not (
                        0
                        < updated["lower"]
                        < updated["upper"]
                    )
                )

                if invalid_grid:
                    st.error("Проверь диапазон.")

                else:
                    bot["settings"] = updated

                    save_bot(
                        bot,
                        "Изменён план",
                        canonical(updated),
                    )

                    st.session_state["_flash"] = (
                        "План обновлён и прочитан "
                        "из PostgreSQL."
                    )

                    st.rerun()


# =========================================================
# КАРТОЧКИ БОТОВ
# =========================================================

def bot_card(bot, compact=False):
    try:
        ticker = quote(bot["coin"], bot["market"])
        price = ticker["price"]
    except Exception:
        ticker = None
        price = None

    state = assess(bot, price)

    key = bot["id"]
    position = bot["position"]

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
            bot["name"]
            + " · "
            + bot["lifecycle"]
            + " · "
            + bot["market"]
        )

        columns = st.columns(3)

        columns[0].metric(
            "Последняя цена",
            fmt(price, 6),
        )

        if bot["direction"] == "Neutral":
            pnl_label = "PnL с OKX: снимок"
        elif bot["strategy"] == "DCA":
            pnl_label = "Общий PnL ≈ USDT"
        else:
            pnl_label = "Открытый PnL ≈ USDT"

        columns[1].metric(
            pnl_label,
            fmt(state["pnl"]),
        )

        columns[2].metric(
            "Резерв маржи USDT",
            fmt(state["reserve"]),
        )

        st.markdown(
            "### Анализ текущей ситуации"
        )

        getattr(st, state["tone"])(
            state["title"]
            + ". "
            + state["reason"]
        )

        if bot["strategy"] == "DCA":
            st.caption(
                "Закрытые циклы: "
                f"{fmt(state['realized'])} USDT · "
                "Открытый PnL: "
                f"{fmt(state['floating'])} USDT"
            )

        st.caption(
            "Сверка позиции UTC: "
            + (
                position.get("last_check")
                or "не выполнена"
            )
        )

        if ticker:
            timestamp = datetime.fromtimestamp(
                ticker["ts"] / 1000,
                timezone.utc,
            ).isoformat()

            st.caption(
                "Время рыночной цены UTC: "
                + timestamp
            )

        if compact:
            if st.button(
                "Открыть карточку",
                key=key + "open",
            ):
                move(
                    bot["strategy"],
                    focus=key,
                )

            return

        position_form(bot)
        plan_form(bot)

        with st.expander(
            "Уровни и полные настройки"
        ):
            fields = [
                ("tp", "Модельный TP"),
                ("next_so", "Следующий СО"),
                (
                    "liq_distance",
                    "До введённой ликвидации, %",
                ),
            ]

            for field, label in fields:
                st.write(
                    label
                    + ": "
                    + fmt(
                        state[field],
                        6 if field != "liq_distance" else 2,
                    )
                )

            table(
                pd.DataFrame([
                    {
                        "Параметр": name,
                        "Значение": str(value),
                    }
                    for name, value
                    in bot["settings"].items()
                ])
            )

            quantity = num(position.get("volume"))
            average = num(position.get("avg_price"))

            if (
                quantity > 0
                and average > 0
                and sign(bot["direction"])
                and price
            ):
                prices = np.linspace(
                    min(price, average) * 0.85,
                    max(price, average) * 1.15,
                    120,
                )

                pnl = (
                    sign(bot["direction"])
                    * quantity
                    * (prices - average)
                )

                figure = go.Figure(
                    go.Scatter(
                        x=prices,
                        y=pnl,
                        name="Открытый PnL",
                        line={"color": "#00ff9d"},
                    )
                )

                figure.add_hline(
                    y=0,
                    line_dash="dot",
                )

                figure.update_layout(
                    template="plotly_dark",
                    title=(
                        "Профиль позиции "
                        "без комиссий и funding"
                    ),
                    height=330,
                )

                st.plotly_chart(
                    figure,
                    use_container_width=True,
                )

        with st.form(key + "decision"):
            decision = st.radio(
                "Моё решение",
                [
                    "Не трогать",
                    "Проверить на OKX",
                    "Выход по плану",
                ],
                horizontal=True,
            )

            note = st.text_input("Причина")

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
                if not note.strip():
                    st.error(
                        "Укажи причину решения."
                    )

                else:
                    bot["decision"] = {
                        "action": decision,
                        "reason": note.strip(),
                        "created_at": now(),
                        "valid_hours": hours,
                    }

                    save_bot(
                        bot,
                        "Решение пользователя",
                        canonical(bot["decision"]),
                    )

                    st.rerun()

        decision = bot.get("decision")

        if isinstance(decision, dict):
            st.caption(
                "Последнее решение: "
                + str(decision.get("action", ""))
                + " · "
                + str(decision.get("reason", ""))
            )

            if (
                age(decision.get("created_at"))
                >= num(
                    decision.get("valid_hours"),
                    6,
                )
            ):
                st.warning(
                    "Срок решения истёк: "
                    "перепроверь позицию и план."
                )

        elif decision:
            st.caption(str(decision))

        if st.button(
            "Отправить отчёт в Telegram",
            key=key + "telegram",
        ):
            event_key = key + "_telegram_last"

            payload = canonical({
                "title": state["title"],
                "check": position.get("last_check"),
                "pnl": (
                    round(state["pnl"], 2)
                    if state["pnl"] is not None
                    else None
                ),
            })

            previous = st.session_state.get(
                event_key,
                {},
            )

            repeated = (
                previous.get("payload") == payload
                and time.time()
                - previous.get("ts", 0)
                < 60
            )

            if repeated:
                st.info(
                    "Такой отчёт уже отправлен "
                    "менее минуты назад."
                )

            else:
                text = (
                    f"{bot['name']}\n"
                    f"{bot['coin']} · "
                    f"{bot['strategy']} · "
                    f"{bot['direction']}\n\n"
                    f"{state['title']}\n"
                    f"{state['reason']}\n\n"
                    f"Цена: {fmt(price, 6)}\n"
                    f"PnL: {fmt(state['pnl'])} USDT\n"
                    "Сверка UTC: "
                    f"{position.get('last_check') or 'нет'}\n\n"
                    "Проверь исполнение и действуй "
                    "по своему плану на OKX. "
                    "Торговая команда не отправлялась."
                )

                send_telegram(text)

                st.session_state[event_key] = {
                    "payload": payload,
                    "ts": time.time(),
                }

                st.success(
                    "Отчёт отправлен. "
                    "Защита от повторов действует "
                    "в текущей сессии."
                )

        st.caption(
            "Комиссии и funding открытой позиции "
            "отдельно не учтены. "
            "«Не трогать» не отключает стоп "
            "и предупреждения. "
            "Автоматического закрытия сделок нет."
        )


def cards(bots, compact=False):
    for bot in bots:
        try:
            bot_card(bot, compact)

        except Exception as exc:
            if isinstance(exc, ValueError):
                st.error(str(exc))
            else:
                st.error(
                    "Действие по карточке "
                    f"«{bot.get('name', 'Бот')}» "
                    "не подтверждено: "
                    f"{type(exc).__name__}. "
                    "Обнови список перед повтором. "
                    "Данные не удаляются."
                )


def list_bots(bots, prefix, compact=False):
    status = st.radio(
        "Показывать",
        ["Все", "Работает", "Черновик", "Закрыт"],
        horizontal=True,
        key=prefix + "filter",
    )

    selected = [
        bot
        for bot in bots
        if status == "Все"
        or bot["lifecycle"] == status
    ]

    selected.sort(
        key=lambda bot: (
            bot["id"]
            != st.session_state.get("focus")
        )
    )

    if not selected:
        st.info(
            "Нет карточек для выбранного фильтра."
        )

    cards(selected, compact)


# =========================================================
# НАСТРОЙКИ
# =========================================================

def settings_page(bots):
    panel(
        "Настройки",
        "PostgreSQL, проверка подключения, "
        "резервные копии и Telegram.",
    )

    st.write(
        "Пароль: включён через APP_PASSWORD."
    )

    if DB_READY:
        st.success(
            "PostgreSQL доступна. "
            "Карточки прочитаны из базы."
        )
    elif DB_URL:
        st.error(
            "Адрес базы задан, но чтение карточек "
            "не подтверждено. Пустой список "
            "не означает, что данные удалены."
        )
    else:
        st.warning(
            "DATABASE_URL не настроен. "
            "Сохранение заблокировано."
        )

    if st.button("Проверить PostgreSQL"):
        try:
            check_postgres()

            st.success(
                "SELECT 1 выполнен. "
                "Это проверка соединения, "
                "не резервного копирования "
                "и не права записи."
            )

        except Exception as exc:
            st.error(
                "Проверка не пройдена: "
                + type(exc).__name__
                + ". Проверь реальный адрес базы "
                "и параметры доступа."
            )

    if DB_READY:
        st.caption(
            f"Всего карточек в этой базе: {len(bots)}. "
            "Поддерживаются прежние "
            "terminal_bots и terminal_events."
        )

        if st.button(
            "Подготовить резервную копию JSON"
        ):
            st.session_state["backup"] = {
                "data": backup_bytes(),
                "timestamp": now(),
            }

        backup = st.session_state.get("backup")

        if backup:
            st.caption(
                "Копия сформирована UTC: "
                + backup["timestamp"]
            )

            st.download_button(
                "Скачать подготовленную копию",
                backup["data"],
                "okx_backup.json",
                "application/json",
            )

        uploaded = st.file_uploader(
            "Восстановить JSON, до 5 MB",
            type=["json"],
        )

        confirmed = st.checkbox(
            "Добавить копии с новыми ID. "
            "Не заменять существующие карточки. "
            "После импорта сверить позиции."
        )

        if st.button(
            "Восстановить копии",
            disabled=uploaded is None or not confirmed,
        ):
            if uploaded.size > 5_000_000:
                raise ValueError(
                    "Файл больше 5 MB."
                )

            count = import_backup(
                json.loads(uploaded.getvalue())
            )

            st.session_state["_flash"] = (
                f"Импортировано карточек: {count}. "
                "Они видны как черновики; "
                "сверь позиции перед статусом «Работает»."
            )

            st.rerun()

        with st.expander(
            "Перенести оставшийся локальный SQLite"
        ):
            st.caption(
                "Только если старый файл ещё есть "
                "на этом сервере. "
                "Чтение без изменения исходника. "
                "Повторный импорт создаёт копии."
            )

            confirm_sqlite = st.checkbox(
                "Подтверждаю перенос копий "
                "без удаления оригинала"
            )

            if st.button(
                "Перенести локальные карточки "
                "в PostgreSQL",
                disabled=not confirm_sqlite,
            ):
                if not os.path.isfile(DB_FILE):
                    raise ValueError(
                        "Старый файл не найден. "
                        "Исчезнувший файл без копии "
                        "восстановить нельзя."
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
                            "Таблицы карточек не найдены."
                        )

                finally:
                    connection.close()

                count = import_backup({"bots": raw})

                st.session_state["_flash"] = (
                    f"Перенесено копий: {count}. "
                    "Обнови фактические позиции."
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
                "OKX Terminal Pro: тест подключения. "
                "Торговые команды не отправляются."
            )

            st.success("Тест отправлен.")

    with st.expander(
        "Что указать в Streamlit Secrets",
        expanded=not DB_URL,
    ):
        st.code(
            '''
APP_PASSWORD = "твой-длинный-пароль"

DATABASE_URL = "postgresql://USER:PASSWORD@HOST:5432/DATABASE?sslmode=require"

# Необязательно:
TELEGRAM_TOKEN = "токен"
TELEGRAM_CHAT_ID = "chat-id"
'''.strip(),
            language="toml",
        )

        st.caption(
            "Это пример, не рабочие реквизиты. "
            "Вставь строку подключения своей PostgreSQL. "
            "Существующий настоящий DATABASE_URL "
            "не заменяй примером. "
            "Секреты не публикуй в GitHub."
        )

    st.caption(
        "Автоматические резервные копии нужно "
        "отдельно включить и проверить "
        "у провайдера базы. "
        "Здесь есть ручной экспорт/импорт. "
        "Независимого фонового мониторинга нет; "
        "Telegram отправляется по кнопке."
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

        if st.button(
            "Обновить цены и список"
        ):
            quote.clear()
            api.clear()
            st.rerun()

        if st.button("Выйти"):
            st.session_state["_authenticated"] = False
            st.rerun()

        st.caption(
            "Ручное сопровождение. "
            "Приватный торговый API не используется."
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
                + ". Не удаляй данные "
                "и не меняй адрес на новую базу. "
                "Открой Настройки. "
                "Пустой экран не подтверждает "
                "потерю карточек."
            )

    else:
        st.warning(
            "Нужен DATABASE_URL внешней PostgreSQL. "
            "Сканер и расчёты доступны, "
            "сохранение карточек пока заблокировано."
        )

    flash = st.session_state.pop("_flash", None)

    if flash:
        st.success(flash)

    try:
        if page == "Главная":
            panel(
                "Твои боты",
                "Все сохранённые карточки, "
                "понятные статусы "
                "и действия по плану.",
            )

            actions("home")

            columns = st.columns(3)

            statuses = [
                ("Работает", "В работе"),
                ("Черновик", "Черновики"),
                ("Закрыт", "Завершены"),
            ]

            for column, item in zip(
                columns,
                statuses,
            ):
                status, label = item

                value = (
                    sum(
                        bot["lifecycle"] == status
                        for bot in bots
                    )
                    if DB_READY
                    else "—"
                )

                column.metric(label, value)

            if DB_READY:
                list_bots(
                    bots,
                    "home",
                    compact=True,
                )
            else:
                st.info(
                    "Список не прочитан. "
                    "Это не утверждение, "
                    "что карточек нет."
                )

        elif page == "Сканер":
            scanner()

        elif page in ("DCA", "Grid"):
            panel(
                page,
                "Мои боты и добавление нового "
                "или уже работающего бота.",
            )

            mode = st.radio(
                "Режим",
                ["Мои боты", "Добавить бота"],
                horizontal=True,
                key=page + "mode",
            )

            if mode == "Добавить бота":
                creator(page)

            else:
                if st.button(
                    "Добавить " + page
                ):
                    move(
                        page,
                        "Long" if page == "DCA" else "Neutral",
                        mode="Добавить бота",
                    )

                if DB_READY:
                    selected = [
                        bot
                        for bot in bots
                        if bot["strategy"] == page
                    ]

                    list_bots(selected, page)

                else:
                    st.info(
                        "Подключи или восстанови доступ "
                        "к PostgreSQL в Настройках."
                    )

        elif page == "Открытая позиция":
            panel(
                "Контроль позиций",
                "Позиции и планы видны явно. "
                "«Черновик» не означает "
                "потерю карточки.",
            )

            if DB_READY:
                list_bots(bots, "positions")
            else:
                st.info(
                    "Не удалось прочитать "
                    "карточки из базы."
                )

        elif page == "Журнал":
            panel(
                "Журнал",
                "Создание карточек, изменения планов, "
                "сверки и решения. Время UTC.",
            )

            if DB_READY:
                frame = history()

                if frame.empty:
                    st.info(
                        "В этой базе журнал пока пуст."
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
            else:
                st.info(
                    "Журнал не прочитан: "
                    "нет подтверждённого "
                    "подключения к базе."
                )

            st.caption(
                "Снимки PnL одной позиции "
                "не суммируются как прибыль."
            )

        else:
            settings_page(bots)

    except Exception as exc:
        if isinstance(exc, ValueError):
            st.error(str(exc))
        else:
            st.error(
                "Действие не подтверждено: "
                + type(exc).__name__
                + ". После ошибки записи "
                "обнови список перед повтором. "
                "Адрес базы и токены не публикуй."
            )


main()
