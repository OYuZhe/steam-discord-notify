"""
seed.py — 從 FronkonGames 資料集建立語系基準

資料來源：https://huggingface.co/datasets/FronkonGames/steam-games-dataset
截止日：2026-02-02（124,146 筆）

2026-02-02 之後新增中文的遊戲，只要該遊戲日後有任何 Store 更新，
notify.py 就會在當天偵測到並推播。
"""

import json
import re
from datetime import date
from pathlib import Path

import pandas as pd
import requests

DATA_FILE = Path(__file__).parent / 'languages.json'
PARQUET_URL = (
    'https://huggingface.co/datasets/FronkonGames/steam-games-dataset'
    '/resolve/main/data/train-00000-of-00001.parquet'
)
CHINESE_KEYS = {'Simplified Chinese', 'Traditional Chinese'}


def download_parquet(url: str, dest: Path) -> None:
    print('[INFO] 下載資料集...', flush=True)
    with requests.get(url, stream=True, timeout=180) as r:
        r.raise_for_status()
        total = int(r.headers.get('content-length', 0))
        downloaded = 0
        with dest.open('wb') as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    print(f'\r  {downloaded / total * 100:.1f}%  '
                          f'({downloaded >> 20} MB / {total >> 20} MB)',
                          end='', flush=True)
    print(flush=True)


def parse_langs(raw) -> set:
    if isinstance(raw, list):
        return {str(l).strip() for l in raw if l}
    if not isinstance(raw, str) or not raw.strip():
        return set()
    return {l.strip() for l in re.sub(r'<[^>]+>', '', raw).split(',')}


def main() -> None:
    parquet_path = Path(__file__).parent / '_games_tmp.parquet'
    try:
        download_parquet(PARQUET_URL, parquet_path)

        print('[INFO] 解析資料集...', flush=True)
        df = pd.read_parquet(parquet_path, columns=['appID', 'name', 'supported_languages'])
        print(f'[INFO] 共 {len(df):,} 筆', flush=True)

        stored = {}
        cutoff = '2026-02-02'
        for row in df.itertuples(index=False):
            appid_str = str(row.appID).strip()
            if not appid_str or appid_str == 'nan':
                continue
            langs = parse_langs(row.supported_languages)
            stored[appid_str] = {
                'name':         str(row.name) if isinstance(row.name, str) else f'App {appid_str}',
                'has_chinese':  bool(langs & CHINESE_KEYS),
                'last_checked': cutoff,
            }

        DATA_FILE.write_text(json.dumps(stored, indent=2, ensure_ascii=False), 'utf-8')
        print(f'[INFO] 基準建立完成，共記錄 {len(stored):,} 款遊戲 ✅', flush=True)

    finally:
        if parquet_path.exists():
            parquet_path.unlink()


if __name__ == '__main__':
    main()
