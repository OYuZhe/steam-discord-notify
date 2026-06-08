"""
notify.py — 每日偵測新增繁/簡體中文支援的 Steam 遊戲並推播到 Discord

流程：
  1. IStoreService/GetAppList 取得自上次執行以來有變動的遊戲清單
  2. 逐一查詢 Store API，比對語系是否從「無中文 → 有中文」
  3. 符合條件者推播 Discord embed 通知
"""
import json
import os
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

# ===== 設定 =====
WEBHOOK       = os.environ.get('DISCORD_WEBHOOK', '').strip()
STEAM_API_KEY = os.environ.get('STEAM_API_KEY', '').strip()
MIN_REVIEWS   = 20
DATA_FILE     = Path(__file__).parent / 'languages.json'
META_FILE     = Path(__file__).parent / 'meta.json'

CHINESE_STORE_KEYS = {'Simplified Chinese', 'Traditional Chinese', '簡體中文', '繁體中文'}

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

# 更新執行時間戳記（在查詢前更新，避免重複通知）
now_ts = int(datetime.now(timezone.utc).timestamp())
meta['last_run_ts'] = now_ts
meta['last_run']    = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
META_FILE.write_text(json.dumps(meta, indent=2), 'utf-8')

if not changed_appids:
    print('[INFO] 本次無任何 App 更新')
    raise SystemExit(0)

SKIP_TYPES = {'dlc', 'music', 'demo', 'advertising', 'mod', 'video', 'free'}

to_check = [appid for appid in changed_appids
            if not stored.get(str(appid), {}).get('has_chinese')
            and stored.get(str(appid), {}).get('app_type', 'game') not in SKIP_TYPES]

print(f'[INFO] 實際需查詢：{len(to_check)} 個（跳過已知有中文）')

STORE_SLEEP = 2.0  # 每筆間隔秒數，避免觸發 Store API 速率限制


# ===== 逐一用 Store API 查詢語系 =====
def get_store_info(appid: int) -> tuple[str | None, str | None, list, dict]:
    """回傳 (app_type, name, langs, extra)；查詢失敗時 app_type 為 None。"""
    url  = f'https://store.steampowered.com/api/appdetails?appids={appid}&l=tchinese'
    wait = 60
    for _ in range(3):
        try:
            r = requests.get(url, timeout=15)
            if r.status_code == 429:
                print(f'  [WARN] 速率限制，等待 {wait} 秒...', flush=True)
                time.sleep(wait)
                wait *= 2
                continue
            data = r.json()
            if not data or not data.get(str(appid), {}).get('success'):
                return None, None, [], {}
            app_data = data[str(appid)]['data']
            release  = app_data.get('release_date', {})
            if release.get('coming_soon') or not release.get('date'):
                return 'coming_soon', app_data.get('name', f'App {appid}'), [], {}
            app_type  = app_data.get('type', '').lower()
            name      = app_data.get('name', f'App {appid}')
            # split('*')[0] 去掉星號（部分語音支援標記）及後方的備註文字
            raw_langs = app_data.get('supported_languages', '')
            langs     = [l.strip().split('*')[0].strip() for l in re.sub(r'<[^>]+>', '', raw_langs).split(',')]
            extra = {
                'genres':       ', '.join(g['description'] for g in app_data.get('genres', [])),
                'developers':   ', '.join(app_data.get('developers', [])),
                'release_date': release.get('date', ''),
                'is_free':      app_data.get('is_free', False),
                'header_image': app_data.get('header_image', ''),
            }
            return app_type, name, langs, extra
        except Exception as e:
            print(f'  [WARN] Store API 失敗：{e}', flush=True)
            return None, None, [], {}
    return None, None, [], {}


new_chinese_list = []
notified = set()
today    = datetime.now().strftime('%Y-%m-%d')

for i, appid in enumerate(to_check, 1):
    appid_str = str(appid)
    print(f'[{i}/{len(to_check)}] 查詢 App {appid}...', flush=True)

    app_type, name, langs, extra = get_store_info(appid)

    if app_type is None:
        time.sleep(STORE_SLEEP)
        continue

    if app_type != 'game':
        label = '尚未發售' if app_type == 'coming_soon' else f'非遊戲（{app_type}）'
        print(f'  → {label}，跳過')
        stored[appid_str] = {
            'name': name, 'has_chinese': False, 'app_type': app_type, 'last_checked': today,
        }
        time.sleep(STORE_SLEEP)
        continue

    if extra.get('is_free'):
        print(f'  → 免費遊戲，跳過')
        stored[appid_str] = {'name': name, 'has_chinese': False, 'app_type': 'free', 'last_checked': today}
        time.sleep(STORE_SLEEP)
        continue

    has_chinese = bool(set(langs) & CHINESE_STORE_KEYS)
    had_chinese = stored.get(appid_str, {}).get('has_chinese', False)

    if has_chinese and not had_chinese and appid_str not in notified:
        print(f'  → 🎉 [{name}] 新增中文支援！')

        total_reviews = positive = negative = 0
        try:
            r = requests.get(
                f'https://store.steampowered.com/appreviews/{appid}?json=1&language=all&purchase_type=all',
                timeout=10,
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
                'appid':        appid_str,
                'name':         name,
                'langs':        ', '.join(l for l in langs if l),
                'positive':     positive,
                'negative':     negative,
                'genres':       extra.get('genres', ''),
                'developers':   extra.get('developers', ''),
                'release_date': extra.get('release_date', ''),
                'header_image': extra.get('header_image', ''),
            })
            notified.add(appid_str)
    else:
        print(f'  → 中文：{"✅ 有" if has_chinese else "❌ 無"}')

    stored[appid_str] = {
        'name': name, 'has_chinese': has_chinese, 'last_checked': today,
    }
    time.sleep(STORE_SLEEP)


DATA_FILE.write_text(json.dumps(stored, indent=2, ensure_ascii=False), 'utf-8')
print(f'[INFO] languages.json 已更新，共記錄 {len(stored)} 款遊戲')


# ===== 推播 Discord =====
if not new_chinese_list:
    print('[INFO] 本次無新增中文的遊戲')
    raise SystemExit(0)

print(f'[INFO] 推播 {len(new_chinese_list)} 款遊戲到 Discord...')

BATCH_SIZE  = 10
total       = len(new_chinese_list)
today_str   = datetime.now().strftime('%Y-%m-%d')
batches     = [new_chinese_list[i:i + BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]
batch_count = len(batches)

for idx, batch in enumerate(batches):
    embeds = []
    for game_idx, game in enumerate(batch):
        review_total = game['positive'] + game['negative']
        rate  = round(game['positive'] / review_total * 100) if review_total > 0 else 0
        url   = f"https://store.steampowered.com/app/{game['appid']}/"
        img   = game.get('header_image') or f"https://cdn.akamai.steamstatic.com/steam/apps/{game['appid']}/header.jpg"
        part_str = f'（第 {idx + 1} / {batch_count} 則）' if batch_count > 1 else ''

        is_first = game_idx == 0
        title    = game['name'][:256]
        if idx == 0 and is_first:
            author_name = f'🌏 今日新增中文支援：共 {total} 款遊戲 {part_str}'.strip()
        elif is_first:
            author_name = f'🌏 新增中文支援（續）{part_str}'.strip()
        else:
            author_name = None

        fields = [
            {'name': '📊 評論', 'value': f"👍 {game['positive']}  👎 {game['negative']}（好評率 {rate}%）", 'inline': False},
        ]
        if game.get('genres'):
            fields.append({'name': '🏷️ 類型',   'value': game['genres'],       'inline': True})
        if game.get('developers'):
            fields.append({'name': '🛠️ 開發商', 'value': game['developers'],   'inline': True})
        if game.get('release_date'):
            fields.append({'name': '📅 發售日', 'value': game['release_date'], 'inline': True})

        embed = {
            'title':     title[:256],
            'url':       url,
            'color':     5763719,
            'image':     {'url': img},
            'fields':    fields,
            'footer':    {'text': f'Steam 中文更新通知 · {today_str}'},
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }
        if author_name:
            embed['author'] = {'name': author_name}
        embeds.append(embed)

    payload = {'embeds': embeds}
    r = requests.post(WEBHOOK, json=payload, timeout=10)

    if r.status_code == 429:
        print(f'[WARN] Discord 速率限制，等待 5 秒...')
        time.sleep(5)
        r = requests.post(WEBHOOK, json=payload, timeout=10)

    if r.status_code >= 400:
        print(f'[WARN] Discord 推播失敗（HTTP {r.status_code}，第 {idx + 1} 則）')
    else:
        print(f'[NOTIFY] 已推播第 {idx + 1} 則（{len(batch)} 款）')

    if idx < batch_count - 1:
        time.sleep(2)
