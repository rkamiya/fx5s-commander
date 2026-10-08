"""実機との通信を確認するためのコマンドラインツール（初期検証手順 3〜5 用）。

例:
    fx5s-probe --host 192.168.1.20 --port 5000 connect
    fx5s-probe --host 192.168.1.20 read M100
    fx5s-probe --host 192.168.1.20 write M100 1

書き込めるのは M デバイスのみ。ハンドシェイクは行わないので、ON にした M は自分で OFF に戻すこと。
"""

from __future__ import annotations

import argparse
import sys

from fx5s_commander.config import PLC_TYPES
from fx5s_commander.devices import parse_device
from fx5s_commander.plc.client import PlcError
from fx5s_commander.plc.slmp import SlmpPlcClient


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fx5s-probe",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--plc-type", choices=PLC_TYPES, default="L")
    parser.add_argument("--timeout", type=float, default=2.0)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("connect", help="接続できるかだけ確認する")
    read = sub.add_parser("read", help="M デバイスを読む")
    read.add_argument("device")
    write = sub.add_parser("write", help="M デバイスに書く")
    write.add_argument("device")
    write.add_argument("value", type=int, choices=(0, 1))
    args = parser.parse_args(argv)

    device = None
    if args.action in ("read", "write"):
        try:
            device = parse_device(args.device)
        except ValueError as e:
            parser.error(str(e))

    client = SlmpPlcClient(args.host, args.port, plc_type=args.plc_type, timeout_sec=args.timeout)
    try:
        client.connect()
        print(f"接続 OK: {args.host}:{args.port}")
        if args.action == "read":
            print(f"{device} = {int(client.read_bit(device))}")
        elif args.action == "write":
            client.write_bit(device, bool(args.value))
            print(f"{device} <- {args.value}")
            print(f"{device} = {int(client.read_bit(device))}（読み直し）")
    except PlcError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
