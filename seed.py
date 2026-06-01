import json
import re
import time
from datetime import date
from pathlib import Path

import requests
from steam.client import SteamClient

DATA_FILE = Path(__file__).parent / 'languages.json'

stored = json.loads(DATA_FILE.read_text('utf-8')) if DATA_FILE.exists() else {}

# ===== 連線 Steam（取 appid 清單用）=====
print('[INFO] 連線 Steam CM...', flush=True)
client = SteamClient()
client.anonymous_login()
print('[INFO] 連線成功', flush=True)

print('[INFO] 透過 PICS 取得全量 App 清單...', flush=True)
changes = client.get_changes_since(1, app_changes=True, package_changes=False)
client.disconnect()

all_appids = [c.appid for c in changes.app_changes if str(c.appid) not in stored]
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
