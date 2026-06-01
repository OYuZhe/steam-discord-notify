<?php

error_reporting(E_ALL);
ini_set('display_errors', 1);

// ===== 設定 =====
$webhook     = trim(getenv('DISCORD_WEBHOOK') ?: '');
$steamApiKey = trim(getenv('STEAM_API_KEY') ?: '');
$minReviews  = 50;
$seedPages   = 10;
$dataFile    = __DIR__ . '/languages.json';
$metaFile    = __DIR__ . '/meta.json';
$chineseKeys = ['Simplified Chinese', 'Traditional Chinese'];

if (!$webhook)     exit('[ERROR] DISCORD_WEBHOOK 未設定' . PHP_EOL);
if (!$steamApiKey) exit('[ERROR] STEAM_API_KEY 未設定' . PHP_EOL);

// ===== HTTP 工具函式（curl，含逾時與狀態碼檢查）=====
function httpGet(string $url, int $timeout = 15): ?string {
    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT        => $timeout,
        CURLOPT_FOLLOWLOCATION => true,
        CURLOPT_USERAGENT      => 'Mozilla/5.0 (compatible; SteamChineseNotifier/1.0)',
    ]);
    $result = curl_exec($ch);
    $code   = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $error  = curl_error($ch);
    curl_close($ch);

    if ($error) {
        echo "[WARN] curl 錯誤：{$error}" . PHP_EOL;
        return null;
    }
    if ($code !== 200) {
        echo "[WARN] HTTP {$code}：{$url}" . PHP_EOL;
        return null;
    }
    return $result ?: null;
}

// ===== 讀取 meta & 語系資料 =====
$meta   = file_exists($metaFile) ? (json_decode(file_get_contents($metaFile), true) ?? []) : [];
$stored = file_exists($dataFile) ? (json_decode(file_get_contents($dataFile), true) ?? []) : [];

// 確保檔案一定存在（讓 git add 不會報錯）
if (!file_exists($dataFile)) file_put_contents($dataFile, '{}');
if (!file_exists($metaFile)) file_put_contents($metaFile, '{}');

$lastChangeNumber = (int)($meta['last_change_number'] ?? 0);
$isFirstRun       = ($lastChangeNumber === 0);

// ===== 取得 Steam change number =====
echo '[INFO] 查詢 Steam GetAppChanges...' . PHP_EOL;
$changesRaw = httpGet(
    "https://api.steampowered.com/ISteamApps/GetAppChanges/v2/?changeNumber={$lastChangeNumber}&key={$steamApiKey}"
);

if (!$changesRaw) {
    exit('[ERROR] 無法連接 Steam GetAppChanges API，請確認 STEAM_API_KEY 是否正確' . PHP_EOL);
}

$changesData = json_decode($changesRaw, true);
if ($changesData === null) {
    exit('[ERROR] Steam API 回傳無效 JSON：' . $changesRaw . PHP_EOL);
}

$currentChangeNumber = (int)($changesData['current_change_number'] ?? $lastChangeNumber);
$forceFullUpdate     = !empty($changesData['force_full_update']);

// GetAppChanges 可能回傳 object 或 array，統一處理
$rawChangedApps = $changesData['appchanges'] ?? [];
$changedApps    = [];
if (is_array($rawChangedApps)) {
    foreach ($rawChangedApps as $key => $val) {
        // object 格式：{"570": {...}}  或  array 格式：[{"appid":570,...}]
        $appid = is_numeric($key) && isset($val['appid']) ? (string)$val['appid'] : (string)$key;
        $changedApps[$appid] = $val;
    }
}

echo "[INFO] change number：{$lastChangeNumber} → {$currentChangeNumber}" . PHP_EOL;
echo '[INFO] 有變動 App：' . count($changedApps) . ' 個' . PHP_EOL;

// 立即儲存最新 change number
$meta['last_change_number'] = $currentChangeNumber;
$meta['last_run']           = date('Y-m-d H:i:s');
file_put_contents($metaFile, json_encode($meta, JSON_PRETTY_PRINT));

// =========================================================
// 首次執行：用 SteamSpy 掃描前 10,000 款遊戲建立基準
// =========================================================
if ($isFirstRun || $forceFullUpdate) {
    echo '[INFO] 首次執行，掃描 SteamSpy 前 ' . ($seedPages * 1000) . ' 款遊戲...' . PHP_EOL;
    echo '[INFO] 本次不推播，僅建立基準資料' . PHP_EOL;

    $allGames = [];
    for ($page = 0; $page < $seedPages; $page++) {
        echo '[INFO] SteamSpy 第 ' . ($page + 1) . "/{$seedPages} 頁..." . PHP_EOL;

        $raw = httpGet("https://steamspy.com/api.php?request=all&page={$page}", 20);
        if (!$raw) {
            echo "[WARN] 第 {$page} 頁取得失敗，停止翻頁" . PHP_EOL;
            break;
        }

        $games = json_decode($raw, true);
        if (!is_array($games) || empty($games)) {
            echo '[INFO] 已無更多資料' . PHP_EOL;
            break;
        }

        $allGames = array_merge($allGames, $games);
        sleep(2);
    }

    $filtered = array_filter($allGames, function ($g) use ($minReviews) {
        return isset($g['positive'], $g['negative'])
            && ($g['positive'] + $g['negative']) > $minReviews;
    });

    echo '[INFO] 評論數 > ' . $minReviews . ' 的遊戲：' . count($filtered) . ' 款' . PHP_EOL;
    echo '[INFO] 預計需要約 ' . round(count($filtered) * 0.5 / 60) . ' 分鐘...' . PHP_EOL;

    $i = 0; $total = count($filtered);
    foreach ($filtered as $game) {
        if (!isset($game['appid'])) continue;
        $appid = (string)$game['appid'];
        $i++;

        if (isset($stored[$appid])) continue;

        echo "[{$i}/{$total}] {$game['name']} ({$appid})" . PHP_EOL;

        $raw = httpGet("https://store.steampowered.com/api/appdetails?appids={$appid}&filters=supported_languages");
        if (!$raw) { usleep(500000); continue; }

        $data = json_decode($raw, true);
        if (!is_array($data) || empty($data[$appid]['success'])) { usleep(500000); continue; }

        $languages  = $data[$appid]['data']['supported_languages'] ?? '';
        $hasChinese = false;
        foreach ($chineseKeys as $key) {
            if (stripos($languages, $key) !== false) { $hasChinese = true; break; }
        }

        $stored[$appid] = [
            'name'         => $game['name'] ?? "App {$appid}",
            'has_chinese'  => $hasChinese,
            'last_checked' => date('Y-m-d'),
        ];

        echo '  → 中文：' . ($hasChinese ? '✅ 有' : '❌ 無') . PHP_EOL;

        if ($i % 100 === 0) {
            file_put_contents($dataFile, json_encode($stored, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE));
            echo "[INFO] 進度儲存（{$i}/{$total}）" . PHP_EOL;
        }

        usleep(500000);
    }

    file_put_contents($dataFile, json_encode($stored, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE));
    echo '[INFO] 基準建立完成，共記錄 ' . count($stored) . ' 款遊戲 ✅' . PHP_EOL;
    exit(0);
}

// =========================================================
// 後續執行：追蹤有更新的遊戲
// =========================================================
if (empty($changedApps)) {
    echo '[INFO] 本次無任何 App 更新' . PHP_EOL;
    exit(0);
}

$newChineseList = [];
$notified       = [];   // 防止同一遊戲重複推播
$i = 0; $total = count($changedApps);

foreach ($changedApps as $appid => $changeData) {
    $appid = (string)$appid;
    $i++;

    if (isset($stored[$appid]) && ($stored[$appid]['has_chinese'] ?? false)) continue;

    echo "[{$i}/{$total}] 查詢 App {$appid}..." . PHP_EOL;

    $raw = httpGet("https://store.steampowered.com/api/appdetails?appids={$appid}");
    if (!$raw) { usleep(500000); continue; }

    $data = json_decode($raw, true);
    if (!is_array($data) || empty($data[$appid]['success'])) { usleep(500000); continue; }

    $appData = $data[$appid]['data'] ?? [];
    if (empty($appData)) { usleep(300000); continue; }

    $type = $appData['type'] ?? '';
    $name = $appData['name'] ?? "App {$appid}";

    if ($type !== 'game') {
        echo "  → [{$name}] 非遊戲（{$type}），跳過" . PHP_EOL;
        usleep(300000);
        continue;
    }

    $totalReviews = $appData['recommendations']['total'] ?? 0;
    if ($totalReviews < $minReviews) {
        echo "  → [{$name}] 評論數 {$totalReviews} < {$minReviews}，跳過" . PHP_EOL;
        usleep(300000);
        continue;
    }

    $languages  = $appData['supported_languages'] ?? '';
    $hasChinese = false;
    foreach ($chineseKeys as $key) {
        if (stripos($languages, $key) !== false) { $hasChinese = true; break; }
    }

    $wasTracked = isset($stored[$appid]);
    $hadChinese = $wasTracked && ($stored[$appid]['has_chinese'] ?? false);

    if ($hasChinese && $wasTracked && !$hadChinese && !isset($notified[$appid])) {
        echo "  → 🎉 [{$name}] 新增中文支援！" . PHP_EOL;

        $reviewRaw  = httpGet("https://store.steampowered.com/appreviews/{$appid}?json=1&language=all&purchase_type=all");
        $reviewJson = $reviewRaw ? json_decode($reviewRaw, true) : null;
        $reviewData = is_array($reviewJson) ? ($reviewJson['query_summary'] ?? []) : [];

        $newChineseList[] = [
            'appid'    => $appid,
            'name'     => $name,
            'languages'=> strip_tags($languages),
            'positive' => (int)($reviewData['total_positive'] ?? 0),
            'negative' => (int)($reviewData['total_negative'] ?? 0),
            'total'    => $totalReviews,
        ];
        $notified[$appid] = true;
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

file_put_contents($dataFile, json_encode($stored, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE));
echo '[INFO] languages.json 已更新，共記錄 ' . count($stored) . ' 款遊戲' . PHP_EOL;

// ===== 推播 Discord =====
if (empty($newChineseList)) {
    echo '[INFO] 本次無新增中文的遊戲' . PHP_EOL;
    exit(0);
}

echo '[INFO] 推播 ' . count($newChineseList) . ' 款遊戲到 Discord...' . PHP_EOL;

foreach ($newChineseList as $game) {
    $reviewTotal = $game['positive'] + $game['negative'];
    $rate        = $reviewTotal > 0 ? round($game['positive'] / $reviewTotal * 100) : 0;
    $langText    = mb_substr($game['languages'], 0, 1000);  // Discord field 上限 1024

    $payload = [
        'embeds' => [[
            'title'     => mb_substr("🎮 新增中文支援：{$game['name']}", 0, 256),
            'url'       => "https://store.steampowered.com/app/{$game['appid']}/",
            'color'     => 5763719,
            'fields'    => [
                ['name' => '📊 評論', 'value' => "👍 {$game['positive']}  👎 {$game['negative']}（好評率 {$rate}%）", 'inline' => false],
                ['name' => '🌐 支援語系', 'value' => $langText ?: '（無資料）', 'inline' => false],
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
        CURLOPT_TIMEOUT        => 10,
    ]);
    $response = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);

    if ($httpCode === 429) {
        echo "[WARN] Discord 速率限制，等待 5 秒..." . PHP_EOL;
        sleep(5);
    } elseif ($httpCode >= 400) {
        echo "[WARN] Discord 推播失敗（HTTP {$httpCode}）：{$game['name']}" . PHP_EOL;
    } else {
        echo "[NOTIFY] 已推播：{$game['name']}" . PHP_EOL;
    }

    sleep(2);
}
