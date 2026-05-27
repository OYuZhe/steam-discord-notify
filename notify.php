<?php

echo "STEP 1 - PHP START\n";

$webhook = getenv('DISCORD_WEBHOOK');

echo "WEBHOOK:\n";
var_dump(getenv('DISCORD_WEBHOOK'));

if (!$webhook) {
    exit('Webhook not found');
}

$data = [
    'content' => 'GitHub Actions 測試成功'
];

$ch = curl_init($webhook);

curl_setopt_array($ch, [
    CURLOPT_POST => true,
    CURLOPT_POSTFIELDS => json_encode($data),
    CURLOPT_HTTPHEADER => [
        'Content-Type: application/json'
    ],
    CURLOPT_RETURNTRANSFER => true
]);

$result = curl_exec($ch);

curl_close($ch);

echo $result;
