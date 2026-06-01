import json
import time
from datetime import date
from pathlib import Path

import requests
from steam.client import SteamClient

DATA_FILE   = Path(__file__).parent / 'languages.json'
MIN_REVIEWS = 20

stored = json.loads(DATA_FILE.read_text('utf-8')) if DATA_FILE.exists() else {}

# ===== 透過 SteamSpy 取得所有 appid =====
print('[INFO] 透過 SteamSpy 取得 App 清單...')
all_appids_set = set(int(k) for k in stored)
page = 0
while True:
    print(f'[INFO] SteamSpy 第 {page + 1} 頁...')
    try:
        r = requests.get(f'https://steamspy.com/api.php?request=all&page={page}', timeout=20)
        games = r.json()
        if not games:
            break
        for appid in games:
            all_appids_set.add(int(appid))
    except Exception as e:
        print(f'[WARN] 第 {page} 頁失敗：{e}，停止翻頁')
        break
    page += 1
    time.sleep(2)

all_appids = [a for a in all_appids_set if str(a) not in stored]
print(f'[INFO] 共 {len(all_appids)} 個 appid 待查（已跳過 {len(stored)} 個已有記錄）')

# ===== 連線 Steam =====
print('[INFO] 連線 Steam CM...')
client = SteamClient()
client.anonymous_login()
print('[INFO] 連線成功')

CHINESE_KEYS = {'schinese', 'tchinese'}
batch_size   = 250
total        = len(all_appids)

for i in range(0, total, batch_size):
    batch = all_appids[i:i + batch_size]
    print(f'[INFO] 查詢 PICS（{i}–{i + len(batch)}/{total}）...')

    try:
        info = client.get_product_info(apps=batch)
    except Exception as e:
        print(f'[WARN] PICS 查詢失敗：{e}，等待後重試...')
        time.sleep(10)
        try:
            info = client.get_product_info(apps=batch)
        except Exception as e2:
            print(f'[WARN] 重試失敗，跳過此批次：{e2}')
            continue

    for appid in batch:
        appid_str = str(appid)
        app    = info.get('apps', {}).get(appid, {})
        common = app.get('common', {})

        if not common:
            continue

        if common.get('type', '').lower() != 'game':
            continue

        langs       = set((common.get('languages') or {}).keys())
        has_chinese = bool(langs & CHINESE_KEYS)
        name        = common.get('name', f'App {appid}')

        stored[appid_str] = {
            'name':         name,
            'has_chinese':  has_chinese,
            'last_checked': str(date.today()),
        }

    if (i // batch_size) % 10 == 0:
        DATA_FILE.write_text(json.dumps(stored, indent=2, ensure_ascii=False), 'utf-8')
        print(f'[INFO] 進度儲存（{i}/{total}，已記錄 {len(stored)} 款遊戲）')

    time.sleep(1)

client.disconnect()
DATA_FILE.write_text(json.dumps(stored, indent=2, ensure_ascii=False), 'utf-8')
print(f'[INFO] 基準建立完成，共記錄 {len(stored)} 款遊戲 ✅')
