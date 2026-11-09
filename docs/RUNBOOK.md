# 運用手順

## 導入

1. Python 3.10 以上を用意する。追加パッケージは不要である。
2. `config.example.json` を基に設定ファイルを作成する。ホスト所在地（`host_lat` / `host_lon` / `host_area_names`）は保護対象ホストの実際の値に置き換える。
3. 秘密情報を環境変数に設定する。
   - `RESILIENCE_DISCORD_WEBHOOK`: Discord Webhook URL
   - `RESILIENCE_RCON_PASSWORD`: RCON を有効化する場合のみ
4. systemd ユニット（`deploy/`）を配置し、有効化する。receiver と agent は保護対象ホスト、watcher はホスト外部に置く。

## 日常確認

- インシデント記録（`incident_log_path` の JSONL）に `route_disconnected` が連続していないか。
- watcher の `heartbeat_lost` が発生していないか。

## 発災時の挙動と手動操作

- 停止推奨が出た場合、インシデント記録と同じ場所に再起動抑制フラグ（`<incident_log_path>.suppress-restart`）が作られる。サーバーを再起動する前に、フラグの有無を確認すること。フラグの削除は手動で行う。
- ログイン停止コマンドを設定していない構成では、ログイン停止は状態追跡と通知のみであり、実際のゲート操作は手動である。

## 検証

- 単体テスト: `python3 -m unittest discover -s tests`
- リプレイ: 記録済みペイロードを `python3 -m resilience replay` に流し、想定した ACTION が出力されるか確認する。
- 実接続確認: receiver を起動し、インシデント記録に両経路の `route_connected` が記録され、`route_disconnected` が続かないことを確認する。
