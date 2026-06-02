"""
trending.py — 依模式從 Steam 取得熱門遊戲清單並推播到 Discord，顯示是否支援中文

MODE 環境變數：
  Trending  (預設) 從 Steam popularnew 分類取得遊戲
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
    url = 'https://store.steampowered.com/search/results/'
    params = {'filter': 'popularnew', 'json': '1', 'cc': 'TW', 'l': 'tchinese'}
    print(f'  [DEBUG] GET {url} params={params}', flush=True)
    r = requests.get(url, params=params, timeout=15)
    print(f'  [DEBUG] HTTP {r.status_code}，回應長度 {len(r.text)} bytes', flush=True)
    r.raise_for_status()
    data = r.json()
    items = data.get('items', [])
    print(f'  [DEBUG] items 數量：{len(items)}', flush=True)
    if items:
        print(f'  [DEBUG] item[0] keys：{list(items[0].keys())}', flush=True)
        print(f'  [DEBUG] item[0] logo：{items[0].get("logo", "（無）")[:80]}', flush=True)
    appids = []
    for item in items:
        logo = item.get('logo', '')
        m = re.search(r'/apps/(\d+)/', logo)
        if m:
            appids.append(m.group(1))
        else:
            print(f'  [DEBUG] 無法解析 appid，logo={logo[:80]}', flush=True)
    return appids


def fetch_hot() -> list[str]:
    url = 'https://api.steampowered.com/ISteamChartsService/GetMostPlayedGames/v1/'
    print(f'  [DEBUG] GET {url}', flush=True)
    r = requests.get(url, params={'key': STEAM_API_KEY}, timeout=15)
    print(f'  [DEBUG] HTTP {r.status_code}，回應長度 {len(r.text)} bytes', flush=True)
    r.raise_for_status()
    ranks = r.json().get('response', {}).get('ranks', [])
    print(f'  [DEBUG] ranks 數量：{len(ranks)}', flush=True)
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


# ===== 逐一查詢 appdetails =====
def get_game_info(appid: str) -> dict | None:
    try:
        url = f'https://store.steampowered.com/api/appdetails?appids={appid}&l=tchinese'
        rd = requests.get(url, timeout=15)
        print(f'    [DEBUG] appdetails HTTP {rd.status_code}', flush=True)

        if rd.status_code != 200:
            print(f'    [DEBUG] 非 200，跳過', flush=True)
            return None

        data = rd.json()
        entry = data.get(appid, {})
        if not entry.get('success'):
            print(f'    [DEBUG] success=false，跳過', flush=True)
            return None

        app_data = entry['data']
        app_type = app_data.get('type', '').lower()
        name     = app_data.get('name', f'App {appid}')

        if app_type != 'game':
            print(f'    [DEBUG] type={app_type}，跳過', flush=True)
            return None

        release = app_data.get('release_date', {})
        if release.get('coming_soon'):
            print(f'    [DEBUG] coming_soon，跳過', flush=True)
            return None
        if not release.get('date'):
            print(f'    [DEBUG] 無發售日，跳過', flush=True)
            return None

        raw_langs   = app_data.get('supported_languages', '')
        langs       = {l.strip() for l in re.sub(r'<[^>]+>', '', raw_langs).split(',')}
        has_chinese = bool(langs & CHINESE_KEYS)
        print(f'    [DEBUG] 語系（前5）：{list(langs)[:5]}，有中文：{has_chinese}', flush=True)

        time.sleep(0.5)

        rv = requests.get(
            f'https://store.steampowered.com/appreviews/{appid}?json=1&language=all&purchase_type=all',
            timeout=10
        )
        print(f'    [DEBUG] appreviews HTTP {rv.status_code}', flush=True)
        summary  = rv.json().get('query_summary', {})
        positive = summary.get('total_positive', 0)
        negative = summary.get('total_negative', 0)
        total    = positive + negative
        rate     = round(positive / total * 100) if total > 0 else 0
        print(f'    [DEBUG] 評論：👍{positive} 👎{negative} 好評率{rate}%', flush=True)

        return {
            'appid':        appid,
            'name':         name,
            'has_chinese':  has_chinese,
            'is_free':      app_data.get('is_free', False),
            'positive':     positive,
            'negative':     negative,
            'rate':         rate,
            'genres':       ', '.join(g['description'] for g in app_data.get('genres', [])),
            'developers':   ', '.join(app_data.get('developers', [])),
            'release_date': release.get('date', ''),
        }
    except Exception as e:
        print(f'    [DEBUG] 例外：{e}', flush=True)
        return None


print(f'[INFO] 查詢遊戲資訊（共 {len(source_appids)} 款）...', flush=True)
qualified = []

for i, appid in enumerate(source_appids, 1):
    print(f'  [{i}/{len(source_appids)}] App {appid}...', flush=True)
    info = get_game_info(appid)
    if info:
        chinese_label = '✅ 有中文' if info['has_chinese'] else '❌ 無中文'
        print(f'    → {info["name"]}（{chinese_label}）', flush=True)
        qualified.append(info)
    time.sleep(1)

if not qualified:
    raise SystemExit('[ERROR] 無法取得任何遊戲資訊')

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
    title         = f'🎮 Steam {mode_label} 熱門遊戲' if i == 0 else game['name'][:256]
    chinese_label = '✅ 支援中文' if game['has_chinese'] else '❌ 不支援中文'
    free_label    = '（免費）' if game['is_free'] else ''

    fields = [
        {'name': '🌐 中文支援', 'value': chinese_label,                                                                        'inline': True},
        {'name': '📊 評論',    'value': f"👍 {game['positive']}  👎 {game['negative']}（好評率 {game['rate']}%）{free_label}", 'inline': False},
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
print(f'[DEBUG] Discord 推播 HTTP {r.status_code}', flush=True)

if r.status_code >= 400:
    print(f'[WARN] Discord 推播失敗（HTTP {r.status_code}）')
else:
    print('[NOTIFY] 預覽推播成功')
