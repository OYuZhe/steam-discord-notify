# steam-discord-notify

Steam 遊戲 Discord 通知機器人，提供兩種功能：

1. **每日中文更新通知**：自動偵測新增繁/簡體中文支援的遊戲並推播
2. **熱門遊戲推播**：手動觸發，依三種模式推播當前熱門遊戲清單

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

每天 06:00（台灣時間）自動執行，無需額外設定。
也可到 Actions → **Steam 中文更新通知** → Run workflow 手動觸發。

---

## 功能一：每日中文更新通知（notify.py）

### 運作方式

1. 透過 `IStoreService/GetAppList` 取得自上次執行以來有變動的遊戲清單
2. 逐一查詢 Steam Store API，比對語系是否從「無中文 → 有中文」
3. 符合條件者推播 Discord embed 通知（含評論數、好評率、支援語系）

### 推播條件

- 遊戲類型為 `game`（排除 DLC、音樂、Demo、Mod 等）
- 尚未發售（`coming_soon`）的遊戲略過，待正式上市後偵測
- 評論數 ≥ 20
- 語系從「無繁/簡體中文」變為「有繁/簡體中文」

---

## 功能二：熱門遊戲推播（trending.py）

Actions → **Steam 熱門中文遊戲推播** → Run workflow

### 參數

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `mode` | `Trending` | 篩選模式（見下方） |
| `page` | `1` | 分頁，每頁 10 款 |
| `month` | 留空 | 僅 Rising 模式有效，格式 `YYYY-MM`，留空表示當月 |

### 模式說明

| 模式 | 來源 | 說明 |
|------|------|------|
| `Trending` | Steam `popularnew` | Steam 官方「新品與熱門」清單 |
| `Hot` | `ISteamChartsService/GetMostPlayedGames` | 當前同時在線人數排行 |
| `Rising` | `ISteamChartsService/GetMonthTopAppReleases` | 當月 Top Releases，依評論增長速度（則/天）排序，自動排除 F2P、MMO、Battle Royale |

### Rising 模式細節

- 來源為 Steam 官方當月新作排行（Platinum / Gold / Silver 三級）
- 以「評論數 ÷ 上架天數」計算竄升速度，過濾上架超過 90 天的遊戲
- 指定月份：填入 `month` 參數（例如 `2026-05`）；留空時優先查當月，不足 10 筆自動補上個月

---

## 檔案說明

| 檔案 | 說明 |
|------|------|
| `seed.py` | 首次建立語系基準，從 HuggingFace 資料集載入 |
| `notify.py` | 每日排程，查詢有變動的遊戲並推播 Discord |
| `trending.py` | 手動觸發，依模式取得熱門遊戲並推播 Discord |
| `requirements.txt` | 相依套件（`requests`） |
| `requirements-seed.txt` | `seed.py` 相依套件（`requests`、`datasets`） |
| `languages.json` | 各遊戲的語系狀態（由 Actions 自動維護） |
| `meta.json` | 上次執行時間戳記，用於增量查詢 |
