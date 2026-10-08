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

```powershell
fx5s-commander
```

画面右上の **[設定]** から、接続先とリレーの割り当てを変更できます。

**[接続設定] タブ**
- **モック PLC を使う**：チェックを入れると実機に接続せず、ラダーの動きを真似るモック PLC で動かします。実機がなくても画面の動作を確認できます。
- **IP アドレス / ポート番号**：実機の接続先です（モックのときは入力できません）。
- **[接続確認]**：保存する前に、その接続先と通信できるか確かめられます。[リレー] タブで入力中のリレーを読み取ります（書き込みはしません）。

**[リレー] タブ**
- **指令（書き込み）**：ON / OFF / 停止要求のボタンが書き込む内部リレー（M デバイス）を指定します。
- **ランプ（読み出し）**：稼働中 / 停止中のランプが読み出す内部リレーを指定します。
- M 以外や、同じリレーを複数の用途に割り当てることはできません。

**[保存]** を押すと設定がその場で反映され、`config.toml` に保存されます。

`config.toml` がない場合は既定値（192.168.1.20:5000）で起動します。PLC 種別やタイムアウトなど、画面にない項目は `config.toml` を直接編集してください（書式は `config.example.toml`）。画面から保存すると、`config.toml` 内のコメントは消えます。

ログは `logs/fx5s-commander.log` に出力されます。

## ボタン・ランプと PLC デバイス（既定値）

| 画面 | デバイス | 方向 |
|---|---|---|
| ON ボタン | M100 | 書き込み |
| OFF ボタン | M101 | 書き込み |
| 停止要求ボタン | M102 | 書き込み |
| 稼働中ランプ | M300 | 読み出し |
| 停止中ランプ | M301 | 読み出し |

ランプは 0.5 秒ごとに PLC から読み出し、M が ON なら点灯します。読み出せないときは灰色になります。

ボタンを押すと、アプリはデバイスを ON にし、ラダーが OFF に戻すのを待ちます。OFF に戻れば「PLC が受け付けた」と表示します。これは設備が動いたことを意味しません。
デバイスの割り当ては [設定] の [リレー] タブか `config.toml` で変更できます（M デバイスのみ）。

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
| `src/fx5s_commander/settings_window.py` | 設定画面（接続設定・リレー） |
| `src/fx5s_commander/worker.py` | 通信用のバックグラウンドスレッド |
| `src/fx5s_commander/commands.py` | 指令の送信と受付確認 |
| `src/fx5s_commander/monitor.py` | ランプ用の状態読み出し |
| `src/fx5s_commander/plc/` | PLC 通信（実機用、モック、書き込みガード） |
| `src/fx5s_commander/config.py` | 設定ファイルの読み込み |
| `src/fx5s_commander/probe.py` | 通信確認用のコマンドラインツール |

## ライセンス

MIT
