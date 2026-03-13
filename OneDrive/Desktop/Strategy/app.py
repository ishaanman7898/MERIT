"""
Gold Signal Bot — Desktop Application
XAU/USD  |  1-minute candles  |  Heikin Ashi + custom strategies
"""

import json
import os
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

import customtkinter as ctk

import engine

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT           = Path(__file__).parent
CONFIG_PATH    = ROOT / "config.json"
STRATEGIES_DIR = ROOT / "strategies"
STRATEGIES_DIR.mkdir(exist_ok=True)

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_CONFIG = {
    "symbol":                 "GC=F",
    "interval":               "1m",
    "discord_webhook":        "",
    "check_interval_seconds": 60,
    "lookback_candles":       50,
    "active_strategy":        "heikin_ashi",
    "take_profit_usd":        10.0,
    "stop_loss_usd":          5.0,
}

STRATEGY_TEMPLATE = '''\
"""
Strategy name: My Strategy
--------------------------
df columns: Open, High, Low, Close, Volume
Last row = most recent candle.
Return "BUY", "SELL", or None.
"""

import pandas as pd


def generate_signal(df: pd.DataFrame) -> str | None:
    # Write your strategy below.
    # Example: always return None (do nothing)
    return None
'''

# ── Config helpers ─────────────────────────────────────────────────────────────

def load_config() -> dict:
    if CONFIG_PATH.exists():
        cfg = json.loads(CONFIG_PATH.read_text())
        for k, v in DEFAULT_CONFIG.items():
            cfg.setdefault(k, v)
        return cfg
    return DEFAULT_CONFIG.copy()


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def list_strategies() -> list[str]:
    return sorted(p.stem for p in STRATEGIES_DIR.glob("*.py"))


# ── Colour palette ─────────────────────────────────────────────────────────────
BG_DARK   = "#0d0d0f"
BG_PANEL  = "#141417"
BG_CARD   = "#1a1a1f"
BG_EDITOR = "#111114"
FG_DIM    = "#555560"
FG_MID    = "#888899"
FG_MAIN   = "#d4d4e0"
FG_GREEN  = "#22bb66"
FG_RED    = "#cc3333"
FG_GOLD   = "#c8a840"
FG_BLUE   = "#4488cc"
FONT_MONO = ("Courier New", 11)
FONT_UI   = ("Segoe UI", 11)
FONT_HEAD = ("Segoe UI", 13, "bold")

# ═══════════════════════════════════════════════════════════════════════════════
#  Application
# ═══════════════════════════════════════════════════════════════════════════════

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("Gold Signal Bot  |  XAU/USD")
        self.geometry("1160x760")
        self.minsize(1000, 640)

        self._cfg     = load_config()
        self._bot: engine.TradingEngine | None = None
        self._active_trade: dict | None = None
        self._price_var = tk.StringVar(value="--")

        self._build_ui()
        self._refresh_trade_table()

    # ── Layout ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Top bar ──────────────────────────────────────────────────────────
        top = ctk.CTkFrame(self, height=48, corner_radius=0, fg_color=BG_PANEL)
        top.pack(fill="x")
        top.pack_propagate(False)

        ctk.CTkLabel(top, text="GOLD SIGNAL BOT", font=ctk.CTkFont("Segoe UI", 15, "bold"),
                     text_color=FG_GOLD).pack(side="left", padx=18, pady=12)
        ctk.CTkLabel(top, text="XAU/USD", font=ctk.CTkFont("Segoe UI", 12),
                     text_color=FG_DIM).pack(side="left", padx=(0, 24))

        self._bot_status = ctk.CTkLabel(top, text="STOPPED", font=ctk.CTkFont("Segoe UI", 12, "bold"),
                                         text_color=FG_DIM)
        self._bot_status.pack(side="right", padx=18)
        ctk.CTkLabel(top, text="Status:", font=ctk.CTkFont("Segoe UI", 11),
                     text_color=FG_DIM).pack(side="right", padx=(0, 4))

        self._live_price_lbl = ctk.CTkLabel(top, textvariable=self._price_var,
                                             font=ctk.CTkFont("Courier New", 16, "bold"),
                                             text_color=FG_GOLD)
        self._live_price_lbl.pack(side="right", padx=24)
        ctk.CTkLabel(top, text="Price:", font=ctk.CTkFont("Segoe UI", 11),
                     text_color=FG_DIM).pack(side="right", padx=(0, 4))

        # ── Tabs ──────────────────────────────────────────────────────────────
        self._tabs = ctk.CTkTabview(self, corner_radius=6, fg_color=BG_DARK,
                                     segmented_button_fg_color=BG_PANEL,
                                     segmented_button_selected_color=BG_CARD)
        self._tabs.pack(fill="both", expand=True, padx=10, pady=(4, 10))

        for name in ("Live", "Trades", "Strategy Editor", "Backtest", "Settings"):
            self._tabs.add(name)

        self._build_live()
        self._build_trades()
        self._build_editor()
        self._build_backtest()
        self._build_settings()

    # ══════════════════════════════════════════════════════════════════════════
    #  Tab: Live
    # ══════════════════════════════════════════════════════════════════════════

    def _build_live(self):
        tab = self._tabs.tab("Live")
        tab.columnconfigure(0, weight=0, minsize=280)
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(0, weight=1)

        # ── Left column: controls + active trade ──────────────────────────────
        left = ctk.CTkFrame(tab, fg_color=BG_PANEL, corner_radius=6)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.columnconfigure(0, weight=1)

        # Strategy selector
        _section(left, "Strategy", row=0)
        strats = list_strategies() or ["heikin_ashi"]
        self._live_strat_var = ctk.StringVar(value=self._cfg.get("active_strategy", strats[0]))
        self._live_strat_menu = ctk.CTkOptionMenu(
            left, variable=self._live_strat_var, values=strats, width=240,
            command=self._on_live_strategy_change,
        )
        self._live_strat_menu.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="ew")

        # TP / SL
        _section(left, "Take Profit  /  Stop Loss  (USD per oz)", row=2)
        tpsl_row = ctk.CTkFrame(left, fg_color="transparent")
        tpsl_row.grid(row=3, column=0, padx=12, pady=(0, 12), sticky="ew")
        tpsl_row.columnconfigure((0, 1), weight=1)

        ctk.CTkLabel(tpsl_row, text="TP $", text_color=FG_MID).grid(row=0, column=0, sticky="w")
        self._tp_var = ctk.StringVar(value=str(self._cfg.get("take_profit_usd", 10.0)))
        ctk.CTkEntry(tpsl_row, textvariable=self._tp_var, width=100).grid(row=1, column=0, sticky="ew", padx=(0, 6))

        ctk.CTkLabel(tpsl_row, text="SL $", text_color=FG_MID).grid(row=0, column=1, sticky="w")
        self._sl_var = ctk.StringVar(value=str(self._cfg.get("stop_loss_usd", 5.0)))
        ctk.CTkEntry(tpsl_row, textvariable=self._sl_var, width=100).grid(row=1, column=1, sticky="ew")

        ctk.CTkButton(tpsl_row, text="Apply", width=60, height=28,
                      command=self._apply_tpsl).grid(row=2, column=0, columnspan=2, sticky="e", pady=(4, 0))

        # Start / Stop
        _section(left, "Bot Controls", row=4)
        btn_row = ctk.CTkFrame(left, fg_color="transparent")
        btn_row.grid(row=5, column=0, padx=12, pady=(0, 12), sticky="ew")
        btn_row.columnconfigure((0, 1), weight=1)

        self._start_btn = ctk.CTkButton(btn_row, text="Start", fg_color="#1a5c35",
                                         hover_color="#144528", command=self._start_bot)
        self._start_btn.grid(row=0, column=0, padx=(0, 4), sticky="ew")
        self._stop_btn  = ctk.CTkButton(btn_row, text="Stop", fg_color="#5c1a1a",
                                         hover_color="#451414", state="disabled", command=self._stop_bot)
        self._stop_btn.grid(row=0, column=1, padx=(4, 0), sticky="ew")

        # Active trade card
        _section(left, "Active Trade", row=6)
        self._trade_card = ctk.CTkFrame(left, fg_color=BG_CARD, corner_radius=6)
        self._trade_card.grid(row=7, column=0, padx=12, pady=(0, 12), sticky="ew")
        self._trade_card.columnconfigure((0, 1), weight=1)

        self._tc_labels: dict[str, ctk.CTkLabel] = {}
        for r, (key, label) in enumerate([
            ("side",  "Side"),
            ("entry", "Entry"),
            ("tp",    "Take Profit"),
            ("sl",    "Stop Loss"),
            ("open",  "Opened"),
        ]):
            ctk.CTkLabel(self._trade_card, text=label, text_color=FG_DIM,
                         font=ctk.CTkFont("Segoe UI", 10)).grid(row=r, column=0, sticky="w", padx=10, pady=(4 if r == 0 else 0, 0))
            lbl = ctk.CTkLabel(self._trade_card, text="--", font=ctk.CTkFont("Courier New", 11, "bold"))
            lbl.grid(row=r, column=1, sticky="e", padx=10, pady=(4 if r == 0 else 0, 0))
            self._tc_labels[key] = lbl

        ctk.CTkButton(self._trade_card, text="Close Trade Now", height=28,
                      fg_color="#3a1515", hover_color="#551c1c",
                      command=self._manual_close).grid(
            row=5, column=0, columnspan=2, padx=10, pady=(8, 10), sticky="ew")

        # ── Right column: log ─────────────────────────────────────────────────
        right = ctk.CTkFrame(tab, fg_color=BG_PANEL, corner_radius=6)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        log_hdr = ctk.CTkFrame(right, fg_color="transparent")
        log_hdr.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 4))
        ctk.CTkLabel(log_hdr, text="Log", font=ctk.CTkFont("Segoe UI", 12, "bold"),
                     text_color=FG_MAIN).pack(side="left")
        ctk.CTkButton(log_hdr, text="Clear", width=60, height=24,
                      command=self._clear_log).pack(side="right")

        self._log_box = ctk.CTkTextbox(right, font=ctk.CTkFont("Courier New", 11),
                                        wrap="word", state="disabled",
                                        fg_color=BG_EDITOR, text_color=FG_MAIN)
        self._log_box.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

    def _on_live_strategy_change(self, val: str):
        self._cfg["active_strategy"] = val
        save_config(self._cfg)

    def _apply_tpsl(self):
        try:
            tp = float(self._tp_var.get())
            sl = float(self._sl_var.get())
        except ValueError:
            messagebox.showerror("Invalid", "TP and SL must be numbers.")
            return
        self._cfg["take_profit_usd"] = tp
        self._cfg["stop_loss_usd"]   = sl
        save_config(self._cfg)

    def _start_bot(self):
        self._apply_tpsl()
        cfg = load_config()
        self._bot = engine.TradingEngine(cfg, self._append_log, self._on_trade_update)
        self._bot.start()
        self._start_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")
        self._bot_status.configure(text="RUNNING", text_color=FG_GREEN)

    def _stop_bot(self):
        if self._bot:
            self._bot.stop()
        self._start_btn.configure(state="normal")
        self._stop_btn.configure(state="disabled")
        self._bot_status.configure(text="STOPPED", text_color=FG_DIM)

    def _manual_close(self):
        if not self._bot or not self._active_trade:
            return
        self._bot.close_active_trade()

    def _append_log(self, msg: str):
        self.after(0, self._write_log, msg)

    def _write_log(self, msg: str):
        self._log_box.configure(state="normal")
        self._log_box.insert("end", msg + "\n")
        self._log_box.see("end")
        self._log_box.configure(state="disabled")

    def _clear_log(self):
        self._log_box.configure(state="normal")
        self._log_box.delete("1.0", "end")
        self._log_box.configure(state="disabled")

    def _on_trade_update(self, trade: dict | None):
        self._active_trade = trade
        self.after(0, self._refresh_trade_card, trade)
        self.after(0, self._refresh_trade_table)
        if trade:
            price_str = f"${trade['entry']:,.2f}"
            self.after(0, self._price_var.set, price_str)

    def _refresh_trade_card(self, trade: dict | None):
        if trade is None:
            for lbl in self._tc_labels.values():
                lbl.configure(text="--", text_color=FG_MID)
            return
        side_color = FG_GREEN if trade["side"] == "BUY" else FG_RED
        self._tc_labels["side"].configure(text=trade["side"], text_color=side_color)
        self._tc_labels["entry"].configure(text=f"${trade['entry']:,.2f}", text_color=FG_MAIN)
        self._tc_labels["tp"].configure(text=f"${trade['tp']:,.2f}", text_color=FG_GREEN)
        self._tc_labels["sl"].configure(text=f"${trade['sl']:,.2f}", text_color=FG_RED)
        self._tc_labels["open"].configure(text=trade.get("open_time", "--")[:19], text_color=FG_MID)

    # ══════════════════════════════════════════════════════════════════════════
    #  Tab: Trades
    # ══════════════════════════════════════════════════════════════════════════

    def _build_trades(self):
        tab = self._tabs.tab("Trades")
        tab.rowconfigure(1, weight=1)
        tab.columnconfigure(0, weight=1)

        # Stats row
        self._trade_stats = ctk.CTkFrame(tab, fg_color=BG_PANEL, corner_radius=6, height=70)
        self._trade_stats.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self._trade_stats.pack_propagate(False)
        self._stat_vars: dict[str, tk.StringVar] = {}
        for key, label in [("total", "Total Trades"), ("wins", "Wins"),
                            ("losses", "Losses"), ("winrate", "Win Rate"),
                            ("total_pnl", "Total PnL")]:
            f = ctk.CTkFrame(self._trade_stats, fg_color="transparent")
            f.pack(side="left", padx=24, pady=8)
            ctk.CTkLabel(f, text=label, text_color=FG_DIM, font=ctk.CTkFont("Segoe UI", 10)).pack()
            sv = tk.StringVar(value="--")
            ctk.CTkLabel(f, textvariable=sv, font=ctk.CTkFont("Courier New", 14, "bold"),
                         text_color=FG_MAIN).pack()
            self._stat_vars[key] = sv

        ctk.CTkButton(self._trade_stats, text="Refresh", width=80, height=28,
                      command=self._refresh_trade_table).pack(side="right", padx=16, pady=18)

        # Table
        tree_frame = ctk.CTkFrame(tab, fg_color=BG_PANEL, corner_radius=6)
        tree_frame.grid(row=1, column=0, sticky="nsew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        _apply_tree_style()
        cols = ("#", "Side", "Entry", "TP", "SL", "Exit", "PnL", "Reason", "Opened", "Closed")
        self._trades_tree = ttk.Treeview(tree_frame, columns=cols, show="headings")
        widths = [40, 60, 90, 90, 90, 90, 90, 90, 140, 140]
        for col, w in zip(cols, widths):
            self._trades_tree.heading(col, text=col)
            self._trades_tree.column(col, width=w, anchor="center", minwidth=40)
        self._trades_tree.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)

        sb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._trades_tree.yview)
        sb.grid(row=0, column=1, sticky="ns", pady=6)
        self._trades_tree.configure(yscrollcommand=sb.set)
        self._trades_tree.tag_configure("buy",  foreground=FG_GREEN)
        self._trades_tree.tag_configure("sell", foreground=FG_RED)
        self._trades_tree.tag_configure("open", foreground=FG_GOLD)

    def _refresh_trade_table(self):
        trades = engine.load_trades()
        for row in self._trades_tree.get_children():
            self._trades_tree.delete(row)

        wins = losses = 0
        total_pnl = 0.0

        for t in reversed(trades):
            pnl     = t.get("pnl")
            reason  = t.get("status", "")
            is_open = reason == "OPEN"
            pnl_str = "--" if pnl is None else (f"+${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}")
            if pnl is not None:
                if pnl >= 0:
                    wins += 1
                else:
                    losses += 1
                total_pnl += pnl

            tag = "open" if is_open else ("buy" if t.get("side") == "BUY" else "sell")
            self._trades_tree.insert("", "end", values=(
                t.get("id", ""),
                t.get("side", ""),
                f"${t['entry']:,.2f}" if t.get("entry") else "--",
                f"${t['tp']:,.2f}"    if t.get("tp")    else "--",
                f"${t['sl']:,.2f}"    if t.get("sl")    else "--",
                f"${t['close_price']:,.2f}" if t.get("close_price") else "--",
                pnl_str,
                reason,
                t.get("open_time",  "--")[:19] if t.get("open_time")  else "--",
                t.get("close_time", "--")[:19] if t.get("close_time") else "--",
            ), tags=(tag,))

        total = wins + losses
        wr    = f"{wins/total*100:.1f}%" if total else "--"
        pnl_s = (f"+${total_pnl:,.2f}" if total_pnl >= 0 else f"-${abs(total_pnl):,.2f}") if total else "--"
        self._stat_vars["total"].set(str(len(trades)))
        self._stat_vars["wins"].set(str(wins))
        self._stat_vars["losses"].set(str(losses))
        self._stat_vars["winrate"].set(wr)
        self._stat_vars["total_pnl"].set(pnl_s)

    # ══════════════════════════════════════════════════════════════════════════
    #  Tab: Strategy Editor
    # ══════════════════════════════════════════════════════════════════════════

    def _build_editor(self):
        tab = self._tabs.tab("Strategy Editor")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)

        # Toolbar
        bar = ctk.CTkFrame(tab, fg_color=BG_PANEL, corner_radius=6)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        ctk.CTkLabel(bar, text="Strategy:", text_color=FG_MID).pack(side="left", padx=(12, 4), pady=8)
        strats = list_strategies() or ["(none)"]
        self._editor_var = ctk.StringVar(value=strats[0])
        self._editor_menu = ctk.CTkOptionMenu(bar, variable=self._editor_var, values=strats, width=200)
        self._editor_menu.pack(side="left", padx=(0, 10))

        for label, cmd in [("Load", self._editor_load), ("Save", self._editor_save),
                            ("Save As", self._editor_save_as), ("New", self._editor_new),
                            ("Delete", self._editor_delete)]:
            ctk.CTkButton(bar, text=label, width=80, height=30, command=cmd).pack(side="left", padx=3)

        self._editor_status = ctk.CTkLabel(bar, text="", text_color=FG_GREEN,
                                            font=ctk.CTkFont("Segoe UI", 11))
        self._editor_status.pack(side="right", padx=12)

        # Editor area
        editor_outer = ctk.CTkFrame(tab, fg_color=BG_PANEL, corner_radius=6)
        editor_outer.grid(row=1, column=0, sticky="nsew")
        editor_outer.rowconfigure(0, weight=1)
        editor_outer.columnconfigure(1, weight=1)

        # Line numbers
        self._line_nums = tk.Text(editor_outer, bg=BG_EDITOR, fg=FG_DIM, width=4,
                                   font=FONT_MONO, state="disabled", takefocus=False,
                                   relief="flat", bd=0)
        self._line_nums.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)

        self._code_text = tk.Text(editor_outer, bg=BG_EDITOR, fg=FG_MAIN,
                                   insertbackground=FG_MAIN, font=FONT_MONO,
                                   wrap="none", undo=True, selectbackground="#333355",
                                   relief="flat", bd=0)
        self._code_text.grid(row=0, column=1, sticky="nsew", pady=6)

        sb_y = ttk.Scrollbar(editor_outer, orient="vertical",   command=self._code_text.yview)
        sb_y.grid(row=0, column=2, sticky="ns", pady=6)
        sb_x = ttk.Scrollbar(editor_outer, orient="horizontal", command=self._code_text.xview)
        sb_x.grid(row=1, column=1, sticky="ew", padx=6)
        self._code_text.configure(yscrollcommand=sb_y.set, xscrollcommand=sb_x.set)
        self._code_text.bind("<KeyRelease>", self._update_line_nums)
        self._code_text.bind("<Tab>", lambda e: (self._code_text.insert("insert", "    "), "break")[1])
        self._code_text.bind("<MouseWheel>", lambda e: self._line_nums.yview_moveto(self._code_text.yview()[0]))

        if strats and strats[0] != "(none)":
            self._load_strategy_file(strats[0])

    def _update_line_nums(self, _=None):
        n = int(self._code_text.index("end-1c").split(".")[0])
        self._line_nums.configure(state="normal")
        self._line_nums.delete("1.0", "end")
        self._line_nums.insert("1.0", "\n".join(str(i) for i in range(1, n + 1)))
        self._line_nums.configure(state="disabled")

    def _load_strategy_file(self, name: str):
        path = STRATEGIES_DIR / f"{name}.py"
        if not path.exists():
            return
        self._code_text.delete("1.0", "end")
        self._code_text.insert("1.0", path.read_text())
        self._editor_status.configure(text=f"Loaded: {name}.py")
        self._update_line_nums()

    def _editor_load(self):
        self._load_strategy_file(self._editor_var.get())

    def _editor_save(self):
        name = self._editor_var.get()
        if not name or name == "(none)":
            self._editor_save_as()
            return
        (STRATEGIES_DIR / f"{name}.py").write_text(self._code_text.get("1.0", "end-1c"))
        self._editor_status.configure(text=f"Saved: {name}.py")
        self._refresh_strategy_menus()

    def _editor_save_as(self):
        dlg  = ctk.CTkInputDialog(text="Strategy name (no spaces, no .py):", title="Save As")
        name = dlg.get_input()
        if not name:
            return
        name = name.strip().replace(" ", "_").replace(".py", "")
        (STRATEGIES_DIR / f"{name}.py").write_text(self._code_text.get("1.0", "end-1c"))
        self._editor_var.set(name)
        self._editor_status.configure(text=f"Saved: {name}.py")
        self._refresh_strategy_menus()

    def _editor_new(self):
        dlg  = ctk.CTkInputDialog(text="New strategy name:", title="New Strategy")
        name = dlg.get_input()
        if not name:
            return
        name = name.strip().replace(" ", "_").replace(".py", "")
        self._code_text.delete("1.0", "end")
        self._code_text.insert("1.0", STRATEGY_TEMPLATE)
        self._editor_var.set(name)
        self._editor_status.configure(text=f"New (unsaved): {name}.py")
        self._update_line_nums()

    def _editor_delete(self):
        name = self._editor_var.get()
        if not name or name == "(none)":
            return
        if not messagebox.askyesno("Delete", f"Delete strategy '{name}'?"):
            return
        p = STRATEGIES_DIR / f"{name}.py"
        if p.exists():
            p.unlink()
        self._code_text.delete("1.0", "end")
        self._editor_status.configure(text="")
        self._refresh_strategy_menus()

    def _refresh_strategy_menus(self):
        strats = list_strategies() or ["(none)"]
        for menu, var in [
            (self._editor_menu,    self._editor_var),
            (self._live_strat_menu, self._live_strat_var),
            (self._bt_strat_menu,  self._bt_strat_var),
        ]:
            menu.configure(values=strats)
            if var.get() not in strats:
                var.set(strats[0])

    # ══════════════════════════════════════════════════════════════════════════
    #  Tab: Backtest
    # ══════════════════════════════════════════════════════════════════════════

    def _build_backtest(self):
        tab = self._tabs.tab("Backtest")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)

        # Config bar
        cfg_bar = ctk.CTkFrame(tab, fg_color=BG_PANEL, corner_radius=6)
        cfg_bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        strats = list_strategies() or ["heikin_ashi"]
        self._bt_strat_var = ctk.StringVar(value=strats[0])
        _inline_label(cfg_bar, "Strategy")
        self._bt_strat_menu = ctk.CTkOptionMenu(cfg_bar, variable=self._bt_strat_var,
                                                  values=strats, width=180)
        self._bt_strat_menu.pack(side="left", padx=(0, 12))

        self._bt_symbol_var = _inline_entry(cfg_bar, "Symbol", "GC=F",  70)
        self._bt_start_var  = _inline_entry(cfg_bar, "Start",  "2024-01-01", 105)
        self._bt_end_var    = _inline_entry(cfg_bar, "End",    "2024-12-31", 105)
        self._bt_tp_var     = _inline_entry(cfg_bar, "TP $",   str(self._cfg.get("take_profit_usd", 10)), 65)
        self._bt_sl_var     = _inline_entry(cfg_bar, "SL $",   str(self._cfg.get("stop_loss_usd", 5)),   65)

        intervals = ["1d", "1h", "30m", "15m", "5m"]
        self._bt_interval_var = ctk.StringVar(value="1d")
        _inline_label(cfg_bar, "Interval")
        ctk.CTkOptionMenu(cfg_bar, variable=self._bt_interval_var, values=intervals,
                           width=75).pack(side="left", padx=(0, 12))

        self._bt_run_btn = ctk.CTkButton(cfg_bar, text="Run Backtest", width=130, height=32,
                                          command=self._run_backtest, fg_color="#1a3c5c")
        self._bt_run_btn.pack(side="right", padx=12, pady=8)

        # Stat cards
        stats_row = ctk.CTkFrame(tab, fg_color="transparent")
        stats_row.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self._bt_stat_vars: dict[str, tk.StringVar] = {}
        for key, label in [("trades", "Trades"), ("win_rate", "Win Rate"),
                            ("total_pnl", "Total PnL $"), ("max_drawdown", "Max Drawdown $"),
                            ("avg_trade", "Avg Trade $")]:
            card = ctk.CTkFrame(stats_row, fg_color=BG_CARD, corner_radius=6, width=160, height=66)
            card.pack(side="left", padx=6)
            card.pack_propagate(False)
            ctk.CTkLabel(card, text=label, text_color=FG_DIM,
                         font=ctk.CTkFont("Segoe UI", 10)).pack(pady=(8, 0))
            sv = tk.StringVar(value="--")
            ctk.CTkLabel(card, textvariable=sv, font=ctk.CTkFont("Courier New", 15, "bold"),
                         text_color=FG_MAIN).pack()
            self._bt_stat_vars[key] = sv

        self._bt_progress = ctk.CTkProgressBar(tab, height=6)
        self._bt_progress.grid(row=1, column=0, sticky="ew", padx=0, pady=(58, 0))
        self._bt_progress.set(0)

        # Trade table
        tree_frame = ctk.CTkFrame(tab, fg_color=BG_PANEL, corner_radius=6)
        tree_frame.grid(row=2, column=0, sticky="nsew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        cols = ("Side", "Entry $", "Exit $", "PnL $", "Reason", "Bar")
        self._bt_tree = ttk.Treeview(tree_frame, columns=cols, show="headings")
        widths = [70, 100, 100, 100, 100, 70]
        for col, w in zip(cols, widths):
            self._bt_tree.heading(col, text=col)
            self._bt_tree.column(col, width=w, anchor="center")
        self._bt_tree.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        sb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._bt_tree.yview)
        sb.grid(row=0, column=1, sticky="ns", pady=6)
        self._bt_tree.configure(yscrollcommand=sb.set)
        self._bt_tree.tag_configure("win",  foreground=FG_GREEN)
        self._bt_tree.tag_configure("loss", foreground=FG_RED)

    def _run_backtest(self):
        self._bt_run_btn.configure(state="disabled", text="Running...")
        self._bt_progress.set(0)
        for v in self._bt_stat_vars.values():
            v.set("--")
        for row in self._bt_tree.get_children():
            self._bt_tree.delete(row)

        try:
            tp = float(self._bt_tp_var.get())
            sl = float(self._bt_sl_var.get())
        except ValueError:
            messagebox.showerror("Invalid", "TP and SL must be numbers.")
            self._bt_run_btn.configure(state="normal", text="Run Backtest")
            return

        def worker():
            result = engine.run_backtest(
                strategy_name=self._bt_strat_var.get(),
                symbol=self._bt_symbol_var.get().strip().upper(),
                start=self._bt_start_var.get().strip(),
                end=self._bt_end_var.get().strip(),
                interval=self._bt_interval_var.get(),
                tp_usd=tp,
                sl_usd=sl,
                progress_cb=lambda p: self.after(0, self._bt_progress.set, p),
            )
            self.after(0, self._display_backtest, result)

        threading.Thread(target=worker, daemon=True).start()

    def _display_backtest(self, result: dict):
        self._bt_run_btn.configure(state="normal", text="Run Backtest")
        self._bt_progress.set(1)
        if "error" in result:
            messagebox.showerror("Backtest Error", result["error"])
            return

        self._bt_stat_vars["trades"].set(str(result["trades"]))
        self._bt_stat_vars["win_rate"].set(f"{result['win_rate']}%")

        def pnl_val(v):
            return (f"+${v:,.2f}" if v >= 0 else f"-${abs(v):,.2f}")

        for key in ("total_pnl", "max_drawdown", "avg_trade"):
            v   = result[key]
            sv  = self._bt_stat_vars[key]
            sv.set(pnl_val(v))

        for t in result["trade_list"]:
            pnl = t["pnl"]
            tag = "win" if pnl >= 0 else "loss"
            self._bt_tree.insert("", "end", values=(
                t["side"],
                f"${t['entry']:,.2f}",
                f"${t['exit']:,.2f}",
                pnl_val(pnl),
                t["reason"],
                t["bar"],
            ), tags=(tag,))

    # ══════════════════════════════════════════════════════════════════════════
    #  Tab: Settings
    # ══════════════════════════════════════════════════════════════════════════

    def _build_settings(self):
        tab = self._tabs.tab("Settings")
        tab.columnconfigure(1, weight=1)

        cfg = self._cfg
        fields = [
            ("Discord Webhook URL",         "discord_webhook",        str,   550),
            ("Check Interval (seconds)",    "check_interval_seconds", int,   120),
            ("Lookback Candles",            "lookback_candles",       int,   120),
            ("Take Profit (USD per oz)",    "take_profit_usd",        float, 120),
            ("Stop Loss (USD per oz)",      "stop_loss_usd",          float, 120),
            ("Data Interval",               "interval",               str,   120),
        ]

        self._setting_vars: dict[str, tuple[tk.StringVar, type]] = {}

        for r, (label, key, typ, width) in enumerate(fields):
            ctk.CTkLabel(tab, text=label, text_color=FG_MID, anchor="e", width=220).grid(
                row=r, column=0, sticky="e", padx=(16, 10), pady=8)
            sv = ctk.StringVar(value=str(cfg.get(key, "")))
            ctk.CTkEntry(tab, textvariable=sv, width=width).grid(row=r, column=1, sticky="w", pady=8)
            self._setting_vars[key] = (sv, typ)

        ctk.CTkButton(tab, text="Save Settings", width=160, command=self._save_settings).grid(
            row=len(fields), column=1, sticky="w", pady=16)
        self._settings_ok = ctk.CTkLabel(tab, text="", text_color=FG_GREEN)
        self._settings_ok.grid(row=len(fields) + 1, column=1, sticky="w")

    def _save_settings(self):
        for key, (sv, typ) in self._setting_vars.items():
            try:
                self._cfg[key] = typ(sv.get().strip())
            except (ValueError, TypeError):
                pass
        save_config(self._cfg)
        self._settings_ok.configure(text="Saved.")
        self.after(3000, lambda: self._settings_ok.configure(text=""))
        # Sync TP/SL to live tab
        self._tp_var.set(str(self._cfg.get("take_profit_usd", 10.0)))
        self._sl_var.set(str(self._cfg.get("stop_loss_usd", 5.0)))


# ── Widget helpers ─────────────────────────────────────────────────────────────

def _section(parent, text: str, row: int):
    ctk.CTkLabel(parent, text=text.upper(), text_color=FG_DIM,
                 font=ctk.CTkFont("Segoe UI", 9, "bold")).grid(
        row=row, column=0, sticky="w", padx=12, pady=(10, 2))


def _inline_label(parent, text: str):
    ctk.CTkLabel(parent, text=text, text_color=FG_MID).pack(side="left", padx=(10, 4), pady=8)


def _inline_entry(parent, label: str, default: str, width: int) -> ctk.StringVar:
    _inline_label(parent, label)
    sv = ctk.StringVar(value=default)
    ctk.CTkEntry(parent, textvariable=sv, width=width).pack(side="left", padx=(0, 4))
    return sv


def _apply_tree_style():
    style = ttk.Style()
    style.theme_use("clam")
    style.configure("Treeview",
                     background=BG_CARD, foreground=FG_MAIN,
                     fieldbackground=BG_CARD, rowheight=26, font=FONT_UI)
    style.configure("Treeview.Heading",
                     background=BG_PANEL, foreground=FG_MID, font=("Segoe UI", 10, "bold"))
    style.map("Treeview", background=[("selected", "#2a2a3a")])


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    os.chdir(ROOT)
    app = App()
    app.mainloop()
