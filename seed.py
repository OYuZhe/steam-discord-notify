"""
seed.py — 從 FronkonGames 資料集建立語系基準

資料來源：https://huggingface.co/datasets/FronkonGames/steam-games-dataset
截止日：2026-02-02（124,146 筆）

2026-02-02 之後新增中文的遊戲，只要該遊戲日後有任何 Store 更新，
notify.py 就會在當天偵測到並推播。

授權：CC BY 4.0 — https://huggingface.co/datasets/FronkonGames/steam-games-dataset
"""

import json
import re
from pathlib import Path

from datasets import load_dataset

DATA_FILE = Path(__file__).parent / 'languages.json'
CHINESE_KEYS = {'Simplified Chinese', 'Traditional Chinese'}


def parse_langs(raw) -> set:
    if isinstance(raw, list):
        return {str(l).strip() for l in raw if l}
    if not isinstance(raw, str) or not raw.strip():
        return set()
    # JSON 字串格式：'["English", "Simplified Chinese"]'
    if raw.strip().startswith('['):
        try:
            parsed = json.loads(raw)
            return {str(l).strip() for l in parsed if l}
        except Exception:
            pass
    # 逗號分隔字串（Store API 回傳，含 HTML tag）
    return {l.strip() for l in re.sub(r'<[^>]+>', '', raw).split(',')}


def main() -> None:
    print('[INFO] 載入資料集（FronkonGames/steam-games-dataset）...', flush=True)
    ds = load_dataset('FronkonGames/steam-games-dataset', split='train')
    print(f'[INFO] 共 {len(ds):,} 筆', flush=True)

    stored = {}
    cutoff = '2026-02-02'
    for row in ds:
        appid_str = str(row.get('appID', '')).strip()
        if not appid_str or appid_str == 'nan':
            continue
        langs = parse_langs(row.get('supported_languages', ''))
        stored[appid_str] = {
            'name':         row.get('name') or f'App {appid_str}',
            'has_chinese':  bool(langs & CHINESE_KEYS),
            'last_checked': cutoff,
        }

    DATA_FILE.write_text(json.dumps(stored, indent=2, ensure_ascii=False), 'utf-8')
    print(f'[INFO] 基準建立完成，共記錄 {len(stored):,} 款遊戲 ✅', flush=True)


if __name__ == '__main__':
    main()
