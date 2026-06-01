import json
import os
import time
from datetime import date, datetime
from pathlib import Path

import requests
from steam.client import SteamClient

# ===== 設定 =====
WEBHOOK       = os.environ.get('DISCORD_WEBHOOK', '').strip()
MIN_REVIEWS   = 50
DATA_FILE     = Path(__file__).parent / 'languages.json'
META_FILE     = Path(__file__).parent / 'meta.json'
CHINESE_KEYS  = {'schinese', 'tchinese'}  # PICS 語系格式

if not WEBHOOK:
    raise SystemExit('[ERROR] DISCORD_WEBHOOK 未設定')

# ===== 讀取狀態檔 =====
meta   = json.loads(META_FILE.read_text('utf-8')) if META_FILE.exists() else {}
stored = json.loads(DATA_FILE.read_text('utf-8')) if DATA_FILE.exists() else {}

DATA_FILE.touch()
META_FILE.touch()

last_change_number = int(meta.get('last_change_number', 0))
is_first_run       = not stored

# ===== 連線 Steam（匿名，不需帳號或 API Key）=====
print('[INFO] 連線 Steam CM...')
client = SteamClient()
client.anonymous_login()
print('[INFO] 連線成功')

# ===== 取得有變動的 App 清單（PICS GetAppChanges）=====
print(f'[INFO] 查詢 PICS 變動（change number: {last_change_number}）...')
changes = client.get_changes_since(last_change_number, app_changes=True, package_changes=False)

current_change_number = changes.current_change_number
changed_appids = [c.appid for c in changes.app_changes]

print(f'[INFO] change number：{last_change_number} → {current_change_number}')
print(f'[INFO] 有變動 App：{len(changed_appids)} 個')

meta['last_change_number'] = current_change_number
meta['last_run'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
META_FILE.write_text(json.dumps(meta, indent=2), 'utf-8')

# =========================================================
# 首次執行：用 SteamSpy 掃描前 10,000 款遊戲建立基準
# =========================================================
if is_first_run:
    print('[INFO] 首次執行，掃描 SteamSpy 前 10,000 款遊戲...')
    print('[INFO] 本次不推播，僅建立基準資料')

    all_games = {}
    for page in range(10):
        print(f'[INFO] SteamSpy 第 {page + 1}/10 頁...')
        try:
            r = requests.get(f'https://steamspy.com/api.php?request=all&page={page}', timeout=20)
            games = r.json()
            if not games:
                break
            all_games.update(games)
        except Exception as e:
            print(f'[WARN] 第 {page} 頁失敗：{e}')
            break
        time.sleep(2)

    filtered = {
        appid: g for appid, g in all_games.items()
        if (g.get('positive', 0) + g.get('negative', 0)) > MIN_REVIEWS
    }
    print(f'[INFO] 評論數 > {MIN_REVIEWS} 的遊戲：{len(filtered)} 款')

    appids = [int(a) for a in filtered]
    batch_size = 250
    total = len(appids)

    for i in range(0, total, batch_size):
        batch = appids[i:i + batch_size]
        print(f'[INFO] 查詢 PICS 語系資料（{i}–{i + len(batch)}/{total}）...')
        try:
            info = client.get_product_info(apps=batch)
        except Exception as e:
            print(f'[WARN] PICS 查詢失敗：{e}')
            time.sleep(5)
            continue

        for appid in batch:
            appid_str = str(appid)
            if appid_str in stored:
                continue
            app = info.get('apps', {}).get(appid, {})
            common = app.get('common', {})
            name   = common.get('name', f'App {appid}')
            langs  = set((common.get('languages') or {}).keys())
            has_chinese = bool(langs & CHINESE_KEYS)

            stored[appid_str] = {
                'name':         name,
                'has_chinese':  has_chinese,
                'last_checked': str(date.today()),
            }

        if i % 1000 == 0 and i > 0:
            DATA_FILE.write_text(json.dumps(stored, indent=2, ensure_ascii=False), 'utf-8')
            print(f'[INFO] 進度儲存（{i}/{total}）')

        time.sleep(1)

    DATA_FILE.write_text(json.dumps(stored, indent=2, ensure_ascii=False), 'utf-8')
    print(f'[INFO] 基準建立完成，共記錄 {len(stored)} 款遊戲 ✅')
    client.disconnect()
    raise SystemExit(0)

# =========================================================
# 後續執行：查詢有變動的 App
# =========================================================
if not changed_appids:
    print('[INFO] 本次無任何 App 更新')
    client.disconnect()
    raise SystemExit(0)

# 過濾：已知有中文 或 7 天內查過的跳過
today = date.today()
to_check = []
for appid in changed_appids:
    appid_str = str(appid)
    entry = stored.get(appid_str)
    if entry and entry.get('has_chinese'):
        continue
    if entry and entry.get('last_checked'):
        diff = (today - date.fromisoformat(entry['last_checked'])).days
        if diff < 7:
            continue
    to_check.append(appid)

print(f'[INFO] 實際需查詢：{len(to_check)} 個（跳過已知有中文或 7 天內查過）')

# 批次查詢 PICS 產品資訊
new_chinese_list = []
notified = set()
batch_size = 250

for i in range(0, len(to_check), batch_size):
    batch = to_check[i:i + batch_size]
    print(f'[INFO] 查詢 PICS（{i}–{i + len(batch)}/{len(to_check)}）...')
    try:
        info = client.get_product_info(apps=batch)
    except Exception as e:
        print(f'[WARN] PICS 查詢失敗：{e}')
        time.sleep(5)
        continue

    for appid in batch:
        appid_str = str(appid)
        app    = info.get('apps', {}).get(appid, {})
        common = app.get('common', {})

        if not common:
            continue

        app_type = common.get('type', '').lower()
        name     = common.get('name', f'App {appid}')

        if app_type != 'game':
            print(f'  → [{name}] 非遊戲（{app_type}），跳過')
            continue

        langs       = set((common.get('languages') or {}).keys())
        has_chinese = bool(langs & CHINESE_KEYS)
        was_tracked = appid_str in stored
        had_chinese = was_tracked and stored[appid_str].get('has_chinese', False)

        if has_chinese and was_tracked and not had_chinese and appid_str not in notified:
            print(f'  → 🎉 [{name}] 新增中文支援！')

            # 查評論數（Steam Store API，免 key）
            total_reviews = positive = negative = 0
            try:
                r = requests.get(
                    f'https://store.steampowered.com/appreviews/{appid}?json=1&language=all&purchase_type=all',
                    timeout=10
                )
                summary  = r.json().get('query_summary', {})
                positive = summary.get('total_positive', 0)
                negative = summary.get('total_negative', 0)
                total_reviews = summary.get('total_reviews', positive + negative)
            except Exception:
                pass

            if total_reviews < MIN_REVIEWS:
                print(f'  → [{name}] 評論數 {total_reviews} < {MIN_REVIEWS}，跳過')
            else:
                new_chinese_list.append({
                    'appid':    appid_str,
                    'name':     name,
                    'langs':    ', '.join(sorted(langs)),
                    'positive': positive,
                    'negative': negative,
                    'total':    total_reviews,
                })
                notified.add(appid_str)
        else:
            print(f'  → [{name}] 中文：{"✅ 有" if has_chinese else "❌ 無"}')

        stored[appid_str] = {
            'name':         name,
            'has_chinese':  has_chinese,
            'last_checked': str(today),
        }

    time.sleep(1)

client.disconnect()

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
