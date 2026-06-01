# steam-discord-notify

監控 Steam 遊戲新增繁/簡體中文支援，自動推播通知到 Discord。

## 運作方式

1. 每天透過 `IStoreService/GetAppList` 取得自上次執行以來有變動的遊戲清單
2. 逐一查詢 Steam Store API，比對語系是否從「無中文 → 有中文」
3. 符合條件者推播 Discord embed 通知（含評論數、好評率、支援語系）

## 初次設定

### 1. 設定 Repository Secrets

| Secret | 說明 |
|--------|------|
| `DISCORD_WEBHOOK` | Discord 頻道的 Webhook URL |
| `STEAM_API_KEY` | Steam Web API 金鑰（取得：steamcommunity.com/dev/apikey） |

### 2. 建立語系基準資料（只需執行一次）

Actions → **建立語系基準資料** → Run workflow

從 [FronkonGames/steam-games-dataset](https://huggingface.co/datasets/FronkonGames/steam-games-dataset)（CC BY 4.0）載入約 124,146 筆遊戲語系紀錄，執行完成後自動將 `languages.json` commit 回 repo。

> 資料集涵蓋至 2026-02-02，之後新發售的遊戲在首次有 Store 更新時會被 `notify.py` 補上。

### 3. 啟用每日排程

每天 09:00（台灣時間）自動執行，無需額外設定。
也可到 Actions → **Steam 中文更新通知** → Run workflow 手動觸發。

## 檔案說明

| 檔案 | 說明 |
|------|------|
| `seed.py` | 首次建立語系基準，從 HuggingFace 資料集載入 |
| `notify.py` | 每日排程，查詢有變動的遊戲並推播 Discord |
| `requirements.txt` | `notify.py` 相依套件（`requests`） |
| `requirements-seed.txt` | `seed.py` 相依套件（`requests`、`datasets`） |
| `languages.json` | 各遊戲的語系狀態（由 Actions 自動維護） |
| `meta.json` | 上次執行時間戳記，用於增量查詢 |

## 推播條件

- 遊戲類型為 `game`（排除 DLC、音樂、Demo、Mod 等）
- 尚未發售（`coming_soon`）的遊戲略過，待正式上市後偵測
- 評論數 ≥ 20
- 語系從「無繁/簡體中文」變為「有繁/簡體中文」
