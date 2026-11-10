"""Python brain (FastAPI). Headless:  python main.py --nogui   |   GUI: python main.py"""
import csv
import os
import threading
import time
from collections import defaultdict, deque

from fastapi import FastAPI
from pydantic import BaseModel

from engine import Config, analyze, build_df

CFG = Config()
JOURNAL = os.getenv("QX_JOURNAL", "journal.csv")
LOCK = threading.Lock()
EVENTS = deque(maxlen=500)      # human-readable log lines, drained by the GUI
last_asset = None
app = FastAPI()


def ev(msg):
    EVENTS.append(f"{time.strftime('%H:%M:%S')}  {msg}")


def journal(row):
    try:
        new = not os.path.exists(JOURNAL)
        with open(JOURNAL, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["time", "asset", "strategy", "dir", "entry", "exit", "win", "train_wr", "test_wr"])
            w.writerow(row)
    except OSError as e:
        ev(f"journal write failed: {e}")


class Book:
    def __init__(self, asset):
        self.asset, self.c, self.last = asset, [], None
        self.pending, self.result = [], None
        self.live = defaultdict(lambda: {"w": 0, "l": 0})

    def tick(self, t, p):
        tf = CFG.tf
        b = int(t // tf) * tf
        if self.c and b < self.c[-1][0]:
            return                                    # out-of-order tick
        self.last = (t, p)
        self._resolve(t, p)
        if self.c and b == self.c[-1][0]:
            r = self.c[-1]
            r[2], r[3], r[4] = max(r[2], p), min(r[3], p), p
            return
        self.c.append([b, p, p, p, p])
        if len(self.c) > 3000:
            del self.c[:1000]
        if len(self.c) > 1:
            self._on_close(t, p, b)

    def _resolve(self, t, p):
        for x in list(self.pending):
            if t >= x["exp"]:
                win = (p - x["entry"]) * x["dir"] > 0
                self.live[x["strategy"]]["w" if win else "l"] += 1
                journal([time.strftime("%F %T"), self.asset, x["strategy"], x["dir"],
                         x["entry"], p, int(win), x["train_wr"], x["test_wr"]])
                ev(f"{'WIN ' if win else 'LOSS'}  {self.asset}  {x['strategy']}  "
                   f"{'CALL' if x['dir'] > 0 else 'PUT'}  {x['entry']:.5f} -> {p:.5f}")
                self.pending.remove(x)

    def _on_close(self, t, p, b):
        df = build_df(self.c[-1000:-1])               # closed candles only
        self.result = r = analyze(df, CFG)
        if r["status"] == "ready" and r["signal"] != "WAIT" and not self.pending:
            self.pending.append({
                "strategy": r["strategy"], "dir": 1 if r["signal"] == "CALL" else -1,
                "entry": p, "exp": b + CFG.expiry_bars * CFG.tf,
                "train_wr": r["best"]["train"]["wr"], "test_wr": r["best"]["test"]["wr"],
            })
            ev(f"SIGNAL {r['signal']}  {self.asset}  via {r['strategy']}  expiry {CFG.expiry_bars * CFG.tf}s")


books = {}


def state(asset):
    b = books.get(asset)
    if not b:
        return {"asset": asset, "candles": 0}
    return {
        "asset": asset, "price": b.last[1] if b.last else None,
        "candles": len(b.c), "need": CFG.min_candles, "tf": CFG.tf,
        "expiry_s": CFG.expiry_bars * CFG.tf, "result": b.result,
        "pending": b.pending, "live": {k: dict(v) for k, v in b.live.items()},
    }


class Tick(BaseModel):
    a: str
    t: float
    p: float


class Ticks(BaseModel):
    ticks: list[Tick]


@app.post("/ticks")
def ticks(body: Ticks):
    global last_asset
    last = None
    with LOCK:
        for x in sorted(body.ticks, key=lambda x: x.t):
            t = x.t / 1000 if x.t > 1e11 else x.t     # ms -> s
            if x.a not in books:
                books[x.a] = Book(x.a)
                ev(f"first tick for {x.a}")
            books[x.a].tick(t, x.p)
            last = x.a
        if last:
            last_asset = last
        return state(last) if last else {}


@app.get("/state/{asset}")
def get_state(asset: str):
    return state(asset)
