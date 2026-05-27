<?php

// ===== 設定 =====
$webhook     = getenv('DISCORD_WEBHOOK');
$minReviews  = 50;
$seedPages   = 10;       // 首次執行：掃描 SteamSpy 前 10 頁（共約 10,000 款遊戲）
$dataFile    = 'languages.json';
$metaFile    = 'meta.json';
$chineseKeys = ['Simplified Chinese', 'Traditional Chinese'];

if (!$webhook) {
    exit('[ERROR] DISCORD_WEBHOOK 未設定' . PHP_EOL);
}

// ===== 讀取 meta & 語系資料 =====
$meta   = file_exists($metaFile) ? (json_decode(file_get_contents($metaFile), true) ?? []) : [];
$stored = file_exists($dataFile) ? (json_decode(file_get_contents($dataFile), true) ?? []) : [];

$lastChangeNumber = (int)($meta['last_change_number'] ?? 0);
$isFirstRun       = ($lastChangeNumber === 0);

// ===== 取得目前 Steam change number =====
echo '[INFO] 查詢 Steam GetAppChanges...' . PHP_EOL;
$changesRaw = @file_get_contents("https://api.steampowered.com/ISteamApps/GetAppChanges/v1/?changeNumber={$lastChangeNumber}");

if (!$changesRaw) {
    exit('[ERROR] 無法連接 Steam API' . PHP_EOL);
}

$changesData         = json_decode($changesRaw, true);
$currentChangeNumber = (int)($changesData['current_change_number'] ?? $lastChangeNumber);
$changedApps         = $changesData['appchanges'] ?? [];
$forceFullUpdate     = !empty($changesData['force_full_update']);

echo "[INFO] change number：{$lastChangeNumber} → {$currentChangeNumber}" . PHP_EOL;

// 立即儲存最新 change number
$meta['last_change_number'] = $currentChangeNumber;
$meta['last_run']           = date('Y-m-d H:i:s');
file_put_contents($metaFile, json_encode($meta, JSON_PRETTY_PRINT));

// =========================================================
// 首次執行：用 SteamSpy 掃描前 10,000 款遊戲建立基準
// =========================================================
if ($isFirstRun || $forceFullUpdate) {
    echo '[INFO] 首次執行，掃描 SteamSpy 前 ' . ($seedPages * 1000) . ' 款遊戲建立基準...' . PHP_EOL;
    echo '[INFO] 本次不推播，僅記錄各遊戲目前語系狀態' . PHP_EOL;

    // 抓 SteamSpy 多頁
    $allGames = [];
    for ($page = 0; $page < $seedPages; $page++) {
        echo '[INFO] 取得 SteamSpy 第 ' . ($page + 1) . "/{$seedPages} 頁..." . PHP_EOL;

        $raw = @file_get_contents("https://steamspy.com/api.php?request=all&page={$page}");
        if (!$raw) {
            echo "[WARN] 第 {$page} 頁取得失敗，停止翻頁" . PHP_EOL;
            break;
        }

        $games = json_decode($raw, true);
        if (empty($games)) {
            echo '[INFO] 已無更多資料' . PHP_EOL;
            break;
        }

        $allGames = array_merge($allGames, $games);
        sleep(2);
    }

    // 過濾評論數
    $filtered = array_filter($allGames, fn($g) => ($g['positive'] + $g['negative']) > $minReviews);
    echo '[INFO] 評論數 > ' . $minReviews . ' 的遊戲：' . count($filtered) . ' 款' . PHP_EOL;
    echo '[INFO] 預計需要約 ' . round(count($filtered) * 0.5 / 60) . ' 分鐘...' . PHP_EOL;

    $i     = 0;
    $total = count($filtered);

    foreach ($filtered as $game) {
        $appid = (string)$game['appid'];
        $i++;

        // 已有記錄則跳過（避免重複查詢）
        if (isset($stored[$appid])) {
            continue;
        }

        echo "[{$i}/{$total}] {$game['name']} ({$appid})" . PHP_EOL;

        $raw = @file_get_contents("https://store.steampowered.com/api/appdetails?appids={$appid}&filters=supported_languages");
        if (!$raw) {
            usleep(500000);
            continue;
        }

        $data = json_decode($raw, true);
        if (empty($data[$appid]['success'])) {
            usleep(500000);
            continue;
        }

        $languages  = $data[$appid]['data']['supported_languages'] ?? '';
        $hasChinese = false;
        foreach ($chineseKeys as $key) {
            if (stripos($languages, $key) !== false) {
                $hasChinese = true;
                break;
            }
        }

        $stored[$appid] = [
            'name'         => $game['name'],
            'has_chinese'  => $hasChinese,
            'last_checked' => date('Y-m-d'),
        ];

        echo '  → 中文：' . ($hasChinese ? '✅ 有' : '❌ 無') . PHP_EOL;

        // 每 100 筆存一次，避免中途失敗全部遺失
        if ($i % 100 === 0) {
            file_put_contents($dataFile, json_encode($stored, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE));
            echo "[INFO] 進度儲存（{$i}/{$total}）" . PHP_EOL;
        }

        usleep(500000);
    }

    file_put_contents($dataFile, json_encode($stored, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE));
    echo '[INFO] 基準建立完成，共記錄 ' . count($stored) . ' 款遊戲' . PHP_EOL;
    echo '[INFO] 下次執行開始正式追蹤新增中文的遊戲 ✅' . PHP_EOL;
    exit(0);
}

// =========================================================
// 後續執行：用 GetAppChanges 追蹤有更新的遊戲
// =========================================================
echo '[INFO] 有變動的 App：' . count($changedApps) . ' 個' . PHP_EOL;

if (empty($changedApps)) {
    echo '[INFO] 本次無任何 App 更新' . PHP_EOL;
    exit(0);
}

$newChineseList = [];
$i     = 0;
$total = count($changedApps);

foreach ($changedApps as $appid => $changeData) {
    $appid = (string)$appid;
    $i++;

    // 已確認有中文 → 不需要再查
    if (isset($stored[$appid]) && ($stored[$appid]['has_chinese'] ?? false)) {
        continue;
    }

    echo "[{$i}/{$total}] 查詢 App {$appid}..." . PHP_EOL;

    $raw = @file_get_contents("https://store.steampowered.com/api/appdetails?appids={$appid}");
    if (!$raw) {
        usleep(500000);
        continue;
    }

    $data = json_decode($raw, true);
    if (empty($data[$appid]['success'])) {
        usleep(500000);
        continue;
    }

    $appData = $data[$appid]['data'];
    $type    = $appData['type'] ?? '';
    $name    = $appData['name'] ?? "App {$appid}";

    // 只處理遊戲本體（排除 DLC、音樂、工具等）
    if ($type !== 'game') {
        echo "  → [{$name}] 非遊戲（{$type}），跳過" . PHP_EOL;
        usleep(300000);
        continue;
    }

    // 評論數過濾
    $totalReviews = $appData['recommendations']['total'] ?? 0;
    if ($totalReviews < $minReviews) {
        echo "  → [{$name}] 評論數 {$totalReviews} < {$minReviews}，跳過" . PHP_EOL;
        usleep(300000);
        continue;
    }

    // 語系判斷
    $languages  = $appData['supported_languages'] ?? '';
    $hasChinese = false;
    foreach ($chineseKeys as $key) {
        if (stripos($languages, $key) !== false) {
            $hasChinese = true;
            break;
        }
    }

    $wasTracked = isset($stored[$appid]);
    $hadChinese = $wasTracked && ($stored[$appid]['has_chinese'] ?? false);

    if ($hasChinese && $wasTracked && !$hadChinese) {
        // 有基準記錄 + 之前沒中文 + 現在有 → 確定是新增！
        echo "  → 🎉 [{$name}] 新增中文支援！" . PHP_EOL;

        $reviewRaw  = @file_get_contents("https://store.steampowered.com/appreviews/{$appid}?json=1&language=all&purchase_type=all");
        $reviewData = $reviewRaw ? (json_decode($reviewRaw, true)['query_summary'] ?? []) : [];

        $newChineseList[] = [
            'appid'    => $appid,
            'name'     => $name,
            'languages'=> strip_tags($languages),
            'positive' => $reviewData['total_positive'] ?? 0,
            'negative' => $reviewData['total_negative'] ?? 0,
            'total'    => $totalReviews,
        ];
    } elseif ($hasChinese && !$wasTracked) {
        echo "  → [{$name}] 首次記錄（有中文），存入基準" . PHP_EOL;
    } else {
        echo "  → [{$name}] 中文：" . ($hasChinese ? '✅ 有' : '❌ 無') . "（評論：{$totalReviews}）" . PHP_EOL;
    }

    $stored[$appid] = [
        'name'         => $name,
        'has_chinese'  => $hasChinese,
        'last_checked' => date('Y-m-d'),
    ];

    usleep(500000);
}

// ===== 儲存語系資料 =====
file_put_contents($dataFile, json_encode($stored, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE));
echo '[INFO] languages.json 已更新，共記錄 ' . count($stored) . ' 款遊戲' . PHP_EOL;

// ===== 推播 Discord =====
if (empty($newChineseList)) {
    echo '[INFO] 本次無新增中文的遊戲' . PHP_EOL;
    exit(0);
}

echo '[INFO] 推播 ' . count($newChineseList) . ' 款遊戲到 Discord...' . PHP_EOL;

foreach ($newChineseList as $game) {
    $total = $game['positive'] + $game['negative'];
    $rate  = $total > 0 ? round($game['positive'] / $total * 100) : 0;

    $payload = [
        'embeds' => [[
            'title'     => "🎮 新增中文支援：{$game['name']}",
            'url'       => "https://store.steampowered.com/app/{$game['appid']}/",
            'color'     => 5763719,
            'fields'    => [
                [
                    'name'   => '📊 評論',
                    'value'  => "👍 {$game['positive']}  👎 {$game['negative']}（好評率 {$rate}%）",
                    'inline' => false,
                ],
                [
                    'name'   => '🌐 支援語系',
                    'value'  => mb_substr($game['languages'], 0, 1024),
                    'inline' => false,
                ],
            ],
            'timestamp' => date('c'),
        ]],
    ];

    $ch = curl_init($webhook);
    curl_setopt_array($ch, [
        CURLOPT_POST           => true,
        CURLOPT_POSTFIELDS     => json_encode($payload, JSON_UNESCAPED_UNICODE),
        CURLOPT_HTTPHEADER     => ['Content-Type: application/json'],
        CURLOPT_RETURNTRANSFER => true,
    ]);
    curl_exec($ch);
    curl_close($ch);

    echo "[NOTIFY] 已推播：{$game['name']}" . PHP_EOL;
    sleep(1);
}
