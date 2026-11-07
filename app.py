import os
import json
import math
import time
import uuid
import hmac
import sqlite3
from datetime import datetime, timezone
from contextlib import contextmanager
from urllib.request import Request, urlopen
from urllib.parse import urlencode

import pandas as pd
import streamlit as st


# =========================================================
# КОНФИГУРАЦИЯ
# =========================================================

st.set_page_config(
    page_title="OKX Terminal",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

API = "https://www.okx.com/api/v5"

PAGES = [
    "Главная",
    "Сканер",
    "Мои боты",
    "DCA",
    "Grid",
    "Журнал",
    "Настройки",
]

COINS = [
    "BTC", "ETH", "SOL", "BNB", "XRP",
    "DOGE", "ADA", "AVAX", "LINK", "DOT",
    "TON", "TRX", "LTC", "NEAR", "APT",
    "ARB", "OP", "SUI", "PEPE", "INJ",
]


def secret(name, default=""):
    try:
        return st.secrets.get(name, os.getenv(name, default))
    except Exception:
        return os.getenv(name, default)


DATABASE_URL = str(secret("DATABASE_URL")).strip()
SQLITE_PATH = str(secret("SQLITE_PATH", "bots.sqlite3"))


def now():
    return datetime.now(timezone.utc).isoformat()


def num(value, default=0.0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (ValueError, TypeError):
        return default


def fmt(value, digits=2):
    if value is None:
        return "Нет данных"
    return f"{value:,.{digits}f}"


def hours_since(value):
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(
            0.0,
            (datetime.now(timezone.utc) - dt).total_seconds() / 3600,
        )
    except (ValueError, TypeError):
        return float("inf")


def sign(direction):
    if direction == "Long":
        return 1
    if direction == "Short":
        return -1
    return 0


# =========================================================
# ДИЗАЙН
# =========================================================

def apply_design():
    st.markdown(
        """
        <style>
        :root {
            --bg: #080d16;
            --panel: #111b2b;
            --border: #28364c;
            --text: #e8edf7;
            --muted: #a8b5ca;
            --green: #65e9b0;
            --red: #ff8da5;
            --yellow: #ffe097;
        }

        .stApp {
            background:
                radial-gradient(
                    ellipse at top left,
                    rgba(22, 78, 83, .35),
                    transparent 48%
                ),
                radial-gradient(
                    ellipse at top right,
                    rgba(56, 39, 101, .30),
                    transparent 45%
                ),
                var(--bg);
            color: var(--text);
        }

        .block-container {
            max-width: 1400px;
            padding-top: 2rem;
            padding-bottom: 3rem;
        }

        h1, h2, h3 {
            letter-spacing: -.035em;
        }

        [data-testid="stSidebar"] {
            background: #0c1321;
            border-right: 1px solid var(--border);
        }

        [data-testid="stMetric"] {
            background: linear-gradient(135deg, #142235, #101827);
            border: 1px solid var(--border);
            border-radius: 18px;
            padding: 18px;
        }

        [data-testid="stMetricValue"] {
            font-size: clamp(1.2rem, 3vw, 2rem);
        }

        .hero {
            background:
                radial-gradient(
                    ellipse at top left,
                    rgba(37, 123, 102, .25),
                    transparent 60%
                ),
                linear-gradient(120deg, #102831, #181c35);
            border: 1px solid #345163;
            border-radius: 26px;
            padding: 30px;
            margin-bottom: 22px;
            box-shadow: 0 20px 70px rgba(0, 0, 0, .25);
        }

        .hero-label {
            color: #77dfbd;
            font-size: .8rem;
            letter-spacing: .16em;
            font-weight: 700;
        }

        .hero h1 {
            font-size: clamp(2rem, 5vw, 3.5rem);
            line-height: 1.08;
            margin: 12px 0;
        }

        .hero p {
            color: #b8c5d9;
            line-height: 1.6;
            max-width: 800px;
        }

        .stButton button,
        .stFormSubmitButton button,
        .stDownloadButton button {
            border-radius: 12px;
            min-height: 46px;
            font-weight: 700;
        }

        .stButton button:hover,
        .stFormSubmitButton button:hover {
            border-color: #65e9b0;
        }

        .st-key-home_long button {
            color: #84f0bd;
            background: #143a31;
            border: 1px solid #347e64;
        }

        .st-key-home_short button {
            color: #ffabc0;
            background: #40212d;
            border: 1px solid #8b4059;
        }

        .st-key-home_neutral button {
            color: #ffe097;
            background: #37321e;
            border: 1px solid #84743c;
        }

        [data-testid="stExpander"] {
            border-radius: 14px;
            border-color: var(--border);
        }

        @media(max-width: 640px) {
            .block-container {
                padding: 1rem;
            }

            .hero {
                padding: 21px;
                border-radius: 20px;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# =========================================================
# ХРАНИЛИЩЕ
# =========================================================

@contextmanager
def db():
    if DATABASE_URL:
        try:
            import psycopg2
        except ImportError as exc:
            raise RuntimeError(
                "Для внешней базы установите psycopg2-binary "
                "через requirements.txt."
            ) from exc

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


def sql(connection, query, params=()):
    cursor = connection.cursor()

    if DATABASE_URL:
        query = query.replace("?", "%s")

    cursor.execute(query, params)
    return cursor


def init_db():
    with db() as connection:
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


def add_event(connection, bot_id, title, details):
    sql(
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
    with db() as connection:
        rows = sql(
            connection,
            "SELECT document, revision FROM terminal_bots",
        ).fetchall()

    result = []

    for document, revision in rows:
        bot = json.loads(document)
        bot["_revision"] = revision
        result.append(bot)

    return sorted(
        result,
        key=lambda item: item.get("updated_at", ""),
        reverse=True,
    )


def save_bot(bot, event_title, event_details):
    document = dict(bot)
    revision = document.pop("_revision", None)
    document["updated_at"] = now()

    payload = json.dumps(
        document,
        ensure_ascii=False,
        allow_nan=False,
    )

    with db() as connection:
        if revision is None:
            sql(
                connection,
                """
                INSERT INTO terminal_bots
                (id, document, revision)
                VALUES (?, ?, ?)
                """,
                (document["id"], payload, 1),
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
                    payload,
                    document["id"],
                    revision,
                ),
            )

            if cursor.rowcount != 1:
                raise ValueError(
                    "Карточка изменилась в другой вкладке. "
                    "Обновите страницу перед сохранением."
                )

        add_event(
            connection,
            document["id"],
            event_title,
            event_details,
        )


def load_events():
    with db() as connection:
        rows = sql(
            connection,
            """
            SELECT bot_id, created_at, title, details
            FROM terminal_events
            ORDER BY created_at DESC
            LIMIT 2000
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


def normalize_import(raw):
    if not isinstance(raw, dict):
        raise ValueError("Неверный формат карточки.")

    document = dict(raw)

    for field in ("settings", "position"):
        value = document.get(field, {})

        if isinstance(value, str):
            value = json.loads(value)

        if not isinstance(value, dict):
            raise ValueError(
                f"Поле {field} должно быть объектом."
            )

        document[field] = value

    strategy = document.get("strategy")
    direction = document.get("direction")
    coin = str(document.get("coin", "")).strip().upper()

    if strategy not in ("DCA", "Grid"):
        raise ValueError("Неизвестная стратегия.")

    if direction not in ("Long", "Short", "Neutral"):
        raise ValueError("Неизвестное направление.")

    if strategy == "DCA" and direction == "Neutral":
        raise ValueError("Для DCA нужно Long или Short.")

    if not coin or not coin.isalnum():
        raise ValueError("Неверная монета.")

    document.pop("_revision", None)

    market = str(document.get("market", "SWAP"))
    document["market"] = (
        "SWAP"
        if "SWAP" in market or "Фьючерсы" in market
        else "SPOT"
    )

    document["coin"] = coin
    document["name"] = str(
        document.get("name", f"{coin} {strategy}")
    ).strip()

    document["lifecycle"] = "Черновик"
    document["position"]["last_check"] = ""
    document.setdefault("created_at", now())
    document.setdefault("decision", "")

    settings = document["settings"]

    settings.setdefault("leverage", 1.0)
    settings.setdefault("stale_hours", 6.0)
    settings.setdefault("liq_warn", 10.0)
    settings.setdefault("stop_price", 0.0)
    settings.setdefault("max_loss", 0.0)

    settings.setdefault(
        "base_margin",
        document["position"].get("base_margin", 0.0),
    )

    settings.setdefault(
        "total_budget",
        num(settings.get("base_margin"))
        + num(settings.get("reserve")),
    )

    settings.setdefault(
        "first_so",
        settings.get("base_amount", 10.0),
    )

    return document


def import_documents(raw_documents, journal=None):
    if not isinstance(raw_documents, list):
        raise ValueError("В копии отсутствует список bots.")

    if len(raw_documents) > 1000:
        raise ValueError("Слишком много карточек в копии.")

    prepared = []

    for raw in raw_documents:
        document = normalize_import(raw)
        document["id"] = str(uuid.uuid4())
        document["updated_at"] = now()

        if journal:
            document["imported_journal"] = journal

        prepared.append(document)

    with db() as connection:
        for document in prepared:
            sql(
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
                "Добавлен черновик. Требуется новая сверка.",
            )

    return len(prepared)


def import_legacy_sqlite():
    if not os.path.isfile(SQLITE_PATH):
        return 0

    old = sqlite3.connect(SQLITE_PATH)

    try:
        old.row_factory = sqlite3.Row

        exists = old.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'bots'
            """
        ).fetchone()

        if not exists:
            return 0

        rows = [
            dict(row)
            for row in old.execute("SELECT * FROM bots")
        ]
    finally:
        old.close()

    return import_documents(rows)


# =========================================================
# ПУБЛИЧНЫЕ ДАННЫЕ OKX
# =========================================================

def instrument(coin, market):
    suffix = "-SWAP" if market == "SWAP" else ""
    return f"{coin}-USDT{suffix}"


def okx_get(path, params):
    url = API + path + "?" + urlencode(params)

    request = Request(
        url,
        headers={"User-Agent": "OKX-Terminal"},
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
    symbol = instrument(coin, market)

    rows = okx_get(
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

    price = num(row.get("last"))
    timestamp = num(row.get("ts")) / 1000

    if price <= 0:
        raise ValueError("Нет корректной рыночной цены.")

    if timestamp <= 0 or time.time() - timestamp > 180:
        raise ValueError("Рыночная цена устарела.")

    return {
        "price": price,
        "timestamp": timestamp,
        "symbol": symbol,
    }


def safe_price(bot):
    try:
        return get_quote(
            bot["coin"],
            bot["market"],
        )["price"]
    except Exception:
        return None


@st.cache_data(ttl=300, show_spinner=False)
def get_candles(coin, market, days):
    symbol = instrument(coin, market)

    cutoff = int(
        (time.time() - days * 86400) * 1000
    )

    collected = {}
    after = None
    previous_oldest = None

    for _ in range(90):
        params = {
            "instId": symbol,
            "bar": "1H",
            "limit": "100",
        }

        if after is not None:
            params["after"] = str(after)

        batch = okx_get(
            "/market/history-candles",
            params,
        )

        if not batch:
            break

        oldest = min(int(row[0]) for row in batch)

        for row in batch:
            if (
                len(row) >= 9
                and row[8] == "1"
                and int(row[0]) >= cutoff
            ):
                collected[int(row[0])] = [
                    int(row[0]),
                    float(row[1]),
                    float(row[2]),
                    float(row[3]),
                    float(row[4]),
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
            "Недостаточно закрытых часовых свечей."
        )

    frame = pd.DataFrame(
        sorted(collected.values()),
        columns=[
            "timestamp",
            "open",
            "high",
            "low",
            "close",
        ],
    )

    frame["time"] = pd.to_datetime(
        frame["timestamp"],
        unit="ms",
        utc=True,
    )

    return frame


# =========================================================
# DCA: ПЛАН И СРЕДНЯЯ
# =========================================================

def dca_levels(settings, direction):
    entry = num(settings.get("entry"))
    step = num(settings.get("step"))
    count = int(settings.get("so_count", 0))
    first = num(settings.get("base_amount"))
    first_so = num(settings.get("first_so"))
    multiplier = num(settings.get("mart"))

    if (
        entry <= 0
        or step <= 0
        or first <= 0
        or first_so <= 0
        or multiplier < 1
        or not 0 <= count <= 30
        or direction not in ("Long", "Short")
    ):
        raise ValueError(
            "Проверьте параметры DCA."
        )

    rows = []
    total_notional = 0.0
    total_quantity = 0.0

    for index in range(count + 1):
        price = entry * (
            1 - sign(direction) * step * index / 100
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
            "Ордер": (
                "Первый вход"
                if index == 0
                else f"СО {index}"
            ),
            "Цена": price,
            "Номинал USDT": amount,
            "Накопленный номинал": total_notional,
            "Модельная средняя": (
                total_notional / total_quantity
            ),
        })

    return rows


# =========================================================
# КОНТРОЛЬ РИСКА И ПЛАНА
# =========================================================

def assess(bot, price):
    settings = bot["settings"]
    position = bot.get("position", {})
    direction = bot["direction"]

    used_margin = (
        num(position.get("base_margin"))
        + num(position.get("added_margin"))
    )

    result = {
        "action": "Проверить на OKX",
        "risk": "Не оценён",
        "reason": "",
        "pnl": None,
        "remaining": max(
            0.0,
            num(settings.get("total_budget")) - used_margin,
        ),
        "tp": None,
        "next_so": None,
        "liq_distance": None,
    }

    if bot.get("lifecycle") != "Работает":
        result["reason"] = (
            "Бот не отмечен как работающий. "
            "Активная позиция не подтверждена."
        )
        return result

    if price is None:
        result["reason"] = (
            "Нет свежей рыночной цены. "
            "Расчёты по нулевой цене отключены."
        )
        return result

    fresh = hours_since(
        position.get("last_check")
    ) <= num(
        settings.get("stale_hours"),
        6.0,
    )

    reasons = []
    high_risk = False
    exit_triggered = False

    average = num(position.get("avg_price"))
    quantity = num(position.get("volume"))
    liquidation = num(position.get("liq_price"))

    if (
        liquidation > 0
        and direction in ("Long", "Short")
    ):
        distance = (
            sign(direction)
            * (price - liquidation)
            / price
            * 100
        )

        result["liq_distance"] = distance

        if distance <= num(
            settings.get("liq_warn"),
            10.0,
        ):
            high_risk = True
            reasons.append(
                "Цена близка к введённой ликвидации "
                "или пересекла её. Срочно сверить позицию. "
                "Это не расчёт биржевого MMR."
            )

    if not fresh:
        reasons.append(
            "Ручная сверка отсутствует или устарела. "
            "Нельзя достоверно рекомендовать продолжение."
        )
    elif direction == "Neutral":
        reasons.append(
            "Neutral: PnL двух сторон и всех Grid-ордеров "
            "не моделируется. Проверьте Total PnL на OKX."
        )
    elif average <= 0 or quantity <= 0:
        reasons.append(
            "Не подтверждены объём позиции "
            "и фактическая средняя цена."
        )
    else:
        result["pnl"] = (
            sign(direction)
            * quantity
            * (price - average)
        )

    loss_limit = num(settings.get("max_loss"))

    if (
        result["pnl"] is not None
        and loss_limit > 0
        and result["pnl"] <= -loss_limit
    ):
        exit_triggered = True
        high_risk = True
        reasons.append(
            "Достигнут лимит убытка открытой позиции. "
            "Комиссии, funding и прошлые циклы "
            "в эту оценку не включены."
        )

    stop = num(settings.get("stop_price"))

    if (
        stop > 0
        and direction in ("Long", "Short")
        and sign(direction) * (price - stop) <= 0
    ):
        exit_triggered = True
        high_risk = True
        reasons.append(
            "Достигнута сигнальная стоп-цена. "
            "Приложение не выставляло стоп-ордер."
        )

    if bot["strategy"] == "DCA":
        levels = dca_levels(settings, direction)

        executed = max(
            0,
            min(
                int(position.get("executed_so", 0)),
                len(levels) - 1,
            ),
        )

        if executed + 1 < len(levels):
            next_price = levels[executed + 1]["Цена"]
            result["next_so"] = next_price

            if (
                sign(direction)
                * (price - next_price)
                <= 0
            ):
                reasons.append(
                    f"Достигнут уровень СО {executed + 1}. "
                    "Проверьте исполнение на OKX "
                    "и обновите объём и среднюю."
                )

        if fresh and average > 0:
            tp = average * (
                1
                + sign(direction)
                * num(settings.get("tp"), 1.5)
                / 100
            )

            result["tp"] = tp

            if sign(direction) * (price - tp) >= 0:
                reasons.append(
                    "Достигнут модельный TP текущего цикла. "
                    "Он задан как движение цены от средней, "
                    "а не ROI на маржу. Проверьте исполнение."
                )

    elif bot["strategy"] == "Grid":
        lower = num(settings.get("lower"))
        upper = num(settings.get("upper"))

        if upper <= lower or lower <= 0:
            reasons.append(
                "Некорректный сохранённый диапазон Grid."
            )
        elif price < lower or price > upper:
            reasons.append(
                "Цена вне сохранённого диапазона Grid. "
                "Это не означает, что позиция закрыта. "
                "Проверьте ордера и остаточную позицию."
            )
        elif (
            min(price - lower, upper - price)
            / (upper - lower)
            <= 0.10
        ):
            reasons.append(
                "Цена в крайних 10% диапазона Grid. "
                "Проверьте состояние бота."
            )

        target = num(settings.get("target_price"))

        if (
            target > 0
            and direction in ("Long", "Short")
            and sign(direction) * (price - target) >= 0
        ):
            reasons.append(
                "Достигнута заданная целевая цена Grid. "
                "Проверьте правило завершения на OKX."
            )

    if result["remaining"] <= 0:
        reasons.append(
            "Лимит маржи исчерпан. "
            "Дальнейшие добавления будут вне плана."
        )

    if exit_triggered:
        result["action"] = "Выход по плану"
    elif not reasons:
        result["action"] = "Не трогать по плану"

    if high_risk:
        result["risk"] = "Высокий"
    elif reasons:
        result["risk"] = "Требует проверки"
    else:
        result["risk"] = (
            "Контролируемый по введённым данным"
        )

    result["reason"] = (
        "\n\n".join(reasons)
        if reasons
        else (
            "Из проверяемых правил ничего не сработало. "
            "Это не прогноз и не гарантия безопасности."
        )
    )

    return result


# =========================================================
# TELEGRAM
# =========================================================

def telegram_credentials():
    token = str(secret("TELEGRAM_TOKEN"))
    chat_id = str(secret("TELEGRAM_CHAT_ID"))

    try:
        if not token:
            token = str(
                st.secrets["telegram"]["token"]
            )
        if not chat_id:
            chat_id = str(
                st.secrets["telegram"]["chat_id"]
            )
    except Exception:
        pass

    return token, chat_id


def send_telegram(message):
    token, chat_id = telegram_credentials()

    if not token or not chat_id:
        raise ValueError(
            "Настройте TELEGRAM_TOKEN и "
            "TELEGRAM_CHAT_ID в Secrets."
        )

    payload = json.dumps({
        "chat_id": chat_id,
        "text": message[:4000],
    }).encode("utf-8")

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


def make_report(bot, price, state):
    position = bot.get("position", {})

    return (
        f"{bot['name']}\n"
        f"{bot['coin']} · {bot['strategy']} · "
        f"{bot['direction']}\n\n"
        f"Действие: {state['action']}\n"
        f"Риск: {state['risk']}\n\n"
        f"Цена: {fmt(price, 6)}\n"
        f"Открытый PnL, оценка: "
        f"{fmt(state['pnl'])} USDT\n"
        f"Остаток бюджета маржи: "
        f"{fmt(state['remaining'])} USDT\n"
        f"Последняя сверка UTC: "
        f"{position.get('last_check') or 'нет'}\n\n"
        f"{state['reason']}\n\n"
        "Приложение не отправляло торговую команду. "
        "Действия подтверждаются пользователем на OKX."
    )


# =========================================================
# ОГРАНИЧЕННЫЙ МОДЕЛЬНЫЙ БЭКТЕСТ
# =========================================================

def simulate(
    frame,
    settings,
    strategy,
    direction,
    commission,
):
    if strategy == "Grid" and direction != "Long":
        raise ValueError(
            "Grid-бэктест поддерживает "
            "только модель Spot Long."
        )

    capital = num(settings["model_capital"])

    wallet = capital
    quantity = 0.0
    average = 0.0
    cycle_entry = 0.0
    executed_so = 0

    fees = 0.0
    cycles = 0
    equity_curve = []

    peak = capital
    max_drawdown = 0.0

    grid_lots = {}
    grid_levels = []

    if strategy == "Grid":
        lower = settings["lower"]
        upper = settings["upper"]
        intervals = int(settings["grids"])

        grid_levels = [
            lower
            + (upper - lower) * i / intervals
            for i in range(intervals + 1)
        ]

        allocation = (
            capital
            / intervals
            / (1 + commission)
        )

    prices = frame["close"].tolist()

    for index, price in enumerate(prices):
        if strategy == "DCA":
            direction_sign = sign(direction)

            if quantity == 0:
                amount = settings["base_amount"]

                if amount * (1 + commission) > wallet:
                    raise ValueError(
                        "Недостаточно модельного капитала."
                    )

                cycle_entry = price
                executed_so = 0
                average = price
                quantity = amount / price

                entry_fee = amount * commission
                wallet -= entry_fee
                fees += entry_fee

            elif (
                direction_sign
                * (price / average - 1)
                * 100
                >= settings["tp"]
            ):
                exit_fee = (
                    quantity * price * commission
                )

                wallet += (
                    direction_sign
                    * quantity
                    * (price - average)
                    - exit_fee
                )

                fees += exit_fee
                quantity = 0.0
                cycles += 1

            elif (
                executed_so < settings["so_count"]
                and direction_sign
                * (price / cycle_entry - 1)
                * 100
                <= -settings["step"] * (executed_so + 1)
            ):
                amount = (
                    settings["first_so"]
                    * settings["mart"] ** executed_so
                )

                current_equity = (
                    wallet
                    + direction_sign
                    * quantity
                    * (price - average)
                )

                if (
                    quantity * average + amount <= capital
                    and current_equity
                    > amount * commission
                ):
                    added_quantity = amount / price

                    average = (
                        quantity * average + amount
                    ) / (
                        quantity + added_quantity
                    )

                    quantity += added_quantity

                    entry_fee = amount * commission
                    wallet -= entry_fee
                    fees += entry_fee
                    executed_so += 1

            equity = (
                wallet
                + direction_sign
                * quantity
                * (price - average)
            )

        else:
            # Продаём только ранее купленные лоты.
            # Новые покупки не продаются в ту же свечу.
            for level_index in list(grid_lots):
                target = grid_levels[level_index + 1]

                if price >= target:
                    units = grid_lots.pop(level_index)
                    gross = units * price
                    exit_fee = gross * commission

                    wallet += gross - exit_fee
                    fees += exit_fee
                    cycles += 1

            if index > 0:
                previous = prices[index - 1]

                for level_index, level in enumerate(
                    grid_levels[:-1]
                ):
                    required_cash = (
                        allocation * (1 + commission)
                    )

                    if (
                        level_index not in grid_lots
                        and previous > level >= price
                        and wallet >= required_cash
                    ):
                        grid_lots[level_index] = (
                            allocation / price
                        )

                        wallet -= required_cash
                        fees += allocation * commission

            equity = (
                wallet
                + sum(grid_lots.values()) * price
            )

        if equity <= 0:
            raise ValueError(
                "Модельный капитал исчерпан. "
                "Результат не используется."
            )

        peak = max(peak, equity)

        drawdown = (
            (peak - equity) / peak * 100
            if peak > 0
            else 0.0
        )

        max_drawdown = max(
            max_drawdown,
            drawdown,
        )

        equity_curve.append(equity)

    metrics = {
        "Итоговая equity USDT": equity_curve[-1],
        "Результат USDT": equity_curve[-1] - capital,
        "Доходность %": (
            equity_curve[-1] / capital - 1
        ) * 100,
        "Макс. просадка %": max_drawdown,
        "Комиссии USDT": fees,
        "Закрытых циклов / лотов": cycles,
    }

    return metrics, equity_curve


# =========================================================
# НАВИГАЦИЯ И ЭЛЕМЕНТЫ ФОРМ
# =========================================================

def navigate(page, direction=None):
    st.session_state["pending_page"] = page

    if direction:
        st.session_state["preferred_direction"] = direction

    st.rerun()


def numeric(
    label,
    value,
    key,
    minimum=0.0,
    maximum=None,
):
    kwargs = {
        "label": label,
        "value": float(value),
        "min_value": float(minimum),
        "key": key,
    }

    if maximum is not None:
        kwargs["max_value"] = float(maximum)

    return st.number_input(**kwargs)


# =========================================================
# ФОРМА СОЗДАНИЯ DCA / GRID
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

    default_direction = (
        directions.index(preferred)
        if preferred in directions
        else 0
    )

    name = st.text_input(
        "Название плана",
        value=f"Мой {strategy}",
        key=prefix + "_name",
    )

    coin = st.text_input(
        "Монета без USDT",
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
        index=default_direction,
        horizontal=True,
        key=prefix + "_direction_" + preferred,
    )

    if market == "SPOT" and direction != "Long":
        st.warning(
            "В этой версии Spot поддерживается "
            "только для Long."
        )
        return

    leverage = numeric(
        "Плечо — для проверки маржи, "
        "не множитель готового PnL",
        1,
        prefix + "_leverage",
        1,
        100,
    )

    if market == "SPOT" and leverage != 1:
        st.warning(
            "Для Spot установите плечо 1."
        )
        return

    base_margin = numeric(
        "Базовая выделенная маржа / капитал Spot, USDT",
        100,
        prefix + "_base_margin",
        0.01,
    )

    reserve = numeric(
        "Отдельный резерв добавления маржи, USDT",
        50,
        prefix + "_reserve",
    )

    settings = {
        "leverage": leverage,
        "base_margin": base_margin,
        "reserve": reserve,
        "total_budget": base_margin + reserve,
    }

    st.caption(
        f"Лимит выделяемых средств: "
        f"{base_margin + reserve:.2f} USDT. "
        "Добавление маржи не считается прибылью."
    )

    settings["max_loss"] = numeric(
        "Сигнал по убытку открытой позиции, USDT "
        "(0 = отключён)",
        0,
        prefix + "_max_loss",
    )

    settings["stop_price"] = numeric(
        "Сигнальная стоп-цена "
        "(0 = нет; ордер на OKX не создаётся)",
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
        "Предупреждение при расстоянии "
        "до введённой ликвидации, %",
        10,
        prefix + "_liq_warn",
        0.1,
        100,
    )

    valid = bool(name.strip()) and coin.isalnum()

    if strategy == "DCA":
        settings["entry"] = numeric(
            "Плановая цена первого входа",
            100,
            prefix + "_entry",
            0.00000001,
        )

        settings["tp"] = numeric(
            "TP: движение цены от средней, % "
            "(не ROI маржи)",
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
            "Количество страховочных ордеров",
            min_value=0,
            max_value=30,
            value=4,
            step=1,
            key=prefix + "_so_count",
        )

        settings["base_amount"] = numeric(
            "Номинал первого ордера, USDT — не маржа",
            10,
            prefix + "_base_amount",
            0.01,
        )

        settings["first_so"] = numeric(
            "Номинал первого СО, USDT",
            10,
            prefix + "_first_so",
            0.01,
        )

        settings["mart"] = numeric(
            "Множитель объёма последующих СО",
            1.2,
            prefix + "_mart",
            1,
            3,
        )

        try:
            levels = dca_levels(
                settings,
                direction,
            )

            st.subheader("План усреднения")

            st.dataframe(
                pd.DataFrame(levels),
                hide_index=True,
                use_container_width=True,
            )

            planned_margin = (
                levels[-1]["Накопленный номинал"]
                / leverage
            )

            st.caption(
                f"Модельная маржа на все ордера: "
                f"{planned_margin:.2f} USDT "
                "без комиссий и биржевого резерва."
            )

            if planned_margin >= base_margin:
                valid = False
                st.error(
                    "Базовой маржи недостаточно "
                    "для всех ордеров с запасом. "
                    "Уменьшите номиналы."
                )

        except ValueError as error:
            valid = False
            st.error(str(error))

    else:
        settings["lower"] = numeric(
            "Нижняя граница — точная цена",
            90,
            prefix + "_lower",
            0.00000001,
        )

        settings["upper"] = numeric(
            "Верхняя граница — точная цена",
            110,
            prefix + "_upper",
            0.00000001,
        )

        settings["grids"] = st.number_input(
            "Количество интервалов "
            "(уровней будет N + 1)",
            min_value=2,
            max_value=200,
            value=10,
            step=1,
            key=prefix + "_grids",
        )

        settings["target_price"] = numeric(
            "Целевая цена завершения "
            "(0 = не задана)",
            0,
            prefix + "_target",
        )

        if settings["upper"] <= settings["lower"]:
            valid = False

            st.error(
                "Верхняя граница должна быть "
                "выше нижней."
            )

        if valid:
            prices = [
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

            st.subheader("Уровни Grid")

            st.line_chart(
                pd.DataFrame({
                    "Цена уровня": prices,
                })
            )

    st.caption(
        "Если стоп и лимит убытка отключены, "
        "выход по убытку заранее не ограничен. "
        "Добавление маржи не устраняет убыток."
    )

    if st.button(
        "Сохранить план",
        type="primary",
        disabled=not valid,
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
                "created_at": now(),
                "decision": "",
            }

            save_bot(
                bot,
                "Создан план",
                "Запуск на OKX ещё не подтверждён.",
            )

            navigate("Мои боты")

        except Exception as error:
            st.error(
                "План не сохранён: "
                + str(error)
            )

    st.divider()

    backtest_panel(
        strategy,
        direction,
        market,
        coin,
        settings,
        valid,
        prefix,
    )


# =========================================================
# СРАВНЕНИЕ АЛЬТЕРНАТИВ
# =========================================================

def backtest_panel(
    strategy,
    direction,
    market,
    coin,
    settings,
    valid,
    prefix,
):
    st.subheader("Бэктест и альтернативы")

    st.caption(
        "Сравнение на одних исторических свечах. "
        "Альтернативы не называются безопасными "
        "или лучшими без оснований."
    )

    days = st.selectbox(
        "Запрошенная история, дней",
        [7, 30, 90],
        key=prefix + "_days",
    )

    commission = numeric(
        "Комиссия за одну сторону, %",
        0.05,
        prefix + "_commission",
        0,
        5,
    ) / 100

    run = st.button(
        "Рассчитать план и две альтернативы",
        disabled=not valid,
        key=prefix + "_run_test",
    )

    if run:
        if settings["leverage"] != 1:
            st.warning(
                "Бэктест доступен только при плече 1x. "
                "Ликвидация и обслуживание маржи "
                "здесь не моделируются."
            )
        elif (
            strategy == "Grid"
            and (
                market != "SPOT"
                or direction != "Long"
            )
        ):
            st.warning(
                "Grid-бэктест доступен только "
                "для модели Spot Long. "
                "Futures Grid не выдаётся "
                "за достоверную симуляцию."
            )
        else:
            try:
                with st.spinner(
                    "Загружаю историю и считаю..."
                ):
                    frame = get_candles(
                        coin,
                        market,
                        days,
                    )

                    gaps = int(
                        (
                            frame["timestamp"]
                            .diff()
                            .dropna()
                            > 3600000
                        ).sum()
                    )

                    if gaps:
                        raise ValueError(
                            "В истории есть пропуски "
                            "более часа. "
                            "Сравнение остановлено."
                        )

                    variants = [
                        (
                            "Исходный",
                            dict(settings),
                        ),
                        (
                            "Альтернатива A",
                            dict(settings),
                        ),
                        (
                            "Альтернатива B",
                            dict(settings),
                        ),
                    ]

                    if strategy == "DCA":
                        variants[1][1]["mart"] = 1.0
                        variants[2][1]["step"] *= 1.5
                    else:
                        middle = (
                            settings["lower"]
                            + settings["upper"]
                        ) / 2

                        half_width = (
                            settings["upper"]
                            - settings["lower"]
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

                    table = []
                    curves = {}

                    for label, variant in variants:
                        variant["model_capital"] = (
                            settings["base_margin"]
                        )

                        if strategy == "DCA":
                            dca_levels(
                                variant,
                                direction,
                            )

                        metrics, curve = simulate(
                            frame,
                            variant,
                            strategy,
                            direction,
                            commission,
                        )

                        table.append({
                            "Вариант": label,
                            **metrics,
                            "Параметры": json.dumps(
                                variant,
                                ensure_ascii=False,
                            ),
                        })

                        curves[label] = curve

                    st.session_state[
                        prefix + "_test_result"
                    ] = {
                        "table": table,
                        "curves": curves,
                        "coverage": (
                            f"{frame['time'].iloc[0]} — "
                            f"{frame['time'].iloc[-1]}"
                        ),
                        "bars": len(frame),
                        "coin": coin,
                        "market": market,
                    }

            except Exception as error:
                st.session_state.pop(
                    prefix + "_test_result",
                    None,
                )

                st.error(
                    "Бэктест не выполнен: "
                    + str(error)
                )

    result = st.session_state.get(
        prefix + "_test_result"
    )

    if result:
        st.caption(
            f"Последний расчёт: "
            f"{result['coin']} · {result['market']}. "
            f"Фактическая история: "
            f"{result['coverage']}. "
            f"Закрытых свечей 1H: {result['bars']}. "
            "После изменения полей пересчитайте."
        )

        st.dataframe(
            pd.DataFrame(result["table"]),
            hide_index=True,
            use_container_width=True,
        )

        st.line_chart(
            pd.DataFrame(result["curves"])
        )

        st.warning(
            "Ограничения: исполнения по закрытиям "
            "часовых свечей; без funding, "
            "проскальзывания, очереди ордеров, "
            "ликвидации и точных правил OKX. "
            "Открытая позиция включена в equity, "
            "но не закрывается в конце принудительно. "
            "DCA — линейная учебная модель, "
            "не точный спотовый кошелёк. "
            "Резерв маржи, сигнальный стоп "
            "и лимит убытка в симуляции "
            "не исполняются."
        )


# =========================================================
# КАРТОЧКИ БОТОВ
# =========================================================

def bot_card(bot):
    identifier = bot["id"]
    settings = bot["settings"]
    position = bot.get("position", {})

    with st.container(border=True):
        st.subheader(bot["name"])

        st.caption(
            f"{bot['coin']} · {bot['market']} · "
            f"{bot['strategy']} · {bot['direction']} · "
            f"{bot['lifecycle']}"
        )

        price = safe_price(bot)
        state = assess(bot, price)

        columns = st.columns(3)

        columns[0].metric(
            "Рыночная цена",
            fmt(price, 6),
        )

        columns[1].metric(
            "Открытый PnL, оценка USDT",
            fmt(state["pnl"]),
        )

        columns[2].metric(
            "Остаток бюджета маржи USDT",
            fmt(state["remaining"]),
        )

        st.write(
            "Действие по плану: "
            + state["action"]
        )

        st.write(
            "Риск: "
            + state["risk"]
        )

        if state["risk"] == "Высокий":
            st.error(state["reason"])
        else:
            st.info(state["reason"])

        st.caption(
            "Последняя сверка UTC: "
            + (
                position.get("last_check")
                or "нет"
            )
        )

        st.caption(
            "Объём вводится в базовой монете, "
            "НЕ в контрактах. "
            "PnL открытой позиции не равен "
            "общему результату бота."
        )

        if state["tp"] is not None:
            st.write(
                "Модельный TP цикла: "
                + fmt(state["tp"], 6)
            )

        if state["next_so"] is not None:
            st.write(
                "Следующий СО по плану: "
                + fmt(state["next_so"], 6)
            )

        if state["liq_distance"] is not None:
            st.write(
                "До введённой ликвидации, %: "
                + fmt(state["liq_distance"])
            )

        if bot.get("decision"):
            st.caption(
                "Последнее решение: "
                + bot["decision"]
            )

        with st.expander(
            "Сохранённые настройки"
        ):
            st.json(settings)

        with st.expander(
            "Сверить позицию / подтвердить запуск"
        ):
            position_form(bot)

        with st.form(
            "decision_" + identifier
        ):
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

            submitted = st.form_submit_button(
                "Записать решение"
            )

            if submitted:
                bot["decision"] = (
                    decision
                    + " · "
                    + now()
                    + " · "
                    + reason
                )

                save_bot(
                    bot,
                    "Решение пользователя",
                    bot["decision"],
                )

                st.rerun()

        st.caption(
            "Решение «Не трогать» не отключает "
            "предупреждения и не отменяет лимиты."
        )

        if st.button(
            "Отправить статус в Telegram",
            key="telegram_" + identifier,
            use_container_width=True,
        ):
            try:
                send_telegram(
                    make_report(
                        bot,
                        price,
                        state,
                    )
                )

                st.success(
                    "Telegram подтвердил отправку."
                )

            except Exception:
                st.error(
                    "Отправка не подтверждена. "
                    "Проверьте Telegram Secrets "
                    "и соединение."
                )

        with st.expander(
            "История этой карточки"
        ):
            events = load_events()

            filtered = events[
                events["Бот ID"] == identifier
            ]

            st.dataframe(
                filtered,
                hide_index=True,
                use_container_width=True,
            )


def position_form(bot):
    identifier = bot["id"]
    settings = bot["settings"]
    position = bot.get("position", {})

    states = [
        "Черновик",
        "Работает",
        "Закрыт",
    ]

    current_state = bot.get(
        "lifecycle",
        "Черновик",
    )

    with st.form(
        "position_" + identifier
    ):
        lifecycle = st.selectbox(
            "Фактическое состояние на OKX",
            states,
            index=states.index(
                current_state
                if current_state in states
                else "Черновик"
            ),
        )

        quantity = numeric(
            "Объём в базовой монете, "
            "например BTC — не контракты",
            num(position.get("volume")),
            identifier + "_quantity",
        )

        average = numeric(
            "Фактическая средняя цена",
            num(position.get("avg_price")),
            identifier + "_average",
        )

        liquidation = numeric(
            "Ликвидационная цена с OKX "
            "(0 = неизвестна)",
            num(position.get("liq_price")),
            identifier + "_liquidation",
        )

        base_margin = numeric(
            "Базовая выделенная маржа",
            num(
                position.get("base_margin"),
                num(settings.get("base_margin")),
            ),
            identifier + "_margin",
        )

        added_margin = numeric(
            "Всего добавлено маржи",
            num(position.get("added_margin")),
            identifier + "_added",
        )

        if bot["strategy"] == "DCA":
            maximum_so = int(
                settings.get("so_count", 0)
            )

            executed_so = st.number_input(
                "Исполнено СО текущего цикла",
                min_value=0,
                max_value=maximum_so,
                value=max(
                    0,
                    min(
                        int(
                            position.get(
                                "executed_so",
                                0,
                            )
                        ),
                        maximum_so,
                    ),
                ),
                step=1,
            )
        else:
            executed_so = 0

        note = st.text_input(
            "Комментарий к сверке"
        )

        confirmed = st.checkbox(
            "Проверил значения на OKX. "
            "Это ручной снимок, "
            "не автоматическая синхронизация."
        )

        submitted = st.form_submit_button(
            "Сохранить сверку"
        )

        if submitted:
            if not confirmed:
                st.error(
                    "Подтвердите ручную сверку."
                )

            elif (
                lifecycle == "Работает"
                and bot["direction"] != "Neutral"
                and (
                    quantity <= 0
                    or average <= 0
                )
            ):
                st.error(
                    "Для работающей направленной позиции "
                    "нужны объём и средняя цена."
                )

            else:
                bot["position"] = {
                    "volume": quantity,
                    "avg_price": average,
                    "liq_price": liquidation,
                    "base_margin": base_margin,
                    "added_margin": added_margin,
                    "executed_so": int(executed_so),
                    "last_check": now(),
                }

                bot["lifecycle"] = lifecycle

                save_bot(
                    bot,
                    "Ручная сверка",
                    note
                    or "Значения введены пользователем.",
                )

                st.rerun()


# =========================================================
# ГЛАВНАЯ
# =========================================================

def home_page(bots):
    st.markdown(
        """
        <div class="hero">
            <div class="hero-label">
                OKX TERMINAL · PERSONAL DESK
            </div>

            <h1>Твой план.<br>Твой контроль.</h1>

            <p>
                Подготовка DCA и Grid, сравнение вариантов,
                уровни усреднения, бюджет маржи
                и понятные решения по твоему плану.
                Без выдуманного баланса
                и обещаний доходности.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    columns = st.columns(3)

    columns[0].metric(
        "Сохранено планов",
        len(bots),
    )

    columns[1].metric(
        "Работают по твоей сверке",
        sum(
            bot["lifecycle"] == "Работает"
            for bot in bots
        ),
    )

    columns[2].metric(
        "Черновики",
        sum(
            bot["lifecycle"] == "Черновик"
            for bot in bots
        ),
    )

    st.subheader("Выбери направление")

    columns = st.columns(3)

    if columns[0].button(
        "ЛОНГ · DCA",
        key="home_long",
        use_container_width=True,
    ):
        navigate("DCA", "Long")

    if columns[1].button(
        "ШОРТ · DCA",
        key="home_short",
        use_container_width=True,
    ):
        navigate("DCA", "Short")

    if columns[2].button(
        "НЕЙТРАЛЬНО · GRID",
        key="home_neutral",
        use_container_width=True,
    ):
        navigate("Grid", "Neutral")

    columns = st.columns(3)

    if columns[0].button(
        "Сканер рынка",
        use_container_width=True,
    ):
        navigate("Сканер")

    if columns[1].button(
        "Контроль моих ботов",
        use_container_width=True,
    ):
        navigate("Мои боты")

    if columns[2].button(
        "Grid Long / Short",
        use_container_width=True,
    ):
        navigate("Grid", "Long")

    st.info(
        "Приложение не отправляет торговые команды. "
        "Цены обновляются при выполнении страницы "
        "и по кнопке. Постоянный фоновый мониторинг "
        "при закрытой вкладке не запущен. "
        "Telegram отправляется по кнопке."
    )

    if bots:
        st.subheader("Последние планы")

        rows = [
            {
                "Название": bot["name"],
                "Монета": bot["coin"],
                "Стратегия": bot["strategy"],
                "Направление": bot["direction"],
                "Состояние": bot["lifecycle"],
            }
            for bot in bots[:10]
        ]

        st.dataframe(
            pd.DataFrame(rows),
            hide_index=True,
            use_container_width=True,
        )


# =========================================================
# СКАНЕР
# =========================================================

def scanner_page():
    st.title("Сканер рынка")

    market = st.radio(
        "Рынок",
        ["SWAP", "SPOT"],
        horizontal=True,
    )

    selected_coins = st.multiselect(
        "Монеты — список, не рейтинг TOP-20",
        COINS,
        default=["BTC", "ETH", "SOL"],
    )

    if st.button(
        "Обновить сканер",
        type="primary",
    ):
        results = []
        errors = []

        with st.spinner(
            "Загружаю рыночные данные..."
        ):
            for coin in selected_coins:
                try:
                    frame = get_candles(
                        coin,
                        market,
                        7,
                    )

                    quote = get_quote(
                        coin,
                        market,
                    )

                    change = (
                        frame["close"].iloc[-1]
                        / frame["close"].iloc[-25]
                        - 1
                    ) * 100

                    volatility = (
                        frame["close"]
                        .pct_change()
                        .dropna()
                        .std()
                        * math.sqrt(24)
                        * 100
                    )

                    results.append({
                        "Монета": coin,
                        "Цена": quote["price"],
                        "Изменение 24H, %": change,
                        "Волатильность 1D, оценка %":
                            volatility,
                        "Контекст": (
                            "Рост за 24H"
                            if change > 0
                            else "Снижение за 24H"
                        ),
                    })

                except Exception:
                    errors.append(coin)

        st.session_state["scanner_result"] = {
            "market": market,
            "rows": results,
            "errors": errors,
            "created_at": now(),
        }

    result = st.session_state.get(
        "scanner_result"
    )

    if result:
        st.caption(
            f"Последний расчёт: "
            f"{result['market']} · "
            f"{result['created_at']}"
        )

        st.dataframe(
            pd.DataFrame(result["rows"]),
            hide_index=True,
            use_container_width=True,
        )

        if result["errors"]:
            st.warning(
                "Не загрузились: "
                + ", ".join(result["errors"])
            )

    st.caption(
        "Контекст описывает прошлое движение. "
        "Это не подтверждённый сигнал "
        "на открытие Long или Short."
    )


# =========================================================
# НАСТРОЙКИ И КОПИИ
# =========================================================

def settings_page(bots):
    st.title("Настройки")

    st.subheader("Telegram")

    st.caption(
        "Данные задаются в Streamlit Secrets, "
        "не в открытом GitHub."
    )

    if st.button(
        "Отправить тест Telegram"
    ):
        try:
            send_telegram(
                "OKX Terminal: соединение подтверждено. "
                "Автоматические сделки не включены."
            )

            st.success(
                "Telegram подтвердил отправку."
            )
        except Exception:
            st.error(
                "Отправка не подтверждена. "
                "Проверьте токен, Chat ID и соединение."
            )

    st.subheader("Резервная копия")

    backup_bots = []

    for bot in bots:
        document = dict(bot)
        document.pop("_revision", None)
        backup_bots.append(document)

    backup = {
        "version": 4,
        "created_at": now(),
        "bots": backup_bots,
        "events": load_events().to_dict(
            "records"
        ),
    }

    st.download_button(
        "Скачать все планы и журнал JSON",
        data=json.dumps(
            backup,
            ensure_ascii=False,
            indent=2,
        ),
        file_name="okx_backup.json",
        mime="application/json",
        use_container_width=True,
    )

    uploaded = st.file_uploader(
        "Восстановить JSON-копию",
        type=["json"],
    )

    confirmed = st.checkbox(
        "Подтверждаю импорт. "
        "Карточки будут добавлены с новыми ID; "
        "существующие не заменяются."
    )

    if st.button(
        "Импортировать JSON",
        disabled=(
            uploaded is None
            or not confirmed
        ),
    ):
        try:
            if uploaded.size > 5_000_000:
                raise ValueError(
                    "Файл больше 5 MB."
                )

            source = json.loads(
                uploaded.getvalue()
            )

            if not isinstance(source, dict):
                raise ValueError(
                    "Неверная структура копии."
                )

            count = import_documents(
                source.get("bots"),
                source.get("events"),
            )

            st.success(
                f"Добавлено карточек: {count}. "
                "Перед контролем проведите сверку."
            )

        except Exception as error:
            st.error(
                "Импорт не выполнен: "
                + str(error)
            )

    st.subheader("Старые карточки SQLite")

    st.caption(
        "Старый файл не удаляется. "
        "Повторный импорт создаст дополнительные копии."
    )

    if st.button(
        "Импортировать старую таблицу bots"
    ):
        try:
            count = import_legacy_sqlite()

            st.success(
                f"Добавлено: {count}. "
                "Проверьте единицы, бюджеты "
                "и фактическую позицию."
            )

        except Exception:
            st.error(
                "Не удалось импортировать старую таблицу. "
                "Используйте JSON-копию, если она есть."
            )

    st.subheader("Пример Streamlit Secrets")

    st.code(
        '''
APP_PASSWORD = "ваш-длинный-пароль"

# Необязательно для локального запуска.
# Для постоянного внешнего хранения:
DATABASE_URL = "postgresql://user:password@host/database?sslmode=require"

# Необязательно, если Telegram не нужен:
TELEGRAM_TOKEN = "токен-бота"
TELEGRAM_CHAT_ID = "chat-id"
'''.strip(),
        language="toml",
    )

    st.warning(
        "Если DATABASE_URL не задан, используется "
        "локальный SQLite. Обновление страницы "
        "не удаляет карточки, но пересоздание "
        "облачного сервера может удалить локальный файл. "
        "Скачивайте копии или подключите внешнюю базу."
    )


# =========================================================
# ВХОД
# =========================================================

def check_login():
    password = str(secret("APP_PASSWORD"))

    if not password:
        st.warning(
            "Вход не защищён. "
            "Задайте APP_PASSWORD в Secrets "
            "или ограничьте доступ к приложению. "
            "Не публикуйте личные позиции "
            "в открытом приложении."
        )
        return

    if st.session_state.get("authenticated"):
        return

    st.title("Вход в личный терминал")

    entered = st.text_input(
        "Пароль",
        type="password",
    )

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
# ЗАПУСК ПРИЛОЖЕНИЯ
# =========================================================

def main():
    apply_design()
    check_login()
    init_db()

    if DATABASE_URL:
        st.caption(
            "Хранилище: внешний PostgreSQL. "
            "При ошибке подключения приложение "
            "не переключается на пустую локальную базу."
        )
    else:
        st.caption(
            "Хранилище: локальный SQLite. "
            "Для постоянного внешнего хранения "
            "настройте DATABASE_URL."
        )

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
        st.caption(
            "Подготовка и контроль DCA / Grid"
        )

        page = st.radio(
            "Раздел",
            PAGES,
            key="navigation",
        )

        st.divider()

        st.caption(
            "Ручной контроль. "
            "Приватные торговые API-ключи "
            "не используются."
        )

        if st.button(
            "Обновить рыночные цены",
            use_container_width=True,
        ):
            get_quote.clear()
            st.rerun()

    bots = load_bots()

    if page == "Главная":
        home_page(bots)

    elif page == "Сканер":
        scanner_page()

    elif page == "Мои боты":
        st.title("Мои боты")

        if not bots:
            st.info(
                "Создайте план в DCA / Grid "
                "или импортируйте копию "
                "в Настройках."
            )

        for bot in bots:
            try:
                bot_card(bot)
            except Exception:
                st.error(
                    "Не удалось обработать карточку "
                    f"«{bot.get('name', '')}». "
                    "Данные не удалены. "
                    "Проверьте сохранённые настройки "
                    "и журнал сервера."
                )

    elif page == "DCA":
        st.title("DCA · Подготовка плана")
        creator("DCA")

    elif page == "Grid":
        st.title("Grid · Подготовка плана")
        creator("Grid")

    elif page == "Журнал":
        st.title("Журнал решений · UTC")

        st.dataframe(
            load_events(),
            hide_index=True,
            use_container_width=True,
        )

        st.caption(
            "Повторные снимки PnL не суммируются: "
            "они могут относиться "
            "к одной и той же позиции."
        )

    elif page == "Настройки":
        settings_page(bots)


try:
    main()

except Exception as error:
    st.error(
        "Операция не завершена: "
        + type(error).__name__
        + "."
    )

    st.info(
        "Проверьте зависимости, подключение к базе "
        "и журнал сервера. "
        "При ошибке внешней базы приложение "
        "не создаёт вместо неё пустое хранилище. "
        "Секреты подключения здесь не отображаются."
    )
