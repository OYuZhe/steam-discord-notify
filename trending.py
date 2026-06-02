"""
trending.py — 依模式從 Steam 取得熱門遊戲清單，篩選有中文支援的遊戲並推播到 Discord

MODE 環境變數：
  Trending  (預設) 從 Steam New & Trending 分類取得遊戲
  Hot              從 Steam 當前同時在線人數排行取得遊戲
"""
import os
import re
import time
from datetime import datetime, timezone

import requests

WEBHOOK       = os.environ.get('DISCORD_WEBHOOK', '').strip()
STEAM_API_KEY = os.environ.get('STEAM_API_KEY', '').strip()
MODE          = os.environ.get('MODE', 'Trending').strip()
try:
    PAGE = max(1, int(os.environ.get('PAGE', '1') or '1'))
except ValueError:
    PAGE = 1
SAMPLE        = 10
CHINESE_KEYS  = {'Simplified Chinese', 'Traditional Chinese'}

if not WEBHOOK:
    raise SystemExit('[ERROR] DISCORD_WEBHOOK 未設定')
if not STEAM_API_KEY:
    raise SystemExit('[ERROR] STEAM_API_KEY 未設定')


# ===== 取得候選 appid 清單 =====
def fetch_trending() -> list[str]:
    r = requests.get(
        'https://store.steampowered.com/api/featuredcategories/',
        params={'cc': 'TW', 'l': 'tchinese'},
        timeout=15
    )
    r.raise_for_status()
    items = r.json().get('new_and_trending', {}).get('items', [])
    return [str(item['id']) for item in items]


def fetch_hot() -> list[str]:
    r = requests.get(
        'https://api.steampowered.com/ISteamChartsService/GetMostPlayedGames/v1/',
        params={'key': STEAM_API_KEY},
        timeout=15
    )
    r.raise_for_status()
    ranks = r.json().get('response', {}).get('ranks', [])
    return [str(item['appid']) for item in ranks]


MODE_FUNCS = {
    'Trending': (fetch_trending, 'New & Trending'),
    'Hot':      (fetch_hot,     '熱門同時在線'),
}

if MODE not in MODE_FUNCS:
    raise SystemExit(f'[ERROR] 不支援的 MODE：{MODE}，可用值：{", ".join(MODE_FUNCS)}')

fetch_func, mode_label = MODE_FUNCS[MODE]

print(f'[INFO] 模式：{mode_label}，取得候選清單...', flush=True)
try:
    source_appids = fetch_func()
    print(f'[INFO] 來源清單共 {len(source_appids)} 款', flush=True)
except Exception as e:
    raise SystemExit(f'[ERROR] 取得清單失敗：{e}')


# ===== 逐一查詢 appdetails，篩選有中文的遊戲 =====
def get_game_info(appid: str) -> dict | None:
    """回傳遊戲資訊，無中文支援或查詢失敗時回傳 None"""
    try:
        rd = requests.get(
            f'https://store.steampowered.com/api/appdetails?appids={appid}&l=tchinese',
            timeout=15
        )
        data = rd.json()
        if not data or not data.get(appid, {}).get('success'):
            return None
        app_data = data[appid]['data']

        if app_data.get('type', '').lower() != 'game':
            return None
        if app_data.get('is_free'):
            return None
        release = app_data.get('release_date', {})
        if release.get('coming_soon') or not release.get('date'):
            return None

        raw_langs = app_data.get('supported_languages', '')
        langs     = {l.strip() for l in re.sub(r'<[^>]+>', '', raw_langs).split(',')}
        if not langs & CHINESE_KEYS:
            return None

        time.sleep(0.5)

        rv = requests.get(
            f'https://store.steampowered.com/appreviews/{appid}?json=1&language=all&purchase_type=all',
            timeout=10
        )
        summary  = rv.json().get('query_summary', {})
        positive = summary.get('total_positive', 0)
        negative = summary.get('total_negative', 0)
        total    = positive + negative
        rate     = round(positive / total * 100) if total > 0 else 0

        return {
            'appid':        appid,
            'name':         app_data.get('name', f'App {appid}'),
            'positive':     positive,
            'negative':     negative,
            'rate':         rate,
            'genres':       ', '.join(g['description'] for g in app_data.get('genres', [])),
            'developers':   ', '.join(app_data.get('developers', [])),
            'release_date': release.get('date', ''),
        }
    except Exception:
        return None


print(f'[INFO] 查詢遊戲資訊與中文支援（共 {len(source_appids)} 款）...', flush=True)
qualified = []

for i, appid in enumerate(source_appids, 1):
    print(f'  [{i}/{len(source_appids)}] App {appid}...', flush=True)
    info = get_game_info(appid)
    if info:
        print(f'    → ✅ {info["name"]}（有中文）', flush=True)
        qualified.append(info)
    time.sleep(1)

print(f'[INFO] 有中文支援：{len(qualified)} 款', flush=True)

if not qualified:
    raise SystemExit('[ERROR] 來源清單中沒有找到有中文支援的遊戲')

total_pages = (len(qualified) + SAMPLE - 1) // SAMPLE
page = max(1, min(PAGE, total_pages))

if page != PAGE:
    print(f'[INFO] 頁碼 {PAGE} 超出範圍，調整為第 {page} 頁（共 {total_pages} 頁）', flush=True)

start = (page - 1) * SAMPLE
sample = qualified[start:start + SAMPLE]
print(f'[INFO] 第 {page} / {total_pages} 頁（第 {start+1}～{start+len(sample)} 款），準備推播...', flush=True)


# ===== 組合 Discord embeds =====
today_str = datetime.now().strftime('%Y-%m-%d')
embeds = []

for i, game in enumerate(sample):
    appid = game['appid']
    url   = f'https://store.steampowered.com/app/{appid}/'
    img   = f'https://cdn.akamai.steamstatic.com/steam/apps/{appid}/header.jpg'
    title = f'🌏 預覽推播：Steam {mode_label} 中文遊戲' if i == 0 else game['name'][:256]

    fields = [
        {'name': '📊 評論', 'value': f"👍 {game['positive']}  👎 {game['negative']}（好評率 {game['rate']}%）", 'inline': False},
    ]
    if game.get('genres'):
        fields.append({'name': '🏷️ 類型',   'value': game['genres'],       'inline': True})
    if game.get('developers'):
        fields.append({'name': '🛠️ 開發商', 'value': game['developers'],   'inline': True})
    if game.get('release_date'):
        fields.append({'name': '📅 發售日', 'value': game['release_date'], 'inline': True})

    embeds.append({
        'title':     title[:256],
        'url':       url,
        'color':     5763719,
        'image':     {'url': img},
        'fields':    fields,
        'footer':    {'text': f'PREVIEW · {mode_label} · {today_str}'},
        'timestamp': datetime.now(timezone.utc).isoformat(),
    })

    print(f'  [{i+1}/{len(sample)}] {game["name"]}（好評率 {game["rate"]}%）')


# ===== 推播 =====
payload = {'embeds': embeds}
r = requests.post(WEBHOOK, json=payload, timeout=10)

if r.status_code >= 400:
    print(f'[WARN] Discord 推播失敗（HTTP {r.status_code}）')
else:
    print('[NOTIFY] 預覽推播成功')
