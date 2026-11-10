"""AlphaTrade Brain GUI (tkinter): settings, strategy params, start/stop, live signal, log."""
import copy
import json
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import uvicorn

import engine
import server
import strategies


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


SETTINGS = os.path.join(app_dir(), "settings.json")
server.JOURNAL = os.path.join(app_dir(), "journal.csv")

GENERAL = [  # key, label, type, tooltip
    ("tf", "Candle size (seconds)", int, "Tick data is grouped into candles of this length."),
    ("expiry_bars", "Expiry (candles)", int, "Trade length = candles x candle size."),
    ("payout_pct", "Payout %", float, "Broker payout on a win. Break-even win rate = 1 / (1 + payout)."),
    ("window", "Selection window (candles)", int, "How many recent candles are used to rank strategies."),
    ("min_candles", "Warm-up candles", int, "No analysis until this many closed candles exist (min 80)."),
    ("min_train", "Min train trades", int, "A strategy needs this many setups in the train part to be eligible."),
    ("min_test", "Min test trades", int, "Out-of-sample setups needed before a TRADE verdict."),
    ("port", "Server port", int, "Extension talks to 127.0.0.1:<port>. Also set the same port in the extension Options."),
]
PRESETS = {
    "Fast (5s candles, ~8 min warm-up)": {"tf": 5, "expiry_bars": 4, "min_candles": 100},
    "Balanced (15s candles)": {"tf": 15, "expiry_bars": 4, "min_candles": 150},
    "Slow (30s candles)": {"tf": 30, "expiry_bars": 2, "min_candles": 120},
}
HINTS = {
    "sr_price_action": "Rejection candle (pin bar / engulfing) at the recent high/low.\n"
                       "lookback = candles for the S/R level, tol = distance to level in ATR.",
    "trend_pullback": "Higher-timeframe EMA trend + pullback to the fast EMA.\n"
                      "htf_mult = higher TF multiple, fast/slow = EMA periods.",
    "rsi_stoch_reversal": "Counter-trade at RSI + stochastic extremes, skipped in strong trends.\n"
                          "lo/hi = RSI levels, trend_cap = max EMA gap in ATR.",
}
GREEN, RED, GRAY, AMBER = "#1fa760", "#d64545", "#8b93a7", "#d9930d"


def default_settings():
    c = engine.Config()
    return {
        "general": {"tf": c.tf, "expiry_bars": c.expiry_bars, "payout_pct": round(c.payout * 100, 2),
                    "window": c.window, "min_candles": c.min_candles, "min_train": c.min_train,
                    "min_test": c.min_test, "port": 8765},
        "enabled": {n: True for n in strategies.DEFAULTS},
        "params": copy.deepcopy(strategies.DEFAULTS),
        "on_top": False,
    }


def load_settings():
    s = default_settings()
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            d = json.load(f)
        s["general"].update(d.get("general", {}))
        s["enabled"].update(d.get("enabled", {}))
        for n, p in d.get("params", {}).items():
            if n in s["params"]:
                s["params"][n].update(p)
        s["on_top"] = bool(d.get("on_top", False))
    except (OSError, ValueError):
        pass
    return s


def save_settings(s):
    try:
        with open(SETTINGS, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2)
    except OSError:
        pass


def apply_to_server(s):
    g, c = s["general"], server.CFG
    old_tf = c.tf
    c.tf, c.expiry_bars = g["tf"], g["expiry_bars"]
    c.payout, c.window = g["payout_pct"] / 100.0, g["window"]
    c.min_candles, c.min_train, c.min_test = g["min_candles"], g["min_train"], g["min_test"]
    for n in strategies.DEFAULTS:
        strategies.ENABLED[n] = bool(s["enabled"].get(n, True))
        strategies.PARAMS[n].update(s["params"][n])
    if c.tf != old_tf:
        with server.LOCK:
            server.books.clear()     # candles of the old size are meaningless


class App:
    def __init__(self, root):
        self.root = root
        root.title("AlphaTrade Brain")
        root.geometry("700x680")
        self.s = load_settings()
        self.srv = self.thread = None
        self.want_running = False
        self.gv, self.ev_, self.pv = {}, {}, {}

        top = ttk.Frame(root, padding=(10, 8))
        top.pack(fill="x")
        self.status = tk.Label(top, text="● Stopped", fg=RED, font=("Segoe UI", 10, "bold"))
        self.status.pack(side="left")
        self.btn = ttk.Button(top, text="Start", width=8, command=self.toggle)
        self.btn.pack(side="right")
        ttk.Button(top, text="Apply", width=8, command=self.apply).pack(side="right", padx=6)
        self.top_var = tk.BooleanVar(value=self.s["on_top"])
        ttk.Checkbutton(top, text="Always on top", variable=self.top_var,
                        command=self.set_top).pack(side="right", padx=10)

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.build_status(nb)
        self.build_general(nb)
        self.build_strategies(nb)
        self.build_log(nb)

        self.set_top()
        root.protocol("WM_DELETE_WINDOW", self.close)
        if self.apply(silent=True):
            self.start_server()
        self.refresh()

    # ---------- tabs ----------
    def build_status(self, nb):
        f = ttk.Frame(nb, padding=12)
        nb.add(f, text="Status")
        self.sig = tk.Label(f, text="—", font=("Segoe UI", 32, "bold"), fg=GRAY)
        self.sig.pack(anchor="w")
        self.sub = ttk.Label(f, text="Waiting for ticks from the extension…")
        self.sub.pack(anchor="w")
        self.prog = ttk.Progressbar(f, maximum=100)
        self.prog.pack(fill="x", pady=8)
        self.detail = ttk.Label(f, justify="left")
        self.detail.pack(anchor="w", pady=4)
        cols = ("asset", "candles", "price", "signal", "strategy")
        self.tree = ttk.Treeview(f, columns=cols, show="headings", height=6)
        for c, w in zip(cols, (120, 70, 100, 70, 170)):
            self.tree.heading(c, text=c.title())
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, pady=(10, 0))

    def build_general(self, nb):
        f = ttk.Frame(nb, padding=12)
        nb.add(f, text="Settings")
        row = ttk.Frame(f)
        row.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        ttk.Label(row, text="Preset:").pack(side="left")
        self.preset = ttk.Combobox(row, values=list(PRESETS), state="readonly", width=34)
        self.preset.pack(side="left", padx=8)
        self.preset.bind("<<ComboboxSelected>>", self.on_preset)
        for i, (key, label, _t, tip) in enumerate(GENERAL, start=1):
            ttk.Label(f, text=label).grid(row=i, column=0, sticky="w", pady=4)
            v = tk.StringVar(value=str(self.s["general"][key]))
            v.trace_add("write", lambda *_: self.update_expiry())
            self.gv[key] = v
            ttk.Entry(f, textvariable=v, width=12).grid(row=i, column=1, padx=10)
            ttk.Label(f, text=tip, foreground=GRAY, wraplength=330).grid(row=i, column=2, sticky="w")
        self.expiry_lbl = ttk.Label(f, font=("Segoe UI", 10, "bold"))
        self.expiry_lbl.grid(row=len(GENERAL) + 1, column=0, columnspan=3, sticky="w", pady=(12, 0))
        self.be_lbl = ttk.Label(f)
        self.be_lbl.grid(row=len(GENERAL) + 2, column=0, columnspan=3, sticky="w")
        bar = ttk.Frame(f)
        bar.grid(row=len(GENERAL) + 3, column=0, columnspan=3, sticky="w", pady=14)
        ttk.Button(bar, text="Reset to defaults", command=self.reset_defaults).pack(side="left")
        ttk.Button(bar, text="Clear collected data", command=self.clear_data).pack(side="left", padx=8)
        ttk.Button(bar, text="Open data folder", command=self.open_folder).pack(side="left")
        self.update_expiry()

    def build_strategies(self, nb):
        f = ttk.Frame(nb, padding=12)
        nb.add(f, text="Strategies")
        for name, params in strategies.DEFAULTS.items():
            box = ttk.LabelFrame(f, text=name, padding=8)
            box.pack(fill="x", pady=6)
            v = tk.BooleanVar(value=bool(self.s["enabled"].get(name, True)))
            self.ev_[name] = v
            ttk.Checkbutton(box, text="Enabled", variable=v).grid(row=0, column=0, sticky="w")
            ttk.Label(box, text=HINTS[name], foreground=GRAY, justify="left").grid(
                row=1, column=0, columnspan=8, sticky="w", pady=(2, 6))
            for j, pk in enumerate(params):
                ttk.Label(box, text=pk).grid(row=2, column=2 * j, sticky="e", padx=(0, 4))
                pv = tk.StringVar(value=str(self.s["params"][name][pk]))
                self.pv[(name, pk)] = pv
                ttk.Entry(box, textvariable=pv, width=8).grid(row=2, column=2 * j + 1, padx=(0, 14))
        ttk.Label(f, foreground=GRAY, wraplength=620,
                  text="Changes take effect after Apply. Candles already collected are kept; "
                       "strategies are re-evaluated on the next candle close.").pack(anchor="w", pady=8)

    def build_log(self, nb):
        f = ttk.Frame(nb, padding=6)
        nb.add(f, text="Log")
        self.text = tk.Text(f, height=20, state="disabled", wrap="none", font=("Consolas", 9))
        sb = ttk.Scrollbar(f, command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(fill="both", expand=True)

    # ---------- helpers ----------
    def log(self, msg):
        self.text.configure(state="normal")
        self.text.insert("end", msg + "\n")
        self.text.see("end")
        self.text.configure(state="disabled")

    def set_top(self):
        self.root.attributes("-topmost", bool(self.top_var.get()))

    def update_expiry(self):
        try:
            tf, k = int(self.gv["tf"].get()), int(self.gv["expiry_bars"].get())
            pay = float(self.gv["payout_pct"].get()) / 100
            self.expiry_lbl.config(text=f"Set trade expiry on the platform to: {tf * k} s")
            self.be_lbl.config(text=f"Break-even win rate: {100 / (1 + pay):.1f}%")
        except (ValueError, ZeroDivisionError, KeyError, AttributeError):
            pass

    def on_preset(self, _e=None):
        for k, v in PRESETS[self.preset.get()].items():
            self.gv[k].set(str(v))

    def reset_defaults(self):
        d = default_settings()
        for k, v in d["general"].items():
            self.gv[k].set(str(v))
        for n in strategies.DEFAULTS:
            self.ev_[n].set(True)
            for pk, pv in d["params"][n].items():
                self.pv[(n, pk)].set(str(pv))

    def clear_data(self):
        with server.LOCK:
            server.books.clear()
        server.last_asset = None
        self.log(f"{time.strftime('%H:%M:%S')}  collected data cleared")

    def open_folder(self):
        d = app_dir()
        try:
            if sys.platform.startswith("win"):
                os.startfile(d)  # noqa
            elif sys.platform == "darwin":
                subprocess.Popen(["open", d])
            else:
                subprocess.Popen(["xdg-open", d])
        except OSError:
            messagebox.showinfo("Data folder", d)

    # ---------- settings ----------
    def read(self):
        g = {}
        for key, label, typ, _ in GENERAL:
            try:
                g[key] = typ(self.gv[key].get().strip())
            except ValueError:
                raise ValueError(f"{label}: not a valid number")
        if g["tf"] < 1 or g["expiry_bars"] < 1:
            raise ValueError("Candle size and expiry must be at least 1")
        if g["payout_pct"] <= 0:
            raise ValueError("Payout % must be greater than 0")
        if g["window"] < 100 or g["min_candles"] < 80:
            raise ValueError("Selection window >= 100 and warm-up candles >= 80")
        if g["min_train"] < 1 or g["min_test"] < 1:
            raise ValueError("Min train/test trades must be at least 1")
        if not 1024 <= g["port"] <= 65535:
            raise ValueError("Port must be between 1024 and 65535")
        enabled = {n: bool(v.get()) for n, v in self.ev_.items()}
        if not any(enabled.values()):
            raise ValueError("Enable at least one strategy")
        params = {}
        for (n, pk), v in self.pv.items():
            default = strategies.DEFAULTS[n][pk]
            try:
                val = (int if isinstance(default, int) else float)(v.get().strip())
            except ValueError:
                raise ValueError(f"{n}.{pk}: not a valid number")
            if val <= 0:
                raise ValueError(f"{n}.{pk} must be greater than 0")
            params.setdefault(n, {})[pk] = val
        if params["trend_pullback"]["fast"] >= params["trend_pullback"]["slow"]:
            raise ValueError("trend_pullback: fast EMA must be smaller than slow EMA")
        return {"general": g, "enabled": enabled, "params": params, "on_top": bool(self.top_var.get())}

    def apply(self, silent=False):
        try:
            new = self.read()
        except ValueError as e:
            if not silent:
                messagebox.showerror("Invalid setting", str(e))
            else:
                self.s = default_settings()
            return False if not silent else True
        if (new["general"]["tf"] != server.CFG.tf and server.books
                and not silent
                and not messagebox.askyesno("Candle size changed",
                                            "Changing candle size resets collected data. Continue?")):
            return False
        port_changed = new["general"]["port"] != self.s["general"]["port"]
        self.s = new
        save_settings(new)
        apply_to_server(new)
        self.log(f"{time.strftime('%H:%M:%S')}  settings applied")
        if port_changed and self.want_running and not silent:
            self.stop_server()
            self.start_server()
        return True

    # ---------- server ----------
    def start_server(self):
        port = self.s["general"]["port"]
        cfg = uvicorn.Config(server.app, host="127.0.0.1", port=port, log_level="warning", log_config=None)
        self.srv = uvicorn.Server(cfg)
        self.thread = threading.Thread(target=self.srv.run, daemon=True)
        self.thread.start()
        self.want_running = True
        self.btn.config(text="Stop")
        self.log(f"{time.strftime('%H:%M:%S')}  starting on 127.0.0.1:{port}")

    def stop_server(self):
        if self.srv:
            self.srv.should_exit = True
        if self.thread:
            self.thread.join(3)
        self.want_running = False
        self.btn.config(text="Start")
        self.log(f"{time.strftime('%H:%M:%S')}  stopped")

    def toggle(self):
        if self.want_running:
            self.stop_server()
        elif self.apply():
            self.start_server()

    def close(self):
        try:
            self.s = self.read()
        except ValueError:
            pass
        save_settings(self.s)
        if self.want_running:
            self.srv.should_exit = True
        self.root.destroy()

    # ---------- live view ----------
    def refresh(self):
        try:
            self._refresh()
        except Exception as e:  # never let the UI loop die
            self.sub.config(text=f"(ui error: {e})")
        self.root.after(500, self.refresh)

    def _refresh(self):
        port = self.s["general"]["port"]
        if self.want_running and self.thread and not self.thread.is_alive():
            self.want_running = False
            self.btn.config(text="Start")
            self.status.config(text="● Stopped (port busy?)", fg=RED)
            self.log(f"{time.strftime('%H:%M:%S')}  server stopped unexpectedly - is port {port} in use?")
        elif self.want_running and self.srv and self.srv.started:
            self.status.config(text=f"● Running on 127.0.0.1:{port}", fg=GREEN)
        elif self.want_running:
            self.status.config(text="● Starting…", fg=AMBER)
        else:
            self.status.config(text="● Stopped", fg=RED)

        while server.EVENTS:
            try:
                self.log(server.EVENTS.popleft())
            except IndexError:
                break

        a = server.last_asset
        st = server.state(a) if a in server.books else None
        if not st:
            self.sig.config(text="—", fg=GRAY)
            self.sub.config(text="Waiting for ticks from the extension…")
            self.prog["value"] = 0
            self.detail.config(text="")
        else:
            r = st["result"]
            price = f"{st['price']:.5f}" if st["price"] is not None else ""
            self.sub.config(text=f"{a}   {price}")
            if not r or r["status"] != "ready":
                left = max(0, st["need"] - st["candles"]) * st["tf"] / 60
                self.sig.config(text="WARM-UP", fg=AMBER)
                self.prog["value"] = min(100, 100 * st["candles"] / st["need"])
                self.detail.config(text=f"{st['candles']}/{st['need']} candles x {st['tf']}s   (~{left:.0f} min left)")
            else:
                self.prog["value"] = 100
                sig = r["signal"]
                self.sig.config(text={"CALL": "CALL ▲", "PUT": "PUT ▼"}.get(sig, "WAIT"),
                                fg={"CALL": GREEN, "PUT": RED}.get(sig, GRAY))
                lines = [r["reason"]]
                if sig != "WAIT":
                    lines.append(f"Set expiry: {st['expiry_s']} s")
                b = r.get("best")
                if b:
                    pct = lambda v: "–" if v is None else f"{v * 100:.1f}%"
                    lines.append(f"Best: {b['name']}")
                    lines.append(f"Train WR {pct(b['train']['wr'])} (n={b['train']['n']})   "
                                 f"Test WR {pct(b['test']['wr'])} (n={b['test']['n']})")
                lines.append(f"Break-even WR: {r['breakeven'] * 100:.1f}%")
                for q in st["pending"]:
                    left = max(0, round(q["exp"] - time.time()))
                    lines.append(f"Open: {'CALL' if q['dir'] > 0 else 'PUT'} ({q['strategy']}) ~{left}s left")
                for k, v in st["live"].items():
                    n = v["w"] + v["l"]
                    lines.append(f"Live {k}: {v['w']}W/{v['l']}L" + (f" ({100 * v['w'] / n:.0f}%)" if n else ""))
                self.detail.config(text="\n".join(lines))

        self.tree.delete(*self.tree.get_children())
        for name, b in list(server.books.items()):
            r = b.result if b.result and b.result.get("status") == "ready" else None
            self.tree.insert("", "end", values=(
                name, len(b.c), f"{b.last[1]:.5f}" if b.last else "",
                r["signal"] if r else "warm-up", (r["strategy"] or "-") if r else "-"))


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista" if sys.platform.startswith("win") else "clam")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
