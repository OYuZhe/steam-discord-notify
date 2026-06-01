# steam-discord-notify

監控 Steam 遊戲新增繁/簡體中文支援，自動推播通知到 Discord。

## 運作方式

- 每天透過 Steam PICS 協議取得當日有變動的遊戲清單
- 比對語系基準資料，偵測「之前無中文 → 現在有中文」的遊戲
- 符合條件者推播 Discord embed 通知（含評論數、好評率、支援語系）

## 初次設定

### 1. 設定 Repository Secrets

| Secret | 說明 |
|--------|------|
| `DISCORD_WEBHOOK` | Discord 頻道的 Webhook URL |

### 2. 建立語系基準資料（只需執行一次）

Actions → **建立語系基準資料** → Run workflow

執行完成後會自動將 `languages.json` commit 回 repo。

### 3. 啟用每日排程

每天 09:00（台灣時間）自動執行，無需額外設定。
也可到 Actions → **Steam 中文更新通知** → Run workflow 手動觸發。

## 檔案說明

| 檔案 | 說明 |
|------|------|
| `seed.py` | 首次建立語系基準，掃描 SteamSpy 全部遊戲 |
| `notify.py` | 每日排程，比對 PICS 變動並推播 Discord |
| `languages.json` | 各遊戲的語系狀態（由 Actions 自動更新） |
| `meta.json` | 上次執行的 PICS change number 與時間 |

## 推播條件

- 遊戲類型為 `game`（排除 DLC、工具等）
- 評論數 ≥ 20
- 語系從「無繁/簡體中文」變為「有繁/簡體中文」
