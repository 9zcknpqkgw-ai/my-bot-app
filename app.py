import hashlib
import html
import json
import math
import os
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from plotly.subplots import make_subplots
from ta.momentum import RSIIndicator
from ta.trend import ADXIndicator
from ta.volatility import AverageTrueRange

DB = os.getenv("BOT_DB", "bots.sqlite3")
API = "https://www.okx.com/api/v5"
COINS = ["BTC","ETH","SOL","BNB","XRP","DOGE","ADA","AVAX","LINK","DOT","TON","TRX","LTC","NEAR","APT","ARB","OP","SUI","PEPE","INJ"]
BARS = {"15m":900000,"30m":1800000,"1H":3600000,"4H":14400000,"1Dutc":86400000}
GREEN,RED,BLUE,YELLOW="#00EFA7","#FF5575","#49BFFF","#FFD166"
API_LOCK=threading.Lock()
LAST_REQUEST=[0.0]


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connection():
    db=sqlite3.connect(DB,timeout=30)
    db.row_factory=sqlite3.Row
    db.execute("PRAGMA busy_timeout=30000")
    return db


def init_db():
    with connection() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS bots (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, config TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'Проект', confirmed TEXT,
          checked REAL NOT NULL DEFAULT 0, snapshot TEXT, state TEXT,
          lease REAL NOT NULL DEFAULT 0, created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tests (
          id INTEGER PRIMARY KEY AUTOINCREMENT, bot_id TEXT NOT NULL,
          config_hash TEXT NOT NULL, created TEXT NOT NULL, result TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, bot_id TEXT,
          created TEXT NOT NULL, kind TEXT NOT NULL, message TEXT NOT NULL,
          notify TEXT NOT NULL DEFAULT 'off');
        """)


def config_hash(c):
    return hashlib.sha256(json.dumps(c,sort_keys=True).encode()).hexdigest()[:16]


def event(bot_id,kind,message,notify=False):
    with connection() as db:
        cur=db.execute("INSERT INTO events(bot_id,created,kind,message,notify) VALUES(?,?,?,?,?)",(bot_id,stamp(),kind,message,"pending" if notify else "off"))
        return cur.lastrowid


def bot_get(bot_id):
    with connection() as db:
        row=db.execute("SELECT * FROM bots WHERE id=?",(bot_id,)).fetchone()
    if not row: return None
    result=dict(row)
    for key in ["config","confirmed","snapshot"]:
        result[key]=json.loads(result[key]) if result[key] else None
    return result


def bot_list():
    with connection() as db:
        ids=[r[0] for r in db.execute("SELECT id FROM bots ORDER BY created DESC")]
    return [bot_get(i) for i in ids]


def tests_for(bot_id):
    with connection() as db:
        return [dict(r) for r in db.execute("SELECT * FROM tests WHERE bot_id=? ORDER BY id DESC LIMIT 20",(bot_id,))]


def latest_test(bot):
    for row in tests_for(bot["id"]):
        if row["config_hash"]==config_hash(bot["config"]): return json.loads(row["result"])
    return None


def api_get(endpoint,params=None):
    error="Нет ответа OKX"
    for attempt in range(4):
        with API_LOCK:
            time.sleep(max(0,.18-(time.monotonic()-LAST_REQUEST[0])))
            LAST_REQUEST[0]=time.monotonic()
        try:
            response=requests.get(API+endpoint,params=params,timeout=(8,25),headers={"User-Agent":"OKX-Bot-Manager/1.0"})
            if response.status_code==429:
                error="Лимит запросов OKX"; time.sleep(1+attempt); continue
            response.raise_for_status()
            data=response.json()
            if data.get("code")=="0": return data.get("data",[])
            error=f"OKX {data.get('code')}: {data.get('msg','')}"
        except (requests.RequestException,ValueError) as exc:
            error=str(exc)
        time.sleep(.5*(attempt+1))
    raise RuntimeError(error)


@st.cache_data(ttl=3600,show_spinner=False)
def instrument_map(market):
    rows=api_get("/public/instruments",{"instType":"SPOT" if market=="Спот" else "SWAP"})
    result={}
    for r in rows:
        symbol=r.get("instId","")
        valid=r.get("quoteCcy")=="USDT" if market=="Спот" else r.get("settleCcy")=="USDT" and r.get("ctType")=="linear" and symbol.endswith("-USDT-SWAP")
        if valid and r.get("state")=="live": result[symbol]=r
    if not result: raise RuntimeError("Нет доступных USDT-инструментов")
    return result


@st.cache_data(ttl=45,show_spinner=False)
def market_tickers(market):
    return {r["instId"]:r for r in api_get("/market/tickers",{"instType":"SPOT" if market=="Спот" else "SWAP"})}


def live_price(symbol):
    rows=api_get("/market/ticker",{"instId":symbol})
    if not rows or float(rows[0].get("last",0) or 0)<=0: raise RuntimeError("Нет цены")
    return float(rows[0]["last"])


def frame(rows):
    if not rows: raise RuntimeError("Нет свечей")
    cols=["ts","o","h","l","c","vol","baseVol","quoteVol","confirm"]
    df=pd.DataFrame(rows,columns=cols)
    for col in cols: df[col]=pd.to_numeric(df[col],errors="coerce")
    df=df[df.confirm==1].dropna(subset=["ts","o","h","l","c"])
    df=df[(df[["o","h","l","c"]]>0).all(axis=1)].drop_duplicates("ts").sort_values("ts")
    df["time"]=pd.to_datetime(df.ts,unit="ms",utc=True)
    return df.reset_index(drop=True)


@st.cache_data(ttl=90,show_spinner=False)
def candles(symbol,bar):
    df=frame(api_get("/market/candles",{"instId":symbol,"bar":bar,"limit":"300"}))
    if len(df)<60: raise RuntimeError("Нужно не менее 60 закрытых свечей")
    return df


@st.cache_data(ttl=1800,show_spinner=False)
def history(symbol,bar,start,end):
    cursor,rows=end,[]
    for _ in range(int((end-start)//BARS[bar]//100)+10):
        batch=api_get("/market/history-candles",{"instId":symbol,"bar":bar,"after":str(cursor),"limit":"100"})
        if not batch: break
        rows.extend(batch)
        oldest=min(int(r[0]) for r in batch)
        if oldest<=start: break
        if oldest>=cursor: raise RuntimeError("Ошибка пагинации OKX")
        cursor=oldest
    df=frame(rows)
    df=df[(df.ts>=start)&(df.ts<end)].reset_index(drop=True)
    if len(df)<30: raise RuntimeError("Недостаточно истории")
    return df


def indicators(df):
    df=df.copy()
    df["RSI"]=RSIIndicator(df.c,window=14).rsi()
    adx=ADXIndicator(df.h,df.l,df.c,window=14)
    df["ADX"],df["+DI"],df["-DI"]=adx.adx(),adx.adx_pos(),adx.adx_neg()
    df["ATR"]=AverageTrueRange(df.h,df.l,df.c,window=14).average_true_range()
    return df


def credentials():
    token,chat=os.getenv("TELEGRAM_TOKEN",""),os.getenv("TELEGRAM_CHAT_ID","")
    # Отдельный worker читает тот же локальный secrets.toml или env.
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    file=Path(".streamlit/secrets.toml")
    if file.exists():
        with file.open("rb") as f: section=tomllib.load(f).get("telegram",{})
        token,chat=section.get("token") or token,section.get("chat_id") or chat
    try:
        section=st.secrets.get("telegram",{})
        token,chat=section.get("token") or token,section.get("chat_id") or chat
    except Exception: pass
    return str(token).strip(),str(chat).strip()


def telegram(message):
    token,chat=credentials()
    if not token or not chat: return "error: Не заданы token / chat_id"
    try:
        r=requests.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":chat,"text":message[:4000]},timeout=(8,15))
        data=r.json()
        if r.ok and data.get("ok"): return "sent"
        return f"error: Telegram {data.get('error_code',r.status_code)}; проверьте настройки и Start у бота"
    except requests.Timeout: return "unknown: Тайм-аут; перед повтором проверьте Telegram"
    except Exception: return "error: Соединение с Telegram не установлено"


def dispatch():
    with connection() as db:
        rows=[dict(r) for r in db.execute("SELECT * FROM events WHERE notify='pending' ORDER BY id LIMIT 20")]
    for row in rows:
        # Атомарное присвоение события одному отправителю.
        with connection() as db:
            claim=db.execute("UPDATE events SET notify='sending' WHERE id=? AND notify='pending'",(row["id"],)).rowcount
        if not claim: continue
        result=telegram(f'OKX Manager | {row["kind"]}\nUTC: {row["created"]}\n{row["message"]}')
        with connection() as db: db.execute("UPDATE events SET notify=? WHERE id=?",(result,row["id"]))
        time.sleep(.1)


def defaults(seed=None):
    c=dict(market="Спот",strategy="DCA",side="Long",symbol="BTC-USDT",budget=100.,leverage=1.,base=10.,safety=12.,so=4,step=2.,step_mult=1.,amount_mult=1.2,tp=1.5,lower=90.,upper=110.,grids=10,grid_type="Арифметическая",stop=0.,fee=.05,loss_limit=10.,liq_warning=15.,stale_hours=24.,notify=True)
    if seed: c.update(seed)
    return c


def dca_orders(c,entry):
    sign=1 if c["side"]=="Long" else -1
    offsets=[0.]+[sum(c["step"]*c["step_mult"]**j for j in range(i)) for i in range(1,int(c["so"])+1)]
    amounts=[c["base"]]+[c["safety"]*c["amount_mult"]**i for i in range(int(c["so"]))]
    lev=c["leverage"] if c["market"]!="Спот" else 1.
    rows=[]; total=qty=notional=0.
    for i,(offset,amount) in enumerate(zip(offsets,amounts)):
        price=entry*(1-sign*offset/100)
        if price<=0: raise ValueError("Неположительная цена СО: уменьшите шаг/число СО")
        total+=amount; notional+=amount*lev; qty+=amount*lev/price
        rows.append({"Ордер":"База" if i==0 else f"СО {i}","Цена":price,"Сумма/маржа USDT":amount,"Номинал USDT":amount*lev,"Всего сумма/маржа":total,"Средняя":notional/qty})
    return pd.DataFrame(rows)


def reserve(c):
    sums=c["base"]+sum(c["safety"]*c["amount_mult"]**i for i in range(int(c["so"])))
    lev=c["leverage"] if c["market"]!="Спот" else 1.
    return sums*(1+lev*c["fee"]/100)


def validate(c):
    errors=[]
    if c["budget"]<=0: errors.append("Бюджет должен быть положительным")
    if c["market"]=="Спот" and c["side"]!="Long": errors.append("Спотовая модель поддерживает только Long")
    if c["strategy"]=="DCA":
        if c["side"]=="Neutral": errors.append("DCA не поддерживает Neutral")
        try: dca_orders(c,100.)
        except ValueError as exc: errors.append(str(exc))
        if reserve(c)>c["budget"]: errors.append(f'Резерв DCA с комиссией {reserve(c):.2f} превышает бюджет {c["budget"]:.2f}')
    elif c["lower"]<=0 or c["upper"]<=c["lower"]: errors.append("Проверьте границы Grid")
    return errors


def passport(c):
    rows=[("Рынок / продукт",f'{c["market"]} · {c["strategy"]}'),("Инструмент",c["symbol"]),("Направление",c["side"]),("Выделенный бюджет, USDT",c["budget"])]
    if c["market"]!="Спот": rows.append(("Leverage / Плечо",c["leverage"]))
    if c["strategy"]=="DCA":
        rows += [("Price steps / Шаг, %",c["step"]),("Price steps multiplier",c["step_mult"]),("TP target per cycle, %",c["tp"]),("Initial order amount/margin, USDT",c["base"]),("Safety order amount/margin, USDT",c["safety"]),("Max safety orders",c["so"]),("Amount multiplier",c["amount_mult"])]
    else:
        rows += [("Lower price / Нижняя",c["lower"]),("Upper price / Верхняя",c["upper"]),("Grid quantity / Интервалов",c["grids"]),("Grid type",c["grid_type"])]
    rows += [("Stop price / Стоп, 0 — не задан",c["stop"]),("Комиссия модели, % за сторону",c["fee"])]
    return pd.DataFrame(rows,columns=["Поле","Значение"])


def simulate(df,c,bar,start,end):
    # Для фьючерсов доступна только условная модель 1x, без funding и ликвидаций.
    if c["market"]!="Спот" and c["leverage"]!=1: raise ValueError("Бэктест с плечом выше 1x не реализован. Не подменяем его тестом без плеча.")
    if c["strategy"]=="Grid" and c["side"]!="Long": raise ValueError("Бэктест Short/Neutral Grid не реализован; сохранить и наблюдать такой бот можно.")
    fee=c["fee"]/100; initial=c["budget"]; cash=initial
    qty=locked=fees=realized=0.; cycles=0; next_so=1; orders=[]; lots={}; curve=[]; stopped=False
    sign=1 if c["side"]=="Long" else -1
    levels=np.linspace(c["lower"],c["upper"],int(c["grids"])+1) if c["grid_type"]=="Арифметическая" else np.geomspace(c["lower"],c["upper"],int(c["grids"])+1)
    active=[i for i in range(len(levels)-1) if levels[i]<float(df.iloc[0].o)]
    amount=initial/max(len(active),1)/(1+fee)
    if c["strategy"]=="Grid" and not active: raise ValueError("Нет buy-уровней ниже цены начала теста; сдвиньте диапазон или период")
    def equity(price):
        if c["strategy"]=="DCA": return cash+locked+sign*(qty*price-locked)-qty*price*fee
        return cash+sum(lot["qty"]*price*(1-fee) for lot in lots.values())
    def point(row,price): curve.append({"time":str(row.time),"equity":equity(price)})
    for _,row in df.iterrows():
        o,l,h,close=map(float,[row.o,row.l,row.h,row.c]); point(row,o)
        if c["strategy"]=="DCA":
            closed=False
            if qty>0:
                avg=locked/qty
                target=avg*(1+sign*c["tp"]/100)
                if sign*(o-target)>=0:
                    pnl=sign*(o*qty-locked); exit_fee=qty*o*fee
                    cash+=locked+pnl-exit_fee; realized+=pnl-exit_fee; fees+=exit_fee
                    qty=locked=0.; cycles+=1; closed=True; point(row,o)
            if qty==0 and not closed and c["base"]*(1+fee)<=cash:
                a=c["base"]; f=a*fee; cash-=a+f; qty=a/o; locked=a; fees+=f; realized-=f
                orders=dca_orders(c,o).to_dict("records"); next_so=1; point(row,o)
            adverse=l if sign==1 else h; favorable=h if sign==1 else l
            # Стоп имеет приоритет на неблагоприятном участке.
            stop=c["stop"]
            stop_hit=qty>0 and stop>0 and sign*(adverse-stop)<=0
            adverse_limit=max(adverse,stop) if sign==1 and stop_hit else min(adverse,stop) if stop_hit else adverse
            if qty>0:
                while next_so<=c["so"] and sign*(adverse_limit-orders[next_so]["Цена"])<=0:
                    level=orders[next_so]; fill=min(o,level["Цена"]) if sign==1 else max(o,level["Цена"])
                    point(row,fill); a=level["Номинал USDT"]; f=a*fee
                    if a+f>cash+1e-9: break
                    cash-=a+f; qty+=a/fill; locked+=a; fees+=f; realized-=f; next_so+=1; point(row,fill)
                point(row,adverse_limit)
                if stop_hit:
                    fill=min(o,stop) if sign==1 else max(o,stop)
                    pnl=sign*(qty*fill-locked); f=qty*fill*fee
                    cash+=locked+pnl-f; realized+=pnl-f; fees+=f; qty=locked=0.; stopped=True
                else:
                    target=locked/qty*(1+sign*c["tp"]/100)
                    if sign*(favorable-target)>=0:
                        pnl=sign*(qty*target-locked); f=qty*target*fee
                        cash+=locked+pnl-f; realized+=pnl-f; fees+=f; qty=locked=0.; cycles+=1
                    else: point(row,favorable)
        else:
            sold=set()
            for i,lot in list(lots.items()):
                if o>=lot["target"]:
                    gross=lot["qty"]*lot["target"]; f=gross*fee
                    cash+=gross-f; fees+=f; realized+=gross-f-lot["cost"]; del lots[i]; cycles+=1; sold.add(i)
            stop=c["stop"]; stop_hit=stop>0 and l<=stop
            low_limit=max(l,stop) if stop_hit else l
            for i in reversed(active):
                if i in lots or i in sold or low_limit>levels[i]: continue
                fill=min(o,float(levels[i])); point(row,fill); f=amount*fee
                if amount+f>cash+1e-9: continue
                cash-=amount+f; fees+=f; lots[i]={"qty":amount/fill,"cost":amount+f,"target":float(levels[i+1])}; point(row,fill)
            point(row,low_limit)
            if stop_hit:
                fill=min(o,stop)
                for lot in lots.values():
                    gross=lot["qty"]*fill; f=gross*fee
                    cash+=gross-f; fees+=f; realized+=gross-f-lot["cost"]
                lots={}; stopped=True
            else:
                for i in sorted(list(lots)):
                    lot=lots[i]
                    if h>=lot["target"]:
                        gross=lot["qty"]*lot["target"]; f=gross*fee
                        cash+=gross-f; fees+=f; realized+=gross-f-lot["cost"]; del lots[i]; cycles+=1; point(row,lot["target"])
                point(row,h)
        point(row,close)
        if stopped or curve[-1]["equity"]<=0: break
    f=pd.DataFrame(curve); peak=f.equity.cummax().clip(lower=initial); dd=peak-f.equity
    final=float(f.equity.iloc[-1]); expected=max(1,int((end-start)/BARS[bar]))
    metrics={"Итоговая equity":round(final,3),"PnL USDT":round(final-initial,3),"Доходность %":round((final/initial-1)*100,3),"Макс. просадка USDT":round(float(dd.max()),3),"Макс. просадка %":round(float((dd/peak*100).max()),3),"Комиссии уплачены":round(fees,4),"Завершено циклов":cycles,"Свечей загружено":len(df),"Покрытие %":round(min(100,len(df)/expected*100),2),"Пропуски":bool((df.ts.diff().dropna()!=BARS[bar]).any()),"Стоп сработал":stopped}
    # Сохраняем все контрольные точки, чтобы не скрывать внутрисвечную просадку.
    return {"metrics":metrics,"curve":curve,"bar":bar,"start":str(df.iloc[0].time),"end":str(df.iloc[-1].time),"config":c,"created":stamp()}


def recommendations(bot):
    c=bot["config"]; result=[]
    for error in validate(c): result.append("Блокирующее условие: "+error)
    if c["strategy"]=="DCA":
        result.append(f'Резерв всех ордеров с оценкой входных комиссий: {reserve(c):.2f} USDT из бюджета {c["budget"]:.2f}.')
        if c["tp"]<=2*c["fee"]: result.append("TP не покрывает приблизительную комиссию полного оборота; пересмотрите настройку.")
    else:
        step=(c["upper"]/c["lower"])**(1/c["grids"])-1 if c["grid_type"]=="Геометрическая" else (c["upper"]-c["lower"])/c["grids"]/c["upper"]
        result.append(f'Минимальный приблизительный шаг сетки: {step*100:.3f}%; комиссия оборота около {2*c["fee"]:.3f}%.')
        if step*100<=2*c["fee"]: result.append("Комиссия может съедать прибыль шага — уменьшите количество сеток или пересмотрите диапазон.")
    test=latest_test(bot)
    if not test: result.append("Нет бэктеста текущей версии: прежние результаты не подтверждают новые настройки.")
    else:
        m=test["metrics"]
        result.append(f'Тест текущей версии: доходность {m["Доходность %"]:.2f}%, просадка {m["Макс. просадка %"]:.2f}%. Это один период, не прогноз.')
        if m["Покрытие %"]<95 or m["Пропуски"]: result.append("История неполная или с пропусками; сравнение ограничено.")
        if m["Доходность %"]<=0: result.append("На выбранном периоде модель не дала положительного результата. Не используйте этот тест как основание для запуска.")
        if m["Макс. просадка %"]>c["loss_limit"]: result.append("Просадка теста превышает ваш порог риска; сократите риск конфигурации и протестируйте заново.")
    if c["market"]!="Спот": result.append("Фьючерсная ликвидация, funding, динамика маржи и очередь исполнений не моделируются. Плечо повышает риск; тест без этих факторов не подтверждает безопасность.")
    result.append("Минимальный размер ордера, округление, доступность продукта и фактическую маржу нужно подтвердить в интерфейсе OKX до запуска.")
    return result


def evaluate(bot,price):
    c=bot["config"]; p=bot["confirmed"] or {}; conditions=[]; reasons=[]
    qty=float(p.get("qty",0)); avg=float(p.get("avg",0)); liq=float(p.get("liq",0)); sign=1 if c["side"]=="Long" else -1
    pnl=None; loss=None; distance=None
    stale=(time.time()-float(p.get("updated",0)))/3600>c["stale_hours"]
    if stale: conditions.append("stale"); reasons.append("Данные позиции устарели: нужна ручная сверка с OKX")
    if qty>0 and avg>0 and c["side"]!="Neutral":
        pnl=sign*qty*(price-avg)-qty*price*c["fee"]/100-float(p.get("fees",0))
        loss=-pnl/c["budget"]*100
        if loss>=c["loss_limit"]: conditions.append("loss"); reasons.append(f'Оценочный убыток {loss:.1f}% бюджета достиг вашего порога')
    else: conditions.append("position_unknown"); reasons.append("Фактическая позиция не задана; точный PnL и здоровье неизвестны")
    if c["market"]!="Спот" and c["side"]!="Neutral":
        if liq>0:
            distance=sign*(price-liq)/price*100
            if distance<=c["liq_warning"]: conditions.append("liquidation"); reasons.append(f'До введённой ликвидации {distance:.2f}% по last-цене; проверьте mark price и позицию на OKX')
        else: conditions.append("liq_unknown"); reasons.append("Цена ликвидации неизвестна")
    if c["strategy"]=="Grid":
        if price<c["lower"]: conditions.append("below_grid"); reasons.append("Цена ниже диапазона Grid")
        elif price>c["upper"]: conditions.append("above_grid"); reasons.append("Цена выше диапазона Grid")
        elif min(price-c["lower"],c["upper"]-price)/(c["upper"]-c["lower"])<.05: conditions.append("grid_edge"); reasons.append("Цена у края диапазона Grid")
    else:
        anchor=float(p.get("anchor",0)); completed=int(p.get("completed",0))
        if anchor>0 and completed<c["so"]:
            orders=dca_orders(c,anchor); next_price=float(orders.iloc[completed+1]["Цена"])
            gap=sign*(price-next_price)/price*100
            if gap<=.3: conditions.append("safety_level"); reasons.append(f'Цена у/за расчётным уровнем СО {completed+1}: {next_price:.8f}. Исполнение НЕ подтверждено')
        if qty>0 and avg>0:
            target=avg*(1+sign*c["tp"]/100)
            if sign*(price-target)>=0: conditions.append("tp_level"); reasons.append(f'Цена у/за расчётным TP {target:.8f}; исполнение НЕ подтверждено')
    stop=c["stop"]
    if stop>0 and c["side"]!="Neutral" and sign*(price-stop)<=0: conditions.append("stop_level"); reasons.append("Цена у/за указанным стопом; проверьте исполнение на OKX")
    critical=any(x in conditions for x in ["liquidation","loss","stop_level"])
    unknown=any(x in conditions for x in ["stale","position_unknown","liq_unknown"])
    status="Высокий риск" if critical else "Нужна сверка" if unknown else "Внимание" if conditions else "Пороги не сработали"
    health=None if unknown else 20 if critical else 55 if conditions else 85
    return {"price":price,"pnl":pnl,"distance":distance,"status":status,"health":health,"reasons":reasons or ["По подтверждённым данным настроенные пороги не сработали; это не гарантия безопасности"],"code":"|".join(sorted(conditions)) or "ok","time":stamp()}


def check_bot(bot_id,force=False):
    now=time.time()
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row=db.execute("SELECT checked,lease,status FROM bots WHERE id=?",(bot_id,)).fetchone()
        if not row or row["status"]!="Наблюдается" or row["lease"]>now or (not force and now-row["checked"]<55): return
        db.execute("UPDATE bots SET lease=? WHERE id=?",(now+180,bot_id))
    bot=bot_get(bot_id)
    try:
        snapshot=evaluate(bot,live_price(bot["config"]["symbol"]))
        with connection() as db:
            db.execute("BEGIN IMMEDIATE")
            current=db.execute("SELECT state,status FROM bots WHERE id=?",(bot_id,)).fetchone()
            if current["status"]!="Наблюдается": return
            if current["state"]!=snapshot["code"]:
                message=f'{bot["name"]} | {bot["config"]["symbol"]}\n{snapshot["status"]}\nЦена: {snapshot["price"]:.8f}\n'+"\n".join(snapshot["reasons"])
                db.execute("INSERT INTO events(bot_id,created,kind,message,notify) VALUES(?,?,?,?,?)",(bot_id,stamp(),"Состояние изменилось",message,"pending" if bot["config"]["notify"] else "off"))
            db.execute("UPDATE bots SET snapshot=?,state=?,checked=? WHERE id=?",(json.dumps(snapshot,ensure_ascii=False),snapshot["code"],time.time(),bot_id))
    except Exception as exc:
        error={"error":str(exc),"time":stamp()}
        with connection() as db:
            old=db.execute("SELECT state,status FROM bots WHERE id=?",(bot_id,)).fetchone()
            if old and old["status"]=="Наблюдается":
                if old["state"]!="api_error":
                    db.execute("INSERT INTO events(bot_id,created,kind,message,notify) VALUES(?,?,?,?,?)",(bot_id,stamp(),"Данные недоступны",f'{bot["name"]}: нет свежих данных OKX. Оценка приостановлена.',"pending" if bot["config"]["notify"] else "off"))
                db.execute("UPDATE bots SET snapshot=?,state='api_error',checked=? WHERE id=?",(json.dumps(error,ensure_ascii=False),time.time(),bot_id))
    finally:
        with connection() as db: db.execute("UPDATE bots SET lease=0 WHERE id=?",(bot_id,))


def monitor_once(force=False):
    for bot in bot_list():
        if bot["status"]=="Наблюдается": check_bot(bot["id"],force)
    dispatch()


# ====================== UI ======================
def panel(title,text):
    st.markdown(f'<div class="panel"><h3>{html.escape(str(title))}</h3><p>{html.escape(str(text))}</p></div>',unsafe_allow_html=True)


def figure(fig,height=420):
    fig.update_layout(template="plotly_dark",height=height,paper_bgcolor="#0C1320",plot_bgcolor="#0C1320",font=dict(color="#E8EEF8"),margin=dict(l=15,r=15,t=50,b=25))
    st.plotly_chart(fig,use_container_width=True,config={"displaylogo":False})


def price_chart(symbol,bar):
    df=indicators(candles(symbol,bar)); fig=make_subplots(rows=3,cols=1,shared_xaxes=True,row_heights=[.6,.2,.2],vertical_spacing=.04)
    fig.add_trace(go.Candlestick(x=df.time,open=df.o,high=df.h,low=df.l,close=df.c,name="Цена",increasing_line_color=GREEN,decreasing_line_color=RED),row=1,col=1)
    fig.add_trace(go.Scatter(x=df.time,y=df.RSI,name="RSI 14",line=dict(color=BLUE)),row=2,col=1)
    for col,color in [("ADX",YELLOW),("+DI",GREEN),("-DI",RED)]: fig.add_trace(go.Scatter(x=df.time,y=df[col],name=col,line=dict(color=color)),row=3,col=1)
    for v in [30,70]: fig.add_hline(y=v,line_dash="dot",row=2,col=1)
    fig.add_hline(y=25,line_dash="dot",row=3,col=1)
    fig.update_layout(title=symbol,xaxis_rangeslider_visible=False,legend=dict(orientation="h"))
    figure(fig,650)


def go(page,bot_id=None,seed=None):
    st.session_state["nav"]=page
    if bot_id: st.session_state["selected_bot"]=bot_id
    if page=="Добавить / изменить":
        st.session_state["editing"]=bot_id
        st.session_state["seed"]=seed
        st.session_state["editor_nonce"]=uuid.uuid4().hex[:6]


def editor():
    edit_id=st.session_state.get("editing"); existing=bot_get(edit_id) if edit_id else None
    c=defaults(existing["config"] if existing else st.session_state.get("seed"))
    nonce=st.session_state.get("editor_nonce","new")
    if existing and existing["status"] in ["Наблюдается","Пауза"]:
        st.warning("Параметры запущенного бота не редактируются скрытно. Создайте копию проекта; фактическую позицию обновляйте в карточке.")
        st.button("Создать копию проекта",on_click=go,args=("Добавить / изменить",None,c)); return
    st.caption("Каждая карточка независима. Суммы фьючерсных DCA-ордеров здесь — маржа; для спота — USDT на покупку.")
    market=st.selectbox("Рынок",["Спот","Фьючерсы"],index=0 if c["market"]=="Спот" else 1,key=f"m_{nonce}")
    strategy=st.selectbox("Стратегия",["DCA","Grid"],index=0 if c["strategy"]=="DCA" else 1,key=f"s_{nonce}")
    sides=["Long"] if market=="Спот" else ["Long","Short"] if strategy=="DCA" else ["Long","Short","Neutral"]
    side=st.selectbox("Направление",sides,index=sides.index(c["side"]) if c["side"] in sides else 0,key=f"d_{nonce}_{market}_{strategy}")
    try:
        symbols=sorted(instrument_map(market)); candidate=c["symbol"].split("-")[0]+"-USDT"+("-SWAP" if market!="Спот" else "")
        symbol=st.selectbox("Инструмент OKX",symbols,index=symbols.index(candidate) if candidate in symbols else 0,key=f"sym_{nonce}_{market}")
    except Exception as exc: st.error(str(exc)); return
    with st.form(f"edit_{nonce}_{market}_{strategy}"):
        name=st.text_input("Название",value=existing["name"] if existing else f"{symbol.split('-')[0]} · {market} · {strategy}")
        a,b=st.columns(2); budget=a.number_input("Бюджет USDT",min_value=1.,value=float(c["budget"]))
        leverage=b.number_input("Плечо (для спота 1)",min_value=1.,max_value=125.,value=float(c["leverage"]) if market!="Спот" else 1.,disabled=market=="Спот")
        edited={**c,"market":market,"strategy":strategy,"side":side,"symbol":symbol,"budget":budget,"leverage":leverage}
        if strategy=="DCA":
            a,b,d=st.columns(3)
            edited["base"]=a.number_input("Первый ордер / маржа USDT",min_value=.01,value=float(c["base"]))
            edited["safety"]=b.number_input("Первая страховка / маржа USDT",min_value=.01,value=float(c["safety"]))
            edited["so"]=int(d.number_input("Максимум СО",min_value=0,max_value=30,value=int(c["so"])))
            a,b,d=st.columns(3)
            edited["tp"]=a.number_input("TP на цикл %",min_value=.01,value=float(c["tp"]))
            edited["step"]=b.number_input("Первый шаг %",min_value=.01,value=float(c["step"]))
            edited["amount_mult"]=d.number_input("Множитель суммы СО",min_value=1.,value=float(c["amount_mult"]))
            edited["step_mult"]=st.number_input("Множитель шага цены",min_value=1.,value=float(c["step_mult"]))
            st.caption("СО1 = первая страховка. СО2 = СО1 × множитель. Шаги накапливаются от первого входа; множитель шага 1 даёт 2%, 4%, 6%, 8%.")
        else:
            a,b,d=st.columns(3)
            edited["lower"]=a.number_input("Нижняя граница",min_value=.00000001,value=float(c["lower"]),format="%.8f")
            edited["upper"]=b.number_input("Верхняя граница",min_value=.00000001,value=float(c["upper"]),format="%.8f")
            edited["grids"]=int(d.number_input("Интервалов сетки",min_value=2,max_value=200,value=int(c["grids"])))
            edited["grid_type"]=st.selectbox("Тип сетки",["Арифметическая","Геометрическая"],index=0 if c["grid_type"]=="Арифметическая" else 1)
        a,b=st.columns(2)
        edited["stop"]=a.number_input("Стоп-цена, 0 — нет",min_value=0.,value=float(c["stop"]),format="%.8f")
        edited["fee"]=b.number_input("Комиссия за сторону %",min_value=0.,max_value=5.,value=float(c["fee"]),format="%.4f")
        a,b,d=st.columns(3)
        edited["loss_limit"]=a.number_input("Предупреждение: убыток % бюджета",min_value=.1,value=float(c["loss_limit"]))
        edited["liq_warning"]=b.number_input("Предупреждение: до ликвидации %",min_value=.1,value=float(c["liq_warning"]))
        edited["stale_hours"]=d.number_input("Сверять позицию каждые N часов",min_value=1.,value=float(c["stale_hours"]))
        edited["notify"]=st.checkbox("Telegram-события этого бота",value=bool(c["notify"]))
        save=st.form_submit_button("Сохранить отдельного бота",use_container_width=True)
    if save:
        errors=validate(edited)
        if not name.strip(): errors.append("Введите название")
        if errors:
            for e in errors: st.error(e)
        else:
            bot_id=edit_id or uuid.uuid4().hex
            with connection() as db:
                if existing: db.execute("UPDATE bots SET name=?,config=?,state=NULL WHERE id=?",(name.strip(),json.dumps(edited),bot_id))
                else: db.execute("INSERT INTO bots(id,name,config,created) VALUES(?,?,?,?)",(bot_id,name.strip(),json.dumps(edited),stamp()))
            event(bot_id,"Настройки изменены" if existing else "Проект создан",f"{name}: сохранена версия {config_hash(edited)}")
            st.success("Бот сохранён. Его настройки не меняют другие карточки.")
            st.button("Открыть карточку",on_click=go,args=("Карточка бота",bot_id))


def bot_detail():
    bots=bot_list()
    if not bots: st.info("Сначала добавьте бота"); return
    ids=[b["id"] for b in bots]; labels={b["id"]:b["name"] for b in bots}
    chosen=st.session_state.get("selected_bot")
    bot_id=st.selectbox("Бот",ids,index=ids.index(chosen) if chosen in ids else 0,format_func=lambda x:labels[x])
    bot=bot_get(bot_id); c=bot["config"]
    st.caption(f'{c["symbol"]} · {c["market"]} · {c["strategy"]} · {c["side"]} · {bot["status"]} · версия {config_hash(c)}')
    a,b=st.columns(2)
    a.button("Изменить настройки",on_click=go,args=("Добавить / изменить",bot_id))
    b.button("Копия для сравнения",on_click=go,args=("Добавить / изменить",None,c))
    tabs=st.tabs(["План и OKX","Бэктест","Запуск / сверка","Состояние","События"])
    with tabs[0]:
        for line in recommendations(bot): st.write("• "+line)
        st.subheader("Значения для переноса на OKX")
        st.dataframe(passport(c).astype(str),hide_index=True,use_container_width=True)
        st.download_button("Скачать памятку OKX",passport(c).to_csv(index=False).encode("utf-8-sig"),file_name=f"okx_{bot_id[:8]}.csv",mime="text/csv")
        st.caption("Это значения, не API-команда. Названия и единицы перепроверьте в выбранном продукте OKX. Плечо, минимальный ордер и доступность стратегии биржа проверяет отдельно. Автоперенос настроек не реализован.")
        if c["strategy"]=="DCA":
            anchor=st.number_input("Предполагаемый первый вход для плана",min_value=.00000001,value=float((bot["confirmed"] or {}).get("anchor",100.) or 100.),format="%.8f",key=f"plan_{bot_id}")
            st.dataframe(dca_orders(c,anchor),hide_index=True,use_container_width=True)
    with tabs[1]:
        st.warning("Приближённая симуляция: в Long путь свечи open → low → high → close, в Short open → high → low → close. Исполнение внутри свечи неизвестно. Без funding, очереди лимиток и ликвидаций. Futures выше 1x и Short/Neutral Grid не тестируются.")
        a,b=st.columns(2); bar=a.selectbox("Таймфрейм теста",list(BARS),key=f"bar_{bot_id}"); days=int(b.number_input("Дней",min_value=1,max_value=180,value=30,key=f"days_{bot_id}"))
        if st.button("Тестировать эту версию",key=f"test_{bot_id}"):
            try:
                if validate(c): raise ValueError("Сначала устраните ошибки конфигурации")
                end=int(time.time()*1000)//BARS[bar]*BARS[bar]; start=end-days*86400000
                with st.spinner("Загрузка постраничной истории и расчёт..."):
                    result=simulate(history(c["symbol"],bar,start,end),c,bar,start,end)
                with connection() as db: db.execute("INSERT INTO tests(bot_id,config_hash,created,result) VALUES(?,?,?,?)",(bot_id,config_hash(c),stamp(),json.dumps(result,ensure_ascii=False)))
                event(bot_id,"Бэктест завершён",f'{bot["name"]}: версия {config_hash(c)}, {days} дней, {bar}; доходность {result["metrics"]["Доходность %"]:.2f}%',c["notify"])
                dispatch(); st.success("Результат сохранён для этой версии")
            except Exception as exc: st.error(str(exc))
        tests=tests_for(bot_id)
        if tests:
            options=list(range(len(tests))); idx=st.selectbox("Сохранённый тест",options,format_func=lambda i:f'{tests[i]["created"]} · '+("текущая версия" if tests[i]["config_hash"]==config_hash(c) else "УСТАРЕВШАЯ версия"),key=f"testsel_{bot_id}")
            test=json.loads(tests[idx]["result"])
            if tests[idx]["config_hash"]!=config_hash(c): st.warning("Настройки изменены. Этот результат не относится к текущей конфигурации.")
            st.dataframe(pd.DataFrame([test["metrics"]]),hide_index=True,use_container_width=True)
            curve=pd.DataFrame(test["curve"]); curve["time"]=pd.to_datetime(curve.time,utc=True)
            fig=go.Figure(go.Scatter(x=curve.time,y=curve.equity,name="Equity",line=dict(color=GREEN)))
            fig.update_layout(title="Капитал с открытой позицией и оценкой комиссии выхода")
            figure(fig)
            st.caption(f'История {test["start"]} — {test["end"]}. Тест — не портфельный и не прогноз. TP в модели задан как движение от средней цены; комиссии вычитаются отдельно.')
        else: st.info("Эта карточка ещё не тестировалась")
    with tabs[2]:
        st.info("Сначала создайте/проверьте бота на OKX. Здесь вы подтверждаете факт запуска вручную; приложение ничего не запускает на бирже.")
        p=bot["confirmed"] or {}
        with st.form(f"confirm_{bot_id}"):
            a,b=st.columns(2)
            avg=a.number_input("Фактическая средняя входа",min_value=0.,value=float(p.get("avg",0)),format="%.8f")
            qty=b.number_input("Количество базовой монеты (не контрактов)",min_value=0.,value=float(p.get("qty",0)),format="%.8f")
            a,b=st.columns(2)
            liq=a.number_input("Ликвидация из OKX, 0 — неизвестна",min_value=0.,value=float(p.get("liq",0)),format="%.8f",disabled=c["market"]=="Спот")
            fees=b.number_input("Комиссии текущего входа USDT",min_value=0.,value=float(p.get("fees",0)),format="%.6f")
            anchor=st.number_input("Цена первого ордера ТЕКУЩЕГО цикла DCA",min_value=0.,value=float(p.get("anchor",0)),format="%.8f",disabled=c["strategy"]!="DCA")
            completed=int(st.number_input("Подтверждённые СО текущего цикла",min_value=0,max_value=int(c["so"]),value=min(int(p.get("completed",0)),int(c["so"])),disabled=c["strategy"]!="DCA"))
            consent=st.checkbox("Подтверждаю: бот реально запущен на OKX; данные сверены")
            submit=st.form_submit_button("Сохранить сверку и включить наблюдение")
        if submit:
            if not consent: st.error("Нужно подтвердить фактический запуск")
            elif c["side"]!="Neutral" and (avg<=0 or qty<=0): st.error("Введите среднюю цену и количество позиции; если позиции нет, оставьте мониторинг на паузе")
            else:
                confirmed=dict(avg=avg,qty=qty,liq=liq,fees=fees,anchor=anchor,completed=completed,updated=time.time(),time=stamp())
                with connection() as db: db.execute("UPDATE bots SET confirmed=?,status='Наблюдается',state=NULL,checked=0 WHERE id=?",(json.dumps(confirmed),bot_id))
                event(bot_id,"Ручная сверка",f'{bot["name"]}: пользователь подтвердил позицию на OKX',False)
                check_bot(bot_id,True); dispatch(); st.success("Данные сохранены; первая проверка выполнена. Состояние — в соседней вкладке.")
        a,b=st.columns(2)
        if a.button("Пауза наблюдения",key=f"pause_{bot_id}"):
            with connection() as db: db.execute("UPDATE bots SET status='Пауза' WHERE id=?",(bot_id,))
            event(bot_id,"Пауза",f'{bot["name"]}: остановлен только мониторинг, НЕ бот на бирже'); st.success("Мониторинг на паузе")
        if b.button("Пометить закрытым вручную",key=f"close_{bot_id}"):
            with connection() as db: db.execute("UPDATE bots SET status='Закрыт' WHERE id=?",(bot_id,))
            event(bot_id,"Закрытие подтверждено",f'{bot["name"]}: пользователь отметил закрытие; API-проверки нет'); st.success("Отмечено закрытие; торговые команды не отправлялись")
    with tabs[3]:
        if st.button("Проверить сейчас",key=f"check_{bot_id}"): check_bot(bot_id,True); dispatch()
        fresh=bot_get(bot_id); snap=fresh["snapshot"]
        if snap:
            if "error" in snap: st.error(snap["error"])
            else:
                panel(snap["status"]," · ".join(snap["reasons"]))
                a,b,d=st.columns(3); a.metric("Last-цена",f'{snap["price"]:.8f}'); b.metric("Условная оценка",f'{snap["health"]}/100' if snap["health"] is not None else "Неизвестно"); d.metric("Оценочный PnL",f'{snap["pnl"]:.4f} USDT' if snap["pnl"] is not None else "Неизвестно")
            st.caption(f'Проверка UTC: {snap["time"]}; сверка позиции: {(fresh["confirmed"] or {}).get("time","нет")}. Проверка цены не обновляет фактическую позицию.')
        else: st.info("Сначала подтвердите запуск и выполните проверку")
        st.warning("Без приватного API исполнения СО/TP, фактический PnL Grid, funding и ликвидация не подтверждаются. После нового цикла DCA обновляйте цену первого входа и число СО.")
        bar=st.selectbox("Таймфрейм графика",list(BARS),index=2,key=f"chartbar_{bot_id}")
        if st.checkbox("Показать свечи и индикаторы",key=f"chart_{bot_id}"):
            try: price_chart(c["symbol"],bar)
            except Exception as exc: st.error(str(exc))
    with tabs[4]: show_events(bot_id)


def show_events(bot_id=None):
    with connection() as db:
        rows=db.execute("SELECT e.*,b.name AS bot FROM events e LEFT JOIN bots b ON b.id=e.bot_id "+("WHERE e.bot_id=? " if bot_id else "")+"ORDER BY e.id DESC LIMIT 500",(bot_id,) if bot_id else ()).fetchall()
    if not rows: st.info("Событий пока нет"); return
    df=pd.DataFrame([dict(r) for r in rows]); df=df.rename(columns={"created":"Дата UTC","kind":"Событие","message":"Описание","notify":"Telegram","bot":"Бот"})
    st.dataframe(df[["Дата UTC","Бот","Событие","Описание","Telegram"]],hide_index=True,use_container_width=True)
    st.download_button("Скачать события CSV",df.to_csv(index=False).encode("utf-8-sig"),file_name="bot_events.csv",mime="text/csv",key=f"events_csv_{bot_id}")
    failed=df[df.Telegram.str.startswith(("error:","unknown:","sending"))]
    if not failed.empty:
        st.caption("Неоднозначная отправка не повторяется автоматически, чтобы не создавать дубли. Перед повтором проверьте чат.")
        selected=st.selectbox("Событие для ручной повторной отправки",failed.id.tolist(),key=f"retry_sel_{bot_id}")
        if st.button("Отправить выбранное событие ещё раз",key=f"retry_{bot_id}"):
            with connection() as db: db.execute("UPDATE events SET notify='pending' WHERE id=?",(int(selected),))
            dispatch(); st.success("Попытка выполнена; обновите страницу для статуса")


def scanner():
    a,b,d=st.columns(3); market=a.selectbox("Рынок",["Спот","Фьючерсы"]); strategy=b.selectbox("Подбираем для",["DCA","Grid"]); sides=["Long"] if market=="Спот" else ["Long","Short"] if strategy=="DCA" else ["Long","Short","Neutral"]
    side=d.selectbox("Направление",sides); bar=st.selectbox("Таймфрейм",list(BARS),index=2)
    st.caption("Сканер — технический фильтр, не подбор гарантированно прибыльных настроек. Создание проекта не запускает ордера.")
    if st.button("Проверить 20 монет"):
        try:
            info=instrument_map(market); ticker_map=market_tickers(market)
            symbols=[f'{coin}-USDT'+("-SWAP" if market!="Спот" else "") for coin in COINS]
            rows=[]; errors=[]; progress=st.progress(0.)
            def scan(symbol):
                last=indicators(candles(symbol,bar)).iloc[-1]; t=ticker_map[symbol]
                volume=float(t.get("volCcy24h",0) or 0)*(float(t.get("last",0) or 0) if market!="Спот" else 1.)
                listing=int(info[symbol].get("listTime",0) or 0)
                young=listing>0 and (time.time()*1000-listing)/86400000<180
                direction=last["+DI"]>last["-DI"] if side=="Long" else last["-DI"]>last["+DI"]
                candidate=last.ADX<25 if strategy=="Grid" else last.ADX>=25 and direction and 30<=last.RSI<=65
                status="Низкая ликвидность" if volume<10000000 else "Молодой инструмент" if young else "Кандидат" if candidate else "Ждать"
                return {"Инструмент":symbol,"Рынок":market,"Стратегия":strategy,"Направление":side,"Цена":float(t["last"]),"RSI":float(last.RSI),"ADX":float(last.ADX),"Объём USDT (оценка)":volume,"Статус":status}
            available=[s for s in symbols if s in info and s in ticker_map]
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures={pool.submit(scan,s):s for s in available}
                for i,future in enumerate(as_completed(futures),1):
                    try: rows.append(future.result())
                    except Exception as exc: errors.append(f"{futures[future]}: {exc}")
                    progress.progress(i/max(len(available),1))
            progress.empty(); rows.sort(key=lambda r:r["Объём USDT (оценка)"],reverse=True)
            st.session_state["scan"]={"rows":rows,"errors":errors,"missing":[s for s in symbols if s not in available],"bar":bar}
        except Exception as exc: st.error(str(exc))
    saved=st.session_state.get("scan")
    if saved:
        if saved["missing"]: st.warning("Недоступны: "+", ".join(saved["missing"]))
        if saved["errors"]:
            with st.expander("Ошибки"): st.write(saved["errors"])
        if saved["rows"]:
            df=pd.DataFrame(saved["rows"]); st.dataframe(df,hide_index=True,use_container_width=True)
            symbol=st.selectbox("Создать проект для",df["Инструмент"].tolist()); row=df[df["Инструмент"]==symbol].iloc[0]
            seed=defaults(dict(market=row["Рынок"],strategy=row["Стратегия"],side=row["Направление"],symbol=symbol,lower=float(row["Цена"])*.9,upper=float(row["Цена"])*1.1))
            st.button("Настроить своего бота на основе выбора",on_click=go,args=("Добавить / изменить",None,seed))
            if st.button("График выбранного инструмента"):
                try: price_chart(symbol,saved["bar"])
                except Exception as exc: st.error(str(exc))
            if st.button("Отправить сводку в Telegram"):
                message="Сканер: технические кандидаты\n"+"\n".join(f'{r["Инструмент"]} | {r["Рынок"]} | {r["Стратегия"]} {r["Направление"]}: {r["Статус"]}' for r in saved["rows"])
                st.info(telegram(message))


def main():
    st.set_page_config(page_title="OKX Bot Manager",page_icon="⚡",layout="wide",initial_sidebar_state="auto")
    init_db()
    st.markdown("""<style>
    :root{color-scheme:dark}.stApp{background:radial-gradient(900px 500px at 0 0,rgba(0,239,167,.06),transparent 65%),#060910;color:#E8EEF8}
    [data-testid="stSidebar"],[data-testid="stSidebar"]>div,[data-testid="stHeader"]{background:#0B101B!important;opacity:1!important}
    h1,h2,h3,h4,[data-testid="stWidgetLabel"] p,[data-testid="stMarkdownContainer"] p{color:#E8EEF8!important}
    [data-testid="stSidebar"] [data-testid="stRadio"] label{background:#152033;border:1px solid #2D3C56;border-radius:12px;padding:10px;margin-bottom:6px}
    [data-testid="stTextInput"] input,[data-testid="stNumberInput"] input{background:#121C2C!important;color:#F2F6FF!important;-webkit-text-fill-color:#F2F6FF!important}
    [data-baseweb="select"]>div{background:#121C2C!important;color:#F2F6FF!important}
    .stButton>button,.stFormSubmitButton>button{background:linear-gradient(110deg,#00EFA7,#3BBEFF)!important;border:0;border-radius:12px;min-height:44px;transition:transform .2s}
    .stButton>button p,.stFormSubmitButton>button p{color:#031019!important;font-weight:700!important}
    .stButton>button:hover{transform:translateY(-2px)}
    .panel{background:linear-gradient(135deg,#152034,#0D1420);border:1px solid #2B3B55;border-radius:16px;padding:18px;margin-bottom:14px}
    @media(max-width:768px){.block-container{padding:1rem 1rem 4rem!important}h1{font-size:1.9rem!important}}
    </style>""",unsafe_allow_html=True)
    pages=["Мои боты","Добавить / изменить","Карточка бота","Сканер / подбор","Журнал событий","Настройки"]
    with st.sidebar:
        st.markdown("## ⚡ OKX Bot Manager")
        page=st.radio("Раздел",pages,key="nav",label_visibility="collapsed")
        active=st.checkbox("Проверять при открытой странице",value=True)
        st.caption("Автопроверка раз в 60 секунд действует только при активной сессии. Для закрытой страницы нужен worker.py на постоянно работающем сервере.")
    st.title(page)
    @st.fragment(run_every="60s" if active else None)
    def heartbeat():
        if active:
            monitor_once()
            st.caption("Проверка активных карточек: "+stamp()+" UTC. Telegram — только при смене состояния.")
    heartbeat()
    if page=="Мои боты":
        panel("Сначала проект — затем OKX","Добавьте бота, настройте его отдельно, проведите тест, прочитайте ограничения и перенесите значения на OKX. После запуска подтвердите фактические данные позиции.")
        st.button("＋ Добавить бота",on_click=go,args=("Добавить / изменить",))
        bots=bot_list()
        if not bots: st.info("Пока нет ботов. Старый журнал анализов не импортируется в карточки автоматически.")
        for bot in bots:
            c=bot["config"]; snap=bot["snapshot"] or {}
            with st.container(border=True):
                st.subheader(bot["name"])
                st.write(f'{c["symbol"]} · {c["market"]} · {c["strategy"]} {c["side"]} · {bot["status"]}')
                st.caption(f'Бюджет {c["budget"]:.2f} USDT · состояние: {snap.get("status","не оценено")} · проверка: {snap.get("time","нет")}')
                if latest_test(bot): st.caption("Есть тест текущей версии")
                else: st.caption("Текущая версия не протестирована")
                st.button("Открыть настройки, тест и состояние",key=bot["id"],on_click=go,args=("Карточка бота",bot["id"]))
        st.warning("SQLite хранится на сервере. Облачный локальный диск не гарантирует сохранность. Выгружайте резервную копию. Приложение рассчитано на одного владельца; публичный доступ открывает общие карточки и Telegram-действия.")
    elif page=="Добавить / изменить": editor()
    elif page=="Карточка бота": bot_detail()
    elif page=="Сканер / подбор": scanner()
    elif page=="Журнал событий":
        st.caption("Здесь только создание/изменение бота, тесты, ручные сверки и изменения состояния. Проверка без изменений строку не создаёт.")
        show_events()
    else:
        panel("Telegram","Используется прежний блок [telegram] в Secrets: token и chat_id. Секреты в базу карточек не записываются.")
        if st.button("Тест Telegram"): st.info(telegram("OKX Bot Manager: связь проверена ✅"))
        st.code('[telegram]\ntoken = "ВАШ_ТОКЕН"\nchat_id = "ВАШ_CHAT_ID"',language="toml")
        st.subheader("Мониторинг без открытого браузера")
        st.code("python worker.py",language="bash")
        st.write("Запускайте на постоянно работающем сервере рядом с приложением и той же bots.sqlite3. Worker использует TELEGRAM_TOKEN / TELEGRAM_CHAT_ID или локальный .streamlit/secrets.toml. На Streamlit Cloud отдельный постоянный worker этой поставкой не разворачивается.")
        st.warning("Бот не отправляет торговые команды. Сообщение о цене у СО/TP не означает, что ордер исполнен. Mark price, ликвидация и фактические исполнения требуют проверки на OKX.")
        with connection() as db:
            backup=sqlite3.connect(":memory:"); db.backup(backup)
            dump="\n".join(backup.iterdump()); backup.close()
        st.download_button("Резервная копия карточек и событий SQL",dump.encode("utf-8"),file_name="bots_backup.sql",mime="text/plain")
        st.caption("Копия содержит позиции и настройки, но не Telegram-токен. Не публикуйте её.")


if __name__=="__main__":
    main()
