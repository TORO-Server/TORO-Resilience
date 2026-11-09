# TORO-Resilience

災害対応システム。無料のデータ経路のみで動作し、追加の依存を持たず Python 3 標準ライブラリだけで実行できる。

## 構成

| コンポーネント | 役割 |
|---|---|
| EEW レシーバ | Wolfx（予報・警報）と P2P地震情報（警報・発表検出）の WebSocket に常時接続し、緊急地震速報を受信する |
| Tier エンジン | 予測震度と経路間の照合に基づき、通知・保存開始・ログイン停止・停止推奨を判断する |
| heartbeat agent | 保護対象ホスト上で heartbeat ファイルを60秒ごとに更新する |
| watcher | ホスト外部で heartbeat の途絶（180秒）を検知して通知する |

## 実行

```sh
python3 -m resilience --config config.json receiver
python3 -m resilience --config config.json agent
python3 -m resilience --config config.json watcher
```

設定は JSON ファイルで与える（`config.example.json` 参照）。秘密情報はファイルに書かず、環境変数名で参照する。ホストの所在地（緯度経度・対象地域名）は設定側で与えるものであり、本リポジトリには含まれない。

検証用に、記録済みの経路ペイロードをエンジンへ流すリプレイがある。

```sh
python3 -m resilience --config config.json replay --source p2p payload.json
```

## テスト

```sh
python3 -m unittest discover -s tests
```

設計判断と無料経路の制約は `docs/DESIGN.md`、運用手順は `docs/RUNBOOK.md` を参照。
