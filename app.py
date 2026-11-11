import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests
import streamlit as st

from ta.momentum import RSIIndicator
from ta.trend import ADXIndicator


st.set_page_config(
    page_title="OKX Terminal",
    layout="wide",
)

API = "https://www.okx.com/api/v5"

PAGES = [
    "1. Главная",
    "2. Сканер рынка",
    "3. DCA",
    "4. Grid",
    "5. Открытая позиция",
    "6. Журнал",
    "7. Настройки",
]

COINS = [
    "BTC",
    "ETH",
    "SOL",
    "XRP",
    "DOGE",
    "ADA",
    "AVAX",
    "LINK",
    "DOT",
    "LTC",
    "BCH",
    "TRX",
    "TON",
    "NEAR",
    "APT",
    "ARB",
    "OP",
    "SUI",
    "INJ",
    "UNI",
]

DEFAULT_STEP = 2.0
DEFAULT_TP = 1.5


# =========================================================
# SESSION STATE AND NAVIGATION
# =========================================================

def initialize():
    defaults = {
        "menu": PAGES[0],
        "scan": None,
        "plans": [],
        "results": {},
        "dca_defaults": dict(
            coin="BTC",
            direction="LONG",
            budget=100.0,
            step=DEFAULT_STEP,
            tp=DEFAULT_TP,
            order_margin=10.0,
            leverage=3,
            max_so=4,
            fee=0.05,
        ),
        "grid_defaults": dict(
            coin="BTC",
            budget=100.0,
            lower=0.0,
            upper=0.0,
            grids=10,
            fee=0.10,
        ),
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    pending = st.session_state.pop(
        "pending_route",
        None,
    )

    if pending:
        kind = pending["kind"]

        st.session_state["menu"] = (
            "3. DCA"
            if kind == "dca"
            else "4. Grid"
        )

        values = dict(
            st.session_state[kind + "_defaults"]
        )

        values.update(pending["values"])

        st.session_state[
            kind + "_defaults"
        ] = values

        # Сброс значений формы выполняется до создания виджетов.
        for field in values:
            st.session_state.pop(
                kind + "_" + field,
                None,
            )

    if st.session_state["menu"] not in PAGES:
        st.session_state["menu"] = PAGES[0]


def navigate(kind, values):
    st.session_state["pending_route"] = dict(
        kind=kind,
        values=values,
    )

    st.rerun()


# =========================================================
# LIGHT UI
# =========================================================

def styles():
    st.markdown(
        """
<style>
.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stHeader"] {
    background: #f6f8fc;
    color: #172033;
}

.block-container {
    max-width: 1250px;
    padding-top: 1.5rem;
    padding-bottom: 3rem;
}

h1,
h2,
h3,
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li {
    color: #172033 !important;
}

[data-testid="stWidgetLabel"] p,
[data-testid="stCheckbox"] p,
[data-testid="stExpander"] summary p {
    color: #172033 !important;
}

[data-testid="stCaptionContainer"] p {
    color: #53627a !important;
}

[data-testid="stSidebar"] {
    background: #fff;
    border-right: 1px solid #e0e6f0;
}

[data-testid="stMetric"] {
    background: #fff;
    border: 1px solid #e0e6f0;
    border-radius: 14px;
    padding: 16px;
}

[data-testid="stMetricLabel"] p,
[data-testid="stMetricValue"] div {
    color: #172033 !important;
}

.stButton button,
.stFormSubmitButton button {
    background: #2563eb !important;
    color: #fff !important;
    border: 0 !important;
    border-radius: 10px;
    min-height: 43px;
    font-weight: 600;
}

.stButton button p,
.stFormSubmitButton button p {
    color: #fff !important;
}

.stButton button:hover,
.stFormSubmitButton button:hover {
    background: #1d4ed8 !important;
}

.stButton button:disabled {
    background: #94a3b8 !important;
    color: #fff !important;
}

[data-testid="stNumberInput"] input,
[data-testid="stTextInput"] input {
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
[data-testid="stSelectbox"] input,
[role="option"] {
    color: #172033 !important;
    -webkit-text-fill-color: #172033 !important;
}

[role="listbox"],
[role="option"] {
    background: #fff !important;
}

[data-testid="stRadio"] label p {
    color: #172033 !important;
}

[data-testid="stAlert"] {
    background: #eaf2ff !important;
    border-radius: 12px;
}

[data-testid="stAlert"] p,
[data-testid="stAlert"] li {
    color: #172033 !important;
}

[data-testid="stForm"] {
    background: #fff;
    border: 1px solid #e0e6f0;
    border-radius: 16px;
    padding: 20px;
}

.hero {
    background: #fff;
    border: 1px solid #e0e6f0;
    border-radius: 16px;
    padding: 22px;
    margin-bottom: 20px;
}

.hero h2 {
    margin: 0 0 8px;
}

.hero p {
    margin: 0;
    color: #53627a !important;
}
</style>
        """,
        unsafe_allow_html=True,
    )


def heading(title, subtitle):
    st.markdown(
        f'<div class="hero">'
        f"<h2>{title}</h2>"
        f"<p>{subtitle}</p>"
        f"</div>",
        unsafe_allow_html=True,
    )


# =========================================================
# OKX PUBLIC API
# =========================================================

def instrument(coin, market="SWAP"):
    return (
        f"{coin}-USDT"
        + ("-SWAP" if market == "SWAP" else "")
    )


@st.cache_data(ttl=20, show_spinner=False)
def okx_request(path, params):
    for attempt in range(3):
        try:
            response = requests.get(
                API + path,
                params=params,
                timeout=(5, 15),
                headers={
                    "User-Agent": "OKX-Terminal/1.0",
                },
            )

            if response.status_code == 429:
                raise requests.RequestException(
                    "OKX ограничил частоту запросов"
                )

            response.raise_for_status()
            payload = response.json()

            if str(payload.get("code")) != "0":
                raise ValueError(
                    "OKX: "
                    + str(
                        payload.get(
                            "msg",
                            "ошибка API",
                        )
                    )
                )

            return payload.get("data", [])

        except (
            requests.RequestException,
            ValueError,
        ) as error:
            if attempt == 2:
                raise RuntimeError(
                    "Не удалось получить данные OKX: "
                    f"{error}"
                ) from error

            time.sleep(
                0.6 * (attempt + 1)
            )

    return []


def parse_candles(rows):
    clean = []

    for row in rows:
        if (
            len(row) >= 9
            and str(row[8]) == "1"
        ):
            clean.append([
                int(row[0]),
                *[
                    float(value)
                    for value in row[1:5]
                ],
            ])

    frame = pd.DataFrame(
        clean,
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

    if not frame.empty:
        values = frame[
            ["open", "high", "low", "close"]
        ].to_numpy()

        if (
            not np.isfinite(values).all()
            or (values <= 0).any()
        ):
            raise ValueError(
                "В свечах есть некорректные цены."
            )

    frame["time"] = pd.to_datetime(
        frame["ts"],
        unit="ms",
        utc=True,
    )

    return frame


@st.cache_data(ttl=30, show_spinner=False)
def get_price(coin, market="SWAP"):
    symbol = instrument(
        coin,
        market,
    )

    rows = okx_request(
        "/market/ticker",
        {"instId": symbol},
    )

    if not rows:
        raise ValueError(
            f"Нет котировки {symbol}"
        )

    row = rows[0]
    price = float(row["last"])
    timestamp = int(row["ts"]) / 1000

    if (
        not np.isfinite(price)
        or price <= 0
        or abs(time.time() - timestamp) > 180
    ):
        raise ValueError(
            f"Котировка {symbol} "
            "отсутствует или устарела."
        )

    return dict(
        price=price,
        timestamp=timestamp,
    )


@st.cache_data(ttl=180, show_spinner=False)
def get_daily(coin):
    rows = okx_request(
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
            f"Недостаточно дневных свечей для {coin}."
        )

    return frame


@st.cache_data(ttl=300, show_spinner=False)
def get_history_14d(coin, market="SWAP"):
    hour = 3_600_000

    end = (
        int(time.time() * 1000)
        // hour
        * hour
    )

    start = end - 14 * 24 * hour

    after = end
    previous = None
    raw = []

    for _ in range(10):
        batch = okx_request(
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

        raw.extend(batch)

        oldest = min(
            int(row[0])
            for row in batch
        )

        if oldest <= start or oldest == previous:
            break

        previous = oldest
        after = oldest

        time.sleep(0.12)

    frame = parse_candles(raw)

    frame = frame[
        (frame.ts >= start)
        & (frame.ts < end)
    ].reset_index(drop=True)

    expected = np.arange(
        start,
        end,
        hour,
        dtype=np.int64,
    )

    actual = frame.ts.to_numpy(
        dtype=np.int64
    )

    if not np.array_equal(
        actual,
        expected,
    ):
        raise ValueError(
            f"История неполная: "
            f"{len(frame)} из 336 закрытых свечей. "
            "Тест не запускается."
        )

    return frame


# =========================================================
# MARKET SCANNER
# =========================================================

def scan_one(coin):
    frame = get_daily(coin)

    adx_indicator = ADXIndicator(
        frame.high,
        frame.low,
        frame.close,
        window=14,
        fillna=False,
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
            frame.close,
            window=14,
            fillna=False,
        ).rsi().iloc[-1]
    )

    if not np.isfinite(
        [adx, plus_di, minus_di, rsi]
    ).all():
        raise ValueError(
            "Индикаторы ещё не готовы."
        )

    if adx < 25:
        signal = "GRID"
        action = "Подготовить Grid"

    elif plus_di > minus_di:
        signal = "LONG"
        action = "Рассмотреть DCA Long"

    elif minus_di > plus_di:
        signal = "SHORT"
        action = "Рассмотреть DCA Short"

    else:
        signal = "WAIT"
        action = "Ждать"

    return {
        "Монета": coin,
        "Цена": get_price(coin)["price"],
        "Сигнал": signal,
        "Действие": action,
        "Шаг%": DEFAULT_STEP,
        "Тейк%": DEFAULT_TP,
        "ADX": adx,
        "RSI": rsi,
    }


def scanner_page():
    heading(
        "Сканер рынка",
        "20 монет · OKX USDT-SWAP · "
        "RSI и ADX на закрытых свечах 1D",
    )

    if st.button(
        "Сканировать 20 монет",
        use_container_width=True,
    ):
        rows = []
        errors = []
        progress = st.progress(0.0)

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

        st.session_state["scan"] = dict(
            rows=rows,
            errors=errors,
            time=datetime.now(
                timezone.utc
            ).strftime(
                "%d.%m.%Y %H:%M UTC"
            ),
        )

    result = st.session_state["scan"]

    if result is None:
        st.info(
            "Нажми «Сканировать 20 монет»."
        )
        return

    st.caption(
        "Последнее сканирование: "
        + result["time"]
    )

    if result["errors"]:
        with st.expander(
            f"Не удалось рассчитать: "
            f"{len(result['errors'])}"
        ):
            for error in result["errors"]:
                st.write(error)

    if not result["rows"]:
        st.warning(
            "Нет доступных результатов. "
            "Повтори сканирование позже."
        )
        return

    frame = pd.DataFrame(
        result["rows"]
    )

    styled = (
        frame.style
        .set_properties(**{
            "background-color": "#ffffff",
            "color": "#172033",
        })
        .format({
            "Цена": "{:,.6f}",
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
        "Монета для подготовки",
        frame["Монета"].tolist(),
        key="selected_scan_coin",
    )

    row = next(
        item
        for item in result["rows"]
        if item["Монета"] == coin
    )

    columns = st.columns(2)

    if columns[0].button(
        "Создать DCA",
        use_container_width=True,
    ):
        navigate(
            "dca",
            dict(
                coin=coin,
                direction=(
                    "SHORT"
                    if row["Сигнал"] == "SHORT"
                    else "LONG"
                ),
                step=float(row["Шаг%"]),
                tp=float(row["Тейк%"]),
            ),
        )

    if columns[1].button(
        "Создать Grid",
        use_container_width=True,
    ):
        navigate(
            "grid",
            dict(
                coin=coin,
                lower=float(row["Цена"]) * 0.9,
                upper=float(row["Цена"]) * 1.1,
            ),
        )

    st.caption(
        "GRID — сценарий, не рекомендация "
        "выбрать направление DCA. "
        "Для GRID/WAIT форма DCA открывается "
        "как редактируемый LONG-шаблон. "
        "Шаг 2% и тейк 1.5% — начальные настройки, "
        "не результат оптимизации."
    )


# =========================================================
# DCA BACKTEST
# =========================================================

def simulate_dca(
    frame,
    budget,
    direction,
    step,
    tp,
    order_margin,
    leverage,
    max_so,
    fee,
):
    if (
        direction not in ("LONG", "SHORT")
        or min(
            budget,
            step,
            tp,
            order_margin,
            leverage,
        ) <= 0
        or max_so < 0
        or fee < 0
    ):
        raise ValueError(
            "Некорректные параметры DCA."
        )

    rate = fee / 100
    sign = 1 if direction == "LONG" else -1

    if (
        order_margin
        * (1 + leverage * rate)
        > budget
    ):
        raise ValueError(
            "Бюджет не покрывает "
            "первый ордер и комиссию."
        )

    balance = float(budget)
    quantity = 0.0
    average = 0.0
    anchor = 0.0
    margin_used = 0.0

    cycles = 0
    additions = 0
    executed_so = 0
    fees = 0.0
    skipped = 0

    curve = []

    for row in frame.itertuples(index=False):
        price = float(row.close)

        if quantity == 0:
            nominal = order_margin * leverage
            entry_fee = nominal * rate

            if order_margin + entry_fee <= balance:
                quantity = nominal / price
                average = price
                anchor = price
                margin_used = order_margin
                executed_so = 0

                balance -= entry_fee
                fees += entry_fee

        elif (
            sign
            * (price / average - 1)
            * 100
            >= tp
        ):
            closing_fee = (
                quantity * price * rate
            )

            balance += (
                sign
                * quantity
                * (price - average)
                - closing_fee
            )

            fees += closing_fee

            quantity = 0.0
            average = 0.0
            margin_used = 0.0

            cycles += 1

        elif (
            executed_so < max_so
            and sign
            * (price / anchor - 1)
            * 100
            <= -step * (executed_so + 1)
        ):
            nominal = order_margin * leverage
            entry_fee = nominal * rate

            floating = (
                sign
                * quantity
                * (price - average)
            )

            available_equity = (
                balance + min(floating, 0.0)
            )

            if (
                margin_used
                + order_margin
                + entry_fee
                <= available_equity
            ):
                new_quantity = nominal / price

                average = (
                    quantity * average + nominal
                ) / (
                    quantity + new_quantity
                )

                quantity += new_quantity
                margin_used += order_margin
                balance -= entry_fee

                fees += entry_fee
                executed_so += 1
                additions += 1

            else:
                skipped += 1

        floating = (
            sign
            * quantity
            * (price - average)
            if quantity
            else 0.0
        )

        equity = balance + floating

        if equity <= 0:
            raise ValueError(
                "Модельный капитал исчерпан. "
                "Тест остановлен: "
                "биржевая ликвидация "
                "в этой модели не рассчитывается."
            )

        curve.append({
            "Время UTC": row.time,
            "Капитал USDT": equity,
        })

    if not curve:
        raise ValueError(
            "Нет свечей для теста."
        )

    final_equity = curve[-1]["Капитал USDT"]

    return dict(
        roi=(
            final_equity / budget - 1
        ) * 100,
        cycles=cycles,
        pnl=final_equity - budget,
        fees=fees,
        floating=floating,
        additions=additions,
        skipped=skipped,
        curve=pd.DataFrame(curve),
    )


# =========================================================
# GRID BACKTEST
# =========================================================

def simulate_grid(
    frame,
    budget,
    lower,
    upper,
    grids,
    fee,
):
    if (
        budget <= 0
        or lower <= 0
        or upper <= lower
        or grids < 2
        or fee < 0
    ):
        raise ValueError(
            "Проверь бюджет и диапазон Grid."
        )

    rate = fee / 100

    levels = np.linspace(
        lower,
        upper,
        grids + 1,
    )

    order_quote = (
        budget / grids / (1 + rate)
    )

    cash = float(budget)
    lots = {}
    fees = 0.0
    cycles = 0
    previous = None
    curve = []

    for row in frame.itertuples(index=False):
        price = float(row.close)

        for index in list(lots):
            if price >= levels[index + 1]:
                gross = (
                    lots.pop(index) * price
                )

                cash += gross * (1 - rate)
                fees += gross * rate
                cycles += 1

        if previous is not None:
            for index, level in enumerate(
                levels[:-1]
            ):
                cost = (
                    order_quote * (1 + rate)
                )

                if (
                    index not in lots
                    and previous > level >= price
                    and cash + 1e-9 >= cost
                ):
                    lots[index] = (
                        order_quote / price
                    )

                    cash -= cost
                    fees += order_quote * rate

        equity = (
            cash
            + sum(lots.values()) * price
        )

        curve.append({
            "Время UTC": row.time,
            "Капитал USDT": equity,
        })

        previous = price

    if not curve:
        raise ValueError(
            "Нет свечей для теста."
        )

    final_equity = curve[-1]["Капитал USDT"]

    return dict(
        roi=(
            final_equity / budget - 1
        ) * 100,
        cycles=cycles,
        pnl=final_equity - budget,
        fees=fees,
        open_lots=len(lots),
        curve=pd.DataFrame(curve),
    )


# =========================================================
# BACKTEST DISPLAY
# =========================================================

def result_panel(kind, current_params):
    saved = st.session_state[
        "results"
    ].get(kind)

    if not saved:
        return

    st.subheader(
        "Последний бэктест"
    )

    if saved["params"] != current_params:
        st.warning(
            "Параметры изменены. "
            "Ниже старый результат — "
            "нажми «Проверить на истории» "
            "для пересчёта."
        )

    result = saved["result"]
    columns = st.columns(3)

    columns[0].metric(
        "Доходность от бюджета",
        f"{result['roi']:.2f}%",
    )

    columns[1].metric(
        "Закрытых циклов",
        result["cycles"],
    )

    columns[2].metric(
        "Результат USDT",
        f"{result['pnl']:.2f}",
    )

    st.caption(
        saved["description"]
    )

    st.line_chart(
        result["curve"].set_index(
            "Время UTC"
        )
    )

    st.caption(
        f"Комиссии модели: "
        f"{result['fees']:.4f} USDT. "
        "Открытая позиция включена "
        "в итоговый капитал по последней цене; "
        "комиссия её будущего закрытия "
        "не вычтена."
    )

    if kind == "dca":
        st.caption(
            f"Усреднений: "
            f"{result['additions']} · "
            f"Отложенных попыток СО "
            f"из-за бюджета: "
            f"{result['skipped']} · "
            f"Открытый PnL: "
            f"{result['floating']:.4f} USDT"
        )

    else:
        st.caption(
            f"Незакрытых лотов: "
            f"{result['open_lots']}"
        )

    with st.expander(
        "Параметры этого расчёта"
    ):
        st.write(
            saved["params"]
        )


def run_backtest(kind, params):
    st.session_state[
        "results"
    ].pop(
        kind,
        None,
    )

    with st.spinner(
        "Загружаю 14 дней истории 1H и считаю..."
    ):
        market = (
            "SWAP"
            if kind == "dca"
            else "SPOT"
        )

        frame = get_history_14d(
            params["coin"],
            market,
        )

        calculation = {
            key: value
            for key, value in params.items()
            if key != "coin"
        }

        if kind == "dca":
            result = simulate_dca(
                frame,
                **calculation,
            )

        else:
            result = simulate_grid(
                frame,
                **calculation,
            )

        description = (
            f"{instrument(params['coin'], market)} · "
            f"{len(frame)} свечей 1H · "
            f"{frame.time.iloc[0]} — "
            f"{frame.time.iloc[-1]} "
            "(время начала свечей, UTC)"
        )

        st.session_state[
            "results"
        ][kind] = dict(
            params=dict(params),
            result=result,
            description=description,
        )


# =========================================================
# DCA PAGE
# =========================================================

def dca_page():
    heading(
        "DCA",
        "Редактируемый план "
        "и упрощённая проверка "
        "на истории OKX USDT-SWAP",
    )

    defaults = st.session_state[
        "dca_defaults"
    ]

    with st.form("dca_form"):
        coin = st.selectbox(
            "Монета",
            COINS,
            index=COINS.index(
                defaults["coin"]
            ),
            key="dca_coin",
        )

        directions = [
            "LONG",
            "SHORT",
        ]

        direction = st.selectbox(
            "Направление",
            directions,
            index=directions.index(
                defaults["direction"]
            ),
            key="dca_direction",
        )

        budget = st.number_input(
            "Общий бюджет, USDT",
            min_value=10.0,
            value=float(
                defaults["budget"]
            ),
            step=10.0,
            key="dca_budget",
        )

        columns = st.columns(2)

        step = columns[0].number_input(
            "Шаг СО от первого входа, %",
            min_value=0.1,
            max_value=25.0,
            value=float(
                defaults["step"]
            ),
            step=0.1,
            key="dca_step",
        )

        tp = columns[1].number_input(
            "Тейк от средней цены, %",
            min_value=0.1,
            max_value=30.0,
            value=float(
                defaults["tp"]
            ),
            step=0.1,
            key="dca_tp",
        )

        with st.expander(
            "Параметры модели"
        ):
            order_margin = st.number_input(
                "Маржа каждого ордера, USDT",
                min_value=1.0,
                value=float(
                    defaults["order_margin"]
                ),
                key="dca_order_margin",
            )

            leverage = st.number_input(
                "Плечо",
                min_value=1,
                max_value=10,
                value=int(
                    defaults["leverage"]
                ),
                key="dca_leverage",
            )

            max_so = st.number_input(
                "Максимум СО в цикле",
                min_value=0,
                max_value=10,
                value=int(
                    defaults["max_so"]
                ),
                key="dca_max_so",
            )

            fee = st.number_input(
                "Комиссия модели за сторону, %",
                min_value=0.0,
                max_value=1.0,
                value=float(
                    defaults["fee"]
                ),
                step=0.01,
                key="dca_fee",
            )

        st.caption(
            "По умолчанию 10 USDT — маржа ордера: "
            "при 3x номинал равен 30 USDT. "
            "Это не означает, что весь бюджет "
            "используется сразу."
        )

        columns = st.columns(2)

        test = columns[0].form_submit_button(
            "Проверить на истории",
            use_container_width=True,
        )

        save = columns[1].form_submit_button(
            "Сохранить план в памяти",
            use_container_width=True,
        )

    params = dict(
        coin=coin,
        direction=direction,
        budget=budget,
        step=step,
        tp=tp,
        order_margin=order_margin,
        leverage=int(leverage),
        max_so=int(max_so),
        fee=fee,
    )

    if test or save:
        st.session_state[
            "dca_defaults"
        ] = dict(params)

        try:
            if (
                direction == "LONG"
                and step * max_so >= 100
            ):
                raise ValueError(
                    "Шаг и число СО создают "
                    "неположительную цену уровня."
                )

            if (
                order_margin
                * (1 + leverage * fee / 100)
                > budget
            ):
                raise ValueError(
                    "Бюджет не покрывает "
                    "первый ордер с комиссией."
                )

            if test:
                run_backtest(
                    "dca",
                    params,
                )

            else:
                st.session_state[
                    "plans"
                ].append(
                    dict(
                        strategy="DCA",
                        params=dict(params),
                        created_at=datetime.now(
                            timezone.utc
                        ).isoformat(),
                    )
                )

                st.success(
                    "План сохранён в текущей сессии. "
                    "Сделка на OKX не открывалась."
                )

        except Exception as error:
            st.error(
                str(error)
            )

    result_panel(
        "dca",
        params,
    )

    st.info(
        "Модель: вход по первому закрытию 1H; "
        "СО — фиксированными суммами "
        "на линейных уровнях от первого входа; "
        "максимум одно исполнение за свечу; "
        "тейк по движению цены от средней, "
        "не по ROI маржи. "
        "Новый цикл — не раньше следующей свечи."
    )

    st.caption(
        "Без funding, ликвидации, проскальзывания "
        "и внутрисвечного пути. "
        "Плечо 3x не делает эту модель "
        "точным биржевым тестом. "
        "Комиссия — настраиваемое допущение, "
        "не проверенный тариф твоего аккаунта."
    )


# =========================================================
# GRID PAGE
# =========================================================

def grid_page():
    heading(
        "Grid",
        "Упрощённый Spot Long Grid · "
        "арифметические уровни · без плеча",
    )

    defaults = st.session_state[
        "grid_defaults"
    ]

    with st.form("grid_form"):
        coin = st.selectbox(
            "Монета",
            COINS,
            index=COINS.index(
                defaults["coin"]
            ),
            key="grid_coin",
        )

        budget = st.number_input(
            "Бюджет, USDT",
            min_value=10.0,
            value=float(
                defaults["budget"]
            ),
            step=10.0,
            key="grid_budget",
        )

        columns = st.columns(2)

        lower = columns[0].number_input(
            "Нижняя граница",
            min_value=0.0,
            value=float(
                defaults["lower"]
            ),
            format="%.8f",
            key="grid_lower",
        )

        upper = columns[1].number_input(
            "Верхняя граница",
            min_value=0.0,
            value=float(
                defaults["upper"]
            ),
            format="%.8f",
            key="grid_upper",
        )

        grids = st.number_input(
            "Количество интервалов Grid",
            min_value=2,
            max_value=100,
            value=int(
                defaults["grids"]
            ),
            key="grid_grids",
        )

        fee = st.number_input(
            "Комиссия модели за сторону, %",
            min_value=0.0,
            max_value=1.0,
            value=float(
                defaults["fee"]
            ),
            step=0.01,
            key="grid_fee",
        )

        st.caption(
            "Введи диапазон вручную. "
            "После перехода из сканера "
            "предложено ±10% от цены SWAP: "
            "это лишь начальный шаблон; "
            "Spot-цена может отличаться."
        )

        columns = st.columns(2)

        test = columns[0].form_submit_button(
            "Проверить на истории",
            use_container_width=True,
        )

        save = columns[1].form_submit_button(
            "Сохранить план в памяти",
            use_container_width=True,
        )

    params = dict(
        coin=coin,
        budget=budget,
        lower=lower,
        upper=upper,
        grids=int(grids),
        fee=fee,
    )

    if test or save:
        st.session_state[
            "grid_defaults"
        ] = dict(params)

        try:
            if lower <= 0 or upper <= lower:
                raise ValueError(
                    "Нижняя граница должна быть > 0, "
                    "верхняя — выше нижней."
                )

            if test:
                run_backtest(
                    "grid",
                    params,
                )

            else:
                st.session_state[
                    "plans"
                ].append(
                    dict(
                        strategy="Grid",
                        params=dict(params),
                        created_at=datetime.now(
                            timezone.utc
                        ).isoformat(),
                    )
                )

                st.success(
                    "Grid-план сохранён "
                    "в текущей сессии. "
                    "Сделка не открывалась."
                )

        except Exception as error:
            st.error(
                str(error)
            )

    result_panel(
        "grid",
        params,
    )

    st.info(
        "Модель начинает с USDT, "
        "без начальной покупки монеты. "
        "При пересечении уровня вниз "
        "покупает по закрытию 1H, "
        "при достижении следующего уровня вверх "
        "продаёт по закрытию. "
        "Цикл — один закрытый лот. "
        "Оставшиеся монеты учитываются в капитале."
    )

    st.caption(
        "Это не симуляция Futures Neutral Grid "
        "и не точное воспроизведение OKX Grid. "
        "Внутрисвечные касания, очередь ордеров "
        "и проскальзывание не учитываются."
    )


# =========================================================
# OPEN POSITION / CURRENT QUOTES
# =========================================================

def position_page():
    heading(
        "Открытая позиция",
        "Текущие котировки BTC и ETH. "
        "Фактическую позицию на OKX "
        "приложение не читает.",
    )

    if st.button(
        "Обновить котировки"
    ):
        get_price.clear()
        okx_request.clear()

    columns = st.columns(2)

    for column, coin in zip(
        columns,
        ["BTC", "ETH"],
    ):
        try:
            quote = get_price(coin)

            column.metric(
                coin + " / USDT-SWAP",
                f"{quote['price']:,.2f}",
            )

            timestamp = datetime.fromtimestamp(
                quote["timestamp"],
                timezone.utc,
            ).strftime(
                "%H:%M:%S UTC"
            )

            column.caption(
                "Данные OKX: " + timestamp
            )

        except Exception as error:
            column.error(
                str(error)
            )


# =========================================================
# MAIN
# =========================================================

def main():
    initialize()
    styles()

    with st.sidebar:
        st.title(
            "OKX Terminal"
        )

        page = st.radio(
            "Раздел",
            PAGES,
            key="menu",
            label_visibility="collapsed",
        )

        st.caption(
            "Публичный API. "
            "Торговые команды не отправляются."
        )

        st.warning(
            "Планы и результаты хранятся "
            "только в текущей сессии. "
            "После её потери они исчезнут."
        )

    if page == "2. Сканер рынка":
        scanner_page()

    elif page == "3. DCA":
        dca_page()

    elif page == "4. Grid":
        grid_page()

    elif page == "5. Открытая позиция":
        position_page()

    else:
        st.title(
            page.split(". ", 1)[1]
        )

        st.info(
            "В разработке"
        )


main()
