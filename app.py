import os
import json
import math
import time
import uuid
import hmac
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlencode

import pandas as pd
import streamlit as st


# =========================================================
# CONFIG
# =========================================================

st.set_page_config(
    page_title="OKX Control",
    page_icon="📈",
    layout="wide",
)

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

API = "https://www.okx.com/api/v5"


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
        return "—"
    return f"{value:,.{digits}f}"


def direction_sign(direction):
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
    kwargs = {
        "label": label,
        "value": float(value),
        "min_value": float(minimum),
        "key": key,
    }

    if maximum is not None:
        kwargs["max_value"] = float(maximum)

    return st.number_input(**kwargs)


def navigate(page, direction=None):
    st.session_state["pending_page"] = page

    if direction:
        st.session_state["preferred_direction"] = direction

    st.rerun()


# =========================================================
# DESIGN
# =========================================================

def design():
    st.markdown(
        """
<style>
.stApp {
    background: #0b1019;
    color: #e9eef8;
}

.block-container {
    max-width: 1350px;
    padding-top: 1.5rem;
    padding-bottom: 3rem;
}

h1, h2, h3 {
    color: #edf3ff !important;
    letter-spacing: -.025em;
}

[data-testid="stSidebar"] {
    background: #101824;
    border-right: 1px solid #263247;
}

[data-testid="stSidebar"] p,
[data-testid="stSidebar"] label {
    color: #d5deed !important;
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
    color: #aebdd3 !important;
}

[data-testid="stMetricValue"],
[data-testid="stMetricValue"] div {
    color: #f3f7ff !important;
    font-size: clamp(1.2rem, 3vw, 1.9rem);
}

.stButton button,
.stFormSubmitButton button,
.stDownloadButton button {
    border-radius: 11px;
    min-height: 44px;
    font-weight: 700;
}

.st-key-long_home button {
    color: #8ef0bf;
    background: #15372c;
    border: 1px solid #33785d;
}

.st-key-short_home button {
    color: #ffa5b7;
    background: #3c202b;
    border: 1px solid #864052;
}

.st-key-grid_home button {
    color: #ffe39b;
    background: #38311c;
    border: 1px solid #84713a;
}

.desk {
    border: 1px solid #2c4058;
    background: linear-gradient(120deg, #122b31, #151d30);
    border-radius: 18px;
    padding: 20px 24px;
    margin-bottom: 20px;
}

.desk .eyebrow {
    color: #7ddbb9;
    font-size: .75rem;
    letter-spacing: .15em;
    font-weight: 700;
}

.desk .title {
    color: #f1f6ff;
    font-size: clamp(1.6rem, 4vw, 2.3rem);
    font-weight: 800;
    margin-top: 6px;
}

.desk .subtitle {
    color: #b6c4d8;
    margin-top: 7px;
}

[data-testid="stExpander"] {
    border-radius: 12px;
}

@media(max-width: 640px) {
    .block-container {
        padding: 1rem;
    }

    .desk {
        padding: 17px;
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

    if not password:
        return

    if st.session_state.get("authenticated"):
        return

    st.title("OKX Control")

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
# Используется та же terminal_bots, что в предыдущем коде.
# =========================================================

@contextmanager
def database():
    if DB_URL:
        try:
            import psycopg2
        except ImportError as error:
            raise RuntimeError(
                "Добавьте psycopg2-binary "
                "в requirements.txt."
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

        connection.execute(
            "PRAGMA busy_timeout=20000"
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

    if DB_URL:
        statement = statement.replace("?", "%s")

    cursor.execute(statement, parameters)
    return cursor


def initialize_database():
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


def write_event(connection, bot_id, title, details):
    query(
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
        rows = query(
            connection,
            "SELECT document, revision FROM terminal_bots",
        ).fetchall()

    bots = []

    for document, revision in rows:
        bot = json.loads(document)
        bot["_revision"] = revision
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
            query(
                connection,
                """
                INSERT INTO terminal_bots
                (id, document, revision)
                VALUES (?, ?, ?)
                """,
                (
                    document["id"],
                    payload,
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
                    payload,
                    document["id"],
                    revision,
                ),
            )

            if cursor.rowcount != 1:
                raise ValueError(
                    "Карточка изменена в другой вкладке. "
                    "Обновите страницу."
                )

        write_event(
            connection,
            document["id"],
            title,
            details,
        )


def events():
    with database() as connection:
        rows = query(
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


# =========================================================
# OKX
# =========================================================

def instrument(coin, market):
    return (
        f"{coin}-USDT-SWAP"
        if market == "SWAP"
        else f"{coin}-USDT"
    )


def api_get(path, parameters):
    request = Request(
        API + path + "?" + urlencode(parameters),
        headers={"User-Agent": "OKX-Control"},
    )

    with urlopen(request, timeout=15) as response:
        payload = json.load(response)

    if payload.get("code") != "0":
        raise ValueError(
            "OKX не подтвердил запрос."
        )

    return payload.get("data", [])


@st.cache_data(ttl=20, show_spinner=False)
def quote(coin, market):
    symbol = instrument(coin, market)

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
        raise ValueError(
            "Инструмент не найден."
        )

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

    return price


@st.cache_data(ttl=180, show_spinner=False)
def daily_candles(coin, market):
    raw = api_get(
        "/market/candles",
        {
            "instId": instrument(coin, market),
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
            "Мало закрытых дневных свечей."
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
def hourly_history(coin, market, days):
    cutoff = int(
        (time.time() - days * 86400) * 1000
    )

    collected = {}
    after = None
    previous = None

    for _ in range(90):
        parameters = {
            "instId": instrument(coin, market),
            "bar": "1H",
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
        frame["ts"].diff().dropna() > 3600000
    ).any():
        raise ValueError(
            "Есть пропуски в часовой истории."
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


def calculate_indicators(frame):
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

    smoothed_plus = wilder(plus_dm)
    smoothed_minus = wilder(minus_dm)

    plus_di = 100 * smoothed_plus / atr
    minus_di = 100 * smoothed_minus / atr

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
            & smoothed_plus.eq(0)
            & smoothed_minus.eq(0)
        )
    )

    dx.loc[flat] = 0

    frame["RSI"] = rsi
    frame["ADX"] = wilder(dx)
    frame["ATR %"] = atr / frame["close"] * 100
    frame["+DI"] = plus_di
    frame["-DI"] = minus_di

    return frame


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
        raise ValueError(
            "Некорректные параметры DCA."
        )

    rows = []
    total = 0.0
    quantity = 0.0

    for index in range(count + 1):
        price = entry * (
            1
            - direction_sign(direction)
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

        total += amount
        quantity += amount / price

        rows.append({
            "Ордер": "Вход" if index == 0 else f"СО {index}",
            "Цена": price,
            "Номинал USDT": amount,
            "Всего номинал": total,
            "Средняя модельная": total / quantity,
        })

    return rows


# =========================================================
# BOT ASSESSMENT
# =========================================================

def assess(bot, price):
    settings = bot["settings"]
    position = bot.get("position", {})
    direction = bot["direction"]

    allocated = (
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
            number(settings.get("total_budget")) - allocated,
        ),
        "tp": None,
        "next_so": None,
        "liquidation_distance": None,
    }

    if bot.get("lifecycle") != "Работает":
        state["reason"] = (
            "Активная позиция не подтверждена. "
            "Открой сверку, чтобы отметить запуск."
        )
        return state

    if price is None:
        state["reason"] = (
            "Свежая рыночная цена недоступна. "
            "Не используем ноль вместо цены."
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

    if (
        liquidation > 0
        and direction in ("Long", "Short")
    ):
        distance = (
            direction_sign(direction)
            * (price - liquidation)
            / price
            * 100
        )

        state["liquidation_distance"] = distance

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
            "Ручная сверка устарела или отсутствует."
        )
    elif direction == "Neutral":
        reasons.append(
            "Neutral: общий PnL Grid здесь "
            "не моделируется. Проверь Total PnL на OKX."
        )
    elif average <= 0 or quantity <= 0:
        reasons.append(
            "Нужны фактические объём и средняя цена."
        )
    else:
        state["pnl"] = (
            direction_sign(direction)
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
        and direction_sign(direction) * (price - stop) <= 0
    ):
        high_risk = True
        exit_triggered = True
        reasons.append(
            "Достигнута сигнальная стоп-цена. "
            "Биржевой стоп-ордер приложение не выставляло."
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
                direction_sign(direction)
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
                + direction_sign(direction)
                * number(settings.get("tp"), 1.5)
                / 100
            )

            if (
                direction_sign(direction)
                * (price - state["tp"])
                >= 0
            ):
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
                "Некорректный диапазон Grid."
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
            and direction_sign(direction) * (price - target) >= 0
        ):
            reasons.append(
                "Достигнута целевая цена Grid. "
                "Проверь план завершения."
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
        state["risk"] = "Без срабатывания проверяемых правил"

    state["reason"] = (
        "\n\n".join(reasons)
        if reasons
        else (
            "Проверяемые условия не сработали. "
            "Это не прогноз и не гарантия безопасности."
        )
    )

    return state


def safe_assessment(bot):
    try:
        price = quote(bot["coin"], bot["market"])
    except Exception:
        price = None

    try:
        state = assess(bot, price)
    except Exception:
        state = {
            "action": "Проверить настройки",
            "risk": "Не оценён",
            "reason": "Проверь сохранённые параметры карточки.",
            "pnl": None,
            "remaining": None,
            "tp": None,
            "next_so": None,
            "liquidation_distance": None,
        }

    return price, state


# =========================================================
# TELEGRAM
# =========================================================

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

    if not token or not chat:
        raise ValueError(
            "Настрой Telegram в Secrets."
        )

    payload = json.dumps({
        "chat_id": chat,
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


def report(bot, price, state):
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
# SCANNER
# =========================================================

def scanner():
    st.title("Сканер")

    market = st.radio(
        "Рынок",
        ["SWAP", "SPOT"],
        horizontal=True,
        key="scan_market",
    )

    coins = st.multiselect(
        "Монеты",
        COINS,
        default=["BTC", "ETH", "SOL", "XRP", "DOGE"],
    )

    st.caption(
        "Сценарии по исходным правилам RSI/ADX. "
        "Закрытые дневные свечи, не прогноз."
    )

    if st.button(
        "Сканировать",
        type="primary",
        use_container_width=True,
    ):
        rows = []
        errors = []
        progress = st.progress(0.0)

        for index, coin in enumerate(coins):
            try:
                frame = calculate_indicators(
                    daily_candles(coin, market)
                )

                last = frame.iloc[-1]
                price = quote(coin, market)

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
                        scenario = "ЛОНГ"
                        bot_type = "DCA Long"
                        reason = "ADX > 25, RSI < 40"
                    elif rsi > 50:
                        scenario = "ЖДАТЬ"
                        bot_type = "Пауза"
                        reason = "ADX > 25, RSI > 50"
                    else:
                        scenario = "ШОРТ"
                        bot_type = "DCA Short"
                        reason = "ADX > 25, RSI 40–50"
                else:
                    scenario = "GRID"
                    bot_type = "Grid"
                    reason = "ADX ≤ 25"

                flags = []

                if atr > 3:
                    flags.append("ATR > 3%")

                if rsi < 30 or rsi > 70:
                    flags.append("Крайнее значение RSI")

                rows.append({
                    "Монета": coin,
                    "Цена": price,
                    "Сценарий": scenario,
                    "Бот": bot_type,
                    "RSI": rsi,
                    "ADX": adx,
                    "ATR %": atr,
                    "Причина": reason,
                    "Флаги риска": (
                        "; ".join(flags)
                        or "Пороговые флаги не сработали"
                    ),
                })

            except Exception:
                errors.append(coin)

            progress.progress(
                (index + 1) / max(1, len(coins))
            )

        st.session_state["scan_result"] = {
            "market": market,
            "rows": rows,
            "errors": errors,
            "time": now(),
        }

    result = st.session_state.get("scan_result")

    if not result:
        return

    st.caption(
        f"Последний расчёт: {result['market']} · "
        f"{result['time']}"
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

    for column, label in zip(
        columns,
        ["ЛОНГ", "ШОРТ", "GRID", "ЖДАТЬ"],
    ):
        column.metric(
            label,
            int(frame["Сценарий"].eq(label).sum()),
        )

    selected_filter = st.radio(
        "Фильтр",
        ["Все", "ЛОНГ", "ШОРТ", "GRID", "ЖДАТЬ"],
        horizontal=True,
    )

    visible = (
        frame
        if selected_filter == "Все"
        else frame[frame["Сценарий"] == selected_filter]
    )

    st.dataframe(
        visible,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Цена": st.column_config.NumberColumn(
                format="%.6f"
            ),
            "RSI": st.column_config.NumberColumn(
                format="%.1f"
            ),
            "ADX": st.column_config.NumberColumn(
                format="%.1f"
            ),
            "ATR %": st.column_config.NumberColumn(
                format="%.2f"
            ),
        },
    )

    if not visible.empty:
        coin = st.selectbox(
            "Подготовить план для",
            visible["Монета"].tolist(),
        )

        row = frame[frame["Монета"] == coin].iloc[0]

        st.info(
            f"{row['Сценарий']}: {row['Причина']}. "
            f"{row['Флаги риска']}."
        )

        columns = st.columns(3)

        def open_creator(strategy, direction):
            prefix = strategy.lower()

            st.session_state[prefix + "_coin"] = coin
            st.session_state[prefix + "_market"] = result["market"]

            if strategy == "DCA":
                st.session_state[prefix + "_entry"] = float(
                    row["Цена"]
                )

            navigate(strategy, direction)

        if columns[0].button("DCA Long"):
            open_creator("DCA", "Long")

        if columns[1].button(
            "DCA Short",
            disabled=result["market"] == "SPOT",
        ):
            open_creator("DCA", "Short")

        if columns[2].button("Grid"):
            open_creator(
                "Grid",
                "Neutral" if result["market"] == "SWAP" else "Long",
            )

    st.warning(
        "Классификация сохранена из исходных правил. "
        "Её прибыльность не подтверждена. "
        "Отсутствие флагов не означает низкий риск."
    )


# =========================================================
# LIMITED BACKTEST
# =========================================================

def simulate(frame, settings, strategy, direction, fee):
    capital = settings["base_margin"]
    wallet = capital

    quantity = 0.0
    average = 0.0
    first_entry = 0.0
    executed = 0

    fees = 0.0
    cycles = 0
    curve = []
    peak = capital
    drawdown = 0.0

    lots = {}
    prices = frame["close"].tolist()

    if strategy == "Grid":
        count = int(settings["grids"])

        levels = [
            settings["lower"]
            + (
                settings["upper"] - settings["lower"]
            ) * i / count
            for i in range(count + 1)
        ]

        allocation = capital / count / (1 + fee)

    for index, price in enumerate(prices):
        if strategy == "DCA":
            side = direction_sign(direction)

            if quantity == 0:
                amount = settings["base_amount"]

                if amount * (1 + fee) > wallet:
                    raise ValueError(
                        "Недостаточно модельного капитала."
                    )

                quantity = amount / price
                average = price
                first_entry = price
                executed = 0

                wallet -= amount * fee
                fees += amount * fee

            elif (
                side * (price / average - 1) * 100
                >= settings["tp"]
            ):
                close_fee = quantity * price * fee

                wallet += (
                    side * quantity * (price - average)
                    - close_fee
                )

                fees += close_fee
                quantity = 0
                cycles += 1

            elif (
                executed < settings["so_count"]
                and side * (price / first_entry - 1) * 100
                <= -settings["step"] * (executed + 1)
            ):
                amount = (
                    settings["first_so"]
                    * settings["mart"] ** executed
                )

                equity_before = (
                    wallet
                    + side * quantity * (price - average)
                )

                if (
                    quantity * average + amount <= capital
                    and equity_before > amount * fee
                ):
                    new_quantity = amount / price

                    average = (
                        quantity * average + amount
                    ) / (
                        quantity + new_quantity
                    )

                    quantity += new_quantity
                    wallet -= amount * fee
                    fees += amount * fee
                    executed += 1

            equity = (
                wallet
                + side * quantity * (price - average)
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
        "Доходность %": (curve[-1] / capital - 1) * 100,
        "Просадка %": drawdown,
        "Комиссии USDT": fees,
        "Циклов / лотов": cycles,
    }, curve


def alternatives_panel(strategy, direction, coin, market, settings, valid):
    prefix = strategy.lower()

    st.subheader("Альтернативы и исторический тест")

    days = st.selectbox(
        "История, дней",
        [7, 30, 90],
        key=prefix + "_days",
    )

    fee = numeric(
        "Комиссия за сторону, %",
        0.05,
        prefix + "_fee",
        0,
        5,
    ) / 100

    variants = [
        ("Исходный", dict(settings)),
        ("Альтернатива A", dict(settings)),
        ("Альтернатива B", dict(settings)),
    ]

    if strategy == "DCA":
        variants[1][1]["mart"] = 1.0
        variants[2][1]["step"] *= 1.5
    else:
        middle = (settings["lower"] + settings["upper"]) / 2
        width = (settings["upper"] - settings["lower"]) / 2

        variants[1][1]["lower"] = max(
            0.00000001,
            middle - width * 1.5,
        )
        variants[1][1]["upper"] = middle + width * 1.5
        variants[2][1]["grids"] = max(
            2,
            settings["grids"] // 2,
        )

    st.dataframe(
        pd.DataFrame([
            {
                "Вариант": label,
                "Параметры": json.dumps(
                    parameters,
                    ensure_ascii=False,
                ),
            }
            for label, parameters in variants
        ]),
        hide_index=True,
        use_container_width=True,
    )

    if st.button(
        "Сравнить на истории",
        disabled=not valid,
        key=prefix + "_test",
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
                "Историческая модель доступна "
                "при плече 1x. "
                "Grid — только Spot Long. "
                "Futures Grid здесь не симулируется."
            )
        else:
            try:
                with st.spinner("Считаю историю..."):
                    frame = hourly_history(
                        coin,
                        market,
                        days,
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

                    st.session_state[prefix + "_backtest"] = {
                        "rows": rows,
                        "curves": curves,
                        "description": (
                            f"{coin} · {market} · "
                            f"{frame['time'].iloc[0]} — "
                            f"{frame['time'].iloc[-1]} · "
                            f"{len(frame)} свечей 1H"
                        ),
                    }

            except Exception as error:
                st.session_state.pop(
                    prefix + "_backtest",
                    None,
                )
                st.error(str(error))

    result = st.session_state.get(prefix + "_backtest")

    if result:
        st.caption(
            "Последний запуск: "
            + result["description"]
            + ". После изменения полей пересчитай."
        )

        st.dataframe(
            pd.DataFrame(result["rows"]),
            hide_index=True,
            use_container_width=True,
        )

        st.line_chart(
            pd.DataFrame(result["curves"])
        )

    st.caption(
        "Модель по закрытиям 1H. Без funding, "
        "проскальзывания, ликвидации, очереди ордеров "
        "и точных правил OKX. DCA — линейная модель 1x, "
        "не точный спотовый кошелёк. "
        "Открытая позиция включена в equity. "
        "Сигнальные стопы, лимит убытка "
        "и добавление резервной маржи "
        "в бэктесте не исполняются."
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
            "Для Spot в этой версии поддерживается Long."
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
        "Номинал ордеров и выделенная маржа "
        "учитываются отдельно."
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
                0,
                30,
                4,
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
                "Множитель следующих СО",
                1.2,
                prefix + "_mart",
                1,
                3,
            )

        try:
            plan = dca_plan(settings, direction)

            st.dataframe(
                pd.DataFrame(plan),
                hide_index=True,
                use_container_width=True,
            )

            required = plan[-1]["Всего номинал"] / leverage

            st.caption(
                f"Модельная маржа под все ордера: "
                f"{required:.2f} USDT "
                "без комиссий и биржевого резерва."
            )

            if required >= margin:
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
                "Нижняя граница — цена",
                90,
                prefix + "_lower",
                0.00000001,
            )

        with columns[1]:
            settings["upper"] = numeric(
                "Верхняя граница — цена",
                110,
                prefix + "_upper",
                0.00000001,
            )

        settings["grids"] = st.number_input(
            "Количество интервалов (уровней N + 1)",
            2,
            200,
            10,
            key=prefix + "_grids",
        )

        settings["target_price"] = numeric(
            "Целевая цена завершения, 0 = нет",
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
                ) * i / settings["grids"]
                for i in range(settings["grids"] + 1)
            ]

            st.line_chart(
                pd.DataFrame({"Уровни": levels})
            )

    with st.expander("Правила риска и выхода", expanded=True):
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
            "Если стоп и лимит убытка отключены, "
            "выход по убытку заранее не ограничен. "
            "Добавление маржи не устраняет убыток."
        )

    if st.button(
        "Сохранить и открыть карточку",
        type="primary",
        disabled=not valid,
        use_container_width=True,
        key=prefix + "_save",
    ):
        try:
            quote(coin, market)

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

            navigate("Мои боты")

        except Exception as error:
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


# =========================================================
# POSITION FORM
# =========================================================

def position_form(bot):
    identifier = bot["id"]
    settings = bot["settings"]
    position = bot.get("position", {})

    states = ["Черновик", "Работает", "Закрыт"]
    lifecycle = bot.get("lifecycle", "Черновик")

    with st.form("position_" + identifier):
        state = st.selectbox(
            "Фактическое состояние на OKX",
            states,
            index=states.index(
                lifecycle if lifecycle in states else "Черновик"
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
            identifier + "_base_margin",
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
                0,
                maximum,
                max(
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
                state == "Работает"
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

                bot["lifecycle"] = state

                save_bot(
                    bot,
                    "Ручная сверка",
                    note or "Позиция проверена пользователем.",
                )

                st.rerun()


# =========================================================
# BOT CARDS
# =========================================================

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

        columns[0].metric(
            "Цена",
            formatted(price, 6),
        )

        columns[1].metric(
            "Открытый PnL ≈ USDT",
            formatted(state["pnl"]),
        )

        columns[2].metric(
            "Резерв маржи USDT",
            formatted(state["remaining"]),
        )

        st.write(
            "Действие: " + state["action"]
        )

        if state["risk"] == "Высокий":
            st.error(state["reason"])
        else:
            st.info(state["reason"])

        st.caption(
            "Риск: " + state["risk"]
        )

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
                navigate("Мои боты")
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

        if state["liquidation_distance"] is not None:
            st.write(
                "До введённой ликвидации, %: "
                + formatted(state["liquidation_distance"])
            )

        st.caption(
            "Открытый PnL не равен общему результату бота. "
            "Объём вводится в базовой монете, "
            "не в количестве контрактов."
        )

        with st.expander("Сверить позицию / отметить запуск"):
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
            "«Не трогать» не отключает предупреждения "
            "и не отменяет лимиты."
        )

        if st.button(
            "Отправить статус в Telegram",
            key="tg_" + bot["id"],
        ):
            try:
                send_telegram(report(bot, price, state))
                st.success("Telegram подтвердил отправку.")
            except Exception:
                st.error(
                    "Отправка не подтверждена. "
                    "Проверь Telegram в Secrets."
                )


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

    if document.get("direction") not in (
        "Long", "Short", "Neutral"
    ):
        raise ValueError("Неизвестное направление.")

    if (
        document["strategy"] == "DCA"
        and document["direction"] == "Neutral"
    ):
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

    old_market = str(document.get("market", "SWAP"))

    document["market"] = (
        "SWAP"
        if "SWAP" in old_market or "Фьючерсы" in old_market
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


def import_documents(documents, old_events=None):
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
            if old_events:
                document["imported_journal"] = old_events

            query(
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

            write_event(
                connection,
                document["id"],
                "Импорт",
                "Добавлена копия. Требуется сверка.",
            )

    return len(prepared)


def settings_page(bots):
    st.title("Настройки")

    password_ready = bool(secret("APP_PASSWORD"))

    st.write(
        "Пароль: "
        + ("настроен" if password_ready else "не настроен")
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
            "Не публикуй личные позиции открыто."
        )

    if not DB_URL:
        st.warning(
            "Локальные данные могут потеряться "
            "при пересоздании облачного сервера. "
            "Для постоянного внешнего хранения "
            "настрой DATABASE_URL."
        )

    if st.button("Тест Telegram"):
        try:
            send_telegram(
                "OKX Control: соединение подтверждено. "
                "Автоматические сделки не включены."
            )
            st.success("Сообщение отправлено.")
        except Exception:
            st.error(
                "Проверь Telegram Secrets и соединение."
            )

    clean_bots = []

    for bot in bots:
        item = dict(bot)
        item.pop("_revision", None)
        clean_bots.append(item)

    backup = {
        "version": 5,
        "created_at": now(),
        "bots": clean_bots,
        "events": events().to_dict("records"),
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

            source = json.loads(uploaded.getvalue())

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
            st.error(str(error))

    with st.expander("Импорт из старой таблицы SQLite"):
        st.caption(
            "Не удаляет старые записи. "
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

                old_rows = [
                    dict(row)
                    for row in old_connection.execute(
                        "SELECT * FROM bots"
                    )
                ]

                old_connection.close()
                old_connection = None

                count = import_documents(old_rows)

                st.success(
                    f"Добавлено: {count}. "
                    "Проверь единицы и суммы."
                )

            except Exception as error:
                st.error(str(error))

            finally:
                if old_connection is not None:
                    old_connection.close()

    st.subheader("Пример Secrets")

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
        "При смене локальной базы на внешнюю "
        "перенеси карточки через экспорт/импорт. "
        "Фоновый мониторинг здесь не запущен. "
        "Telegram отправляется по кнопке."
    )


# =========================================================
# HOME
# =========================================================

def home(bots):
    st.markdown(
        '<div class="desk">'
        '<div class="eyebrow">OKX CONTROL</div>'
        '<div class="title">Твои боты под контролем</div>'
        '<div class="subtitle">'
        'Планы, позиции и следующие действия — на одном экране.'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    active = [
        bot for bot in bots
        if bot.get("lifecycle") == "Работает"
    ]

    columns = st.columns(3)

    columns[0].metric("Работают по сверке", len(active))
    columns[1].metric("Всего карточек", len(bots))
    columns[2].metric(
        "Черновики",
        sum(
            bot.get("lifecycle") == "Черновик"
            for bot in bots
        ),
    )

    columns = st.columns(3)

    if columns[0].button(
        "ЛОНГ · DCA",
        key="long_home",
        use_container_width=True,
    ):
        navigate("DCA", "Long")

    if columns[1].button(
        "ШОРТ · DCA",
        key="short_home",
        use_container_width=True,
    ):
        navigate("DCA", "Short")

    if columns[2].button(
        "GRID",
        key="grid_home",
        use_container_width=True,
    ):
        navigate("Grid", "Neutral")

    columns = st.columns(2)

    if columns[0].button(
        "Найти идею в сканере",
        use_container_width=True,
    ):
        navigate("Сканер")

    if columns[1].button(
        "Добавить работающего бота",
        use_container_width=True,
    ):
        navigate("Мои боты")

    st.subheader("Работающие боты")

    if not active:
        st.info(
            "Пока нет подтверждённых работающих ботов. "
            "Добавь DCA или Grid, затем сверь позицию."
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
            "Цены обновляются при выполнении страницы. "
            "Фоновый контроль при закрытой вкладке "
            "не работает. Торговых команд нет."
        )

        if not DB_URL:
            st.warning(
                "Для сохранности при пересоздании "
                "сервера нужна внешняя база или копии."
            )


# =========================================================
# MAIN
# =========================================================

def main():
    design()
    login()
    initialize_database()

    pending = st.session_state.pop(
        "pending_page",
        None,
    )

    if pending in PAGES:
        st.session_state["navigation"] = pending

    if st.session_state.get("navigation") not in PAGES:
        st.session_state["navigation"] = "Главная"

    with st.sidebar:
        st.title("OKX Control")

        page = st.radio(
            "Раздел",
            PAGES,
            key="navigation",
        )

        if st.button(
            "Обновить цены",
            use_container_width=True,
        ):
            quote.clear()
            st.rerun()

        st.caption(
            "Ручное подтверждение на OKX. "
            "Торговые API-ключи не используются."
        )

    bots = load_bots()

    if page == "Главная":
        home(bots)

    elif page == "Сканер":
        scanner()

    elif page == "Мои боты":
        st.title("Мои боты")

        columns = st.columns(2)

        if columns[0].button(
            "Добавить DCA",
            use_container_width=True,
        ):
            navigate("DCA", "Long")

        if columns[1].button(
            "Добавить Grid",
            use_container_width=True,
        ):
            navigate("Grid", "Neutral")

        filter_state = st.radio(
            "Показать",
            ["Все", "Работает", "Черновик", "Закрыт"],
            horizontal=True,
        )

        selected = [
            bot for bot in bots
            if filter_state == "Все"
            or bot.get("lifecycle") == filter_state
        ]

        if not selected:
            st.info("Нет карточек для этого фильтра.")

        for bot in selected:
            bot_card(bot)

    elif page == "DCA":
        st.title("DCA")
        creator("DCA")

    elif page == "Grid":
        st.title("Grid")
        creator("Grid")

    elif page == "Журнал":
        st.title("Журнал · UTC")

        frame = events()

        st.dataframe(
            frame,
            hide_index=True,
            use_container_width=True,
        )

        st.download_button(
            "Скачать журнал CSV",
            frame.to_csv(index=False).encode("utf-8-sig"),
            "journal.csv",
            "text/csv",
        )

        st.caption(
            "Повторные снимки одной позиции "
            "не суммируются как заработанная прибыль."
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
        "Проверь зависимости, введённые параметры "
        "и подключение к базе. "
        "Подробности доступны в журнале сервера. "
        "При ошибке PostgreSQL приложение "
        "не переключается на пустую локальную базу."
    )
