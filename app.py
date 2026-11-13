import os
import io
import re
import sys
import json
import time
import math
import uuid
import hmac
import html
import copy
import sqlite3
import traceback
import importlib
import importlib.metadata

from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from urllib.request import Request, urlopen
from urllib.parse import urlencode, urlsplit, parse_qs
from urllib.error import HTTPError, URLError

import numpy as np
import pandas as pd
import streamlit as st


# ======================== КОНФИГУРАЦИЯ ========================

APP_VERSION = "OKX Terminal Pro · SQLite Cloud"
UI_RELEASE = "normal-interface-v23"

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

OKX_API = "https://www.okx.com/api/v5"
HOUR = 3_600_000
DAY = HOUR * 24
STORE_READY = False

DEFAULT_DCA = {
    "tp": 1.5,
    "step": 2.0,
    "so_count": 4,
    "mart": 1.2,
    "leverage": 3.0,
}

CASES = {
    "Базовый": {
        "fee_mult": 1.0,
        "half_spread": 0.0002,
        "slippage": 0.0003,
        "funding": 0.0001,
    },
    "Стресс": {
        "fee_mult": 1.5,
        "half_spread": 0.0005,
        "slippage": 0.0009,
        "funding": 0.0002,
    },
    "Кризис": {
        "fee_mult": 2.0,
        "half_spread": 0.0010,
        "slippage": 0.0030,
        "funding": 0.0003,
    },
}


# ======================== ОБЩИЕ ФУНКЦИИ ========================

def secret(key, default=""):
    try:
        return st.secrets.get(key, os.getenv(key, default))
    except Exception:
        return os.getenv(key, default)


OLD_SQLITE = str(secret("SQLITE_PATH", "bots.sqlite3"))


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
    return {"Long": 1, "Short": -1, "Neutral": 0}.get(direction, 0)


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
            (datetime.now(timezone.utc) - dt).total_seconds() / 3600,
        )
    except (TypeError, ValueError):
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


def redact(text):
    text = str(text)
    values = []

    for key in (
        "DATABASE_URL",
        "APP_PASSWORD",
        "TELEGRAM_TOKEN",
        "TELEGRAM_CHAT_ID",
    ):
        value = str(secret(key, ""))
        if value:
            values.append(value)

    database_url = str(secret("DATABASE_URL", ""))

    if database_url:
        try:
            parsed = urlsplit(database_url)
            if parsed.password:
                values.append(parsed.password)

            for key, items in parse_qs(parsed.query).items():
                if key.lower() in ("apikey", "api_key", "token", "password"):
                    values.extend(items)
        except Exception:
            pass

    for value in sorted(set(values), key=len, reverse=True):
        if len(value) >= 4:
            text = text.replace(value, "[СКРЫТО]")

    text = re.sub(
        r"sqlitecloud://[^\s\"'<>]+",
        "[DATABASE_URL СКРЫТ]",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(?i)(apikey\s*[=:]\s*)[^&\s,\"'<>]+",
        r"\1[СКРЫТО]",
        text,
    )
    return text


# ======================== НАВИГАЦИЯ ========================

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

    if request and request["page"] in PAGES:
        page = request["page"]
        st.session_state["page"] = page

        if page in ("DCA", "Grid"):
            st.session_state[page + "mode"] = (
                "Мои боты" if request["focus"] else "Добавить бота"
            )
            if request["direction"]:
                st.session_state[page + "direction"] = request["direction"]

            for key, value in request["template"].items():
                st.session_state[page + key] = value

        if request["focus"]:
            st.session_state["focus"] = request["focus"]

    if st.session_state.get("page") not in PAGES:
        st.session_state["page"] = "Главная"


# ======================== ОФОРМЛЕНИЕ ========================

def design():
    st.markdown(
        """
<style>
.stApp{background:#080e18!important;color:#edf3ff;color-scheme:dark}
.block-container{max-width:1400px;padding-top:1.5rem}
h1,h2,h3,h4{color:#edf3ff!important}
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,
[data-testid="stWidgetLabel"] p,
[data-testid="stCheckbox"] p,
[data-testid="stExpander"] summary p{color:#e8ecf4!important}
[data-testid="stCaptionContainer"] p{color:#b7c4d8!important}
[data-testid="stSidebar"]{background:#0d1625!important}
[data-testid="stMetric"]{
    background:#132034;border:1px solid #30435f;
    border-radius:12px;padding:15px
}
[data-testid="stMetricLabel"] p,
[data-testid="stMetricLabel"] span{color:#bccae0!important}
[data-testid="stMetricValue"] div{color:white!important}
.stButton button,.stFormSubmitButton button,.stDownloadButton button{
    background:#f5f8ff!important;color:#142033!important;
    border:1px solid #b9c7da!important;border-radius:10px;
    min-height:44px;font-weight:700
}
.stButton button p,.stFormSubmitButton button p,
.stDownloadButton button p{color:inherit!important}
.stButton button:disabled,.stFormSubmitButton button:disabled{
    background:#cbd5e1!important;color:#475569!important;opacity:1!important
}
[class*="st-key-action_"][class*="_long"] button{
    background:#166534!important;color:white!important;
    border:2px solid #4ade80!important
}
[class*="st-key-action_"][class*="_short"] button{
    background:#991b1b!important;color:white!important;
    border:2px solid #f87171!important
}
[class*="st-key-action_"][class*="_neutral"] button{
    background:#facc15!important;color:#302500!important;
    border:2px solid #eab308!important
}
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea{
    background:white!important;color:#172033!important;
    -webkit-text-fill-color:#172033!important
}
[data-testid="stSelectbox"] [data-baseweb="select"]>div,
[role="listbox"],[role="option"]{
    background:white!important;color:#172033!important
}
[data-testid="stSelectbox"] span,[data-testid="stSelectbox"] input{
    color:#172033!important;-webkit-text-fill-color:#172033!important
}
[data-testid="stRadio"] [role="radiogroup"]>label{
    background:white!important;border:2px solid #cbd5e1;
    border-radius:10px;padding:8px 11px!important;margin:3px!important
}
[data-testid="stRadio"] [role="radiogroup"]>label p{color:#172033!important}
.notice{
    background:#edf4ff;color:#142033!important;
    border:1px solid #a8c0e5;border-left:5px solid #2563eb;
    border-radius:10px;padding:14px 16px;margin:10px 0;
    line-height:1.5;overflow-wrap:anywhere
}
.notice.error{
    background:#fff1f2;border-color:#e9a0ac;border-left-color:#b91c1c
}
.notice.warning{
    background:#fff8db;border-color:#e0c76c;border-left-color:#a16207
}
.notice.success{
    background:#ecfdf3;border-color:#8dd3a6;border-left-color:#15803d
}
.notice strong,.notice span,.notice p{color:#142033!important}
.table-wrap{
    overflow:auto;max-height:650px;border:1px solid #30435f;
    border-radius:10px;margin:12px 0
}
.table-wrap table{
    width:100%;border-collapse:collapse;background:#101827
}
.table-wrap th{
    background:#1a2940!important;color:white!important;
    padding:10px;border:1px solid #30435f;white-space:nowrap;
    position:sticky;top:0
}
.table-wrap td{padding:9px 11px;border:1px solid #26364c}
</style>
        """,
        unsafe_allow_html=True,
    )


def notice(text, tone="info"):
    if tone not in ("info", "error", "warning", "success"):
        tone = "info"

    st.markdown(
        f'<div class="notice {tone}">'
        + html.escape(str(text)).replace("\n", "<br>")
        + "</div>",
        unsafe_allow_html=True,
    )


def signal_style(value):
    value = str(value).strip().upper()
    if value in ("LONG", "ЛОНГ"):
        color = "#4ade80"
    elif value in ("SHORT", "ШОРТ"):
        color = "#fb7185"
    elif value in ("GRID", "NEUTRAL"):
        color = "#facc15"
    else:
        color = "#bac6d9"

    return (
        f"color:{color};background-color:#101827;font-weight:700;"
    )


def styled_frame(frame, escape=False):
    formats = {
        column: "{:,.2f}"
        for column in frame.select_dtypes(include="number").columns
    }

    for column in ("Цена", "Средняя"):
        if column in frame:
            formats[column] = "{:,.6f}"

    for column in ("Циклов", "Стопов", "Условных ликвидаций"):
        if column in frame:
            formats[column] = "{:,.0f}"

    styled = (
        frame.style
        .set_properties(**{
            "background-color": "#101827",
            "color": "#edf3ff",
        })
        .format(
            formats,
            na_rep="—",
            escape="html" if escape else None,
        )
    )

    if escape:
        styled = styled.format_index(axis=1, escape="html")

    for column in ("Сигнал", "Направление"):
        if column in frame:
            styled = styled.map(signal_style, subset=[column])

    return styled


def table(frame):
    if frame.empty:
        return

    rendered = (
        styled_frame(frame, True)
        .hide(axis="index")
        .to_html()
    )

    st.markdown(
        '<div class="table-wrap">' + rendered + "</div>",
        unsafe_allow_html=True,
    )


# ======================== ПАРОЛЬ ========================

def login():
    password = str(secret("APP_PASSWORD", ""))

    if not password.strip():
        notice(
            "Вход заблокирован. Добавь APP_PASSWORD в Streamlit Secrets.",
            "error",
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
            entered.encode("utf-8"),
            password.encode("utf-8"),
        ):
            st.session_state["_authenticated"] = True
            st.rerun()
        else:
            notice("Неверный пароль.", "error")

    st.stop()


# ======================== ДИАГНОСТИКА ========================

def dependency_report():
    report = [
        "Версия приложения:", APP_VERSION,
        "", "Python:", sys.version,
        "", "Запущенный app.py:", str(Path(__file__).resolve()),
        "", "Рабочая папка:", str(Path.cwd().resolve()), "",
    ]

    for package in ("streamlit", "pandas", "numpy", "sqlitecloud"):
        try:
            report.append(
                f"{package}: {importlib.metadata.version(package)}"
            )
        except importlib.metadata.PackageNotFoundError:
            report.append(
                f"{package}: пакет не найден в установленном окружении"
            )

    report.append("")

    try:
        module = importlib.import_module("sqlitecloud")
        report.extend([
            "Импорт sqlitecloud: УСПЕШНО",
            "Путь модуля:",
            str(getattr(module, "__file__", "неизвестен")),
        ])

        if not callable(getattr(module, "connect", None)):
            report.append("У модуля нет функции connect().")

    except Exception:
        report.extend([
            "Настоящая ошибка импорта:",
            traceback.format_exc(),
        ])

    directories = {
        Path(__file__).resolve().parent,
        Path.cwd().resolve(),
    }
    names = {
        "uv.lock", "Pipfile", "environment.yml",
        "requirements.txt", "pyproject.toml",
    }

    for directory in sorted(directories, key=str):
        report.extend([
            "", "Папка: " + str(directory),
            "Файлы зависимостей:",
        ])

        try:
            found = [
                repr(item.name)
                for item in directory.iterdir()
                if item.is_file()
                and (
                    item.name in names
                    or item.name.lower().startswith("requirements")
                )
            ]
            report.extend(
                sorted(found) or ["Файлы не найдены."]
            )

            requirements = directory / "requirements.txt"
            if requirements.is_file():
                report.extend([
                    "",
                    "Содержимое requirements.txt:",
                    requirements.read_text(
                        encoding="utf-8",
                        errors="replace",
                    )[:10000],
                ])

        except OSError as exc:
            report.append(type(exc).__name__)

    report.extend([
        "",
        "Диагностика не подключалась к базе.",
        "Значения Secrets не выводятся.",
    ])

    return redact("\n".join(report))


def diagnostics_screen():
    st.title("Техническая диагностика")
    notice(
        "Проверка окружения и импорта библиотеки. "
        "Этот экран не подключается к базе."
    )
    st.code(dependency_report(), language="text")

    if st.button("Вернуться в приложение", key="close_diagnostics"):
        st.session_state["_diagnostics"] = False
        st.rerun()

    st.stop()


# ======================== HTTP ========================

class NetworkError(ValueError):
    pass


class StoreError(ValueError):
    pass


def http_json(
    url,
    method="GET",
    payload=None,
    headers=None,
    timeout=25,
):
    request_headers = {
        "Accept": "application/json",
        "User-Agent": "OKX-Terminal-Server/23",
    }
    request_headers.update(headers or {})

    body = None

    if payload is not None:
        body = canonical(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"

    request = Request(
        url,
        data=body,
        headers=request_headers,
        method=method,
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()

        return json.loads(raw.decode("utf-8")) if raw else None

    except HTTPError as exc:
        message = ""
        try:
            error = json.loads(exc.read().decode("utf-8"))
            message = str(error.get("message", error.get("msg", "")))
        except Exception:
            pass

        raise NetworkError(
            f"HTTP {exc.code}"
            + (": " + redact(message[:350]) if message else "")
        ) from None

    except (URLError, TimeoutError, OSError) as exc:
        raise NetworkError(
            "Сетевой запрос не завершён: " + type(exc).__name__
        ) from None

    except (UnicodeError, json.JSONDecodeError):
        raise NetworkError("Сервер вернул не JSON.") from None


# ======================== SQLITE CLOUD ========================

def cloud_database_url():
    try:
        value = str(st.secrets["DATABASE_URL"]).strip()
    except Exception:
        raise StoreError(
            "В Streamlit Secrets отсутствует DATABASE_URL."
        ) from None

    if not value:
        raise StoreError("DATABASE_URL пустой.")

    try:
        parsed = urlsplit(value)
    except ValueError:
        raise StoreError("Неверный формат DATABASE_URL.") from None

    if parsed.scheme != "sqlitecloud" or not parsed.hostname:
        raise StoreError(
            "Нужен формат "
            "sqlitecloud://HOST:PORT/ИМЯ_БАЗЫ?apikey=КЛЮЧ"
        )

    if not parsed.path.strip("/"):
        raise StoreError(
            "В DATABASE_URL не указано имя базы: "
            "добавь /имя_базы перед ?apikey=…"
        )

    return value


def sqlitecloud_driver():
    try:
        module = importlib.import_module("sqlitecloud")
    except Exception as exc:
        raise StoreError(
            "Не удалось загрузить sqlitecloud.\n"
            + type(exc).__name__ + ": " + redact(str(exc))
            + "\nОткрой техническую диагностику в Настройках."
        ) from None

    if not callable(getattr(module, "connect", None)):
        raise StoreError(
            "У модуля sqlitecloud нет connect(). "
            "Проверь, не перекрывает ли пакет локальный "
            "файл sqlitecloud.py или одноимённая папка."
        )

    return module


@contextmanager
def database(write=False):
    driver = sqlitecloud_driver()
    url = cloud_database_url()
    connection = None
    transaction_started = False

    try:
        connection = driver.connect(url)
        connection.execute(
            "BEGIN IMMEDIATE" if write else "BEGIN"
        )
        transaction_started = True

        yield connection

        connection.execute("COMMIT")
        transaction_started = False

    except Exception as exc:
        if connection is not None and transaction_started:
            try:
                connection.execute("ROLLBACK")
            except Exception:
                pass

        if isinstance(exc, StoreError):
            raise

        raise StoreError(
            "Операция SQLite Cloud не подтверждена:\n"
            + type(exc).__name__ + ": " + redact(str(exc))
            + "\nПосле ошибки записи обнови список перед повтором."
        ) from None

    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


def sql(connection, statement, args=()):
    return connection.execute(statement, args)


def init_database():
    with database(write=True) as connection:
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


def store_health():
    with database() as connection:
        result = sql(connection, "SELECT 1").fetchone()

        if not result or int(result[0]) != 1:
            raise StoreError(
                "База не подтвердила проверочный запрос."
            )

        count = sql(
            connection,
            "SELECT COUNT(*) FROM terminal_bots",
        ).fetchone()

    return {"ready": True, "bots": int(count[0])}


def record(connection, bot_id, title, details):
    sql(
        connection,
        """
        INSERT INTO terminal_events (
            id, bot_id, created_at, title, details
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (str(uuid.uuid4()), bot_id, now(), title, details),
    )


def normalize(raw):
    if not isinstance(raw, dict):
        raise ValueError("Карточка должна быть JSON-объектом.")

    bot = json.loads(canonical(raw))

    if bot.get("strategy") not in ("DCA", "Grid"):
        raise ValueError("Неизвестная стратегия.")

    if bot.get("direction") not in ("Long", "Short", "Neutral"):
        raise ValueError("Неизвестное направление.")

    if bot["strategy"] == "DCA" and bot["direction"] == "Neutral":
        raise ValueError("DCA Neutral не поддерживается.")

    bot["coin"] = (
        str(bot.get("coin", ""))
        .strip().upper().replace("ARBITRUM", "ARB")
    )

    if not bot["coin"].isalnum():
        raise ValueError("Неверная монета.")

    market = str(bot.get("market", "SWAP"))
    bot["market"] = (
        "SWAP"
        if "SWAP" in market or "Фьючерсы" in market
        else "SPOT"
    )

    bot.setdefault("name", bot["coin"] + " " + bot["strategy"])
    bot.setdefault("created_at", now())
    bot.setdefault("lifecycle", "Черновик")

    if bot["lifecycle"] not in ("Черновик", "Работает", "Закрыт"):
        raise ValueError("Неизвестный статус.")

    for field in ("settings", "position"):
        if isinstance(bot.get(field), str):
            bot[field] = json.loads(bot[field])

        bot.setdefault(field, {})

        if not isinstance(bot[field], dict):
            raise ValueError("Неверный формат позиции.")

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
        "leverage": 3,
        "lower": 0,
        "upper": 0,
        "grids": 10,
        "target_price": 0,
        "stop_price": 0,
        "stop_lower": 0,
        "stop_upper": 0,
        "max_loss": 0,
        "stale_hours": 6,
        "danger_pct": 3,
        "liq_warn": 10,
    }

    settings = bot["settings"]

    for key, default in defaults.items():
        value = float(settings.get(key, default))

        if not math.isfinite(value):
            raise ValueError("Неверный параметр: " + key)

        if key in ("so_count", "grids"):
            if value != int(value):
                raise ValueError("Нужно целое число: " + key)
            value = int(value)

        settings[key] = value

    settings["total_budget"] = num(
        settings.get("total_budget"),
        settings["base_margin"] + settings["reserve"],
    )

    bot["position"].setdefault(
        "realized_pnl",
        num(settings.get("realized_pnl")),
    )

    return bot


def load_bots():
    with database() as connection:
        rows = sql(
            connection,
            "SELECT id, document, revision FROM terminal_bots ORDER BY id",
        ).fetchall()

    output = []

    for row in rows:
        bot = normalize(json.loads(row[1]))
        bot["_revision"] = int(row[2])
        output.append(bot)

    return sorted(
        output,
        key=lambda bot: bot.get("updated_at", ""),
        reverse=True,
    )


def comparable_document(document):
    result = dict(document)
    result.pop("_revision", None)
    result.pop("updated_at", None)
    return result


def save_bot(bot, title, details):
    document = normalize(bot)
    revision = document.pop("_revision", None)

    if not document.get("id"):
        raise StoreError("У карточки отсутствует ID.")

    document["updated_at"] = now()
    raw = canonical(document)
    saved_document = document
    new_revision = None

    with database(write=True) as connection:
        existing = sql(
            connection,
            """
            SELECT document, revision
            FROM terminal_bots WHERE id = ?
            """,
            (document["id"],),
        ).fetchone()

        if existing:
            old_document = json.loads(existing[0])
            old_revision = int(existing[1])

            already_saved = (
                comparable_document(old_document)
                == comparable_document(document)
                and (
                    revision is None
                    or old_revision == int(revision) + 1
                )
            )

            if already_saved:
                saved_document = old_document
                new_revision = old_revision
            else:
                if revision is None:
                    raise StoreError(
                        "Карточка с этим ID уже существует. Обнови список."
                    )

                if old_revision != int(revision):
                    raise StoreError(
                        "Карточка изменена в другой вкладке. "
                        "Обнови страницу перед сохранением."
                    )

                new_revision = old_revision + 1

                sql(
                    connection,
                    """
                    INSERT OR REPLACE INTO terminal_bots (
                        id, document, revision
                    ) VALUES (?, ?, ?)
                    """,
                    (document["id"], raw, new_revision),
                )
                record(connection, document["id"], title, details)

        else:
            if revision is not None:
                raise StoreError(
                    "Исходная карточка не найдена. Обнови список."
                )

            new_revision = 1

            sql(
                connection,
                """
                INSERT OR REPLACE INTO terminal_bots (
                    id, document, revision
                ) VALUES (?, ?, ?)
                """,
                (document["id"], raw, new_revision),
            )
            record(connection, document["id"], title, details)

    with database() as connection:
        checked = sql(
            connection,
            """
            SELECT document, revision
            FROM terminal_bots WHERE id = ?
            """,
            (document["id"],),
        ).fetchone()

    if (
        not checked
        or json.loads(checked[0]) != saved_document
        or int(checked[1]) != int(new_revision)
    ):
        raise StoreError(
            "Запись отправлена, но повторная проверка не совпала. "
            "Обнови список перед повтором."
        )


def load_events():
    with database() as connection:
        rows = sql(
            connection,
            """
            SELECT bot_id, created_at, title, details
            FROM terminal_events
            ORDER BY created_at DESC, id DESC
            LIMIT 1000
            """,
        ).fetchall()

    return pd.DataFrame(
        rows,
        columns=["Бот ID", "Дата UTC", "Событие", "Подробности"],
    )


def export_backup():
    with database() as connection:
        bots = [
            json.loads(row[0])
            for row in sql(
                connection,
                "SELECT document FROM terminal_bots ORDER BY id",
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
                FROM terminal_events ORDER BY created_at, id
                """,
            ).fetchall()
        ]

    return json.dumps(
        {
            "version": 23,
            "created_at": now(),
            "bots": bots,
            "events": events,
        },
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    ).encode("utf-8")


def import_backup(payload):
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("bots"), list)
        or len(payload["bots"]) > 1000
    ):
        raise ValueError("Неверная копия или больше 1000 карточек.")

    original_events = payload.get("events", [])

    if not isinstance(original_events, list):
        raise ValueError("Неверный журнал копии.")

    prepared = []
    events = []
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

        events.append({
            "id": str(uuid.uuid4()),
            "bot_id": bot["id"],
            "created_at": now(),
            "title": "Импорт",
            "details": "Добавлена копия. Нужна сверка с OKX.",
        })

    for event in original_events:
        if not isinstance(event, dict):
            raise ValueError("Неверное событие копии.")

        target = mapping.get(str(
            event.get("bot_id", event.get("Бот ID", ""))
        ))

        if target:
            events.append({
                "id": str(uuid.uuid4()),
                "bot_id": target,
                "created_at": now(),
                "title": "Импорт: " + str(
                    event.get("title", event.get("Событие", ""))
                ),
                "details": str(
                    event.get("created_at", event.get("Дата UTC", ""))
                ) + " · " + str(
                    event.get("details", event.get("Подробности", ""))
                ),
            })

    if len(events) > 20000:
        raise ValueError("Слишком большой журнал импорта.")

    with database(write=True) as connection:
        for bot in prepared:
            if sql(
                connection,
                "SELECT id FROM terminal_bots WHERE id = ?",
                (bot["id"],),
            ).fetchone():
                raise StoreError("Конфликт ID при импорте.")

            sql(
                connection,
                """
                INSERT OR REPLACE INTO terminal_bots (
                    id, document, revision
                ) VALUES (?, ?, ?)
                """,
                (bot["id"], canonical(bot), 1),
            )

        for event in events:
            sql(
                connection,
                """
                INSERT INTO terminal_events (
                    id, bot_id, created_at, title, details
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event["id"],
                    event["bot_id"],
                    event["created_at"],
                    event["title"],
                    event["details"],
                ),
            )

    return len(prepared)


# ======================== OKX ========================

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
            payload = http_json(
                OKX_API + path + "?" + urlencode(params),
                timeout=25,
            )
            if str(payload.get("code")) != "0":
                raise NetworkError("OKX не подтвердил запрос.")

            return payload.get("data", [])

        except (NetworkError, ValueError) as exc:
            last_error = exc
            time.sleep(0.4 * (attempt + 1))

    raise ValueError("OKX: " + str(last_error))


def instrument(coin, market="SWAP"):
    return f"{coin}-USDT" + (
        "-SWAP" if market == "SWAP" else ""
    )


@st.cache_data(ttl=20, max_entries=100, show_spinner=False)
def quote(coin, market="SWAP"):
    rows = okx_get(
        "/market/ticker",
        {"instId": instrument(coin, market)},
    )

    if not rows:
        raise ValueError("Инструмент не найден.")

    row = rows[0]
    price = num(row.get("last"))
    timestamp = num(row.get("ts"))

    if (
        price <= 0
        or timestamp <= 0
        or abs(time.time() - timestamp / 1000) > 180
    ):
        raise ValueError("Нет свежей рыночной цены.")

    return {
        "price": price,
        "ts": timestamp,
        "volume": (
            num(row.get("volCcy24h"))
            * (price if market == "SWAP" else 1)
        ),
    }


def parse_candles(rows):
    values = []

    for row in rows:
        confirm_index = 8 if len(row) >= 9 else 5

        if len(row) <= confirm_index:
            continue

        if str(row[confirm_index]) == "1":
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
        or not np.isfinite(frame[columns].to_numpy()).all()
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
    rows = []

    maximum_pages = int(
        math.ceil((end - start) / interval / 100)
    ) + 10

    for _ in range(maximum_pages):
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

        rows.extend(batch)
        oldest = min(int(row[0]) for row in batch)

        if oldest <= start:
            break

        if oldest >= after:
            raise ValueError("История не продвигается.")

        after = oldest

    frame = parse_candles(rows)
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
        or not np.array_equal(frame.ts.to_numpy(), expected)
    ):
        raise ValueError(
            f"{coin}: неполная история "
            + ("Mark Price." if mark else "торговых свечей.")
        )

    return frame


# ======================== ИНДИКАТОРЫ ========================

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
    delta = frame.close.diff()

    gain = rma(delta.clip(lower=0))
    loss = rma(-delta.clip(upper=0))

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
    frame["ADX"] = rma(dx)
    frame["ATR %"] = atr / frame.close * 100
    frame["+DI"] = 100 * plus / atr
    frame["-DI"] = 100 * minus / atr

    frame.loc[atr == 0, ["+DI", "-DI"]] = 0

    frame["EMA50"] = frame.close.ewm(
        span=50,
        adjust=False,
        min_periods=50,
    ).mean()

    return frame


def daily_from_hours(hours):
    source = hours.set_index("time")

    daily = source.resample("1D").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
    })

    counts = source.close.resample("1D").count()

    return indicators(daily[counts == 24].copy())


@st.cache_data(ttl=180, max_entries=50, show_spinner=False)
def daily_market(coin):
    frame = parse_candles(
        okx_get(
            "/market/candles",
            {
                "instId": instrument(coin),
                "bar": "1Dutc",
                "limit": "200",
            },
        )
    )

    if (
        len(frame) < 60
        or (frame.ts.diff().dropna() != DAY).any()
        or time.time() * 1000 - frame.ts.iloc[-1] > 49 * HOUR
    ):
        raise ValueError("Недостаточно свежей дневной истории.")

    return indicators(frame.set_index("time"))


def historical_signals(daily):
    output = daily.copy()
    output["signal"] = 0

    output.loc[
        (output.ADX >= 25)
        & (output["+DI"] > output["-DI"])
        & (output.close > output.EMA50),
        "signal",
    ] = 1

    output.loc[
        (output.ADX >= 25)
        & (output["-DI"] > output["+DI"])
        & (output.close < output.EMA50),
        "signal",
    ] = -1

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

    return output[["signal", "regime"]].shift(1)


# ======================== ГРАФИК ========================

def market_chart(frame, title):
    st.subheader(title)
    data = frame.copy()

    if "time" not in data.columns:
        data = data.reset_index()

    if "time" not in data.columns:
        data = data.rename(
            columns={data.columns[0]: "time"}
        )

    color = {
        "condition": {
            "test": "datum.close >= datum.open",
            "value": "#00df91",
        },
        "value": "#ff5c79",
    }

    spec = {
        "height": 350,
        "background": "#101827",
        "encoding": {
            "x": {
                "field": "time",
                "type": "temporal",
                "title": None,
            },
            "color": color,
        },
        "layer": [
            {
                "mark": "rule",
                "encoding": {
                    "y": {
                        "field": "low",
                        "type": "quantitative",
                        "scale": {"zero": False},
                        "title": "Цена",
                    },
                    "y2": {"field": "high"},
                },
            },
            {
                "mark": {"type": "bar", "size": 5},
                "encoding": {
                    "y": {
                        "field": "open",
                        "type": "quantitative",
                        "scale": {"zero": False},
                        "title": "Цена",
                    },
                    "y2": {"field": "close"},
                },
            },
        ],
        "config": {
            "axis": {
                "labelColor": "#c3d0e5",
                "titleColor": "#e8ecf4",
                "gridColor": "#25334b",
            },
            "view": {"stroke": None},
        },
    }

    try:
        st.vega_lite_chart(
            data[["time", "open", "high", "low", "close"]],
            spec,
            use_container_width=True,
        )
    except Exception:
        st.line_chart(
            data.set_index("time")[["close"]],
            use_container_width=True,
        )

    if "RSI" in data:
        st.caption("RSI")
        st.line_chart(
            data.set_index("time")[["RSI"]],
            use_container_width=True,
        )

    if "ADX" in data:
        st.caption("ADX")
        st.line_chart(
            data.set_index("time")[["ADX"]],
            use_container_width=True,
        )


# ======================== FUNDING ========================

def get_funding(coin, start, end, csv_text, limiter=None):
    if csv_text.strip():
        frame = pd.read_csv(io.StringIO(csv_text))

        required = {"coin", "fundingTime", "fundingRate"}

        if not required.issubset(frame.columns):
            raise ValueError(
                "CSV: нужны coin, fundingTime, fundingRate."
            )

        frame = frame[
            frame.coin.astype(str).str.upper() == coin
        ].copy()

        frame["fundingTime"] = pd.to_numeric(
            frame.fundingTime,
            errors="raise",
        ).astype("int64")

        frame["fundingRate"] = pd.to_numeric(
            frame.fundingRate,
            errors="raise",
        )

    else:
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

        frame = pd.DataFrame({
            "fundingTime": [
                int(row["fundingTime"]) for row in rows
            ],
            "fundingRate": [
                float(row["fundingRate"]) for row in rows
            ],
        })

    frame = (
        frame.drop_duplicates("fundingTime")
        .sort_values("fundingTime")
        .reset_index(drop=True)
    )

    if (
        frame.empty
        or not np.isfinite(frame.fundingRate.to_numpy()).all()
        or frame.fundingTime.iloc[0] > start
        or frame.fundingTime.iloc[-1] < end - 9 * HOUR
    ):
        raise ValueError(
            "Funding не покрывает период. "
            "Нужен полный CSV либо сценарный режим."
        )

    frame = frame[
        (frame.fundingTime >= start - 9 * HOUR)
        & (frame.fundingTime < end)
    ]

    if (frame.fundingTime.diff().dropna() > 9 * HOUR).any():
        raise ValueError("Обнаружен разрыв funding.")

    if (frame.fundingTime % HOUR != 0).any():
        raise ValueError(
            "Funding не на границе часа. "
            "Нужна более точная событийная история."
        )

    return frame


def research_bundle(
    coin,
    days,
    end,
    bar,
    funding_mode,
    csv_text,
    limiter=None,
):
    start = end - days * DAY

    hours = history_candles(
        coin,
        start - 70 * DAY,
        end,
        "1H",
        False,
        limiter,
    )

    signals = historical_signals(
        daily_from_hours(hours)
    )

    trade = (
        hours[hours.ts >= start].copy().reset_index(drop=True)
        if bar == "1H"
        else history_candles(
            coin, start, end, bar, False, limiter
        )
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
        validate="one_to_one",
    )

    days_index = data.time.dt.floor("D")

    data["signal"] = (
        days_index.map(signals.signal)
        .fillna(0)
        .astype(int)
    )

    data["regime"] = (
        days_index.map(signals.regime)
        .fillna("Не определено")
    )

    data["funding_rate"] = 0.0

    if funding_mode == "Фактический":
        funding = get_funding(
            coin, start, end, csv_text, limiter
        )
        rates = funding.groupby("fundingTime").fundingRate.sum()
        data["funding_rate"] = data.ts.map(rates).fillna(0.0)

    return data


@st.cache_data(ttl=600, max_entries=4, show_spinner=False)
def cached_bundle(coin, days, end, bar, funding_mode, csv_text):
    return research_bundle(
        coin, days, end, bar, funding_mode, csv_text
    )


# ======================== РИСК-ДВИЖОК DCA ========================

def fill_price(reference, side, costs, stop=False):
    adverse = (
        costs["half_spread"]
        + costs["slippage"] * (2 if stop else 1)
    )
    return reference * (1 + side * adverse)


class DCAEngine:
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
        self.bar_minimum = float(budget)

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

    def equity_mark(self, mark):
        p = self.position
        return self.cash + (
            p["side"] * p["qty"] * (mark - p["avg"])
            if p else 0.0
        )

    def equity_exit(self, price, stop=True):
        p = self.position

        if not p:
            return self.cash

        execution = fill_price(
            price, -p["side"], self.costs, stop
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
        self.bar_minimum = min(self.bar_minimum, equity)
        self.max_dd = max(
            self.max_dd,
            (self.peak - equity) / self.peak,
        )

        if self.position:
            self.max_margin = max(
                self.max_margin,
                self.position["margin"],
            )
            self.max_notional = max(
                self.max_notional,
                self.position["qty"] * mark,
            )

    def cycle_limit(self):
        limit = self.initial * self.risk["cycle_loss"]

        if self.risk["account_capital"] > 0:
            limit = min(
                limit,
                self.risk["account_capital"] * 0.01,
            )

        return limit

    def first_size(self, price, side, cfg):
        weights = [1.0] + [
            cfg["mart"] ** index
            for index in range(cfg["so_count"])
        ]

        first_fill = fill_price(price, side, self.costs)

        stop_reference = first_fill * (
            1 - side * self.risk["outer_stop"]
        )

        stop_fill = fill_price(
            stop_reference, -side, self.costs, True
        )

        quantity = 0.0
        nominal = 0.0
        open_fees = 0.0
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
                reference, side, self.costs
            )

            quantity += weight / execution
            nominal += weight
            open_fees += weight * self.fee

            loss = (
                -side * (quantity * stop_fill - nominal)
                + open_fees
                + quantity * stop_fill * self.fee
                + nominal * self.costs["funding"] * 9
            )

            worst_loss = max(worst_loss, loss)

        if worst_loss <= 0:
            return 0.0

        by_risk = self.cycle_limit() / worst_loss
        by_budget = max(0.0, self.cash) / (
            sum(weights) / cfg["leverage"]
            + worst_loss
            + sum(weights) * self.fee
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
        nominal = self.first_size(price, signal, cfg)

        if nominal <= 0:
            self.blocked_orders += 1
            return

        execution = fill_price(price, signal, self.costs)
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
            "base": nominal,
            "margin": margin,
            "so": 0,
            "so_disabled": False,
            "opened": timestamp,
            "start_cash": start_cash,
            "risk_limit": self.cycle_limit(),
            "cfg": cfg,
            "regime": regime,
        }

        self.observe(price, mark)

    def close(self, price, mark, timestamp, reason):
        p = self.position

        if not p:
            return

        execution = fill_price(
            price,
            -p["side"],
            self.costs,
            reason != "TP",
        )

        fee = p["qty"] * execution * self.fee

        self.cash += (
            p["side"] * p["qty"] * (execution - p["avg"])
            - fee
        )
        self.fees += fee
        self.cycles += 1
        self.max_cycle_hours = max(
            self.max_cycle_hours,
            (timestamp - p["opened"]) / HOUR,
        )

        key = (
            ("Long" if p["side"] == 1 else "Short")
            + " / " + p["regime"]
        )

        item = self.breakdown.setdefault(
            key, {"pnl": 0.0, "cycles": 0}
        )
        item["pnl"] += self.cash - p["start_cash"]
        item["cycles"] += 1

        if reason != "TP":
            self.stops += 1
            self.cooldown_until = (
                timestamp + self.risk["cooldown"] * HOUR
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

    def threshold_price(self, target):
        p = self.position

        if not p:
            return None

        kappa = 1 - p["side"] * (
            self.costs["half_spread"]
            + 2 * self.costs["slippage"]
        )

        denominator = (
            p["qty"] * kappa * (p["side"] - self.fee)
        )

        if abs(denominator) < 1e-12:
            return None

        return (
            target - self.cash
            + p["side"] * p["qty"] * p["avg"]
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
            p["side"] * p["qty"] * p["avg"] - self.cash
        ) / denominator

    def check_now(self, price, mark, timestamp):
        p = self.position

        if not p:
            self.observe(price, mark)
            return

        equity = self.equity_exit(price)
        maintenance = (
            p["qty"] * mark
            * (self.risk["mmr"] + self.fee)
        )

        take = p["avg"] * (
            1 + p["side"] * p["cfg"]["tp"] / 100
        )
        outer = p["entry"] * (
            1 - p["side"] * self.risk["outer_stop"]
        )

        if self.equity_mark(mark) <= maintenance:
            reason = "MMR"
        elif equity <= self.peak * (1 - self.risk["account_dd"]):
            reason = "ACCOUNT_DD"
        elif equity <= self.day_start * (1 - self.risk["daily_loss"]):
            reason = "DAY"
        elif equity <= p["start_cash"] - p["risk_limit"]:
            reason = "RISK"
        elif p["side"] * (price - outer) <= 0:
            reason = "PRICE"
        elif timestamp - p["opened"] >= self.risk["max_hours"] * HOUR:
            reason = "TIME"
        elif p["side"] * (price - take) >= 0:
            reason = "TP"
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
        nominal = p["base"] * cfg["mart"] ** p["so"]
        execution = fill_price(price, p["side"], self.costs)
        fee = nominal * self.fee
        margin = nominal / cfg["leverage"]

        if self.equity_mark(mark) < p["margin"] + margin + fee:
            p["so_disabled"] = True
            self.blocked_orders += 1
            return

        old_position = copy.deepcopy(p)
        old_cash = self.cash
        additional = nominal / execution

        p["avg"] = (
            p["qty"] * p["avg"] + nominal
        ) / (
            p["qty"] + additional
        )
        p["qty"] += additional
        p["margin"] += margin
        self.cash -= fee

        stop_reference = p["entry"] * (
            1 - p["side"] * self.risk["outer_stop"]
        )

        projected = (
            self.equity_exit(stop_reference) - p["start_cash"]
        )

        if projected < -p["risk_limit"] - 1e-8:
            self.position = old_position
            self.position["so_disabled"] = True
            self.cash = old_cash
            self.blocked_orders += 1
            return

        self.fees += fee
        p["so"] += 1
        self.observe(price, mark)

    def advance(self, a, b, mark_a, mark_b, timestamp):
        price = a
        mark = mark_a
        self.check_now(price, mark, timestamp)

        for _ in range(20):
            p = self.position

            if not p:
                self.observe(b, mark_b)
                return

            delta = b - price
            mark_delta = mark_b - mark
            events = []

            def add(level, reason, priority):
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
                        reason,
                        level,
                    ))

            cfg = p["cfg"]

            add(
                p["avg"] * (
                    1 + p["side"] * cfg["tp"] / 100
                ),
                "TP",
                5,
            )
            add(
                p["entry"] * (
                    1 - p["side"] * self.risk["outer_stop"]
                ),
                "PRICE",
                1,
            )

            if p["side"] * delta < 0:
                for target, reason in [
                    (
                        p["start_cash"] - p["risk_limit"],
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
                ]:
                    add(self.threshold_price(target), reason, 0)

                if (
                    not p["so_disabled"]
                    and p["so"] < cfg["so_count"]
                ):
                    add(
                        p["entry"] * (
                            1
                            - p["side"]
                            * cfg["step"]
                            * (p["so"] + 1)
                            / 100
                        ),
                        "SO",
                        4,
                    )

            liquidation = self.mmr_price()

            if (
                liquidation is not None
                and abs(mark_delta) > 1e-12
                and p["side"] * mark_delta < 0
            ):
                fraction = (liquidation - mark) / mark_delta

                if 1e-9 < fraction <= 1 + 1e-9:
                    events.append((
                        min(1.0, fraction),
                        -1,
                        "MMR",
                        price + delta * fraction,
                    ))

            if not events:
                self.check_now(b, mark_b, timestamp)
                return

            fraction, _, reason, price = min(events)
            mark = mark + mark_delta * fraction

            if reason == "SO":
                self.add_safety(price, mark)
                self.check_now(price, mark, timestamp)
            else:
                self.close(price, mark, timestamp, reason)

        raise ValueError("Слишком много событий в сегменте.")

    def process_bar(self, row, order):
        timestamp = int(row["ts"])
        price = float(row["open"])
        mark = float(row["mark_open"])
        self.bar_minimum = float("inf")

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
                    * self.costs["funding"]
                    if timestamp % (8 * HOUR) == 0
                    else 0.0
                )

            self.cash += funding
            self.funding_cash += funding

        self.check_now(price, mark, timestamp)
        signal = int(row["signal"])

        if self.position and signal == -self.position["side"]:
            self.close(price, mark, timestamp, "FLIP")

        if not self.position:
            self.enter(
                price,
                mark,
                timestamp,
                signal,
                str(row["regime"]),
            )

        for index in range(1, len(order)):
            self.advance(
                float(row[order[index - 1]]),
                float(row[order[index]]),
                float(row["mark_" + order[index - 1]]),
                float(row["mark_" + order[index]]),
                timestamp,
            )

        self.observe(
            float(row["close"]),
            float(row["mark_close"]),
        )

    def summary(self):
        equity = (
            self.cash
            if self.last_price is None
            else min(
                self.equity_mark(self.last_mark),
                self.equity_exit(self.last_price),
            )
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
                if self.halted or equity <= self.initial
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
            candidate.process_bar(row, order)

            alternatives.append((
                candidate.equity_exit(float(row["close"])),
                candidate.bar_minimum,
                candidate,
            ))

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


# ======================== WALK-FORWARD ========================

def select_train(data, budget, risk, funding_mode, optimize):
    candidates = [dict(DEFAULT_DCA)]

    if optimize:
        candidates.extend([
            {**DEFAULT_DCA, "mart": 1.0},
            {**DEFAULT_DCA, "step": 2.4},
        ])

    results = []

    for cfg in candidates:
        engine = DCAEngine(
            budget, cfg, "Базовый", risk, funding_mode
        )
        engine, curve = simulate_research(data, engine)

        if curve.empty:
            continue

        previous = budget
        segment_returns = []

        for chunk in np.array_split(
            curve.equity.to_numpy(),
            3,
        ):
            if len(chunk):
                segment_returns.append(
                    chunk[-1] / previous - 1
                )
                previous = chunk[-1]

        score = min(segment_returns) - 1.5 * engine.max_dd

        if engine.halted:
            score = -float("inf")

        results.append((score, cfg))

    if not results:
        raise ValueError("Train не содержит данных.")

    best = max(results, key=lambda item: item[0])

    if not math.isfinite(best[0]):
        return dict(DEFAULT_DCA), "Train не прошёл ограничения"

    return dict(best[1]), f"Train score {best[0]:.4f}"


def walk_forward(data, budget, risk, funding_mode, folds, optimize):
    start = int(data.ts.iloc[0]) + 180 * DAY
    schedule = []

    for index in range(folds):
        left = start + index * 30 * DAY

        cfg, note = select_train(
            data[
                (data.ts >= left - 180 * DAY)
                & (data.ts < left)
            ],
            budget,
            risk,
            funding_mode,
            optimize,
        )

        schedule.append((
            left,
            left + 30 * DAY,
            cfg,
            note,
            f"OOS {index + 1}",
        ))

    holdout = start + folds * 30 * DAY

    cfg, note = select_train(
        data[
            (data.ts >= holdout - 180 * DAY)
            & (data.ts < holdout)
        ],
        budget,
        risk,
        funding_mode,
        optimize,
    )

    schedule.append((
        holdout,
        holdout + 90 * DAY,
        cfg,
        note,
        "Holdout",
    ))

    rows = []
    summaries = []
    curves = {}
    engines = {}

    for case in CASES:
        engine = DCAEngine(
            budget,
            DEFAULT_DCA,
            case,
            risk,
            funding_mode,
        )
        pieces = []

        for left, right, cfg, note, label in schedule:
            segment = data[
                (data.ts >= left)
                & (data.ts < right)
            ]

            if segment.empty:
                raise ValueError("OOS-окно пустое.")

            engine.config = dict(cfg)

            before = (
                engine.equity_exit(float(segment.open.iloc[0]))
                if engine.last_price is not None
                else budget
            )

            engine, curve = simulate_research(segment, engine)
            after = engine.summary()["Equity USDT"]

            rows.append({
                "Сценарий": case,
                "Окно": label,
                "Начало UTC": pd.to_datetime(
                    left, unit="ms", utc=True
                ).isoformat(),
                "Конец UTC": pd.to_datetime(
                    right, unit="ms", utc=True
                ).isoformat(),
                "Доходность окна %": (
                    (after / before - 1) * 100
                    if before > 0 else np.nan
                ),
                "Equity USDT": after,
                "Параметры новых серий": canonical(cfg),
                "Train": note,
            })
            pieces.append(curve)

        combined = pd.concat(pieces, ignore_index=True)
        curves[case] = combined.set_index("time").equity
        engines[case] = engine
        summaries.append({
            "Сценарий": case,
            **engine.summary(),
        })

    return (
        pd.DataFrame(rows),
        pd.DataFrame(summaries),
        pd.DataFrame(curves),
        engines,
    )


# ======================== ИНТЕРФЕЙС ИССЛЕДОВАНИЯ ========================

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
        fee = st.number_input(
            "Taker-комиссия за сторону, %",
            min_value=0.0,
            max_value=1.0,
            value=0.05,
            step=0.01,
            key=prefix + "fee",
        ) / 100

        cycle_loss = st.number_input(
            "Предел убытка серии, % бюджета",
            min_value=0.1,
            max_value=10.0,
            value=3.0,
            key=prefix + "cycle",
        ) / 100

        account = st.number_input(
            "Капитал аккаунта для лимита 1%; 0 = неизвестен",
            min_value=0.0,
            value=0.0,
            key=prefix + "account",
        )

        mmr = st.number_input(
            "Условный MMR, %, не таблица OKX",
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

        uploaded = st.file_uploader(
            "CSV: coin,fundingTime,fundingRate",
            type=["csv"],
            key=prefix + "csv",
        )

        csv_text = (
            uploaded.getvalue().decode("utf-8-sig")
            if uploaded is not None else ""
        )

        st.caption(
            "fundingTime — Unix milliseconds. "
            "Ставка 0.0001 означает 0.01%."
        )

    risk = {
        "taker_fee": fee,
        "cycle_loss": cycle_loss,
        "account_capital": account,
        "mmr": mmr,
        "outer_stop": 0.10,
        "daily_loss": 0.05,
        "account_dd": 0.10,
        "max_hours": 72.0,
        "cooldown": 24.0,
    }

    return budget, risk, bar, funding_mode, csv_text


def research_warning(bar, funding_mode):
    notice(
        "Исследовательская модель, не допуск к запуску. "
        "MMR постоянный, без tier-таблиц, ADL и portfolio margin. "
        "Размеры не округляются по историческим lotSz/minSz. "
        "Два OHLC-пути не восстанавливают реальные тики.",
        "warning",
    )

    if bar == "1H":
        notice(
            "1H — предварительная оценка. "
            "Внутрисвечная просадка остаётся приближённой."
        )

    if funding_mode == "Сценарный":
        notice(
            "Funding сценарный: списание для обеих сторон "
            "каждые 8 часов. Базовый/Стресс/Кризис: "
            "0.01% / 0.02% / 0.03% от номинала."
        )


def breakdown_table(engines):
    rows = []

    for case, engine in engines.items():
        for key, value in engine.breakdown.items():
            direction, regime = key.split(" / ", 1)

            rows.append({
                "Сценарий": case,
                "Направление": direction,
                "Режим инструмента при входе": regime,
                "Закрытый PnL USDT": value["pnl"],
                "Циклов": value["cycles"],
            })

    if rows:
        table(pd.DataFrame(rows))

    st.caption(
        "Открытая серия включена в equity, "
        "но не в таблицу завершённых серий. "
        "Режим определяется по инструменту, не по BTC."
    )


def single_research(coin):
    st.subheader("Исторические сигналы и Walk-Forward")

    budget, risk, bar, funding_mode, csv_text = research_controls(
        "single_"
    )

    mode = st.radio(
        "Режим",
        ["14 дней", "Walk-Forward"],
        horizontal=True,
        key="single_mode",
    )

    folds = 0
    optimize = False

    if mode == "Walk-Forward":
        folds = st.number_input(
            "OOS-окон по 30 дней",
            min_value=1,
            max_value=6,
            value=3,
            key="wf_folds",
        )
        optimize = st.checkbox(
            "Выбирать параметры на train из трёх вариантов",
            value=False,
            key="wf_optimize",
        )
        st.caption(
            "Train 180 дней, Test 30 дней, holdout 90 дней. "
            "Варианты: исходный шаблон; mart=1; step=2.4%. "
            "Капитал между OOS-окнами не сбрасывается. "
            "Открытые серии продолжаются со своим планом."
        )

    research_warning(bar, funding_mode)

    if st.button(
        "Запустить исследование",
        key="run_single",
        use_container_width=True,
    ):
        st.session_state.pop("single_result", None)

        end = int(time.time() // 3600) * HOUR
        days = (
            14 if mode == "14 дней"
            else 180 + int(folds) * 30 + 90
        )

        with st.spinner(
            "Загружаю историю и считаю. "
            "На мелких свечах это может быть долго..."
        ):
            data = cached_bundle(
                coin, days, end, bar, funding_mode, csv_text
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
                curve_map = {}
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
                        data, engine
                    )
                    summaries.append({
                        "Сценарий": case,
                        **engine.summary(),
                    })
                    curve_map[case] = curve.set_index(
                        "time"
                    ).equity
                    engines[case] = engine

                summary = pd.DataFrame(summaries)
                curves = pd.DataFrame(curve_map)

        st.session_state["single_result"] = {
            "coin": coin,
            "mode": mode,
            "bar": bar,
            "funding": funding_mode,
            "timestamp": now(),
            "windows": windows,
            "summary": summary,
            "curves": curves,
            "engines": engines,
        }

    result = st.session_state.get("single_result")

    if result:
        st.caption(
            f"Последний расчёт: {result['coin']} · "
            f"{result['mode']} · {result['bar']} · "
            f"{result['funding']} · {result['timestamp']}"
        )

        table(result["summary"])
        st.line_chart(result["curves"])

        if not result["windows"].empty:
            st.subheader("OOS и holdout")
            table(result["windows"])

        st.subheader("Стороны и режимы")
        breakdown_table(result["engines"])

        st.download_button(
            "Скачать исследование CSV",
            result["summary"].to_csv(
                index=False
            ).encode("utf-8-sig"),
            "research.csv",
            "text/csv",
        )


# ======================== ПАКЕТНЫЙ ТЕСТ ========================

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
        coin, 14, end, bar, funding_mode, csv_text, limiter
    )
    engine = DCAEngine(
        budget, DEFAULT_DCA, case, risk, funding_mode
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

    directional = st.checkbox(
        "Только текущие LONG/SHORT — условная выборка",
        value=False,
        key="batch_directional",
    )

    coins = sorted({
        row["Монета"]
        for row in saved["rows"]
        if not directional
        or row["Сигнал"] in ("LONG", "SHORT")
    })

    st.caption(
        "Внутри теста Long/Short определяются исторически. "
        "Сегодняшнее направление не переносится на прошлое. "
        "По умолчанию — все монеты сканирования."
    )

    research_warning(bar, funding_mode)

    signature = canonical({
        "coins": coins,
        "scan": saved["timestamp"],
        "budget": budget,
        "risk": risk,
        "bar": bar,
        "funding": funding_mode,
        "case": case,
        "csv": csv_text,
    })

    if st.button(
        "🚀 Проверить ВСЕХ на истории",
        key="run_batch",
        use_container_width=True,
        disabled=not coins,
    ):
        st.session_state.pop("batch_result", None)

        end = int(time.time() // 3600) * HOUR
        limiter = RateLimiter()
        rows = []
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
                    rows.append(future.result())
                except Exception as exc:
                    rows.append({
                        "Монета": coin,
                        "Доходность %": np.nan,
                        "Статус": "Ошибка данных или модели",
                        "Ошибка": redact(str(exc)),
                    })

                progress.progress(index / len(jobs))
                status.caption(
                    f"Обработано {index}/{len(jobs)} · {coin}"
                )

        frame = (
            pd.DataFrame(rows)
            .sort_values(
                "Доходность %",
                ascending=False,
                na_position="last",
            )
            .reset_index(drop=True)
        )

        st.session_state["batch_result"] = {
            "signature": signature,
            "data": frame,
            "timestamp": now(),
        }

    result = st.session_state.get("batch_result")

    if result:
        if result["signature"] != signature:
            notice(
                "Параметры изменились. Нужен новый расчёт."
            )
        else:
            st.caption(result["timestamp"])

            st.dataframe(
                styled_frame(result["data"]),
                hide_index=True,
                use_container_width=True,
            )

            st.download_button(
                "Скачать пакетный тест",
                result["data"].to_csv(
                    index=False
                ).encode("utf-8-sig"),
                "batch_research.csv",
                "text/csv",
            )


# ======================== СКАНЕР ========================

@st.cache_data(ttl=180, max_entries=50, show_spinner=False)
def scanner_coin(coin):
    daily = daily_market(coin)
    last = daily.iloc[-1]
    ticker = quote(coin)

    if not np.isfinite([
        last.RSI,
        last.ADX,
        last.EMA50,
        last["+DI"],
        last["-DI"],
    ]).all():
        raise ValueError(
            "Недостаточно данных индикаторов."
        )

    if last.ADX < 25:
        signal = "GRID"
    elif (
        last["+DI"] > last["-DI"]
        and last.close > last.EMA50
    ):
        signal = "LONG"
    elif (
        last["-DI"] > last["+DI"]
        and last.close < last.EMA50
    ):
        signal = "SHORT"
    else:
        signal = "Не определено"

    return {
        "Монета": coin,
        "Цена": ticker["price"],
        "Сигнал": signal,
        "RSI": last.RSI,
        "ADX": last.ADX,
        "ATR %": last["ATR %"],
        "Объём 24H ≈ USDT": ticker["volume"],
    }


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


def scanner():
    st.title("2. Сканер рынка")
    st.caption(
        "SWAP · дневные закрытые свечи UTC · "
        "EMA50 и ADX/DI · симметричные Long/Short."
    )

    if st.button(
        "Сканировать монеты",
        use_container_width=True,
    ):
        rows = []
        errors = []
        progress = st.progress(0.0)

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
        }

    saved = st.session_state.get("scan")

    if not saved:
        notice("Запусти сканирование.")
        return

    st.caption(saved["timestamp"])

    if saved["errors"]:
        notice("; ".join(saved["errors"]), "warning")

    if not saved["rows"]:
        return

    table(pd.DataFrame(saved["rows"]))
    batch_research(saved)

    coin = st.selectbox(
        "Монета для графика и исследования",
        [row["Монета"] for row in saved["rows"]],
    )

    market_chart(
        daily_market(coin),
        coin + " · дневные свечи",
    )

    columns = st.columns(3)

    for column, label, kind, direction, suffix in [
        (columns[0], "🟢 Long", "DCA", "Long", "long"),
        (columns[1], "🔴 Short", "DCA", "Short", "short"),
        (columns[2], "🟡 Grid", "Grid", "Neutral", "neutral"),
    ]:
        if column.button(
            label,
            key="action_scanner_" + suffix,
        ):
            route(
                kind,
                direction,
                {
                    "coin": coin,
                    "entry": quote(coin)["price"],
                },
            )

    single_research(coin)


# ======================== ПЛАНЫ DCA / GRID ========================

def dca_plan(settings, direction):
    if (
        settings["entry"] <= 0
        or settings["step"] <= 0
        or settings["base_amount"] <= 0
        or settings["first_so"] <= 0
        or settings["mart"] < 1
    ):
        raise ValueError("Проверь параметры DCA.")

    rows = []
    nominal = 0.0
    quantity = 0.0

    for index in range(int(settings["so_count"]) + 1):
        price = settings["entry"] * (
            1
            - sign(direction)
            * settings["step"]
            * index / 100
        )

        if price <= 0:
            raise ValueError("Уровень имеет цену ≤ 0.")

        amount = (
            settings["base_amount"]
            if index == 0
            else settings["first_so"]
            * settings["mart"] ** (index - 1)
        )

        nominal += amount
        quantity += amount / price

        rows.append({
            "Ордер": "Вход" if index == 0 else f"СО {index}",
            "Цена": price,
            "Номинал USDT": amount,
            "Всего номинал": nominal,
            "Средняя": nominal / quantity,
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
        notice(
            "Монета исключена из новых карточек. "
            "Существующие карточки не удаляются.",
            "warning",
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
        notice("Для Spot выбери Long.", "warning")
        return

    settings = {
        "base_margin": ni(
            "Базовая маржа / капитал Spot",
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
            "TP от средней, %",
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
            settings["base_margin"] + settings["reserve"]
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

        for field, label in [
            ("stop_price", "Сигнальный стоп Long/Short"),
            ("stop_lower", "Нижний стоп Neutral"),
            ("stop_upper", "Верхний стоп Neutral"),
            ("max_loss", "Лимит открытого убытка USDT"),
        ]:
            settings[field] = ni(
                label,
                0,
                kind + field,
            )

        settings["stale_hours"] = ni(
            "Актуальность сверки, часов",
            6,
            kind + "stale",
            0.1,
            168,
        )

    valid = (
        bool(name.strip())
        and coin.isalnum()
        and not (
            market == "SPOT"
            and settings["leverage"] != 1
        )
    )

    if kind == "DCA":
        try:
            table(pd.DataFrame(
                dca_plan(settings, direction)
            ))
        except ValueError as exc:
            valid = False
            notice(str(exc))
    else:
        valid = (
            valid
            and 0 < settings["lower"] < settings["upper"]
        )

        if valid:
            st.line_chart(pd.DataFrame({
                "Уровни Grid": np.linspace(
                    settings["lower"],
                    settings["upper"],
                    int(settings["grids"]) + 1,
                ),
            }))

        st.caption(
            "Grid: план и ручное сопровождение. "
            "Исследовательский движок DCA не выдаётся "
            "за точную модель Grid OKX."
        )

    pending_key = kind + "pending"

    if pending_key not in st.session_state:
        st.session_state[pending_key] = {
            "id": str(uuid.uuid4()),
            "created_at": now(),
        }

    if st.button(
        "Сохранить карточку в SQLite Cloud",
        disabled=not valid or not STORE_READY,
        key=kind + "save",
        use_container_width=True,
    ):
        quote(coin, market)
        pending = st.session_state[pending_key]

        save_bot(
            {
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
            },
            "Создана карточка",
            task,
        )

        st.session_state.pop(pending_key, None)
        st.session_state["_flash"] = (
            "Карточка записана и прочитана обратно."
        )
        route(kind, focus=pending["id"])

    if st.button(
        "Начать другую карточку с новым ID",
        key=kind + "new",
    ):
        st.session_state[pending_key] = {
            "id": str(uuid.uuid4()),
            "created_at": now(),
        }
        notice(
            "Новый ID назначен. После ошибки сети "
            "сначала проверь список, чтобы не создать копию."
        )

    if not STORE_READY:
        notice(
            "Хранилище не подтверждено. Сохранение заблокировано.",
            "warning",
        )

    if kind == "DCA" and coin.isalnum():
        single_research(coin)


# ======================== СОПРОВОЖДЕНИЕ ========================

def assess(bot, price):
    s = bot["settings"]
    p = bot["position"]
    side = sign(bot["direction"])

    realized = (
        num(p.get("realized_pnl"))
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
            num(s["total_budget"])
            - num(p.get("base_margin"), s["base_margin"])
            - num(p.get("added_margin")),
        ),
    }

    if bot["lifecycle"] != "Работает":
        result.update(
            title=(
                "План сохранён"
                if bot["lifecycle"] == "Черновик"
                else "Бот отмечен завершённым"
            ),
            reason=(
                "Статус задаётся вручную. "
                "Для работы сверь позицию на OKX."
            ),
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
            (s["stop_lower"] > 0 and price <= s["stop_lower"])
            or (s["stop_upper"] > 0 and price >= s["stop_upper"])
        )
    )

    if stop_hit:
        result.update(
            title="Достигнут сигнальный стоп",
            reason=(
                "Срочно сверь позицию и выполни выход по плану на OKX. "
                "Ордер приложением не отправлялся."
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
        result.update(
            title=(
                "Цена внутри диапазона"
                if s["lower"] <= price <= s["upper"]
                else "Цена вне Grid"
            ),
            reason=(
                "Проверь обе стороны, ордера и Total PnL. "
                "Показан ручной снимок."
            ),
            pnl=p.get("total_pnl_manual"),
        )
        return result

    quantity = num(p.get("volume"))
    average = num(p.get("avg_price"))

    if quantity <= 0:
        result.update(
            title="По сверке открытой позиции нет",
            reason="Проверь ожидание следующего цикла.",
            pnl=realized,
            floating=0.0,
        )
        return result

    if average <= 0:
        result["reason"] = "Нужна фактическая средняя."
        return result

    floating = side * quantity * (price - average)

    result.update(
        floating=floating,
        pnl=realized + floating,
    )

    if s["max_loss"] > 0 and floating <= -s["max_loss"]:
        result.update(
            title="Достигнут лимит открытого убытка",
            reason=(
                "Проверь ручной выход по плану. "
                "Прибыль прошлых циклов лимит не отменяет."
            ),
            tone="error",
        )
        return result

    liquidation = num(p.get("liq_price"))

    if (
        liquidation > 0
        and side * (price - liquidation) / price * 100
        <= s["liq_warn"]
    ):
        result.update(
            title="Цена близко к введённой ликвидации",
            reason=(
                "Сверь Mark Price и MMR на OKX. "
                "Здесь последняя цена и ручной уровень."
            ),
            tone="error",
        )
        return result

    if bot["strategy"] == "DCA":
        result["tp"] = average * (
            1 + side * s["tp"] / 100
        )

        if s["entry"] > 0:
            plan = dca_plan(s, bot["direction"])
            executed = min(
                max(0, int(p.get("executed_so", 0))),
                len(plan) - 1,
            )

            if executed + 1 < len(plan):
                result["next_so"] = plan[executed + 1]["Цена"]
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
                "TP цикла не равен остановке всего бота."
            ),
            tone="success",
        )
    elif (
        bot["strategy"] == "Grid"
        and not s["lower"] <= price <= s["upper"]
    ):
        result.update(
            title="Цена вне Grid",
            reason="Проверь остаточную позицию и план выхода.",
            tone="warning",
        )
    elif (
        max(0, -side * (price / average - 1) * 100)
        >= s["danger_pct"]
    ):
        result.update(
            title="Заданная зона внимания",
            reason="Проверь риск. Это не прогноз разворота.",
            tone="warning",
        )
    else:
        result.update(
            title="Контроль по плану",
            reason=(
                "Жёсткие условия не сработали. "
                "Это не гарантия безопасности."
            ),
            tone="success" if floating > 0 else "info",
        )

    return result


# ======================== TELEGRAM ========================

def send_telegram(text):
    token = str(secret("TELEGRAM_TOKEN", ""))
    chat = str(secret("TELEGRAM_CHAT_ID", ""))

    try:
        token = token or str(st.secrets["telegram"]["token"])
        chat = chat or str(st.secrets["telegram"]["chat_id"])
    except Exception:
        pass

    token = token or st.session_state.get("tg_token", "")
    chat = chat or st.session_state.get("tg_chat", "")

    if not token or not chat:
        raise ValueError("Настрой Telegram.")

    result = http_json(
        f"https://api.telegram.org/bot{token}/sendMessage",
        method="POST",
        payload={
            "chat_id": chat,
            "text": text[:4000],
        },
        timeout=15,
    )

    if not result.get("ok"):
        raise ValueError("Telegram не подтвердил отправку.")


# ======================== КАРТОЧКИ БОТОВ ========================

def bot_card(bot, compact=False):
    try:
        price = quote(bot["coin"], bot["market"])["price"]
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
            bot["name"] + " · " + bot["lifecycle"]
            + " · " + bot["market"]
        )

        columns = st.columns(3)
        columns[0].metric("Цена", fmt(price, 6))
        columns[1].metric(
            "PnL с OKX: снимок"
            if bot["direction"] == "Neutral"
            else "PnL ≈ USDT",
            fmt(result["pnl"]),
        )
        columns[2].metric(
            "Остаток бюджета маржи",
            fmt(result["reserve"]),
        )

        notice(
            result["title"] + ". " + result["reason"],
            result["tone"],
        )

        if bot["strategy"] == "DCA":
            st.caption(
                f"Закрытые циклы: {fmt(result['realized'])} · "
                f"Открытая позиция: {fmt(result['floating'])} USDT"
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
                    total = ni(
                        "Total PnL: ручной снимок",
                        num(p.get("total_pnl_manual")),
                        key + "total",
                        low=None,
                    )
                    quantity = 0.0
                    average = 0.0
                    liquidation = 0.0
                    realized = 0.0
                    executed = 0

                    st.caption(
                        "Для завершения проверь обе стороны "
                        "и остаточные ордера на OKX."
                    )
                else:
                    known = False
                    total = None

                    quantity = ni(
                        "Объём в базовой монете, не контракты",
                        num(p.get("volume")),
                        key + "qty",
                    )
                    average = ni(
                        "Фактическая средняя",
                        num(p.get("avg_price")),
                        key + "avg",
                    )
                    liquidation = ni(
                        "Ликвидационная цена; 0 = неизвестна",
                        num(p.get("liq_price")),
                        key + "liq",
                    )

                    if bot["strategy"] == "DCA":
                        realized = ni(
                            "PnL закрытых циклов, не Total PnL",
                            num(p.get("realized_pnl")),
                            key + "realized",
                            low=None,
                        )

                        maximum = int(s["so_count"])
                        executed = (
                            ni(
                                "Исполнено СО текущего цикла",
                                min(
                                    maximum,
                                    max(0, int(p.get("executed_so", 0))),
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
                    num(p.get("base_margin"), s["base_margin"]),
                    key + "margin",
                )
                added = ni(
                    "Всего добавлено маржи",
                    num(p.get("added_margin")),
                    key + "added",
                )

                confirmed = st.checkbox(
                    "Сверил значения; для завершения "
                    "проверил отсутствие остатков и ордеров"
                )

                if st.form_submit_button(
                    "Сохранить сверку",
                    disabled=not STORE_READY,
                ):
                    if (
                        not confirmed
                        or (quantity > 0 and average <= 0)
                        or (lifecycle == "Закрыт" and quantity > 0)
                    ):
                        notice(
                            "Проверь значения и подтверждение.",
                            "error",
                        )
                    else:
                        bot["lifecycle"] = lifecycle
                        bot["position"] = {
                            "volume": quantity,
                            "avg_price": average,
                            "liq_price": liquidation,
                            "realized_pnl": realized,
                            "executed_so": int(executed),
                            "base_margin": base,
                            "added_margin": added,
                            "total_pnl_manual": (
                                total if known else None
                            ),
                            "last_check": now(),
                        }

                        save_bot(
                            bot,
                            "Сверка позиции",
                            "Значения сверены пользователем с OKX.",
                        )

                        st.session_state["_flash"] = (
                            "Сверка записана и проверена."
                        )
                        st.rerun()

        with st.expander("Изменить план"):
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
                    ("max_loss", "Лимит открытого убытка"),
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
                    disabled=not STORE_READY,
                ):
                    if (
                        bot["strategy"] == "Grid"
                        and not (
                            0 < updated["lower"] < updated["upper"]
                        )
                    ):
                        notice("Неверный диапазон.", "error")
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

            quantity = num(p.get("volume"))
            average = num(p.get("avg_price"))

            if (
                quantity > 0
                and average > 0
                and price
                and sign(bot["direction"])
            ):
                prices = np.linspace(
                    min(price, average) * 0.85,
                    max(price, average) * 1.15,
                    100,
                )

                profile = pd.DataFrame({
                    "Цена": prices,
                    "Открытый PnL": (
                        sign(bot["direction"])
                        * quantity
                        * (prices - average)
                    ),
                }).set_index("Цена")

                st.caption("Профиль без комиссий и funding")
                st.line_chart(profile)

        with st.form(key + "decision"):
            decision = st.radio(
                "Моё решение",
                ["Не трогать", "Проверить на OKX", "Выход по плану"],
                horizontal=True,
            )
            reason = st.text_input("Причина")
            valid_hours = st.number_input(
                "Перепроверить через часов",
                min_value=0.1,
                max_value=168.0,
                value=6.0,
            )

            if st.form_submit_button(
                "Записать решение",
                disabled=not STORE_READY,
            ):
                if not reason.strip():
                    notice("Укажи причину.", "error")
                else:
                    bot["decision"] = {
                        "action": decision,
                        "reason": reason.strip(),
                        "created_at": now(),
                        "valid_hours": valid_hours,
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

            if age_hours(
                decision.get("created_at")
            ) >= num(
                decision.get("valid_hours"),
                6,
            ):
                notice("Срок решения истёк.", "warning")

        elif decision:
            st.caption(str(decision))

        if st.button(
            "Отправить отчёт в Telegram",
            key=key + "telegram",
        ):
            stamp_key = bot["id"] + "_telegram_ts"

            if (
                time.time()
                - st.session_state.get(stamp_key, 0)
                < 60
            ):
                notice(
                    "Повторная отправка доступна через минуту."
                )
            else:
                send_telegram(
                    f"{bot['name']}\n"
                    f"{bot['coin']} · {bot['strategy']} "
                    f"{bot['direction']}\n\n"
                    f"{result['title']}\n{result['reason']}\n\n"
                    f"Цена: {fmt(price, 6)}\n"
                    f"PnL ≈ {fmt(result['pnl'])} USDT\n"
                    f"Сверка: {p.get('last_check') or 'нет'}\n\n"
                    "Торговая команда не отправлялась."
                )

                st.session_state[stamp_key] = time.time()
                notice("Отчёт отправлен.", "success")

        st.caption(
            "PnL карточки приблизительный, без отдельного "
            "учёта комиссий и funding открытой позиции. "
            "«Не трогать» не отключает стоп."
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
        if status == "Все" or bot["lifecycle"] == status
    ]

    selected.sort(
        key=lambda bot: (
            bot["id"] != st.session_state.get("focus")
        )
    )

    if not selected:
        notice("Нет карточек для выбранного фильтра.")

    for bot in selected:
        try:
            bot_card(bot, compact)
        except ValueError as exc:
            notice(redact(str(exc)), "error")
        except Exception as exc:
            notice(
                "Действие по карточке не подтверждено: "
                + type(exc).__name__
                + ". Обнови список перед повтором.",
                "error",
            )


# ======================== НАСТРОЙКИ ========================

def settings_page(bots):
    st.title("Настройки")
    st.caption(APP_VERSION)
    st.subheader("Хранилище ботов")

    if STORE_READY:
        notice(
            "SQLite Cloud подключена. "
            f"Сохранённых карточек: {len(bots)}.",
            "success",
        )
    else:
        notice(
            "Подключение к SQLite Cloud пока не подтверждено. "
            "Сохранение новых карточек заблокировано.",
            "warning",
        )

    if st.button(
        "Проверить соединение с базой",
        key="settings_check_database",
    ):
        try:
            result = store_health()
            notice(
                "Соединение с SQLite Cloud работает. "
                f"Карточек в базе: {result['bots']}.",
                "success",
            )
        except Exception as exc:
            notice(redact(str(exc)), "error")

    st.subheader("Резервные копии")

    if STORE_READY:
        if st.button(
            "Подготовить резервную копию",
            key="settings_prepare_backup",
        ):
            st.session_state["backup"] = {
                "data": export_backup(),
                "timestamp": now(),
            }

        backup = st.session_state.get("backup")

        if backup:
            st.caption(
                "Копия подготовлена UTC: "
                + backup["timestamp"]
            )
            st.download_button(
                "Скачать резервную копию JSON",
                data=backup["data"],
                file_name="okx_backup.json",
                mime="application/json",
                key="settings_download_backup",
            )

        uploaded = st.file_uploader(
            "Восстановить карточки из JSON, до 5 MB",
            type=["json"],
            key="restore_backup",
        )

        confirm = st.checkbox(
            "Добавить копии с новыми ID, "
            "не заменяя существующие карточки",
            key="settings_confirm_restore",
        )

        if st.button(
            "Восстановить копии",
            disabled=uploaded is None or not confirm,
            key="settings_restore_backup",
        ):
            if uploaded.size > 5_000_000:
                raise ValueError("Файл больше 5 MB.")

            count = import_backup(
                json.loads(uploaded.getvalue())
            )

            st.session_state["_flash"] = (
                f"Восстановлено карточек: {count}. "
                "Они добавлены как черновики. "
                "Перед продолжением сверь позиции с OKX."
            )
            st.rerun()

    else:
        notice(
            "Резервное копирование и восстановление "
            "станут доступны после подключения базы."
        )

    with st.expander(
        "Перенести старые карточки из локального файла",
        expanded=False,
    ):
        notice(
            "Используется только оставшийся старый файл "
            "на сервере. Оригинал не изменяется. "
            "Повторный перенос создаёт копии."
        )

        confirmed = st.checkbox(
            "Подтверждаю перенос копий",
            key="settings_confirm_local_import",
        )

        if st.button(
            "Перенести локальные карточки",
            disabled=not confirmed or not STORE_READY,
            key="settings_import_local",
        ):
            if not os.path.isfile(OLD_SQLITE):
                raise ValueError(
                    "Старый локальный файл не найден."
                )

            connection = sqlite3.connect(
                "file:"
                + os.path.abspath(OLD_SQLITE)
                + "?mode=ro",
                uri=True,
            )

            try:
                connection.row_factory = sqlite3.Row

                names = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE type='table'"
                    )
                }

                if "terminal_bots" in names:
                    raw = [
                        json.loads(row[0])
                        for row in connection.execute(
                            "SELECT document FROM terminal_bots"
                        )
                    ]
                elif "bots" in names:
                    raw = [
                        dict(row)
                        for row in connection.execute(
                            "SELECT * FROM bots"
                        )
                    ]
                else:
                    raise ValueError(
                        "В старом файле не найдены таблицы карточек."
                    )
            finally:
                connection.close()

            count = import_backup({"bots": raw})
            st.session_state["_flash"] = (
                f"Перенесено копий: {count}. "
                "Обнови фактические позиции."
            )
            st.rerun()

    st.subheader("Telegram")

    with st.expander(
        "Настроить и проверить Telegram",
        expanded=False,
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
            "Отправить тестовое сообщение",
            key="settings_test_telegram",
        ):
            send_telegram(
                "OKX Terminal Pro: тестовое сообщение. "
                "Торговые команды не отправлялись."
            )
            notice(
                "Тестовое сообщение отправлено.",
                "success",
            )

    with st.expander(
        "Подключение и Secrets",
        expanded=False,
    ):
        st.code(
            '''
APP_PASSWORD = "твой-пароль"

DATABASE_URL = "sqlitecloud://HOST:8860/ИМЯ_БАЗЫ?apikey=ТВОЙ_КЛЮЧ"

# Необязательно:
TELEGRAM_TOKEN = "токен"
TELEGRAM_CHAT_ID = "chat-id"
'''.strip(),
            language="toml",
        )

        st.caption(
            "Это пример формата, не рабочие реквизиты. "
            "Если соединение работает, DATABASE_URL "
            "менять не нужно. Ключи не публикуй."
        )

    with st.expander(
        "Техническая диагностика",
        expanded=False,
    ):
        st.caption(
            "Для обычной работы диагностика не нужна."
        )

        if st.button(
            "Открыть техническую диагностику",
            key="settings_open_diagnostics",
        ):
            st.session_state["_diagnostics"] = True
            st.rerun()

    st.caption(
        "Карточки хранятся в SQLite Cloud. "
        "Автоматические резервные копии проверяются "
        "отдельно у провайдера. "
        "Независимого фонового мониторинга нет. "
        "Приложение не отправляет торговые команды."
    )


# ======================== ГЛАВНОЕ ПРИЛОЖЕНИЕ ========================

def main():
    global STORE_READY

    if st.session_state.get("_ui_release") != UI_RELEASE:
        st.session_state["_ui_release"] = UI_RELEASE
        st.session_state["_diagnostics"] = False

    apply_route()
    design()
    login()

    if st.session_state.get("_diagnostics"):
        diagnostics_screen()

    with st.sidebar:
        st.title("OKX Terminal")
        st.caption("SQLite Cloud")

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
            "Обновить цены и список",
            key="sidebar_refresh",
            use_container_width=True,
        ):
            quote.clear()
            daily_market.clear()
            scanner_coin.clear()
            st.rerun()

        if st.button(
            "Выйти",
            key="sidebar_logout",
            use_container_width=True,
        ):
            st.session_state["_authenticated"] = False
            st.rerun()

        st.caption(
            "Ручное сопровождение ботов. "
            "Торговые команды не отправляются."
        )

    bots = []
    STORE_READY = False
    storage_error = None

    try:
        init_database()
        store_health()
        bots = load_bots()
        STORE_READY = True
    except Exception as exc:
        storage_error = redact(str(exc))

    if STORE_READY:
        notice(
            "Терминал запущен. SQLite Cloud подключена. "
            f"Карточки загружены: {len(bots)}.",
            "success",
        )
    else:
        notice(
            "Не удалось подтвердить подключение к SQLite Cloud. "
            "Карточки не удалены. Сохранение новых изменений "
            "временно заблокировано.\n\n"
            + (storage_error or "Причина не определена."),
            "error",
        )

        if st.button(
            "Показать техническую диагностику",
            key="connection_error_diagnostics",
        ):
            st.session_state["_diagnostics"] = True
            st.rerun()

    flash = st.session_state.pop("_flash", None)

    if flash:
        notice(flash, "success")

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
                value = (
                    sum(
                        bot["lifecycle"] == status
                        for bot in bots
                    )
                    if STORE_READY else "—"
                )
                column.metric(label, value)

            if STORE_READY:
                list_bots(bots, "home", compact=True)
            else:
                notice(
                    "Список не прочитан из базы. "
                    "Это не означает, что карточек нет."
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
                if st.button(
                    "Добавить " + page,
                    key=page + "_add_from_list",
                ):
                    route(
                        page,
                        "Long" if page == "DCA" else "Neutral",
                    )

                if STORE_READY:
                    list_bots(
                        [
                            bot for bot in bots
                            if bot["strategy"] == page
                        ],
                        page,
                    )
                else:
                    notice(
                        "Список станет доступен после "
                        "восстановления подключения к базе."
                    )

        elif page == "Открытая позиция":
            st.title("Контроль позиций")

            if STORE_READY:
                list_bots(bots, "positions")
            else:
                notice(
                    "Не удалось прочитать карточки позиций."
                )

        elif page == "Журнал":
            st.title("Журнал решений")

            if STORE_READY:
                frame = load_events()

                if frame.empty:
                    notice("Журнал пока пуст.")
                else:
                    st.caption(
                        "До 1000 последних событий. "
                        "Полный журнал — в JSON-копии."
                    )
                    table(frame)

                    st.download_button(
                        "Скачать журнал CSV",
                        data=frame.to_csv(
                            index=False
                        ).encode("utf-8-sig"),
                        file_name="journal.csv",
                        mime="text/csv",
                        key="journal_download",
                    )
            else:
                notice(
                    "Журнал временно недоступен: "
                    "подключение к базе не подтверждено."
                )

            st.caption(
                "Повторные снимки PnL одной позиции "
                "не суммируются как прибыль."
            )

        else:
            settings_page(bots)

    except ValueError as exc:
        notice(redact(str(exc)), "error")
    except Exception as exc:
        notice(
            "Действие не подтверждено: "
            + type(exc).__name__
            + ". После ошибки записи обнови список "
            "перед повтором. Ключи не публикуй.",
            "error",
        )


main()
