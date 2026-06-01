import json
import os
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

# ===== 設定 =====
WEBHOOK      = os.environ.get('DISCORD_WEBHOOK', '').strip()
STEAM_API_KEY = os.environ.get('STEAM_API_KEY', '').strip()
MIN_REVIEWS  = 20
DATA_FILE    = Path(__file__).parent / 'languages.json'
META_FILE    = Path(__file__).parent / 'meta.json'

CHINESE_STORE_KEYS = {'Simplified Chinese', 'Traditional Chinese'}

if not WEBHOOK:
    raise SystemExit('[ERROR] DISCORD_WEBHOOK 未設定')
if not STEAM_API_KEY:
    raise SystemExit('[ERROR] STEAM_API_KEY 未設定')
if not DATA_FILE.exists():
    raise SystemExit('[ERROR] languages.json 不存在，請先執行 seed.py 建立基準')

# ===== 讀取狀態檔 =====
meta   = json.loads(META_FILE.read_text('utf-8')) if META_FILE.exists() else {}
stored = json.loads(DATA_FILE.read_text('utf-8'))

# 上次執行時間，預設為 25 小時前確保不漏掉
last_run_ts = int(meta.get('last_run_ts', 0))
if not last_run_ts:
    last_run_ts = int((datetime.now(timezone.utc) - timedelta(hours=25)).timestamp())

print(f'[INFO] 查詢 {datetime.fromtimestamp(last_run_ts, timezone.utc).strftime("%Y-%m-%d %H:%M")} 之後有變動的遊戲...', flush=True)

# ===== 透過 IStoreService/GetAppList 取得有變動的遊戲 =====
changed_appids = []
last_appid = 0

while True:
    params = {
        'key':               STEAM_API_KEY,
        'if_modified_since': last_run_ts,
        'include_games':     'true',
        'max_results':       50000,
    }
    if last_appid:
        params['last_appid'] = last_appid

    try:
        r = requests.get('https://api.steampowered.com/IStoreService/GetAppList/v1/', params=params, timeout=30)
        r.raise_for_status()
        data = r.json().get('response', {})
        apps = data.get('apps', [])
        changed_appids.extend(a['appid'] for a in apps)

        if not data.get('have_more_results'):
            break
        last_appid = data.get('last_appid', 0)
        time.sleep(1)
    except Exception as e:
        print(f'[WARN] GetAppList 失敗：{e}')
        break

print(f'[INFO] 有變動 App：{len(changed_appids)} 個')

# 更新執行時間戳記
now_ts = int(datetime.now(timezone.utc).timestamp())
meta['last_run_ts'] = now_ts
meta['last_run']    = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
META_FILE.write_text(json.dumps(meta, indent=2), 'utf-8')

if not changed_appids:
    print('[INFO] 本次無任何 App 更新')
    raise SystemExit(0)

# 已知有中文的跳過
to_check = [appid for appid in changed_appids
            if not stored.get(str(appid), {}).get('has_chinese')]

print(f'[INFO] 實際需查詢：{len(to_check)} 個（跳過已知有中文）')

# ===== 逐一用 Store API 查詢語系 =====
def get_store_info(appid: int) -> tuple:
    try:
        r = requests.get(
            f'https://store.steampowered.com/api/appdetails?appids={appid}',
            timeout=15
        )
        if r.status_code == 429:
            print('  [WARN] Store API 速率限制，等待 60 秒...', flush=True)
            time.sleep(60)
            r = requests.get(
                f'https://store.steampowered.com/api/appdetails?appids={appid}',
                timeout=15
            )
        data = r.json()
        if not data or not data.get(str(appid), {}).get('success'):
            return None, None, []
        app_data  = data[str(appid)]['data']
        app_type  = app_data.get('type', '').lower()
        name      = app_data.get('name', f'App {appid}')
        raw_langs = app_data.get('supported_languages', '')
        langs     = [l.strip() for l in re.sub(r'<[^>]+>', '', raw_langs).split(',')]
        return app_type, name, langs
    except Exception as e:
        print(f'  [WARN] Store API 失敗：{e}')
        return None, None, []

new_chinese_list = []
notified = set()
today    = datetime.now().strftime('%Y-%m-%d')

for i, appid in enumerate(to_check, 1):
    appid_str = str(appid)
    print(f'[{i}/{len(to_check)}] 查詢 App {appid}...', flush=True)

    app_type, name, langs = get_store_info(appid)

    if app_type is None:
        time.sleep(0.5)
        continue

    if app_type != 'game':
        print(f'  → 非遊戲（{app_type}），跳過')
        time.sleep(0.3)
        continue

    has_chinese = bool(set(langs) & CHINESE_STORE_KEYS)
    had_chinese = stored.get(appid_str, {}).get('has_chinese', False)
    stored_name = stored.get(appid_str, {}).get('name', name)

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
        'last_checked': today,
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
            'timestamp': datetime.now(timezone.utc).isoformat(),
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
