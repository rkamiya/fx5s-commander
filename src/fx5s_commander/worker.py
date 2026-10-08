"""PLC 通信をバックグラウンドの 1 スレッドで順番に実行する。

GUI スレッドで通信すると画面が固まるため、通信はすべてこのスレッドに任せる。
pymcprotocol はスレッドセーフではないので、PLC へのアクセスはこのスレッドだけから行う。

受付ルール:
- 通常のタスク（ON / OFF / 接続確認）は、処理中や待ちのタスクがあれば受け付けない。
  押した操作が後からまとめて実行されるのを防ぐため、キューに溜めない。
- 優先タスク（停止要求）は処理中でも受け付け、待ちの通常タスクより先に実行する。
  ただし実行中のタスクを中断はしないので、最大でハンドシェイク 1 回分待つ。
- バックグラウンドタスク（ランプの読み出し）は、ほかのタスクがすべて終わってから実行する。
  処理中かどうか（busy）の判定には含めないので、読み出し中でも ON / OFF を受け付ける。
  待ちは 1 件までで、既に待ちがあれば受け付けない。
"""

from __future__ import annotations

import itertools
import logging
import queue
import threading
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

_PRIORITY_HIGH = 0
_PRIORITY_NORMAL = 1
_PRIORITY_BACKGROUND = 2
_PRIORITY_SHUTDOWN = 3  # 受付済みのタスクをすべて終えてから止める


class TaskWorker:
    def __init__(
        self,
        on_done: Callable[[Any], None],
        on_exit: Callable[[], None] | None = None,
    ) -> None:
        """on_done はタスクの戻り値（例外が出た場合はその例外）を受け取る。

        on_done と on_exit はワーカースレッドで呼ばれる。
        """
        self._on_done = on_done
        self._on_exit = on_exit
        self._queue: queue.PriorityQueue[tuple[int, int, Callable[[], Any] | None]] = (
            queue.PriorityQueue()
        )
        self._seq = itertools.count()
        self._lock = threading.Lock()
        self._pending = 0
        self._high_queued = False
        self._background_pending = False
        self._closing = False
        self._thread = threading.Thread(target=self._run, name="plc-worker", daemon=True)

    def start(self) -> None:
        self._thread.start()

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._pending > 0

    def submit(self, task: Callable[[], Any], *, priority: bool = False) -> bool:
        """タスクを受け付けたら True、受付ルールにより断ったら False。"""
        with self._lock:
            if self._closing:
                return False
            if priority:
                if self._high_queued:
                    return False
                self._high_queued = True
                level = _PRIORITY_HIGH
            else:
                if self._pending > 0:
                    return False
                level = _PRIORITY_NORMAL
            self._pending += 1
            # 受付と投入をロック内で行い、並行する shutdown() に取りこぼされないようにする
            self._queue.put((level, next(self._seq), task))
        return True

    def submit_background(self, task: Callable[[], Any]) -> bool:
        """バックグラウンドタスクを受け付けたら True。待ちや実行中のものがあれば False。"""
        with self._lock:
            if self._closing or self._background_pending:
                return False
            self._background_pending = True
            self._queue.put((_PRIORITY_BACKGROUND, next(self._seq), task))
        return True

    def shutdown(self, timeout: float | None = None) -> None:
        with self._lock:
            if self._closing:
                return
            self._closing = True
            self._queue.put((_PRIORITY_SHUTDOWN, next(self._seq), None))
        self._thread.join(timeout)

    def _run(self) -> None:
        while True:
            level, _, task = self._queue.get()
            if task is None:
                break
            if level == _PRIORITY_HIGH:
                with self._lock:
                    self._high_queued = False
            try:
                result: Any = task()
            except Exception as e:
                logger.exception("タスクの実行中に予期しないエラーが発生しました")
                result = e
            with self._lock:
                if level == _PRIORITY_BACKGROUND:
                    self._background_pending = False
                else:
                    self._pending -= 1
            self._on_done(result)
        if self._on_exit is not None:
            try:
                self._on_exit()
            except Exception:
                logger.exception("終了処理でエラーが発生しました")
