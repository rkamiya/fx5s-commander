# CLAUDE.md

三菱電機 FX5S PLC を LAN 経由（SLMP 3E フレーム、バイナリ）で操作する Windows 用デスクトップアプリ。Python + tkinter。

使い方は [README.md](README.md)、設計と未決定事項は [docs/design.md](docs/design.md)、ラダーの回路例は [docs/ladder.md](docs/ladder.md) を参照。作業前に design.md を読むこと。

## コマンド

開発環境は Windows（PowerShell）、Python 3.12。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

pytest
ruff check .
ruff format .
```

- 変更後は `pytest` と `ruff check .` が通ることを確認する（CI はない）。
- 実機がなくても、`config.toml` の `[connection] mock = true`（画面の [設定] → モック PLC）で動かせる。
- `config.toml` と `logs/` は git 管理外。設定の書式は `config.example.toml`。

## 構成

`gui.py` → `worker.py`（通信スレッド）→ `commands.py` / `monitor.py` / `text.py` → `plc/client.py`（`GuardedPlcClient`）→ `plc/slmp.py`（実機、pymcprotocol）または `plc/mock.py`。

- GUI から PLC を直接触らない。通信は必ず `TaskWorker` のスレッドで行い、結果はキュー経由で `after()` で反映する。
- 実機とモックは `PlcClient` インターフェースで差し替える。モックは docs/ladder.md のラダーと同じ動きをさせる。

## 安全上の決まり（変えるときは必ずユーザーに確認する）

- PLC への書き込みは `GuardedPlcClient` の許可リストに限る。ビットは設定済みの指令用 M 3 点、ワードは文字列用の D 16 点のみ。X・Y や他のデバイスに書き込む経路を作らない。
- 指令とランプに指定できるのは M のみ、文字列の書き込み先は D のみ。
- 指令は方式 B（PC が M を ON → ラダーが RST → PC が OFF を確認）。ACCEPTED は「PLC が受け付けた」であって設備が動いたことは意味しない。表示文言でもこれを崩さない。
- 停止要求は非常停止ではない。停止要求は ON / OFF より優先して送る。
- FX5S 実機で確認済みなのは M と D の読み出しのみ（`plc_type = "L"`）。書き込みは未確認なので、実機検証済みと書かない。

## 書き方の慣習

- ドキュメント、コードのコメント・docstring、画面の文言、PR のタイトルと本文は日本語。
- コミットメッセージは英語の命令形（例: `Add text input that writes ASCII to D100-D115`）。レビュー対応は `Address review: ...`。
- ブランチ名は `feat/...`、`docs/...`、`chore/...`。
- ruff の設定（行長 100、py311）に合わせる。

## PR レビューへの対応

レビューコメントを確認・対応するよう頼まれたら、コードを直すだけでなく、push 後に各レビュースレッドへ「何をどのコミットで直したか」を日本語で返信する。

```bash
gh api -X POST repos/<owner>/<repo>/pulls/<n>/comments/<id>/replies -f body='...'
```

- スレッドの resolve は頼まれていなければ、する前にユーザーに確認する（リポジトリのルールで、マージ前に全スレッドの resolve が必要）。
