"""tkinter による操作画面。

画面は表示と入力だけを担当し、PLC との通信は TaskWorker 経由でバックグラウンドで行う。
ワーカーからの結果はキューで受け取り、after() で定期的に取り出して画面に反映する。
"""

from __future__ import annotations

import logging
import queue
import tkinter as tk
from datetime import datetime
from tkinter import scrolledtext
from typing import Any

from fx5s_commander.commands import CheckResult, Command, CommandResult, CommandSender, Outcome
from fx5s_commander.config import AppConfig
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


class App:
    def __init__(
        self,
        root: tk.Tk,
        *,
        config: AppConfig,
        sender: CommandSender,
        worker: TaskWorker,
        results: queue.Queue[Any],
        mock: bool,
    ) -> None:
        self._root = root
        self._sender = sender
        self._worker = worker
        self._results = results

        conn = config.connection
        title = "FX5S Commander" + ("（モック）" if mock else "")
        root.title(title)
        root.minsize(420, 420)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        frame = tk.Frame(root, padx=16, pady=12)
        frame.pack(fill=tk.BOTH, expand=True)

        header = tk.Frame(frame)
        header.pack(fill=tk.X)
        target = "モック PLC" if mock else f"{conn.host}:{conn.port}"
        tk.Label(header, text=f"接続先: {target}").pack(side=tk.LEFT)
        self._check_button = tk.Button(header, text="接続確認", command=self._on_check)
        self._check_button.pack(side=tk.RIGHT)

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

    def _on_check(self) -> None:
        if self._worker.submit(self._sender.check_connection):
            self._set_status("接続を確認中…", "black")
        self._update_buttons()

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
            self._set_status(result.message, "#2e7d32" if result.ok else "#c62828")
            self._append_log(result.message)
        else:
            self._set_status(f"内部エラー: {result}", "#c62828")
            self._append_log(f"内部エラー: {result!r}")

    def _update_buttons(self) -> None:
        state = tk.DISABLED if self._worker.busy else tk.NORMAL
        self._command_buttons[Command.ON].config(state=state)
        self._command_buttons[Command.OFF].config(state=state)
        self._check_button.config(state=state)
        # 停止要求は処理中でも押せるようにしておく

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
