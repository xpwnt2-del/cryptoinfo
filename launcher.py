#!/usr/bin/env python3
"""
launcher.py  –  CryptoInfo Trading Bot GUI Launcher

Double-click this file (or use one of the platform scripts) to:
  1. Configure API keys and bot settings via a simple graphical UI.
  2. Install Python dependencies automatically (uses the current Python).
  3. Launch the Flask web app and open it in your default browser.

Supported platforms: Windows, macOS, Linux
Requirements: Python 3.9+ with tkinter (included in standard distributions)
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional

# ── tkinter guard ─────────────────────────────────────────────────────────────
try:
    import tkinter as tk
    from tkinter import messagebox, scrolledtext, ttk
except ImportError:  # pragma: no cover
    print(
        "ERROR: tkinter is not available.\n"
        "On Debian/Ubuntu: sudo apt install python3-tk\n"
        "On Fedora:        sudo dnf install python3-tkinter\n"
        "On macOS/Windows: tkinter is bundled with the official Python installer."
    )
    sys.exit(1)

# ── Paths ─────────────────────────────────────────────────────────────────────

HERE: Path = Path(__file__).parent.resolve()
ENV_FILE: Path = HERE / ".env"
ENV_EXAMPLE: Path = HERE / ".env.example"
REQUIREMENTS: Path = HERE / "requirements.txt"
APP_SCRIPT: Path = HERE / "app.py"

EXCHANGES = ["binance", "coinbase", "kraken", "bybit", "okx"]
OPENAI_MODELS = ["gpt-4o-mini", "gpt-4o", "gpt-4", "gpt-3.5-turbo"]

# Prefix used in .env.example for keys that have not been set yet
_PLACEHOLDER_PREFIX = "your_"
# Seconds to wait for Flask to bind the port before opening the browser
_FLASK_STARTUP_DELAY = 2


# ── .env helpers ──────────────────────────────────────────────────────────────

def _read_env() -> dict:
    """Return key→value pairs from .env (or .env.example as first-run fallback)."""
    path = ENV_FILE if ENV_FILE.exists() else ENV_EXAMPLE
    values: dict = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            key, _, val = stripped.partition("=")
            values[key.strip()] = val.strip()
    return values


def _write_env(values: dict) -> None:
    """Write *values* to .env, preserving comment structure from .env.example."""
    template = ENV_EXAMPLE.read_text(encoding="utf-8") if ENV_EXAMPLE.exists() else ""
    lines = []
    seen: set = set()

    for raw in template.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            lines.append(raw)
            continue
        if "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            seen.add(key)
            lines.append(f"{key}={values[key]}" if key in values else raw)
        else:
            lines.append(raw)

    # Append any keys not present in the template
    for key, val in values.items():
        if key not in seen:
            lines.append(f"{key}={val}")

    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── Dependency helper ─────────────────────────────────────────────────────────

def _pip_install(log_cb) -> bool:
    """Install requirements.txt into the current Python; returns True on success."""
    if not REQUIREMENTS.exists():
        log_cb("requirements.txt not found – skipping dependency install.\n")
        return True

    log_cb("Installing/verifying dependencies (this may take a moment)…\n")
    cmd = [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS), "--quiet"]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(HERE),
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            log_cb(line)
        proc.wait()
        if proc.returncode == 0:
            log_cb("Dependencies ready.\n")
            return True
        log_cb(f"pip install failed (exit code {proc.returncode}).\n")
        return False
    except Exception as exc:
        log_cb(f"pip install error: {exc}\n")
        return False


# ── Main GUI ──────────────────────────────────────────────────────────────────

class LauncherApp:
    """Main launcher window."""

    # Colour palette (Catppuccin Mocha-inspired)
    _BG = "#1e1e2e"
    _BG2 = "#181825"
    _FG = "#cdd6f4"
    _FIELD = "#313244"
    _BORDER = "#45475a"
    _BLUE = "#89b4fa"
    _GREEN = "#a6e3a1"
    _RED = "#f38ba8"

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("CryptoInfo – Bot Launcher")
        self.root.resizable(False, False)

        self._proc: Optional[subprocess.Popen] = None
        self._running = False
        self._env = _read_env()

        self._build_styles()
        self._build_ui()
        self._load_settings()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Styling ───────────────────────────────────────────────────────────────

    def _build_styles(self) -> None:
        self.root.configure(bg=self._BG)
        s = ttk.Style()
        s.theme_use("clam")

        base = dict(
            background=self._BG,
            foreground=self._FG,
            fieldbackground=self._FIELD,
            bordercolor=self._BORDER,
            troughcolor=self._FIELD,
        )
        s.configure(".", **base)
        s.configure("TLabel", background=self._BG, foreground=self._FG)
        s.configure("TEntry", fieldbackground=self._FIELD, foreground=self._FG,
                    insertcolor=self._FG)
        s.configure("TCombobox", fieldbackground=self._FIELD, foreground=self._FG,
                    selectbackground=self._BORDER)
        s.configure("TCheckbutton", background=self._BG, foreground=self._FG)
        s.configure("TButton", background="#6c7086", foreground=self._FG,
                    borderwidth=0, focusthickness=0, padding=6)
        s.map("TButton",
              background=[("active", "#7f849c"), ("disabled", self._BORDER)],
              foreground=[("disabled", "#6c7086")])
        s.configure("Start.TButton", background="#40a02b", foreground="#ffffff")
        s.map("Start.TButton",
              background=[("active", "#4ec93a"), ("disabled", self._BORDER)])
        s.configure("Stop.TButton", background="#e64553", foreground="#ffffff")
        s.map("Stop.TButton",
              background=[("active", "#f05e6a"), ("disabled", self._BORDER)])
        s.configure("TNotebook", background=self._BG2)
        s.configure("TNotebook.Tab", background=self._FIELD, foreground=self._FG,
                    padding=[14, 4])
        s.map("TNotebook.Tab",
              background=[("selected", self._BG)],
              foreground=[("selected", self._BLUE)])
        s.configure("TLabelframe", background=self._BG, bordercolor=self._BORDER)
        s.configure("TLabelframe.Label", background=self._BG, foreground=self._BLUE)
        s.configure("TFrame", background=self._BG)

    # ── UI layout ─────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # Header
        tk.Label(
            self.root, text="🤖  CryptoInfo Trading Bot",
            bg=self._BG2, fg=self._BLUE,
            font=("Helvetica", 17, "bold"), pady=10,
        ).pack(fill="x")

        # Notebook
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=12, pady=(6, 0))
        self._build_settings_tab(nb)
        self._build_log_tab(nb)

        # Bottom bar
        bar = tk.Frame(self.root, bg=self._BG2, pady=8)
        bar.pack(fill="x", side="bottom")

        self._btn_save = ttk.Button(bar, text="💾  Save Settings",
                                    command=self._save_settings)
        self._btn_save.pack(side="left", padx=(12, 4))

        self._btn_start = ttk.Button(bar, text="▶  Start Bot",
                                     command=self._start_bot,
                                     style="Start.TButton")
        self._btn_start.pack(side="left", padx=4)

        self._btn_stop = ttk.Button(bar, text="⏹  Stop Bot",
                                    command=self._stop_bot,
                                    style="Stop.TButton", state="disabled")
        self._btn_stop.pack(side="left", padx=4)

        self._btn_browser = ttk.Button(bar, text="🌐  Open Browser",
                                       command=self._open_browser, state="disabled")
        self._btn_browser.pack(side="left", padx=4)

        self._status_var = tk.StringVar(value="⏸  Stopped")
        self._status_lbl = tk.Label(bar, textvariable=self._status_var,
                                    bg=self._BG2, fg=self._FG,
                                    font=("Helvetica", 11))
        self._status_lbl.pack(side="right", padx=12)

    def _build_settings_tab(self, nb: ttk.Notebook) -> None:
        outer = ttk.Frame(nb)
        nb.add(outer, text="⚙  Settings")

        # Scrollable inner area
        canvas = tk.Canvas(outer, bg=self._BG, highlightthickness=0, width=520)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        pad = {"padx": 12, "pady": 5}

        # Exchange section
        ef = ttk.LabelFrame(inner, text="Exchange", padding=10)
        ef.pack(fill="x", **pad)

        ttk.Label(ef, text="Exchange:").grid(row=0, column=0, sticky="w", pady=3)
        self._exchange_var = tk.StringVar()
        ttk.Combobox(ef, textvariable=self._exchange_var, values=EXCHANGES,
                     state="readonly", width=22).grid(
            row=0, column=1, sticky="w", padx=8, pady=3)

        ttk.Label(ef, text="API Key:").grid(row=1, column=0, sticky="w", pady=3)
        self._api_key_var = tk.StringVar()
        ttk.Entry(ef, textvariable=self._api_key_var, show="•", width=42).grid(
            row=1, column=1, sticky="ew", padx=8, pady=3)

        ttk.Label(ef, text="API Secret:").grid(row=2, column=0, sticky="w", pady=3)
        self._api_secret_var = tk.StringVar()
        ttk.Entry(ef, textvariable=self._api_secret_var, show="•", width=42).grid(
            row=2, column=1, sticky="ew", padx=8, pady=3)

        tk.Label(
            ef,
            text="Leave API Key/Secret empty to use read-only mode (no trading).",
            bg=self._BG, fg=self._BORDER, font=("Helvetica", 9),
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(0, 2))

        # OpenAI section
        af = ttk.LabelFrame(
            inner, text="OpenAI  (optional – enables AI-powered analysis)", padding=10)
        af.pack(fill="x", **pad)

        ttk.Label(af, text="OpenAI API Key:").grid(row=0, column=0, sticky="w", pady=3)
        self._openai_key_var = tk.StringVar()
        ttk.Entry(af, textvariable=self._openai_key_var, show="•", width=42).grid(
            row=0, column=1, sticky="ew", padx=8, pady=3)

        ttk.Label(af, text="Model:").grid(row=1, column=0, sticky="w", pady=3)
        self._openai_model_var = tk.StringVar()
        ttk.Combobox(af, textvariable=self._openai_model_var, values=OPENAI_MODELS,
                     state="readonly", width=22).grid(
            row=1, column=1, sticky="w", padx=8, pady=3)

        # Bot behavior section
        bf = ttk.LabelFrame(inner, text="Bot Behavior", padding=10)
        bf.pack(fill="x", **pad)

        self._dry_run_var = tk.BooleanVar()
        ttk.Checkbutton(
            bf,
            text="Dry Run  (simulate trades – no real orders placed)",
            variable=self._dry_run_var,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=3)

        ttk.Label(bf, text="Check interval (seconds):").grid(
            row=1, column=0, sticky="w", pady=3)
        self._interval_var = tk.StringVar()
        ttk.Entry(bf, textvariable=self._interval_var, width=10).grid(
            row=1, column=1, sticky="w", padx=8, pady=3)

        ttk.Label(bf, text="Min confidence to trade (0–100):").grid(
            row=2, column=0, sticky="w", pady=3)
        self._confidence_var = tk.StringVar()
        ttk.Entry(bf, textvariable=self._confidence_var, width=10).grid(
            row=2, column=1, sticky="w", padx=8, pady=3)

        ttk.Label(bf, text="Trade amount (base currency units):").grid(
            row=3, column=0, sticky="w", pady=3)
        self._trade_amount_var = tk.StringVar()
        ttk.Entry(bf, textvariable=self._trade_amount_var, width=10).grid(
            row=3, column=1, sticky="w", padx=8, pady=3)

        # App settings section
        sf = ttk.LabelFrame(inner, text="App Settings", padding=10)
        sf.pack(fill="x", **pad)

        ttk.Label(sf, text="Port:").grid(row=0, column=0, sticky="w", pady=3)
        self._port_var = tk.StringVar()
        ttk.Entry(sf, textvariable=self._port_var, width=10).grid(
            row=0, column=1, sticky="w", padx=8, pady=3)

        ttk.Label(sf, text="Secret key:").grid(row=1, column=0, sticky="w", pady=3)
        self._secret_key_var = tk.StringVar()
        ttk.Entry(sf, textvariable=self._secret_key_var, show="•", width=42).grid(
            row=1, column=1, sticky="ew", padx=8, pady=3)

        # Spacer at bottom of scrollable area
        ttk.Label(inner).pack(pady=4)

    def _build_log_tab(self, nb: ttk.Notebook) -> None:
        frame = ttk.Frame(nb)
        nb.add(frame, text="📋  Log")

        self._log_text = scrolledtext.ScrolledText(
            frame,
            bg="#11111b", fg=self._FG, insertbackground=self._FG,
            font=("Courier", 10), wrap="word",
            state="disabled", height=16,
        )
        self._log_text.pack(fill="both", expand=True, padx=8, pady=8)

        btn_row = tk.Frame(frame, bg=self._BG)
        btn_row.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(btn_row, text="Clear", command=self._clear_log).pack(side="right")

    # ── Settings load / save ──────────────────────────────────────────────────

    def _load_settings(self) -> None:
        e = self._env

        self._exchange_var.set(e.get("EXCHANGE_ID", "binance"))

        # Strip placeholder text so fields appear blank when not configured
        def _clean(val: str, placeholder: str) -> str:
            return "" if val.startswith(placeholder) else val

        self._api_key_var.set(_clean(e.get("EXCHANGE_API_KEY", ""), _PLACEHOLDER_PREFIX))
        self._api_secret_var.set(_clean(e.get("EXCHANGE_SECRET", ""), _PLACEHOLDER_PREFIX))
        self._openai_key_var.set(_clean(e.get("OPENAI_API_KEY", ""), _PLACEHOLDER_PREFIX))

        model = e.get("OPENAI_MODEL", "gpt-4o-mini")
        self._openai_model_var.set(model if model in OPENAI_MODELS else "gpt-4o-mini")

        self._dry_run_var.set(e.get("DRY_RUN", "true").lower() != "false")
        self._interval_var.set(e.get("BOT_INTERVAL", "60"))
        self._confidence_var.set(e.get("MIN_CONFIDENCE", "70"))
        self._trade_amount_var.set(e.get("BOT_TRADE_AMOUNT", "0.001"))
        self._port_var.set(e.get("PORT", "5000"))
        self._secret_key_var.set(
            _clean(e.get("SECRET_KEY", ""), "change-me"))

    def _save_settings(self) -> None:
        values = {
            "EXCHANGE_ID":      self._exchange_var.get()       or "binance",
            "EXCHANGE_API_KEY": self._api_key_var.get()        or "your_api_key_here",
            "EXCHANGE_SECRET":  self._api_secret_var.get()     or "your_api_secret_here",
            "OPENAI_API_KEY":   self._openai_key_var.get()     or "your_openai_key_here",
            "OPENAI_MODEL":     self._openai_model_var.get()   or "gpt-4o-mini",
            "DRY_RUN":          "false" if not self._dry_run_var.get() else "true",
            "BOT_INTERVAL":     self._interval_var.get()       or "60",
            "MIN_CONFIDENCE":   self._confidence_var.get()     or "70",
            "BOT_TRADE_AMOUNT": self._trade_amount_var.get()   or "0.001",
            "PORT":             self._port_var.get()           or "5000",
            "SECRET_KEY":       self._secret_key_var.get()     or "change-me-to-a-random-string",
            "DEBUG":            "false",
        }
        try:
            _write_env(values)
            self._log("✔ Settings saved to .env\n")
            messagebox.showinfo("Saved", "Settings saved successfully!", parent=self.root)
        except Exception as exc:
            messagebox.showerror("Save Error", f"Could not save settings:\n{exc}",
                                 parent=self.root)

    # ── Bot lifecycle ─────────────────────────────────────────────────────────

    def _start_bot(self) -> None:
        if self._running:
            return
        self._set_buttons(running=False, starting=True)
        self._log("▶ Starting bot…\n")
        threading.Thread(target=self._launch_sequence, daemon=True).start()

    def _launch_sequence(self) -> None:
        """Background thread: install deps → start Flask → open browser."""
        if not _pip_install(self._log):
            self._log("✘ Dependency install failed. Fix the errors above and try again.\n")
            self.root.after(0, lambda: self._set_buttons(running=False))
            return

        port = self._port_var.get() or "5000"
        env = {**os.environ, "PORT": port}

        try:
            self._proc = subprocess.Popen(
                [sys.executable, str(APP_SCRIPT)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
                cwd=str(HERE),
            )
        except Exception as exc:
            self._log(f"✘ Failed to start bot: {exc}\n")
            self.root.after(0, lambda: self._set_buttons(running=False))
            return

        self._running = True
        self.root.after(0, lambda: self._set_buttons(running=True))

        # Give Flask a moment to bind the port, then open browser
        time.sleep(_FLASK_STARTUP_DELAY)
        url = f"http://localhost:{port}"
        self._log(f"🌐 Opening {url}\n")
        webbrowser.open(url)

        # Pipe Flask output into the Log tab
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            self._log(line)

        self._proc.wait()
        self._running = False
        self.root.after(0, lambda: self._set_buttons(running=False))

    def _stop_bot(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._log("⏹ Stopping bot…\n")
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    # ── Button / status helpers ───────────────────────────────────────────────

    def _set_buttons(self, running: bool, starting: bool = False) -> None:
        if starting:
            self._btn_start.config(state="disabled")
            self._btn_save.config(state="disabled")
            self._btn_stop.config(state="disabled")
            self._btn_browser.config(state="disabled")
            self._status_var.set("⏳ Starting…")
            self._status_lbl.config(fg=self._BLUE)
            return

        if running:
            port = self._port_var.get() or "5000"
            self._btn_start.config(state="disabled")
            self._btn_save.config(state="disabled")
            self._btn_stop.config(state="normal")
            self._btn_browser.config(state="normal")
            self._status_var.set(f"●  Running  (port {port})")
            self._status_lbl.config(fg=self._GREEN)
        else:
            self._btn_start.config(state="normal")
            self._btn_save.config(state="normal")
            self._btn_stop.config(state="disabled")
            self._btn_browser.config(state="disabled")
            self._status_var.set("⏸  Stopped")
            self._status_lbl.config(fg=self._FG)

    # ── Log helpers ───────────────────────────────────────────────────────────

    def _log(self, text: str) -> None:
        def _do():
            self._log_text.config(state="normal")
            self._log_text.insert("end", text)
            self._log_text.see("end")
            self._log_text.config(state="disabled")
        self.root.after(0, _do)

    def _clear_log(self) -> None:
        self._log_text.config(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.config(state="disabled")

    # ── Browser helper ────────────────────────────────────────────────────────

    def _open_browser(self) -> None:
        port = self._port_var.get() or "5000"
        webbrowser.open(f"http://localhost:{port}")

    # ── Window close ─────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        if self._running:
            if not messagebox.askyesno(
                "Quit", "The bot is still running.\nStop it and quit?",
                parent=self.root,
            ):
                return
            self._stop_bot()
        self.root.destroy()


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    root = tk.Tk()
    root.geometry("560x640")
    LauncherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
