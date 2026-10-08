"""tkinter による操作画面。

画面は表示と入力だけを担当し、PLC との通信は TaskWorker 経由でバックグラウンドで行う。
ワーカーからの結果はキューで受け取り、after() で定期的に取り出して画面に反映する。
"""

from __future__ import annotations

import logging
import queue
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from tkinter import scrolledtext
from typing import Any

from fx5s_commander.commands import (
    CheckResult,
    Command,
    CommandResult,
    CommandSender,
    Outcome,
    check_connection,
)
from fx5s_commander.config import AppConfig, ConnectionConfig, save_config
from fx5s_commander.plc.client import PlcClient
from fx5s_commander.settings_window import SettingsWindow
from fx5s_commander.worker import TaskWorker

logger = logging.getLogger(__name__)

_POLL_MS = 50
_SHUTDOWN_TIMEOUT_SEC = 5.0

_BUTTON_COLORS = {
    Command.ON: "#2e7d32",
    Command.OFF: "#546e7a",
    Command.STOP: "#c62828",
}

_OUTCOME_COLORS = {
    Outcome.ACCEPTED: "#2e7d32",
    Outcome.NOT_ACCEPTED: "#ef6c00",
    Outcome.BUSY: "#ef6c00",
    Outcome.ERROR: "#c62828",
}


@dataclass(frozen=True)
class ConnectionChanged:
    connection: ConnectionConfig


class App:
    def __init__(
        self,
        root: tk.Tk,
        *,
        config: AppConfig,
        config_path: Path,
        sender: CommandSender,
        client_factory: Callable[[ConnectionConfig], PlcClient],
        worker: TaskWorker,
        results: queue.Queue[Any],
        mock: bool,
    ) -> None:
        self._root = root
        self._config = config
        self._config_path = config_path
        self._sender = sender
        self._client_factory = client_factory
        self._worker = worker
        self._results = results
        self._mock = mock
        self._settings: SettingsWindow | None = None

        title = "FX5S Commander" + ("（モック）" if mock else "")
        root.title(title)
        root.minsize(420, 420)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        frame = tk.Frame(root, padx=16, pady=12)
        frame.pack(fill=tk.BOTH, expand=True)

        header = tk.Frame(frame)
        header.pack(fill=tk.X)
        self._target = tk.Label(header)
        self._target.pack(side=tk.LEFT)
        tk.Button(header, text="設定", command=self._open_settings).pack(side=tk.RIGHT)
        self._update_target()

        buttons = tk.Frame(frame, pady=12)
        buttons.pack(fill=tk.X)
        self._command_buttons: dict[Command, tk.Button] = {}
        for column, command in enumerate(Command):
            button = tk.Button(
                buttons,
                text=f"{command.label}\n({sender.device_for(command)})",
                font=("", 14, "bold"),
                fg="white",
                bg=_BUTTON_COLORS[command],
                activeforeground="white",
                activebackground=_BUTTON_COLORS[command],
                height=3,
                command=lambda c=command: self._on_command(c),
            )
            button.grid(row=0, column=column, sticky="nsew", padx=4)
            buttons.columnconfigure(column, weight=1, uniform="cmd")
            self._command_buttons[command] = button

        tk.Label(
            frame,
            text=(
                "※ 停止要求は非常停止ではありません。"
                "非常時は設備の非常停止スイッチを使用してください。"
            ),
            fg="#c62828",
            wraplength=380,
            justify=tk.LEFT,
        ).pack(fill=tk.X)

        self._status = tk.Label(frame, text="待機中", anchor="w", pady=8)
        self._status.pack(fill=tk.X)

        self._log = scrolledtext.ScrolledText(frame, height=10, state=tk.DISABLED)
        self._log.pack(fill=tk.BOTH, expand=True)

        root.after(_POLL_MS, self._poll)

    def _on_command(self, command: Command) -> None:
        accepted = self._worker.submit(
            lambda: self._sender.send(command), priority=command is Command.STOP
        )
        if accepted:
            self._set_status(f"{command.label} 指令を送信中…", "black")
        else:
            self._set_status(f"処理中のため {command.label} を受け付けませんでした", "#ef6c00")
        self._update_buttons()

    def _open_settings(self) -> None:
        if self._settings is not None:
            return
        self._settings = SettingsWindow(
            self._root,
            connection=self._config.connection,
            on_check=self._check_candidate,
            on_save=self._save_connection,
            on_closed=self._on_settings_closed,
        )
        self._update_buttons()

    def _on_settings_closed(self) -> None:
        self._settings = None

    def _check_candidate(self, connection: ConnectionConfig) -> bool:
        """設定画面で入力中の接続先に、今の接続とは別につないで確認する。"""
        devices = list(self._config.devices.values())

        def task() -> CheckResult:
            client = self._client_factory(connection)
            try:
                return check_connection(client, devices)
            finally:
                client.close()

        accepted = self._worker.submit(task)
        self._update_buttons()
        return accepted

    def _save_connection(self, connection: ConnectionConfig) -> str | None:
        """接続先を切り替えて設定ファイルに保存する。失敗したらエラーメッセージを返す。"""
        if not self._worker.submit(lambda: self._switch_client(connection)):
            return "処理中のため保存できませんでした。しばらくしてからもう一度押してください。"
        self._config = replace(self._config, connection=connection)
        self._update_target()
        try:
            save_config(self._config_path, self._config)
        except OSError as e:
            logger.exception("設定の保存に失敗しました")
            return f"接続先は切り替えましたが、{self._config_path} に保存できませんでした: {e}"
        logger.info("設定を保存しました: %s", self._config_path)
        self._append_log(f"設定を {self._config_path} に保存しました")
        return None

    def _switch_client(self, connection: ConnectionConfig) -> ConnectionChanged:
        # ワーカースレッドで実行する（通信中のクライアントを別スレッドから閉じないため）
        self._sender.set_client(self._client_factory(connection))
        logger.info("接続先を %s:%s に変更しました", connection.host, connection.port)
        return ConnectionChanged(connection)

    def _update_target(self) -> None:
        conn = self._config.connection
        suffix = "（モック）" if self._mock else ""
        self._target.config(text=f"接続先: {conn.host}:{conn.port}{suffix}")

    def _poll(self) -> None:
        while True:
            try:
                result = self._results.get_nowait()
            except queue.Empty:
                break
            self._show_result(result)
        self._update_buttons()
        self._root.after(_POLL_MS, self._poll)

    def _show_result(self, result: Any) -> None:
        if isinstance(result, CommandResult):
            color = _OUTCOME_COLORS[result.outcome]
            self._set_status(result.message, color)
            self._append_log(
                f"{result.command.label} ({result.device}) "
                f"[{result.outcome.value}] {result.message} ({result.elapsed_sec:.2f}s)"
            )
        elif isinstance(result, CheckResult):
            self._append_log(result.message)
            if self._settings is not None:
                self._settings.show_check_result(result)
        elif isinstance(result, ConnectionChanged):
            conn = result.connection
            self._set_status(f"接続先を {conn.host}:{conn.port} に変更しました", "black")
            self._append_log(f"接続先を {conn.host}:{conn.port} に変更しました")
        else:
            self._set_status(f"内部エラー: {result}", "#c62828")
            self._append_log(f"内部エラー: {result!r}")

    def _update_buttons(self) -> None:
        busy = self._worker.busy
        state = tk.DISABLED if busy else tk.NORMAL
        self._command_buttons[Command.ON].config(state=state)
        self._command_buttons[Command.OFF].config(state=state)
        # 停止要求は処理中でも押せるようにしておく
        if self._settings is not None:
            self._settings.set_busy(busy)

    def _set_status(self, text: str, color: str) -> None:
        self._status.config(text=text, fg=color)

    def _append_log(self, line: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self._log.config(state=tk.NORMAL)
        self._log.insert(tk.END, f"{stamp} {line}\n")
        self._log.see(tk.END)
        self._log.config(state=tk.DISABLED)

    def _on_close(self) -> None:
        self._set_status("終了しています…", "black")
        self._root.update_idletasks()
        self._worker.shutdown(timeout=_SHUTDOWN_TIMEOUT_SEC)
        self._root.destroy()
