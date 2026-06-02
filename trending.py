"""
trending.py — 依模式從 Steam 取得熱門遊戲清單並推播到 Discord，顯示是否支援中文

MODE 環境變數：
  Trending  (預設) 從 Steam popularnew 分類取得遊戲
  Hot              從 Steam 當前同時在線人數排行取得遊戲
  Rising           從 Steam GetMonthTopAppReleases 取得當月 Top Releases，依評論速度排序
"""
import os
import re
import time
from datetime import datetime, timezone, date, timedelta

import requests

WEBHOOK       = os.environ.get('DISCORD_WEBHOOK', '').strip()
STEAM_API_KEY = os.environ.get('STEAM_API_KEY', '').strip()
MODE          = os.environ.get('MODE', 'Trending').strip()
try:
    PAGE = max(1, int(os.environ.get('PAGE', '1') or '1'))
except ValueError:
    PAGE = 1
SAMPLE        = 10
CHINESE_KEYS  = {'Simplified Chinese', 'Traditional Chinese', '簡體中文', '繁體中文'}
RISING_SKIP_TAGS = {19, 1774, 3859}  # Free to Play, Massively Multiplayer, Battle Royale

if not WEBHOOK:
    raise SystemExit('[ERROR] DISCORD_WEBHOOK 未設定')
if not STEAM_API_KEY:
    raise SystemExit('[ERROR] STEAM_API_KEY 未設定')


# ===== 取得候選 appid 清單 =====
def fetch_trending() -> list[str]:
    r = requests.get(
        'https://store.steampowered.com/search/results/',
        params={'filter': 'popularnew', 'json': '1', 'cc': 'TW', 'l': 'tchinese'},
        timeout=15,
    )
    r.raise_for_status()
    appids = []
    for item in r.json().get('items', []):
        m = re.search(r'/apps/(\d+)/', item.get('logo', ''))
        if m:
            appids.append(m.group(1))
    return appids


def _month_ts(year: int, month: int) -> int:
    return int(datetime(year, month, 1, tzinfo=timezone.utc).timestamp())


def fetch_rising() -> list[str]:
    url   = 'https://api.steampowered.com/ISteamChartsService/GetMonthTopAppReleases/v1/'
    today = date.today()
    appids = []

    for delta in (0, -1):
        d = (today.replace(day=1) + timedelta(days=32 * delta)).replace(day=1)
        params = {'key': STEAM_API_KEY, 'rtime_month': _month_ts(d.year, d.month), 'include_dlc': 'false'}
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        apps = r.json().get('response', {}).get('top_combined_app_and_dlc_releases', [])
        appids = [str(a['appid']) for a in apps]
        print(f'[INFO] Rising 候選：{d.year}-{d.month:02d} 共 {len(appids)} 筆', flush=True)
        if len(appids) >= 10:
            return appids
        print('[INFO] 結果不足 10 筆，改查上個月', flush=True)

    return appids


def fetch_hot() -> list[str]:
    r = requests.get(
        'https://api.steampowered.com/ISteamChartsService/GetMostPlayedGames/v1/',
        params={'key': STEAM_API_KEY},
        timeout=15,
    )
    r.raise_for_status()
    return [str(item['appid']) for item in r.json().get('response', {}).get('ranks', [])]


MODE_FUNCS = {
    'Trending': (fetch_trending, 'New & Trending'),
    'Hot':      (fetch_hot,     '熱門同時在線'),
    'Rising':   (fetch_rising,  '近期竄升'),
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


_DATE_FMTS = [
    '%d %b, %Y', '%b %d, %Y', '%d %B, %Y', '%B %d, %Y',  # English
    '%Y年%m月%d日', '%Y 年 %m 月 %d 日', '%Y-%m-%d',       # 中文/ISO
]

def _calc_velocity(total_reviews: int, release_date_str: str) -> tuple[float, int]:
    for fmt in _DATE_FMTS:
        try:
            release = datetime.strptime(release_date_str.strip(), fmt).date()
            days = max(1, (date.today() - release).days)
            return total_reviews / days, days
        except ValueError:
            continue
    return float(total_reviews), 0


# ===== 逐一查詢 appdetails =====
def get_game_info(appid: str) -> dict | None:
    try:
        rd = requests.get(f'https://store.steampowered.com/api/appdetails?appids={appid}&l=tchinese', timeout=15)
        if rd.status_code != 200:
            return None

        entry = rd.json().get(appid, {})
        if not entry.get('success'):
            return None

        app_data = entry['data']
        app_type = app_data.get('type', '').lower()
        name     = app_data.get('name', f'App {appid}')

        if app_type != 'game':
            return None

        if MODE == 'Rising':
            all_tag_ids = {c['id'] for c in app_data.get('categories', [])} | {g['id'] for g in app_data.get('genres', [])}
            if RISING_SKIP_TAGS & all_tag_ids:
                return None

        release = app_data.get('release_date', {})
        if release.get('coming_soon') or not release.get('date'):
            return None

        raw_langs   = app_data.get('supported_languages', '')
        langs       = {l.strip().split('*')[0].strip() for l in re.sub(r'<[^>]+>', '', raw_langs).split(',')}
        has_chinese = bool(langs & CHINESE_KEYS)

        time.sleep(0.5)

        rv      = requests.get(f'https://store.steampowered.com/appreviews/{appid}?json=1&language=all&purchase_type=all', timeout=10)
        summary  = rv.json().get('query_summary', {})
        positive = summary.get('total_positive', 0)
        negative = summary.get('total_negative', 0)
        total    = positive + negative
        rate     = round(positive / total * 100) if total > 0 else 0

        release_date_str = release.get('date', '')
        velocity, days   = _calc_velocity(total, release_date_str)

        if MODE == 'Rising' and days > 90:
            return None

        return {
            'appid':        appid,
            'name':         name,
            'has_chinese':  has_chinese,
            'is_free':      app_data.get('is_free', False),
            'positive':     positive,
            'negative':     negative,
            'rate':         rate,
            'velocity':     velocity,
            'days':         days,
            'header_image': app_data.get('header_image', f'https://cdn.akamai.steamstatic.com/steam/apps/{appid}/header.jpg'),
            'genres':       ', '.join(g['description'] for g in app_data.get('genres', [])),
            'developers':   ', '.join(app_data.get('developers', [])),
            'release_date': release_date_str,
        }
    except Exception as e:
        print(f'[WARN] App {appid} 查詢失敗：{e}', flush=True)
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

if MODE == 'Rising':
    qualified.sort(key=lambda g: g['velocity'], reverse=True)
    top = qualified[0]
    print(f'[INFO] Rising 排序完成，第一名：{top["name"]}（{top["velocity"]:.2f} 則/天）', flush=True)

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
    img   = game.get('header_image', f'https://cdn.akamai.steamstatic.com/steam/apps/{appid}/header.jpg')
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

    print(f'  [{i+1}/{len(sample)}] {game["name"]}（好評率 {game["rate"]}%）', flush=True)


# ===== 推播 =====
payload = {'embeds': embeds}
r = requests.post(WEBHOOK, json=payload, timeout=10)

if r.status_code >= 400:
    print(f'[WARN] Discord 推播失敗（HTTP {r.status_code}）', flush=True)
else:
    print('[NOTIFY] 推播成功', flush=True)
