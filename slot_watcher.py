"""
在バンクーバー日本国総領事館の予約カレンダーを監視し、
指定日に空きが出たら ntfy でスマホに通知するスクリプト。

カテゴリ: 各種証明書、パスポート、マイナンバーカードの申請・受領（event=3, plan=8）
対象日:   環境変数 TARGET_DATES

使い方:
  pip install playwright requests
  playwright install chromium
  python slot_watcher.py            # INTERVAL_MIN 分ごとにチェックし続ける
  python slot_watcher.py --once     # 1回だけチェック（cron / Cloud Scheduler 用）

通知: スマホに ntfy アプリを入れ、NTFY_TOPIC と同じトピックを購読する。
予約はしない。空きを見つけて知らせるだけ。
"""

import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from playwright.sync_api import sync_playwright

CALENDAR_URL = "https://cgjvancouver.rsvsys.jp/reservations/calendar"
EVENT_ID = "3"  # 各種証明書、パスポート、マイナンバーカードの申請・受領
# 対象日は Secret / 環境変数 TARGET_DATES で渡す（例: "2026/01/01,2026/01/02"）
TARGET_DATES = sorted(d.strip() for d in os.environ["TARGET_DATES"].split(",") if d.strip())
WEEK_START = TARGET_DATES[0]  # 週表示の起点（この日から7日分が表示される）

# トピック名は誰でも購読できるので、コードには書かない
NTFY_TOPIC = os.environ["NTFY_TOPIC"]  # GitHub Secret / 環境変数で渡す（公開しない）
INTERVAL_MIN = int(os.environ.get("INTERVAL_MIN", "10"))  # サイトに負荷をかけないよう10分以上推奨
TZ = ZoneInfo("America/Vancouver")
_y, _m, _d = map(int, TARGET_DATES[-1].split("/"))
STOP_AFTER = datetime(_y, _m, _d, 16, 0, tzinfo=TZ)  # 最終対象日の16:00（バンクーバー時間）を過ぎたら終了

# 同じ枠を何度も通知しない
_already_notified: set[str] = set()


def fetch_open_slots() -> list[dict]:
    """対象日の空き枠を返す: [{"date": "2026/01/01", "time": "09:00", "stock": 1, "url": ...}]"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(CALENDAR_URL, wait_until="networkidle")

        # カテゴリを選び、週の起点を対象日に合わせる（ページ自身の jQuery を利用）
        page.evaluate(f"$('#event-{EVENT_ID}').prop('checked', true).trigger('change')")
        page.wait_for_timeout(3000)
        page.evaluate(f"$('#sel_date').val('{WEEK_START}').trigger('change')")
        page.wait_for_timeout(3000)
        page.wait_for_selector("table.js_calendar_container thead th")

        slots = page.evaluate(
            """(targets) => {
                const links = [...document.querySelectorAll('a.js_move_reserve[data-date]')];
                return links
                  .filter(a => targets.includes(a.dataset.date) && Number(a.dataset.stock || 0) > 0)
                  .map(a => ({
                      date: a.dataset.date,
                      time: a.dataset.time_from,
                      stock: Number(a.dataset.stock),
                      url: new URL(a.getAttribute('href'), location.origin).href,
                  }));
            }""",
            TARGET_DATES,
        )

        # 対象週が正しく読めたかの確認（全部空振りの誤検知防止）
        headers = page.evaluate(
            "[...document.querySelectorAll('table.js_calendar_container thead th')]"
            ".slice(1).map(th => th.childNodes[0].textContent.trim())"
        )
        browser.close()

    if not any(d[5:] in headers for d in TARGET_DATES):
        raise RuntimeError("対象週を表示できませんでした")  # 公開ログに日付を出さない
    return slots


def notify(title: str, message: str, click_url: str | None = None, buttons: list[tuple[str, str]] | None = None) -> None:
    """ntfy に JSON で送る。buttons は (ラベル, URL) のリスト（最大3つ）。通知をタップすると click_url が開く。"""
    payload = {"topic": NTFY_TOPIC, "title": title, "message": message, "priority": 5, "tags": ["calendar"]}
    if click_url:
        payload["click"] = click_url
    if buttons:
        payload["actions"] = [{"action": "view", "label": label, "url": url} for label, url in buttons[:3]]
    requests.post("https://ntfy.sh/", json=payload, timeout=15).raise_for_status()


def check_once() -> None:
    now = datetime.now(TZ).strftime("%m/%d %H:%M")
    try:
        slots = fetch_open_slots()
    except Exception as e:  # サイト変更・通信エラーは表示だけして次回に再試行
        print(f"[{now}] チェック失敗: {e}")
        return

    new = [s for s in slots if f"{s['date']} {s['time']}" not in _already_notified]
    if not new:
        print(f"[{now}] 空きなし")
        return

    lines = [f"{s['date'][5:]} {s['time']}（残{s['stock']}）" for s in new]
    print(f"[{now}] 空きあり: {len(new)}枠")  # 公開ログには日付を出さない
    # ボタン: 空き枠の予約ページ（最大2つ）＋カレンダー。通知本体のタップは最初の空き枠へ
    buttons = [(f"{s['date'][5:]} {s['time']} を予約", s["url"]) for s in new[:2]]
    buttons.append(("カレンダーを開く", CALENDAR_URL))
    notify(
        "総領事館の予約に空き",
        "警察証明の申請枠が空きました\n" + "\n".join(lines),
        click_url=new[0]["url"],
        buttons=buttons,
    )
    _already_notified.update(f"{s['date']} {s['time']}" for s in new)


def send_test() -> None:
    """表示確認用のテスト通知（実際の空きではない）。リンクはカレンダーを開く。"""
    notify(
        "【テスト】総領事館の予約に空き",
        "表示確認用のテストです（実際の空きではありません）",
        click_url=CALENDAR_URL,
        buttons=[("（例）枠を予約", CALENDAR_URL), ("カレンダーを開く", CALENDAR_URL)],
    )
    print("テスト通知を送信しました")


def main() -> None:
    if "--test" in sys.argv:
        send_test()
        return
    if "--once" in sys.argv:
        if datetime.now(TZ) >= STOP_AFTER:
            print("対象日を過ぎたので何もしません")
            return
        check_once()
        return

    notify("監視スタート", f"{', '.join(d[5:] for d in TARGET_DATES)} の空きを {INTERVAL_MIN} 分ごとに確認します")
    while datetime.now(TZ) < STOP_AFTER:
        check_once()
        time.sleep(INTERVAL_MIN * 60)
    print("対象日を過ぎたので終了します")


if __name__ == "__main__":
    main()
