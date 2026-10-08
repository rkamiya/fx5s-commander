"""設定ウィンドウ。[接続設定] タブで接続先、[リレー] タブで各指令の内部リレーを設定する。

入力の検証と画面表示だけを担当する。接続確認と保存の実処理は App から渡されるコールバックが行う。
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import replace
from tkinter import ttk

from fx5s_commander.commands import CheckResult, Command
from fx5s_commander.config import (
    AppConfig,
    ConfigError,
    ConnectionConfig,
    parse_devices,
    validate_connection,
)
from fx5s_commander.devices import M_DEVICE_MAX, Device

_OK_COLOR = "#2e7d32"
_ERROR_COLOR = "#c62828"

DeviceMap = dict[Command, Device]


class SettingsWindow:
    def __init__(
        self,
        parent: tk.Tk,
        *,
        config: AppConfig,
        on_check: Callable[[ConnectionConfig, DeviceMap], bool],
        on_save: Callable[[ConnectionConfig, DeviceMap], str | None],
        on_closed: Callable[[], None],
    ) -> None:
        """on_check は確認を始めたら True、on_save は失敗時にエラーメッセージを返す。"""
        self._base = config.connection
        self._on_check = on_check
        self._on_save = on_save
        self._on_closed = on_closed
        self._checking = False

        self._window = window = tk.Toplevel(parent)
        window.title("設定")
        window.resizable(False, False)
        window.transient(parent)
        window.protocol("WM_DELETE_WINDOW", self.close)
        window.bind("<Escape>", lambda _: self.close())

        frame = tk.Frame(window, padx=16, pady=12)
        frame.pack(fill=tk.BOTH, expand=True)

        self._notebook = ttk.Notebook(frame)
        self._notebook.pack(fill=tk.BOTH, expand=True)
        self._connection_tab = self._build_connection_tab(config.connection)
        self._relay_tab = self._build_relay_tab(config.devices)
        self._notebook.add(self._connection_tab, text="接続設定")
        self._notebook.add(self._relay_tab, text="リレー")

        self._message = tk.Label(frame, text="", wraplength=320, justify=tk.LEFT, anchor="w")
        self._message.pack(fill=tk.X, pady=(8, 0))

        actions = tk.Frame(frame, pady=8)
        actions.pack(anchor="e")
        self._save_button = tk.Button(actions, text="保存", width=8, command=self._save)
        self._save_button.pack(side=tk.LEFT, padx=4)
        tk.Button(actions, text="キャンセル", width=8, command=self.close).pack(side=tk.LEFT)

        self._update_entries()
        window.grab_set()
        window.focus_set()

    def _build_connection_tab(self, connection: ConnectionConfig) -> tk.Frame:
        tab = tk.Frame(self._notebook, padx=12, pady=12)
        self._mock = tk.BooleanVar(value=connection.mock)
        self._host = tk.StringVar(value=connection.host)
        self._port = tk.StringVar(value=str(connection.port))
        tk.Checkbutton(
            tab,
            text="モック PLC を使う（実機に接続しない）",
            variable=self._mock,
            command=self._update_entries,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        tk.Label(tab, text="IP アドレス").grid(row=1, column=0, sticky="w", pady=4)
        self._host_entry = tk.Entry(tab, textvariable=self._host, width=20)
        self._host_entry.grid(row=1, column=1, sticky="ew", pady=4)
        tk.Label(tab, text="ポート番号").grid(row=2, column=0, sticky="w", pady=4)
        self._port_entry = tk.Entry(tab, textvariable=self._port, width=8)
        self._port_entry.grid(row=2, column=1, sticky="w", pady=4)
        tab.columnconfigure(1, weight=1)

        self._check_button = tk.Button(tab, text="接続確認", command=self._check)
        self._check_button.grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))
        return tab

    def _build_relay_tab(self, devices: DeviceMap) -> tk.Frame:
        tab = tk.Frame(self._notebook, padx=12, pady=12)
        self._relays = {command: tk.StringVar(value=str(devices[command])) for command in Command}
        for row, command in enumerate(Command):
            tk.Label(tab, text=command.label).grid(row=row, column=0, sticky="w", pady=4)
            tk.Entry(tab, textvariable=self._relays[command], width=10).grid(
                row=row, column=1, sticky="w", pady=4
            )
        tk.Label(
            tab,
            text=(
                f"M0〜M{M_DEVICE_MAX} の内部リレーを指定します。"
                "ラダー側の割り当て（受付後に RST する処理を含む）と合わせてください。"
            ),
            fg="#555555",
            wraplength=280,
            justify=tk.LEFT,
        ).grid(row=len(Command), column=0, columnspan=2, sticky="w", pady=(8, 0))
        return tab

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
        values = self._read_input()
        if values is None:
            return
        connection, devices = values
        if self._on_check(connection, devices):
            self._checking = True
            self._show(f"{connection.label} に接続しています…", "black")
        else:
            self._show("処理中です。しばらくしてからもう一度押してください。", _ERROR_COLOR)

    def _save(self) -> None:
        values = self._read_input()
        if values is None:
            return
        error = self._on_save(*values)
        if error is not None:
            self._show(error, _ERROR_COLOR)
            return
        self.close()

    def _read_input(self) -> tuple[ConnectionConfig, DeviceMap] | None:
        """入力を検証する。エラーがあればそのタブを開いてメッセージを出し、None を返す。"""
        try:
            port = int(self._port.get().strip())
        except ValueError:
            return self._fail(self._connection_tab, "ポート番号は数字で入力してください。")
        connection = replace(
            self._base, host=self._host.get().strip(), port=port, mock=self._mock.get()
        )
        try:
            validate_connection(connection)
        except ConfigError as e:
            return self._fail(self._connection_tab, str(e))
        try:
            devices = parse_devices({c: v.get() for c, v in self._relays.items()})
        except ConfigError as e:
            return self._fail(self._relay_tab, str(e))
        return connection, devices

    def _fail(self, tab: tk.Frame, message: str) -> None:
        self._notebook.select(tab)
        self._show(message, _ERROR_COLOR)
        return None

    def _update_entries(self) -> None:
        # モックのときは IP アドレスとポート番号を使わないので入力できないようにする（値は残す）
        state = tk.DISABLED if self._mock.get() else tk.NORMAL
        self._host_entry.config(state=state)
        self._port_entry.config(state=state)

    def _show(self, text: str, color: str) -> None:
        self._message.config(text=text, fg=color)
