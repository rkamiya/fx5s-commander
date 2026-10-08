"""接続先（IP アドレス・ポート番号）を設定するウィンドウ。

入力の検証と画面表示だけを担当する。接続確認と保存の実処理は App から渡されるコールバックが行う。
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import replace

from fx5s_commander.commands import CheckResult
from fx5s_commander.config import ConfigError, ConnectionConfig, validate_connection

_OK_COLOR = "#2e7d32"
_ERROR_COLOR = "#c62828"


class SettingsWindow:
    def __init__(
        self,
        parent: tk.Tk,
        *,
        connection: ConnectionConfig,
        on_check: Callable[[ConnectionConfig], bool],
        on_save: Callable[[ConnectionConfig], str | None],
        on_closed: Callable[[], None],
    ) -> None:
        """on_check は確認を始めたら True、on_save は失敗時にエラーメッセージを返す。"""
        self._base = connection
        self._on_check = on_check
        self._on_save = on_save
        self._on_closed = on_closed
        self._checking = False

        self._window = window = tk.Toplevel(parent)
        window.title("接続設定")
        window.resizable(False, False)
        window.transient(parent)
        window.protocol("WM_DELETE_WINDOW", self.close)
        window.bind("<Escape>", lambda _: self.close())

        frame = tk.Frame(window, padx=16, pady=12)
        frame.pack(fill=tk.BOTH, expand=True)

        self._host = tk.StringVar(value=connection.host)
        self._port = tk.StringVar(value=str(connection.port))
        tk.Label(frame, text="IP アドレス").grid(row=0, column=0, sticky="w", pady=4)
        host_entry = tk.Entry(frame, textvariable=self._host, width=20)
        host_entry.grid(row=0, column=1, sticky="ew", pady=4)
        tk.Label(frame, text="ポート番号").grid(row=1, column=0, sticky="w", pady=4)
        tk.Entry(frame, textvariable=self._port, width=8).grid(row=1, column=1, sticky="w", pady=4)
        frame.columnconfigure(1, weight=1)

        self._check_button = tk.Button(frame, text="接続確認", command=self._check)
        self._check_button.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 4))
        self._message = tk.Label(frame, text="", wraplength=300, justify=tk.LEFT, anchor="w")
        self._message.grid(row=3, column=0, columnspan=2, sticky="ew")

        actions = tk.Frame(frame, pady=8)
        actions.grid(row=4, column=0, columnspan=2, sticky="e")
        self._save_button = tk.Button(actions, text="保存", width=8, command=self._save)
        self._save_button.pack(side=tk.LEFT, padx=4)
        tk.Button(actions, text="キャンセル", width=8, command=self.close).pack(side=tk.LEFT)

        window.grab_set()
        host_entry.focus_set()

    def set_busy(self, busy: bool) -> None:
        """PLC と通信中は接続確認と保存を押せないようにする。"""
        state = tk.DISABLED if busy else tk.NORMAL
        self._check_button.config(state=state)
        self._save_button.config(state=state)

    def show_check_result(self, result: CheckResult) -> None:
        if not self._checking:
            return
        self._checking = False
        self._show(result.message, _OK_COLOR if result.ok else _ERROR_COLOR)

    def close(self) -> None:
        self._window.grab_release()
        self._window.destroy()
        self._on_closed()

    def _check(self) -> None:
        connection = self._read_input()
        if connection is None:
            return
        if self._on_check(connection):
            self._checking = True
            self._show(f"{connection.host}:{connection.port} に接続しています…", "black")
        else:
            self._show("処理中です。しばらくしてからもう一度押してください。", _ERROR_COLOR)

    def _save(self) -> None:
        connection = self._read_input()
        if connection is None:
            return
        error = self._on_save(connection)
        if error is not None:
            self._show(error, _ERROR_COLOR)
            return
        self.close()

    def _read_input(self) -> ConnectionConfig | None:
        try:
            port = int(self._port.get().strip())
        except ValueError:
            self._show("ポート番号は数字で入力してください。", _ERROR_COLOR)
            return None
        connection = replace(self._base, host=self._host.get().strip(), port=port)
        try:
            validate_connection(connection)
        except ConfigError as e:
            self._show(str(e), _ERROR_COLOR)
            return None
        return connection

    def _show(self, text: str, color: str) -> None:
        self._message.config(text=text, fg=color)
