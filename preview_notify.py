"""
preview_notify.py — 從 languages.json 隨機抽選有中文的遊戲推播到 Discord，用於預覽 embed 外觀
"""
import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

WEBHOOK   = os.environ.get('DISCORD_WEBHOOK', '').strip()
DATA_FILE = Path(__file__).parent / 'languages.json'
SAMPLE    = 10

if not WEBHOOK:
    raise SystemExit('[ERROR] DISCORD_WEBHOOK 未設定')
if not DATA_FILE.exists():
    raise SystemExit('[ERROR] languages.json 不存在，請先執行 seed.py')

stored = json.loads(DATA_FILE.read_text('utf-8'))

candidates = [
    (appid, info) for appid, info in stored.items()
    if info.get('has_chinese') and info.get('app_type', 'game') == 'game'
]

if len(candidates) < SAMPLE:
    raise SystemExit(f'[ERROR] 可用遊戲不足 {SAMPLE} 款（現有 {len(candidates)} 款）')

sample = random.sample(candidates, SAMPLE)
print(f'[INFO] 隨機抽選 {SAMPLE} 款遊戲，準備推播...')

today_str = datetime.now().strftime('%Y-%m-%d')


def get_extra_info(appid: str) -> dict:
    try:
        r = requests.get(
            f'https://store.steampowered.com/api/appdetails?appids={appid}&l=tchinese',
            timeout=15
        )
        data = r.json()
        if not data or not data.get(appid, {}).get('success'):
            return {}
        app_data = data[appid]['data']
        genres      = ', '.join(g['description'] for g in app_data.get('genres', []))
        developers  = ', '.join(app_data.get('developers', []))
        release_date = app_data.get('release_date', {}).get('date', '')
        return {'genres': genres, 'developers': developers, 'release_date': release_date}
    except Exception:
        return {}


embeds = []
for i, (appid, info) in enumerate(sample):
    url  = f'https://store.steampowered.com/app/{appid}/'
    img  = f'https://cdn.akamai.steamstatic.com/steam/apps/{appid}/capsule_616x353.jpg'
    name = info.get('name', f'App {appid}')

    positive = negative = 0
    try:
        r = requests.get(
            f'https://store.steampowered.com/appreviews/{appid}?json=1&language=all&purchase_type=all',
            timeout=10
        )
        summary  = r.json().get('query_summary', {})
        positive = summary.get('total_positive', 0)
        negative = summary.get('total_negative', 0)
    except Exception:
        pass

    extra = get_extra_info(appid)

    review_total = positive + negative
    rate  = round(positive / review_total * 100) if review_total > 0 else 0
    title = f'🌏 預覽推播：隨機抽選 {SAMPLE} 款遊戲' if i == 0 else name[:256]

    fields = [
        {'name': '📊 評論',   'value': f"👍 {positive}  👎 {negative}（好評率 {rate}%）", 'inline': False},
    ]
    if extra.get('genres'):
        fields.append({'name': '🏷️ 類型', 'value': extra['genres'],      'inline': True})
    if extra.get('developers'):
        fields.append({'name': '🛠️ 開發商', 'value': extra['developers'], 'inline': True})
    if extra.get('release_date'):
        fields.append({'name': '📅 發售日', 'value': extra['release_date'], 'inline': True})

    embeds.append({
        'title':     title[:256],
        'url':       url,
        'color':     5763719,
        'image':     {'url': img},
        'fields':    fields,
        'footer':    {'text': f'PREVIEW · {today_str}'},
        'timestamp': datetime.now(timezone.utc).isoformat(),
    })

    print(f'  [{i+1}/{SAMPLE}] {name}')
    time.sleep(1)

payload = {'embeds': embeds}
r = requests.post(WEBHOOK, json=payload, timeout=10)

if r.status_code >= 400:
    print(f'[WARN] Discord 推播失敗（HTTP {r.status_code}）')
else:
    print('[NOTIFY] 預覽推播成功')
