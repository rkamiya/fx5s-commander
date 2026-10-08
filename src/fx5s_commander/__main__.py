"""アプリの起動処理。設定を読み込み、通信層・指令処理・画面を組み立てる。"""

from __future__ import annotations

import argparse
import logging
import queue
import sys
import tkinter as tk
from collections.abc import Iterable
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import messagebox
from typing import Any

from fx5s_commander.commands import CommandSender
from fx5s_commander.config import (
    AppConfig,
    ConfigError,
    ConnectionConfig,
    default_config,
    load_config,
)
from fx5s_commander.devices import Device
from fx5s_commander.gui import App
from fx5s_commander.plc.client import GuardedPlcClient, PlcClient
from fx5s_commander.plc.mock import MockPlcClient
from fx5s_commander.plc.slmp import SlmpPlcClient
from fx5s_commander.worker import TaskWorker

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("config.toml")
DEFAULT_LOG_PATH = Path("logs") / "fx5s-commander.log"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fx5s-commander", description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        help=f"設定ファイル（省略時は {DEFAULT_CONFIG_PATH} があれば使い、なければ既定値）",
    )
    parser.add_argument("--mock", action="store_true", help="実機の代わりにモック PLC を使う")
    parser.add_argument(
        "--mock-no-ack",
        action="store_true",
        help="モック PLC が指令を受け付けない（ラダー未対応の PLC を想定）",
    )
    parser.add_argument("--log-file", type=Path, default=DEFAULT_LOG_PATH, help="ログの出力先")
    args = parser.parse_args(argv)

    setup_logging(args.log_file)

    try:
        config = _load(args.config)
    except ConfigError as e:
        logger.error("%s", e)
        _show_startup_error(str(e))
        return 1

    mock = args.mock or args.mock_no_ack

    def client_factory(connection: ConnectionConfig) -> PlcClient:
        return build_client(
            connection, config.devices.values(), mock=mock, mock_ack=not args.mock_no_ack
        )

    sender = CommandSender(
        client_factory(config.connection),
        config.devices,
        ack_timeout_sec=config.handshake.ack_timeout_sec,
        poll_interval_sec=config.handshake.poll_interval_sec,
    )
    results: queue.Queue[Any] = queue.Queue()
    worker = TaskWorker(on_done=results.put, on_exit=sender.close)
    worker.start()

    logger.info("起動しました（%s）", "モック" if mock else "実機")
    root = tk.Tk()
    App(
        root,
        config=config,
        config_path=args.config or DEFAULT_CONFIG_PATH,
        sender=sender,
        client_factory=client_factory,
        worker=worker,
        results=results,
        mock=mock,
    )
    root.mainloop()
    logger.info("終了しました")
    return 0


def build_client(
    connection: ConnectionConfig,
    allowed_writes: Iterable[Device],
    *,
    mock: bool,
    mock_ack: bool = True,
) -> PlcClient:
    inner: PlcClient
    if mock:
        inner = MockPlcClient(ack_delay_sec=0.2 if mock_ack else None)
    else:
        inner = SlmpPlcClient(
            connection.host,
            connection.port,
            plc_type=connection.plc_type,
            timeout_sec=connection.timeout_sec,
        )
    return GuardedPlcClient(inner, allowed_writes)


def setup_logging(log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s"
    )
    file_handler = RotatingFileHandler(
        log_file, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    handlers: list[logging.Handler] = [file_handler]
    if sys.stderr is not None:  # EXE（コンソールなし）では stderr がない
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        handlers.append(stream_handler)
    logging.basicConfig(level=logging.INFO, handlers=handlers, force=True)


def _load(path: Path | None) -> AppConfig:
    if path is not None:
        return load_config(path)
    if DEFAULT_CONFIG_PATH.exists():
        return load_config(DEFAULT_CONFIG_PATH)
    logger.info("%s がないため既定の設定で起動します", DEFAULT_CONFIG_PATH)
    return default_config()


def _show_startup_error(message: str) -> None:
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror("FX5S Commander", message)
    root.destroy()


if __name__ == "__main__":
    sys.exit(main())
