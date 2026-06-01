import json
import os
import time
from datetime import date, datetime
from pathlib import Path

import requests
from steam.client import SteamClient

# ===== 設定 =====
WEBHOOK      = os.environ.get('DISCORD_WEBHOOK', '').strip()
MIN_REVIEWS  = 20
DATA_FILE    = Path(__file__).parent / 'languages.json'
META_FILE    = Path(__file__).parent / 'meta.json'

if not WEBHOOK:
    raise SystemExit('[ERROR] DISCORD_WEBHOOK 未設定')

if not DATA_FILE.exists():
    raise SystemExit('[ERROR] languages.json 不存在，請先執行 seed.py 建立基準')

# ===== 讀取狀態檔 =====
meta   = json.loads(META_FILE.read_text('utf-8')) if META_FILE.exists() else {}
stored = json.loads(DATA_FILE.read_text('utf-8'))

last_change_number = int(meta.get('last_change_number', 0))

# ===== 連線 Steam（僅用於取得變動清單）=====
print('[INFO] 連線 Steam CM...', flush=True)
client = SteamClient()
client.anonymous_login()
print('[INFO] 連線成功', flush=True)

# ===== 取得有變動的 App 清單（PICS）=====
print(f'[INFO] 查詢 PICS 變動（change number: {last_change_number}）...', flush=True)
changes = client.get_changes_since(last_change_number, app_changes=True, package_changes=False)
client.disconnect()

current_change_number = changes.current_change_number
changed_appids = [c.appid for c in changes.app_changes]

print(f'[INFO] change number：{last_change_number} → {current_change_number}')
print(f'[INFO] 有變動 App：{len(changed_appids)} 個')

meta['last_change_number'] = current_change_number
meta['last_run'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
META_FILE.write_text(json.dumps(meta, indent=2), 'utf-8')

if not changed_appids:
    print('[INFO] 本次無任何 App 更新')
    raise SystemExit(0)

# 已知有中文的跳過
to_check = [appid for appid in changed_appids
            if not stored.get(str(appid), {}).get('has_chinese')]

print(f'[INFO] 實際需查詢：{len(to_check)} 個（跳過已知有中文）')

# ===== 逐一用 Store API 查詢語系 =====
def get_store_languages(appid: int) -> tuple[str | None, list[str]]:
    """回傳 (app_type, languages_list)，失敗回傳 (None, [])"""
    try:
        r = requests.get(
            f'https://store.steampowered.com/api/appdetails?appids={appid}',
            timeout=15
        )
        data = r.json()
        if not data or not data.get(str(appid), {}).get('success'):
            return None, []
        app_data  = data[str(appid)]['data']
        app_type  = app_data.get('type', '').lower()
        raw_langs = app_data.get('supported_languages', '')
        # supported_languages 是 HTML 字串，用逗號分隔，簡單解析
        import re
        langs = [l.strip() for l in re.sub(r'<[^>]+>', '', raw_langs).split(',')]
        return app_type, langs
    except Exception as e:
        print(f'  [WARN] Store API 失敗：{e}')
        return None, []

CHINESE_STORE_KEYS = {'Simplified Chinese', 'Traditional Chinese'}

new_chinese_list = []
notified = set()
today    = date.today()

for i, appid in enumerate(to_check, 1):
    appid_str = str(appid)
    print(f'[{i}/{len(to_check)}] 查詢 App {appid}...', flush=True)

    app_type, langs = get_store_languages(appid)

    if app_type is None:
        usleep = 0.5
        time.sleep(usleep)
        continue

    if app_type != 'game':
        print(f'  → 非遊戲（{app_type}），跳過')
        time.sleep(0.3)
        continue

    has_chinese = bool(set(langs) & CHINESE_STORE_KEYS)
    had_chinese = stored.get(appid_str, {}).get('has_chinese', False)
    name        = stored.get(appid_str, {}).get('name', f'App {appid}')

    if has_chinese and not had_chinese and appid_str not in notified:
        print(f'  → 🎉 [{name}] 新增中文支援！')

        total_reviews = positive = negative = 0
        try:
            r = requests.get(
                f'https://store.steampowered.com/appreviews/{appid}?json=1&language=all&purchase_type=all',
                timeout=10
            )
            summary       = r.json().get('query_summary', {})
            positive      = summary.get('total_positive', 0)
            negative      = summary.get('total_negative', 0)
            total_reviews = summary.get('total_reviews', positive + negative)
        except Exception:
            pass

        if total_reviews < MIN_REVIEWS:
            print(f'  → 評論數 {total_reviews} < {MIN_REVIEWS}，跳過')
        else:
            new_chinese_list.append({
                'appid':    appid_str,
                'name':     name,
                'langs':    ', '.join(l for l in langs if l),
                'positive': positive,
                'negative': negative,
            })
            notified.add(appid_str)
    else:
        print(f'  → 中文：{"✅ 有" if has_chinese else "❌ 無"}')

    stored[appid_str] = {
        'name':         name,
        'has_chinese':  has_chinese,
        'last_checked': str(today),
    }

    time.sleep(0.5)

DATA_FILE.write_text(json.dumps(stored, indent=2, ensure_ascii=False), 'utf-8')
print(f'[INFO] languages.json 已更新，共記錄 {len(stored)} 款遊戲')

# ===== 推播 Discord =====
if not new_chinese_list:
    print('[INFO] 本次無新增中文的遊戲')
    raise SystemExit(0)

print(f'[INFO] 推播 {len(new_chinese_list)} 款遊戲到 Discord...')

for game in new_chinese_list:
    review_total = game['positive'] + game['negative']
    rate = round(game['positive'] / review_total * 100) if review_total > 0 else 0

    payload = {
        'embeds': [{
            'title':     f"🎮 新增中文支援：{game['name']}"[:256],
            'url':       f"https://store.steampowered.com/app/{game['appid']}/",
            'color':     5763719,
            'fields': [
                {'name': '📊 評論', 'value': f"👍 {game['positive']}  👎 {game['negative']}（好評率 {rate}%）", 'inline': False},
                {'name': '🌐 支援語系', 'value': game['langs'][:1000] or '（無資料）', 'inline': False},
            ],
            'timestamp': datetime.utcnow().isoformat() + 'Z',
        }]
    }

    r = requests.post(WEBHOOK, json=payload, timeout=10)
    if r.status_code == 429:
        print('[WARN] Discord 速率限制，等待 5 秒...')
        time.sleep(5)
        requests.post(WEBHOOK, json=payload, timeout=10)
    elif r.status_code >= 400:
        print(f"[WARN] Discord 推播失敗（HTTP {r.status_code}）：{game['name']}")
    else:
        print(f"[NOTIFY] 已推播：{game['name']}")

    time.sleep(2)
