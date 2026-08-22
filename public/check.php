<?php
require_once __DIR__ . '/Minhnhatdev_config.php';

header('Content-Type: application/json; charset=utf-8');
set_time_limit(Minhnhatdev_CHECK_TIMEOUT + 30);
set_time_limit(Minhnhatdev_CHECK_TIMEOUT + 30);

function Minhnhatdev_json(array $d): void {
    echo json_encode($d, JSON_UNESCAPED_UNICODE);
    exit;
}

$user = Minhnhatdev_current_user();
if (!$user) {
    Minhnhatdev_json(['ok' => false, 'status' => 'AUTH', 'detail' => 'Bạn cần đăng nhập để sử dụng chức năng này.']);
}
if ((int)$user['banned'] === 1) {
    Minhnhatdev_json(['ok' => false, 'status' => 'BANNED', 'detail' => 'Tài khoản của bạn đã bị khóa.']);
}
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    Minhnhatdev_json(['ok' => false, 'status' => 'ERROR', 'detail' => 'Method không hợp lệ.']);
}
Minhnhatdev_csrf_verify();

$account = trim((string)($_POST['account'] ?? ''));
$password = (string)($_POST['password'] ?? '');

if ($account === '' || $password === '') {
    Minhnhatdev_json(['ok' => false, 'status' => 'ERROR', 'detail' => 'Vui lòng nhập đầy đủ tài khoản và mật khẩu.']);
}
if (strlen($account) > 190 || strlen($password) > 190) {
    Minhnhatdev_json(['ok' => false, 'status' => 'ERROR', 'detail' => 'Dữ liệu nhập quá dài.']);
}

$pdo = Minhnhatdev_db();
Minhnhatdev_init_schema($pdo);

$used = Minhnhatdev_quota_used((int)$user['id']);
$quota = (int)$user['daily_quota'];
$remaining = max(0, $quota - $used);

if ($remaining <= 0) {
    Minhnhatdev_json([
        'ok' => false,
        'status' => 'QUOTA',
        'detail' => "Bạn đã dùng hết {$quota} lượt check hôm nay. Vui lòng quay lại vào ngày mai.",
        'remaining' => 0,
        'quota' => $quota,
    ]);
}

$cmd = escapeshellarg(MinhNhatdev_PYTHON) . ' ' . escapeshellarg(MinhNhatdev_BACKEND)
    . ' ' . escapeshellarg($account) . ' ' . escapeshellarg($password);
$cmd = 'cd ' . escapeshellarg(dirname(MinhNhatdev_BACKEND)) . ' && timeout ' . Minhnhatdev_CHECK_TIMEOUT . ' ' . $cmd . ' 2>/dev/null';

$raw = shell_exec($cmd);
$raw = trim((string)$raw);

$result = null;
if ($raw !== '') {
    $decoded = json_decode($raw, true);
    if (is_array($decoded)) {
        $result = $decoded;
    }
}

if ($result === null) {
    $result = ['ok' => false, 'status' => 'ERROR', 'detail' => 'Backend không phản hồi hoặc quá thời gian chờ (' . Minhnhatdev_CHECK_TIMEOUT . 's). Thử lại sau.', 'line' => '', 'tinh_trang' => ''];
}

$status = strtoupper((string)($result['status'] ?? 'ERROR'));
$line = (string)($result['line'] ?? '');
$tinhTrang = (string)($result['tinh_trang'] ?? '');
$detail = (string)($result['detail'] ?? '');

$log = $pdo->prepare("INSERT INTO check_logs (user_id, account, status, result_line, tinh_trang, detail, ip) VALUES (?, ?, ?, ?, ?, ?, ?)");
$log->execute([
    (int)$user['id'],
    $account,
    $status,
    $line,
    $tinhTrang,
    $detail,
    (string)($_SERVER['REMOTE_ADDR'] ?? ''),
]);

$remainingAfter = max(0, $remaining - 1);

Minhnhatdev_json([
    'ok' => (bool)($result['ok'] ?? false),
    'status' => $status,
    'detail' => $detail,
    'line' => $line,
    'tinh_trang' => $tinhTrang,
    'account' => $account,
    'remaining' => $remainingAfter,
    'quota' => $quota,
]);
