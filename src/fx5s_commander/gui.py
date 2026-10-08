"""tkinter による操作画面。

画面は表示と入力だけを担当し、PLC との通信は TaskWorker 経由でバックグラウンドで行う。
ワーカーからの結果はキューで受け取り、after() で定期的に取り出して画面に反映する。
ランプは一定間隔で PLC から読み出す（読み出しは指令の送信より後回しにする）。
"""

from __future__ import annotations

import logging
import queue
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
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
from fx5s_commander.config import AppConfig, save_config
from fx5s_commander.devices import Device
from fx5s_commander.monitor import Lamp, LampReading, read_lamps
from fx5s_commander.plc.client import PlcClient
from fx5s_commander.settings_window import SettingsWindow
from fx5s_commander.worker import TaskWorker

logger = logging.getLogger(__name__)

_POLL_MS = 50
_LAMP_RETRY_MS = 3000  # 読み出しに失敗したときは間隔を空けて再接続する
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


_LAMP_COLORS = {
    Lamp.RUNNING: "#43a047",
    Lamp.STOPPED: "#e53935",
}
_LAMP_OFF_COLOR = "#5f6368"
_LAMP_UNKNOWN_COLOR = "#d6d6d6"


@dataclass(frozen=True)
class SettingsApplied:
    config: AppConfig


class LampIndicator:
    """丸いランプ 1 個と、その名前・リレーの表示。"""

    _SIZE = 32

    def __init__(self, parent: tk.Widget, lamp: Lamp, device: Device) -> None:
        self._lamp = lamp
        self.frame = tk.Frame(parent)
        self._canvas = tk.Canvas(
            self.frame, width=self._SIZE, height=self._SIZE, highlightthickness=0
        )
        self._canvas.pack(side=tk.LEFT)
        self._circle = self._canvas.create_oval(
            2, 2, self._SIZE - 2, self._SIZE - 2, outline="#9e9e9e", width=1
        )
        self._label = tk.Label(self.frame, justify=tk.LEFT, font=("", 11, "bold"))
        self._label.pack(side=tk.LEFT, padx=(6, 0))
        self.set_device(device)
        self.set_state(None)

    def set_device(self, device: Device) -> None:
        self._label.config(text=f"{self._lamp.label}\n({device})")

    def set_state(self, on: bool | None) -> None:
        """None は状態が分からない（未読み出し・通信エラー）ことを表す。"""
        if on is None:
            color = _LAMP_UNKNOWN_COLOR
        else:
            color = _LAMP_COLORS[self._lamp] if on else _LAMP_OFF_COLOR
        self._canvas.itemconfig(self._circle, fill=color)


class App:
    def __init__(
        self,
        root: tk.Tk,
        *,
        config: AppConfig,
        config_path: Path,
        sender: CommandSender,
        client_factory: Callable[[AppConfig], PlcClient],
        worker: TaskWorker,
        results: queue.Queue[Any],
    ) -> None:
        self._root = root
        self._config = config
        self._config_path = config_path
        self._sender = sender
        self._client_factory = client_factory
        self._worker = worker
        self._results = results
        self._settings: SettingsWindow | None = None
        self._lamps_readable: bool | None = None

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

        lamps = tk.Frame(frame, pady=12)
        lamps.pack(fill=tk.X)
        self._lamps: dict[Lamp, LampIndicator] = {}
        for column, lamp in enumerate(Lamp):
            indicator = LampIndicator(lamps, lamp, config.lamps[lamp])
            indicator.frame.grid(row=0, column=column, padx=4)
            lamps.columnconfigure(column, weight=1, uniform="lamp")
            self._lamps[lamp] = indicator
        self._lamp_status = tk.Label(frame, text="ランプ: 読み出し待ち", fg="#555555", anchor="w")
        self._lamp_status.pack(fill=tk.X)

        buttons = tk.Frame(frame, pady=12)
        buttons.pack(fill=tk.X)
        self._command_buttons: dict[Command, tk.Button] = {}
        for column, command in enumerate(Command):
            button = tk.Button(
                buttons,
                text=_button_text(command, config.devices[command]),
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

        self._status = tk.Label(frame, text="待機中", anchor="w", pady=8)
        self._status.pack(fill=tk.X)

        self._log = scrolledtext.ScrolledText(frame, height=10, state=tk.DISABLED)
        self._log.pack(fill=tk.BOTH, expand=True)

        root.after(_POLL_MS, self._poll)
        root.after(0, self._request_lamp_read)

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
            config=self._config,
            on_check=self._check_candidate,
            on_save=self._save_settings,
            on_closed=self._on_settings_closed,
        )
        self._update_buttons()

    def _on_settings_closed(self) -> None:
        self._settings = None

    def _check_candidate(self, config: AppConfig) -> bool:
        """設定画面で入力中の接続先に、今の接続とは別につないで確認する。"""
        devices = [*config.devices.values(), *config.lamps.values()]

        def task() -> CheckResult:
            client = self._client_factory(config)
            try:
                return check_connection(client, devices)
            finally:
                client.close()

        accepted = self._worker.submit(task)
        self._update_buttons()
        return accepted

    def _save_settings(self, config: AppConfig) -> str | None:
        """設定を反映してファイルに保存する。失敗したらエラーメッセージを返す。"""
        if not self._worker.submit(lambda: self._apply(config)):
            return "処理中のため保存できませんでした。しばらくしてからもう一度押してください。"
        self._config = config
        self._update_target()
        for command, button in self._command_buttons.items():
            button.config(text=_button_text(command, config.devices[command]))
        for lamp, indicator in self._lamps.items():
            indicator.set_device(config.lamps[lamp])
            indicator.set_state(None)
        try:
            save_config(self._config_path, self._config)
        except OSError as e:
            logger.exception("設定の保存に失敗しました")
            return f"設定は反映しましたが、{self._config_path} に保存できませんでした: {e}"
        logger.info("設定を保存しました: %s", self._config_path)
        self._append_log(f"設定を {self._config_path} に保存しました")
        return None

    def _apply(self, config: AppConfig) -> SettingsApplied:
        # ワーカースレッドで実行する（通信中のクライアントを別スレッドから閉じないため）
        self._sender.reconfigure(self._client_factory(config), config.devices)
        logger.info("設定を反映しました: %s", _describe(config))
        return SettingsApplied(config)

    def _update_target(self) -> None:
        conn = self._config.connection
        self._root.title("FX5S Commander" + ("（モック）" if conn.mock else ""))
        self._target.config(text=f"接続先: {conn.label}")

    def _request_lamp_read(self) -> None:
        lamps = dict(self._config.lamps)

        def task() -> LampReading:
            # ワーカースレッドで実行する。例外で定期読み出しが止まらないよう、すべて結果にする
            try:
                return read_lamps(self._sender.client, lamps)
            except Exception as e:
                logger.exception("ランプの読み出し中に予期しないエラーが発生しました")
                return LampReading(None, f"内部エラー: {e}")

        if not self._worker.submit_background(task):
            self._root.after(int(self._config.monitor.interval_sec * 1000), self._request_lamp_read)

    def _show_lamps(self, reading: LampReading) -> None:
        readable = reading.states is not None
        for lamp, indicator in self._lamps.items():
            indicator.set_state(reading.states[lamp] if reading.states is not None else None)
        if readable:
            self._lamp_status.config(text=f"ランプ: {datetime.now():%H:%M:%S} 更新", fg="#555555")
        else:
            self._lamp_status.config(
                text=f"ランプ: 読み出せません（{reading.error}）", fg="#c62828"
            )
        # 毎回ログに出すと埋もれるので、読める・読めないが切り替わったときだけ残す
        if readable != self._lamps_readable:
            if readable:
                self._append_log("ランプの読み出しを開始しました")
            else:
                logger.warning("ランプを読み出せません: %s", reading.error)
                self._append_log(f"ランプを読み出せません: {reading.error}")
            self._lamps_readable = readable
        delay_ms = int(self._config.monitor.interval_sec * 1000) if readable else _LAMP_RETRY_MS
        self._root.after(delay_ms, self._request_lamp_read)

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
        elif isinstance(result, LampReading):
            self._show_lamps(result)
        elif isinstance(result, SettingsApplied):
            message = f"設定を反映しました（{_describe(result.config)}）"
            self._set_status(message, "black")
            self._append_log(message)
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


def _button_text(command: Command, device: Device) -> str:
    return f"{command.label}\n({device})"


def _describe(config: AppConfig) -> str:
    relays = [f"{c.label}={d}" for c, d in config.devices.items()]
    relays += [f"{lamp.label}={d}" for lamp, d in config.lamps.items()]
    return f"接続先: {config.connection.label} / {', '.join(relays)}"
