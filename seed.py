import json
import re
import time
from datetime import date
from pathlib import Path

import os

import requests

STEAM_API_KEY = os.environ.get('STEAM_API_KEY', '').strip()
if not STEAM_API_KEY:
    raise SystemExit('[ERROR] STEAM_API_KEY 未設定')

DATA_FILE = Path(__file__).parent / 'languages.json'

stored = json.loads(DATA_FILE.read_text('utf-8')) if DATA_FILE.exists() else {}

# ===== 連線 Steam（取 appid 清單用）=====
print('[INFO] 透過 IStoreService/GetAppList 取得全量 App 清單...', flush=True)
all_appids_set = set()
last_appid = 0

while True:
    params = {
        'key':           STEAM_API_KEY,
        'include_games': 'true',
        'max_results':   50000,
    }
    if last_appid:
        params['last_appid'] = last_appid

    try:
        r = requests.get('https://api.steampowered.com/IStoreService/GetAppList/v1/', params=params, timeout=30)
        r.raise_for_status()
        data = r.json().get('response', {})
        apps = data.get('apps', [])
        for a in apps:
            all_appids_set.add(a['appid'])
        print(f'[INFO] 已取得 {len(all_appids_set)} 個 appid...', flush=True)

        if not data.get('have_more_results'):
            break
        last_appid = data.get('last_appid', 0)
        time.sleep(1)
    except Exception as e:
        print(f'[WARN] GetAppList 失敗：{e}')
        break

print(f'[INFO] 共取得 {len(all_appids_set)} 個 appid', flush=True)
all_appids = [a for a in all_appids_set if str(a) not in stored]
print(f'[INFO] 共 {len(all_appids)} 個 appid 待查（已跳過 {len(stored)} 個已有記錄）', flush=True)

CHINESE_STORE_KEYS = {'Simplified Chinese', 'Traditional Chinese'}

def get_store_info(appid: int) -> tuple[str | None, str | None, bool]:
    """回傳 (name, app_type, has_chinese)，失敗回傳 (None, None, False)"""
    try:
        r = requests.get(
            f'https://store.steampowered.com/api/appdetails?appids={appid}',
            timeout=15
        )
        data = r.json()
        if not data or not data.get(str(appid), {}).get('success'):
            return None, None, False
        app_data  = data[str(appid)]['data']
        app_type  = app_data.get('type', '').lower()
        name      = app_data.get('name', f'App {appid}')
        raw_langs = app_data.get('supported_languages', '')
        langs     = {l.strip() for l in re.sub(r'<[^>]+>', '', raw_langs).split(',')}
        return name, app_type, bool(langs & CHINESE_STORE_KEYS)
    except Exception as e:
        print(f'  [WARN] Store API 失敗：{e}')
        return None, None, False

total = len(all_appids)

for i, appid in enumerate(all_appids, 1):
    appid_str = str(appid)

    name, app_type, has_chinese = get_store_info(appid)

    if app_type is None or app_type != 'game':
        time.sleep(0.3)
        continue

    stored[appid_str] = {
        'name':         name,
        'has_chinese':  has_chinese,
        'last_checked': str(date.today()),
    }

    if i % 500 == 0:
        DATA_FILE.write_text(json.dumps(stored, indent=2, ensure_ascii=False), 'utf-8')
        print(f'[INFO] 進度儲存（{i}/{total}，已記錄 {len(stored)} 款遊戲）', flush=True)

    time.sleep(0.5)

DATA_FILE.write_text(json.dumps(stored, indent=2, ensure_ascii=False), 'utf-8')
print(f'[INFO] 基準建立完成，共記錄 {len(stored)} 款遊戲 ✅')
