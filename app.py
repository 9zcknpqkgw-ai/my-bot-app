import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests
import streamlit as st

from ta.momentum import RSIIndicator
from ta.trend import ADXIndicator


# =========================================================
# CONFIGURATION
# =========================================================

st.set_page_config(
    page_title="OKX Terminal",
    layout="wide",
)

API_URL = "https://www.okx.com/api/v5"
HOUR_MS = 3_600_000

COINS = [
    "BTC",
    "ETH",
    "SOL",
    "BNB",
    "XRP",
    "DOGE",
    "ADA",
    "AVAX",
    "LINK",
    "DOT",
    "TRX",
    "LTC",
    "NEAR",
    "APT",
    "ARB",
    "OP",
    "SUI",
    "PEPE",
    "INJ",
    "BCH",
]

PAGES = [
    "Главная",
    "Сканер рынка",
    "DCA",
    "Grid",
    "Открытая позиция",
    "Журнал",
    "Настройки",
]


# =========================================================
# SESSION STATE
# =========================================================

def init_state():
    defaults = {
        "page": "Главная",
        "scanner": None,
        "dca_result": None,
        "grid_result": None,
        "dca_plan": None,
        "grid_plan": None,
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    navigation = st.session_state.pop(
        "_navigation",
        None,
    )

    if navigation:
        target = navigation.get("page")

        if target in PAGES:
            st.session_state["page"] = target

        for key, value in navigation.get(
            "prefill",
            {},
        ).items():
            st.session_state[key] = value

    if st.session_state["page"] not in PAGES:
        st.session_state["page"] = "Главная"


def navigate(page, prefill=None):
    st.session_state["_navigation"] = {
        "page": page,
        "prefill": prefill or {},
    }

    st.rerun()


# =========================================================
# INPUT HELPERS
# =========================================================

def number(
    label,
    key,
    default,
    minimum=0.0,
    maximum=None,
    step=None,
):
    arguments = {
        "label": label,
        "key": key,
        "min_value": float(minimum),
    }

    if key not in st.session_state:
        arguments["value"] = float(default)

    if maximum is not None:
        arguments["max_value"] = float(maximum)

    if step is not None:
        arguments["step"] = float(step)

    return st.number_input(**arguments)


def integer(
    label,
    key,
    default,
    minimum,
    maximum,
):
    arguments = {
        "label": label,
        "key": key,
        "min_value": int(minimum),
        "max_value": int(maximum),
        "step": 1,
    }

    if key not in st.session_state:
        arguments["value"] = int(default)

    return st.number_input(**arguments)


# =========================================================
# DESIGN
# =========================================================

def apply_style():
    st.markdown(
        """
<style>
.stApp {
    background: #f6f8fc;
    color: #172033;
    color-scheme: light;
}

.block-container {
    max-width: 1250px;
    padding-top: 1.8rem;
    padding-bottom: 3rem;
}

[data-testid="stSidebar"] {
    background: #ffffff;
    border-right: 1px solid #dce4ef;
}

h1, h2, h3, h4, p, li, label {
    color: #172033;
}

[data-testid="stWidgetLabel"] p {
    color: #172033 !important;
}

[data-testid="stCaptionContainer"] p {
    color: #53647c !important;
}

[data-testid="stMetric"] {
    background: #ffffff;
    border: 1px solid #dce4ef;
    border-radius: 15px;
    padding: 18px;
}

[data-testid="stMetricLabel"] p,
[data-testid="stMetricValue"] div {
    color: #172033 !important;
}

.stButton button,
.stFormSubmitButton button {
    background: #2563eb !important;
    color: #ffffff !important;
    border: 0 !important;
    border-radius: 10px;
    min-height: 43px;
}

.stButton button p,
.stFormSubmitButton button p {
    color: inherit !important;
}

.stButton button:hover,
.stFormSubmitButton button:hover {
    background: #1d4ed8 !important;
}

.stButton button:disabled {
    background: #a9bde5 !important;
    color: #ffffff !important;
}

[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input {
    background: #ffffff !important;
    color: #172033 !important;
    -webkit-text-fill-color: #172033 !important;
}

[data-testid="stNumberInput"] button {
    background: #eaf0fa !important;
    color: #172033 !important;
}

[data-testid="stSelectbox"] [data-baseweb="select"] > div {
    background: #ffffff !important;
    color: #172033 !important;
}

[data-testid="stSelectbox"] span,
[data-testid="stSelectbox"] input {
    color: #172033 !important;
    -webkit-text-fill-color: #172033 !important;
}

[role="listbox"],
[role="option"] {
    background: #ffffff !important;
    color: #172033 !important;
}

[data-testid="stRadio"] label p,
[data-testid="stExpander"] summary p {
    color: #172033 !important;
}

[data-testid="stAlert"] {
    background: #eaf2ff !important;
    color: #172033 !important;
    border-radius: 12px;
}

[data-testid="stAlert"] p,
[data-testid="stAlert"] li {
    color: #172033 !important;
}

[data-testid="stForm"] {
    background: #ffffff;
    border: 1px solid #dce4ef;
    border-radius: 16px;
    padding: 20px;
}

.card {
    background: #ffffff;
    border: 1px solid #dce4ef;
    border-radius: 16px;
    padding: 22px;
    margin-bottom: 18px;
}

.card h2 {
    margin: 0 0 8px;
}

.card p {
    margin: 0;
    color: #53647c;
}

@media(max-width: 640px) {
    .block-container {
        padding: 1rem;
    }

    .card {
        padding: 18px;
    }
}
</style>
        """,
        unsafe_allow_html=True,
    )


def page_header(title, subtitle):
    st.markdown(
        f'<div class="card">'
        f"<h2>{title}</h2>"
        f"<p>{subtitle}</p>"
        f"</div>",
        unsafe_allow_html=True,
    )


# =========================================================
# PUBLIC OKX API
# =========================================================

@st.cache_data(ttl=20, show_spinner=False)
def okx_get(path, params):
    last_error = None

    for attempt in range(3):
        try:
            response = requests.get(
                API_URL + path,
                params=params,
                timeout=(5, 12),
            )

            if (
                response.status_code == 429
                or response.status_code >= 500
            ):
                raise requests.RequestException(
                    f"OKX HTTP {response.status_code}"
                )

            response.raise_for_status()
            payload = response.json()

            if (
                not isinstance(payload, dict)
                or str(payload.get("code")) != "0"
            ):
                raise ValueError(
                    "OKX вернул ошибку запроса."
                )

            data = payload.get("data")

            if not isinstance(data, list):
                raise ValueError(
                    "Неверный формат ответа OKX."
                )

            return data

        except (
            requests.RequestException,
            ValueError,
        ) as error:
            last_error = error

            if attempt < 2:
                time.sleep(
                    0.5 * (attempt + 1)
                )

    raise RuntimeError(
        f"Данные OKX недоступны: {last_error}"
    )


def instrument(coin, market="SWAP"):
    suffix = (
        "-SWAP"
        if market == "SWAP"
        else ""
    )

    return f"{coin}-USDT{suffix}"


@st.cache_data(ttl=20, show_spinner=False)
def get_price(coin, market="SWAP"):
    data = okx_get(
        "/market/ticker",
        {
            "instId": instrument(
                coin,
                market,
            ),
        },
    )

    if not data:
        raise ValueError(
            "Тикер не найден."
        )

    row = data[0]

    price = float(row["last"])
    timestamp = int(row["ts"])

    if (
        not np.isfinite(price)
        or price <= 0
        or time.time() - timestamp / 1000 > 180
    ):
        raise ValueError(
            "Цена отсутствует или устарела."
        )

    return {
        "price": price,
        "timestamp": timestamp,
    }


def parse_candles(rows):
    values = []

    for row in rows:
        if len(row) < 9:
            continue

        if str(row[8]) != "1":
            continue

        values.append([
            int(row[0]),
            float(row[1]),
            float(row[2]),
            float(row[3]),
            float(row[4]),
        ])

    frame = pd.DataFrame(
        values,
        columns=[
            "ts",
            "open",
            "high",
            "low",
            "close",
        ],
    )

    if frame.empty:
        raise ValueError(
            "Нет закрытых свечей."
        )

    frame = (
        frame.drop_duplicates("ts")
        .sort_values("ts")
        .reset_index(drop=True)
    )

    prices = frame[
        ["open", "high", "low", "close"]
    ]

    if (
        not np.isfinite(
            prices.to_numpy()
        ).all()
        or (prices <= 0).any().any()
    ):
        raise ValueError(
            "Некорректные цены в истории."
        )

    frame["time"] = pd.to_datetime(
        frame["ts"],
        unit="ms",
        utc=True,
    )

    return frame


@st.cache_data(ttl=300, show_spinner=False)
def daily_candles(coin):
    rows = okx_get(
        "/market/candles",
        {
            "instId": instrument(coin),
            "bar": "1D",
            "limit": "200",
        },
    )

    frame = parse_candles(rows)

    if len(frame) < 60:
        raise ValueError(
            "Нужно минимум 60 закрытых "
            "дневных свечей."
        )

    differences = (
        frame["ts"].diff().dropna()
    )

    if (
        differences != 24 * HOUR_MS
    ).any():
        raise ValueError(
            "Есть пропуски дневных свечей."
        )

    last_timestamp = int(
        frame["ts"].iloc[-1]
    )

    if (
        time.time() * 1000 - last_timestamp
        > 49 * HOUR_MS
    ):
        raise ValueError(
            "Дневные свечи устарели."
        )

    return frame


@st.cache_data(ttl=300, show_spinner=False)
def history_14_days(
    coin,
    market,
    end_ms,
):
    start_ms = (
        end_ms - 14 * 24 * HOUR_MS
    )

    after = end_ms
    collected = []
    previous_oldest = None

    for _ in range(8):
        rows = okx_get(
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

        if not rows:
            break

        collected.extend(rows)

        oldest = min(
            int(row[0])
            for row in rows
        )

        if (
            oldest <= start_ms
            or oldest == previous_oldest
        ):
            break

        previous_oldest = oldest
        after = oldest

        time.sleep(0.12)

    frame = parse_candles(
        collected
    )

    frame = frame[
        (frame["ts"] >= start_ms)
        & (frame["ts"] < end_ms)
    ].reset_index(drop=True)

    expected = np.arange(
        start_ms,
        end_ms,
        HOUR_MS,
        dtype=np.int64,
    )

    if (
        len(frame) != len(expected)
        or not np.array_equal(
            frame["ts"].to_numpy(),
            expected,
        )
    ):
        raise ValueError(
            "Не получены все 336 закрытых "
            "часовых свечей за 14 дней. "
            "Тест остановлен."
        )

    return frame


# =========================================================
# MARKET SCANNER
# =========================================================

def scan_one(coin):
    frame = daily_candles(coin)

    adx_indicator = ADXIndicator(
        high=frame["high"],
        low=frame["low"],
        close=frame["close"],
        window=14,
    )

    adx = float(
        adx_indicator.adx().iloc[-1]
    )

    plus_di = float(
        adx_indicator.adx_pos().iloc[-1]
    )

    minus_di = float(
        adx_indicator.adx_neg().iloc[-1]
    )

    rsi = float(
        RSIIndicator(
            close=frame["close"],
            window=14,
        ).rsi().iloc[-1]
    )

    if not np.isfinite([
        adx,
        plus_di,
        minus_di,
        rsi,
    ]).all():
        raise ValueError(
            "Индикаторы не готовы."
        )

    if adx < 25:
        signal = "GRID"
        action = "Подготовить Grid"

    elif plus_di > minus_di:
        signal = "LONG"
        action = "Рассмотреть Long"

    elif minus_di > plus_di:
        signal = "SHORT"
        action = "Рассмотреть Short"

    else:
        signal = "WAIT"
        action = "Ждать"

    ticker = get_price(coin)

    return {
        "Монета": coin,
        "Цена": ticker["price"],
        "Сигнал": signal,
        "Действие": action,
        "Шаг%": 2.0,
        "Тейк%": 1.5,
        "ADX": adx,
        "RSI": rsi,
    }


# =========================================================
# BACKTEST RESULT
# =========================================================

def result_pack(
    frame,
    curve,
    budget,
    cycles,
    fees,
    floating,
    halted=False,
):
    if not curve:
        raise ValueError(
            "Нет данных для результата."
        )

    values = np.asarray(
        [budget, *curve],
        dtype=float,
    )

    peaks = np.maximum.accumulate(
        values
    )

    drawdown = float(
        np.max(
            (peaks - values) / peaks
        ) * 100
    )

    return {
        "roi": (
            curve[-1] / budget - 1
        ) * 100,
        "cycles": cycles,
        "equity": curve[-1],
        "pnl": curve[-1] - budget,
        "fees": fees,
        "floating": floating,
        "drawdown": drawdown,
        "halted": halted,
        "curve": pd.DataFrame(
            {
                "Капитал USDT": curve,
            },
            index=frame["time"].iloc[
                :len(curve)
            ],
        ),
        "start": frame["time"].iloc[0],
        "end": frame["time"].iloc[
            len(curve) - 1
        ],
    }


# =========================================================
# DCA SIMULATION
# =========================================================

def simulate_dca(frame, config):
    budget = float(
        config["budget"]
    )

    leverage = float(
        config["leverage"]
    )

    base_margin = float(
        config["order_margin"]
    )

    step = config["step"] / 100
    take = config["tp"] / 100

    safety_count = int(
        config["safety"]
    )

    multiplier = config["multiplier"]
    fee = config["fee"] / 100

    sign = (
        1
        if config["direction"] == "Long"
        else -1
    )

    if (
        budget <= 0
        or base_margin <= 0
        or leverage < 1
        or step <= 0
        or take <= 0
        or multiplier < 1
        or safety_count < 0
    ):
        raise ValueError(
            "Проверь параметры DCA."
        )

    planned_margin = (
        base_margin
        + sum(
            base_margin * multiplier ** index
            for index in range(
                safety_count
            )
        )
    )

    planned_entry_fees = (
        planned_margin
        * leverage
        * fee
    )

    minimum_budget = (
        planned_margin
        + planned_entry_fees
    )

    if minimum_budget > budget:
        raise ValueError(
            "Плану нужно минимум "
            f"{minimum_budget:.2f} USDT "
            "маржи и входных комиссий. "
            "Увеличь бюджет или уменьши "
            "ордера/СО."
        )

    if (
        sign == 1
        and step * safety_count >= 1
    ):
        raise ValueError(
            "Один из уровней Long "
            "имеет цену ≤ 0."
        )

    wallet = budget

    quantity = 0.0
    average = 0.0
    first_entry = 0.0
    used_margin = 0.0

    executed_safety = 0
    cycles = 0

    fees = 0.0
    floating = 0.0
    halted = False

    curve = []

    prices = frame["close"].to_numpy(
        dtype=float
    )

    for price in prices:
        floating = (
            sign
            * quantity
            * (price - average)
            if quantity
            else 0.0
        )

        target_reached = (
            quantity > 0
            and sign
            * (price / average - 1)
            >= take
        )

        if target_reached:
            closing_fee = (
                quantity * price * fee
            )

            wallet += (
                floating - closing_fee
            )

            fees += closing_fee

            quantity = 0.0
            average = 0.0
            used_margin = 0.0
            floating = 0.0

            cycles += 1

        elif quantity == 0:
            notional = (
                base_margin * leverage
            )

            opening_fee = (
                notional * fee
            )

            if (
                wallet
                >= base_margin + opening_fee
            ):
                quantity = (
                    notional / price
                )

                average = price
                first_entry = price
                used_margin = base_margin
                executed_safety = 0

                wallet -= opening_fee
                fees += opening_fee

        elif (
            executed_safety < safety_count
            and sign
            * (price / first_entry - 1)
            <= -step * (executed_safety + 1)
        ):
            extra_margin = (
                base_margin
                * multiplier ** executed_safety
            )

            notional = (
                extra_margin * leverage
            )

            opening_fee = (
                notional * fee
            )

            equity_before = (
                wallet + floating
            )

            required_margin = (
                used_margin
                + extra_margin
                + opening_fee
            )

            if equity_before >= required_margin:
                extra_quantity = (
                    notional / price
                )

                average = (
                    quantity * average
                    + notional
                ) / (
                    quantity + extra_quantity
                )

                quantity += extra_quantity
                used_margin += extra_margin

                wallet -= opening_fee
                fees += opening_fee

                executed_safety += 1

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

        if equity <= 0:
            curve.append(0.0)
            halted = True
            break

        curve.append(equity)

    return result_pack(
        frame=frame,
        curve=curve,
        budget=budget,
        cycles=cycles,
        fees=fees,
        floating=floating,
        halted=halted,
    )


# =========================================================
# GRID SIMULATION
# =========================================================

def simulate_grid(frame, config):
    budget = config["budget"]
    lower = config["lower"]
    upper = config["upper"]

    count = int(config["grids"])
    fee = config["fee"] / 100

    if (
        budget <= 0
        or lower <= 0
        or upper <= lower
        or count < 2
    ):
        raise ValueError(
            "Проверь бюджет, диапазон "
            "и количество интервалов."
        )

    levels = np.linspace(
        lower,
        upper,
        count + 1,
    )

    allocation = (
        budget
        / count
        / (1 + fee)
    )

    wallet = budget
    total_fees = 0.0
    cycles = 0

    lots = {}
    curve = []

    prices = frame["close"].to_numpy(
        dtype=float
    )

    for index, price in enumerate(prices):
        for level_index in list(lots):
            quantity, purchase_cost = lots[
                level_index
            ]

            next_level = levels[
                level_index + 1
            ]

            if price >= next_level:
                gross = (
                    quantity * price
                )

                selling_fee = (
                    gross * fee
                )

                wallet += (
                    gross - selling_fee
                )

                total_fees += selling_fee

                del lots[level_index]
                cycles += 1

        if (
            index > 0
            and lower <= price <= upper
        ):
            for level_index, level in enumerate(
                levels[:-1]
            ):
                full_cost = (
                    allocation * (1 + fee)
                )

                crossed_down = (
                    prices[index - 1]
                    > level
                    >= price
                )

                if (
                    level_index not in lots
                    and crossed_down
                    and wallet + 1e-9 >= full_cost
                ):
                    lots[level_index] = (
                        allocation / price,
                        allocation,
                    )

                    wallet -= full_cost

                    total_fees += (
                        allocation * fee
                    )

        inventory = sum(
            quantity
            for quantity, purchase_cost
            in lots.values()
        )

        equity = (
            wallet + inventory * price
        )

        curve.append(equity)

    floating = sum(
        quantity * prices[-1] - purchase_cost
        for quantity, purchase_cost
        in lots.values()
    )

    return result_pack(
        frame=frame,
        curve=curve,
        budget=budget,
        cycles=cycles,
        fees=total_fees,
        floating=floating,
    )


# =========================================================
# BACKTEST EXECUTION
# =========================================================

def run_test(kind, config):
    end_ms = (
        int(time.time() // 3600)
        * HOUR_MS
    )

    market = (
        "SWAP"
        if kind == "dca"
        else "SPOT"
    )

    with st.spinner(
        "Загружаю 14 дней истории 1H "
        "и считаю результат..."
    ):
        frame = history_14_days(
            coin=config["coin"],
            market=market,
            end_ms=end_ms,
        )

        if kind == "dca":
            result = simulate_dca(
                frame,
                config,
            )
        else:
            result = simulate_grid(
                frame,
                config,
            )

    st.session_state[
        kind + "_result"
    ] = {
        "config": dict(config),
        "result": result,
    }


def show_test(kind):
    saved = st.session_state.get(
        kind + "_result"
    )

    if not saved:
        return

    config = saved["config"]
    result = saved["result"]

    st.subheader(
        "Последний бэктест"
    )

    st.caption(
        f"{config['coin']} · "
        f"{result['start']} — "
        f"{result['end']} · "
        "закрытия 1H"
    )

    columns = st.columns(4)

    columns[0].metric(
        "Доходность от бюджета",
        f"{result['roi']:.2f}%",
    )

    columns[1].metric(
        "Количество циклов",
        result["cycles"],
    )

    columns[2].metric(
        "Результат USDT",
        f"{result['pnl']:.2f}",
    )

    columns[3].metric(
        "Макс. просадка",
        f"{result['drawdown']:.2f}%",
    )

    st.line_chart(
        result["curve"]
    )

    st.caption(
        "Открытый PnL в конце: "
        f"{result['floating']:.2f} USDT. "
        "Уже списанные модельные комиссии: "
        f"{result['fees']:.2f} USDT. "
        "Открытая позиция включена в результат, "
        "но не считается завершённым циклом."
    )

    with st.expander(
        "Параметры этого расчёта"
    ):
        st.write(config)

    if result["halted"]:
        st.error(
            "Модельный капитал исчерпан. "
            "Симуляция остановлена. "
            "Это не расчёт биржевой ликвидации."
        )

    st.caption(
        "После изменения формы "
        "запусти тест заново. "
        "Результат относится к показанному "
        "снимку параметров, а не к новым "
        "несохранённым полям."
    )


# =========================================================
# SCANNER PAGE
# =========================================================

def scanner_page():
    page_header(
        "Сканер рынка",
        "20 монет · OKX USDT-SWAP · "
        "закрытые дневные свечи 1D",
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

        for index, coin in enumerate(COINS):
            try:
                rows.append(
                    scan_one(coin)
                )

            except Exception as error:
                errors.append(
                    f"{coin}: {error}"
                )

            progress.progress(
                (index + 1) / len(COINS)
            )

        st.session_state["scanner"] = {
            "rows": rows,
            "errors": errors,
            "time": datetime.now(
                timezone.utc
            ).strftime(
                "%d.%m.%Y %H:%M UTC"
            ),
        }

    saved = st.session_state[
        "scanner"
    ]

    if not saved:
        st.info(
            "Нажми кнопку сканирования."
        )
        return

    st.caption(
        "Последний запуск: "
        + saved["time"]
    )

    if saved["errors"]:
        with st.expander(
            f"Не рассчитаны: "
            f"{len(saved['errors'])}"
        ):
            for error in saved["errors"]:
                st.write(error)

    if not saved["rows"]:
        st.warning(
            "Не удалось получить данные. "
            "Проверь доступность OKX "
            "и повтори запрос."
        )
        return

    frame = pd.DataFrame(
        saved["rows"]
    )

    styled = (
        frame.style
        .set_properties(**{
            "background-color": "#ffffff",
            "color": "#172033",
        })
        .format({
            "Цена": "{:,.8f}",
            "Шаг%": "{:.2f}",
            "Тейк%": "{:.2f}",
            "ADX": "{:.2f}",
            "RSI": "{:.2f}",
        })
    )

    st.dataframe(
        styled,
        hide_index=True,
        use_container_width=True,
    )

    coin = st.selectbox(
        "Монета для подготовки бота",
        frame["Монета"].tolist(),
    )

    row = next(
        item
        for item in saved["rows"]
        if item["Монета"] == coin
    )

    columns = st.columns(2)

    if columns[0].button(
        "Создать DCA",
        use_container_width=True,
    ):
        direction = (
            "Short"
            if row["Сигнал"] == "SHORT"
            else "Long"
        )

        navigate(
            "DCA",
            {
                "dca_coin": coin,
                "dca_direction": direction,
                "dca_step": float(
                    row["Шаг%"]
                ),
                "dca_tp": float(
                    row["Тейк%"]
                ),
            },
        )

    if columns[1].button(
        "Создать Grid",
        use_container_width=True,
    ):
        navigate(
            "Grid",
            {
                "grid_coin": coin,
            },
        )

    st.caption(
        "При сигнале GRID или WAIT "
        "направление DCA не определено: "
        "в форме по умолчанию стоит Long, "
        "его нужно проверить. "
        "Шаг 2% и тейк 1,5% — шаблон, "
        "не результат оптимизации."
    )


# =========================================================
# DCA PAGE
# =========================================================

def dca_page():
    page_header(
        "DCA",
        "Ручная подготовка плана "
        "и упрощённый бэктест за 14 дней",
    )

    with st.form(
        "dca_form"
    ):
        coin = st.selectbox(
            "Монета",
            COINS,
            key="dca_coin",
        )

        direction = st.selectbox(
            "Направление",
            [
                "Long",
                "Short",
            ],
            key="dca_direction",
        )

        budget = number(
            "Общий бюджет, USDT",
            "dca_budget",
            100,
            1,
        )

        columns = st.columns(2)

        with columns[0]:
            step = number(
                "Шаг СО от первого входа, %",
                "dca_step",
                2,
                0.01,
                50,
            )

        with columns[1]:
            take = number(
                "Тейк от средней цены, %",
                "dca_tp",
                1.5,
                0.01,
                100,
            )

        with st.expander(
            "Расширенные настройки"
        ):
            order_margin = number(
                "Маржа первого ордера "
                "и первого СО, USDT",
                "dca_order",
                10,
                0.1,
            )

            leverage = integer(
                "Плечо модели",
                "dca_leverage",
                3,
                1,
                20,
            )

            safety = integer(
                "Максимум СО за цикл",
                "dca_safety",
                4,
                0,
                20,
            )

            multiplier = number(
                "Множитель маржи следующих СО",
                "dca_multiplier",
                1.2,
                1,
                3,
            )

            fee = number(
                "Комиссия за сторону, "
                "% от номинала",
                "dca_fee",
                0.05,
                0,
                5,
            )

        st.caption(
            "По умолчанию 10 USDT — маржа: "
            "при 3x номинал первого ордера "
            "равен 30 USDT. "
            "Плечо не умножает PnL повторно."
        )

        columns = st.columns(2)

        test = columns[0].form_submit_button(
            "Проверить на истории",
            use_container_width=True,
        )

        save = columns[1].form_submit_button(
            "Сохранить план в сессии",
            use_container_width=True,
        )

    config = {
        "coin": coin,
        "direction": direction,
        "budget": budget,
        "step": step,
        "tp": take,
        "order_margin": order_margin,
        "leverage": leverage,
        "safety": safety,
        "multiplier": multiplier,
        "fee": fee,
    }

    if save:
        st.session_state[
            "dca_plan"
        ] = dict(config)

        st.success(
            "План сохранён только "
            "в текущей сессии. "
            "Бот на OKX не запускался."
        )

    if test:
        st.session_state[
            "dca_result"
        ] = None

        try:
            run_test(
                "dca",
                config,
            )

        except Exception as error:
            st.error(
                str(error)
            )

    show_test(
        "dca"
    )

    with st.expander(
        "Как работает модель DCA"
    ):
        st.write(
            "Вход по первому закрытию 1H. "
            "СО — против позиции, через "
            "фиксированный шаг от первого входа. "
            "Множитель увеличивает маржу "
            "последующих СО. "
            "Не более одного СО на свечу. "
            "TP — движение от средневзвешенной "
            "цены, не ROI маржи. "
            "После закрытия цикл может начаться "
            "на следующей свече. "
            "Новые ордера ограничены бюджетом "
            "и доступной модельной маржой."
        )

        st.warning(
            "Не моделируются funding, "
            "биржевая ликвидация, MMR, "
            "проскальзывание, внутрисвечные "
            "касания, стопы и точные правила OKX. "
            "Реальный результат с плечом "
            "может существенно отличаться. "
            "Доходность включает незакрытую "
            "позицию и не является прогнозом."
        )


# =========================================================
# GRID PAGE
# =========================================================

def grid_page():
    page_header(
        "Grid",
        "Учебный Long Grid без плеча · "
        "данные OKX Spot · ручной диапазон",
    )

    with st.form(
        "grid_form"
    ):
        coin = st.selectbox(
            "Монета",
            COINS,
            key="grid_coin",
        )

        budget = number(
            "Бюджет, USDT",
            "grid_budget",
            100,
            1,
        )

        columns = st.columns(2)

        with columns[0]:
            lower = number(
                "Нижняя граница — введи цену",
                "grid_lower",
                0,
                0,
            )

        with columns[1]:
            upper = number(
                "Верхняя граница — введи цену",
                "grid_upper",
                0,
                0,
            )

        grids = integer(
            "Количество интервалов",
            "grid_count",
            10,
            2,
            100,
        )

        with st.expander(
            "Расширенные настройки"
        ):
            fee = number(
                "Комиссия за сторону, %",
                "grid_fee",
                0.05,
                0,
                5,
            )

        columns = st.columns(2)

        test = columns[0].form_submit_button(
            "Проверить на истории",
            use_container_width=True,
        )

        save = columns[1].form_submit_button(
            "Сохранить план в сессии",
            use_container_width=True,
        )

    config = {
        "coin": coin,
        "budget": budget,
        "lower": lower,
        "upper": upper,
        "grids": grids,
        "fee": fee,
    }

    valid = (
        lower > 0
        and upper > lower
    )

    if test or save:
        if not valid:
            st.error(
                "Введи положительную нижнюю "
                "границу и верхнюю границу "
                "выше нижней."
            )

        elif save:
            st.session_state[
                "grid_plan"
            ] = dict(config)

            st.success(
                "План сохранён только в сессии. "
                "Торговые команды не отправлялись."
            )

        else:
            st.session_state[
                "grid_result"
            ] = None

            try:
                run_test(
                    "grid",
                    config,
                )

            except Exception as error:
                st.error(
                    str(error)
                )

    show_test(
        "grid"
    )

    with st.expander(
        "Как работает модель Grid"
    ):
        st.write(
            "Арифметическая сетка: "
            "N интервалов и N+1 уровней. "
            "Старт — полностью в USDT. "
            "При пересечении вниз покупается лот, "
            "при достижении следующего уровня "
            "вверх он продаётся. "
            "Исполнения приближённо считаются "
            "по закрытиям 1H. "
            "Один цикл — одна завершённая "
            "пара покупки и продажи. "
            "Новые покупки вне диапазона "
            "не выполняются; оставшиеся монеты "
            "продолжают влиять на результат."
        )

        st.warning(
            "Это не Futures Neutral Grid "
            "и не точная копия бота OKX. "
            "Нет шорта, плеча, funding, "
            "очереди ордеров "
            "и внутрисвечных исполнений. "
            "Исторический результат "
            "не гарантирует будущую доходность."
        )


# =========================================================
# OPEN POSITION PAGE
# =========================================================

def position_page():
    page_header(
        "Открытая позиция",
        "Текущие цены BTC и ETH. "
        "Фактическая позиция на бирже "
        "не подключена.",
    )

    if st.button(
        "Обновить цены"
    ):
        get_price.clear()
        okx_get.clear()

    columns = st.columns(2)

    for column, coin in zip(
        columns,
        ["BTC", "ETH"],
    ):
        with column:
            try:
                ticker = get_price(
                    coin
                )

                st.metric(
                    coin + " / USDT SWAP",
                    f"{ticker['price']:,.4f}",
                )

                timestamp = datetime.fromtimestamp(
                    ticker["timestamp"] / 1000,
                    timezone.utc,
                )

                st.caption(
                    timestamp.strftime(
                        "%d.%m.%Y %H:%M:%S UTC"
                    )
                )

            except Exception as error:
                st.warning(
                    f"{coin}: {error}"
                )

    st.info(
        "Без приватного API здесь нет "
        "сведений о твоём объёме, "
        "средней цене, исполнении TP "
        "и ликвидации."
    )


# =========================================================
# MAIN APPLICATION
# =========================================================

def main():
    init_state()
    apply_style()

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

        st.caption(
            "Только публичные данные. "
            "Торговые команды не отправляются."
        )

        st.warning(
            "Все планы и результаты находятся "
            "в памяти текущей сессии. "
            "После её завершения или перезапуска "
            "они могут исчезнуть."
        )

    if page == "Сканер рынка":
        scanner_page()

    elif page == "DCA":
        dca_page()

    elif page == "Grid":
        grid_page()

    elif page == "Открытая позиция":
        position_page()

    else:
        page_header(
            page,
            "В разработке",
        )

        st.info(
            "В разработке"
        )


main()
