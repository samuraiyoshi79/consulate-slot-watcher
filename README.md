# slot-watcher

予約カレンダーの空き枠を定期的に確認し、空きが出たら ntfy で通知する小さなスクリプト。予約は行わない。

## 使い方
- 通知先のトピック名は `NTFY_TOPIC`、対象日は `TARGET_DATES`（例: `2026/01/01,2026/01/02`）で渡す（GitHub Actions では Secret）
- GitHub Actions で定期実行する（`.github/workflows/watch.yml`）
- ローカルで動かす場合:

```
pip install playwright requests
playwright install chromium
NTFY_TOPIC=<topic> TARGET_DATES=<dates> python slot_watcher.py
```
