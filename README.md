# FX5S Commander

Windows PC から LAN（Ethernet）経由で、三菱電機の PLC「FX5S」を操作するデスクトップアプリです。
画面の ON / OFF / 停止要求ボタンを押すと、SLMP（3E フレーム）で PLC の内部リレー（M デバイス）に指令を書き込みます。

> [!WARNING]
> 停止要求は非常停止ではありません。非常停止は、このアプリとは独立した安全回路で実装してください。
> 安全性を確認できるまでは、PLC の出力に実機をつながない状態で検証してください。

現在は叩き台の段階です。設計と未決定事項は [docs/design.md](docs/design.md)、ラダー側の対応は [docs/ladder.md](docs/ladder.md) にまとめています。

## 必要なもの

- Windows 11
- Python 3.11 以上（3.12 で確認済み）
- 三菱電機 FX5S（実機で動かす場合。モックなら不要）

## セットアップ

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## 起動

実機なし（モック PLC）で起動する:

```powershell
fx5s-commander --mock
```

`--mock-no-ack` を付けると、ラダーが指令を受け付けない PLC を真似ます。

実機につなぐ場合は、オプションなしで起動します。

```powershell
fx5s-commander
```

接続先は、画面右上の **[設定]** から変更できます。IP アドレスとポート番号を入力して [接続確認] を押すと、保存する前にその接続先と通信できるか確かめられます。[保存] を押すと接続先が切り替わり、`config.toml` に保存されます。
`config.toml` がない場合は既定値（192.168.1.20:5000）で起動します。PLC 種別やタイムアウトなど、画面にない項目は `config.toml` を直接編集してください（書式は `config.example.toml`）。画面から保存すると、`config.toml` 内のコメントは消えます。

ログは `logs/fx5s-commander.log` に出力されます。

## ボタンと PLC デバイス（既定値）

| ボタン | デバイス |
|---|---|
| ON | M100 |
| OFF | M101 |
| 停止要求 | M102 |

ボタンを押すと、アプリはデバイスを ON にし、ラダーが OFF に戻すのを待ちます。OFF に戻れば「PLC が受け付けた」と表示します。これは設備が動いたことを意味しません。
デバイスの割り当ては `config.toml` で変更できます（M デバイスのみ）。

## 実機との通信確認

アプリを使う前に、`fx5s-probe` で PLC と通信できるか確認できます。

```powershell
fx5s-probe --host 192.168.1.20 connect
fx5s-probe --host 192.168.1.20 read M100
fx5s-probe --host 192.168.1.20 write M100 1
fx5s-probe --host 192.168.1.20 write M100 0
```

GX Works3 のデバイスモニタで M100 が変化することも確認してください。続きの手順は [docs/ladder.md](docs/ladder.md) にあります。

## 開発

```powershell
pytest
ruff check .
ruff format .
```

| パス | 内容 |
|---|---|
| `src/fx5s_commander/gui.py` | メイン画面（tkinter） |
| `src/fx5s_commander/settings_window.py` | 接続設定の画面 |
| `src/fx5s_commander/worker.py` | 通信用のバックグラウンドスレッド |
| `src/fx5s_commander/commands.py` | 指令の送信と受付確認 |
| `src/fx5s_commander/plc/` | PLC 通信（実機用、モック、書き込みガード） |
| `src/fx5s_commander/config.py` | 設定ファイルの読み込み |
| `src/fx5s_commander/probe.py` | 通信確認用のコマンドラインツール |

## ライセンス

MIT
