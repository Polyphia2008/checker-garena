<?php
define('Minhnhatdev_DB_HOST', '127.0.0.1');
define('Minhnhatdev_DB_USER', 'checker');
define('Minhnhatdev_DB_PASS', 'Checker@2026');
define('Minhnhatdev_DB_NAME', 'checker_garena');
define('Minhnhatdev_DAILY_LIMIT', 100);
define('Minhnhatdev_BACKEND', '/home/user/webapp/backend/Minhnhatdev_api.py');
define('Minhnhatdev_PYTHON', '/usr/local/bin/python3');
define('Minhnhatdev_CHECK_TIMEOUT', 240);
define('Minhnhatdev_PROXY_FILE', '/home/user/webapp/backend/proxies.txt');
define('Minhnhatdev_PROXY_ENABLED', '/home/user/webapp/backend/proxy_enabled.flag');
define('Minhnhatdev_BULK_DIR', '/home/user/webapp/backend/bulk_jobs');

session_name('Minhnhatdev_sess');
if (session_status() === PHP_SESSION_NONE) {
    session_start();
}

date_default_timezone_set('Asia/Ho_Chi_Minh');

function Minhnhatdev_db(): PDO {
    static $pdo = null;
    if ($pdo === null) {
        $pdo = new PDO(
            'mysql:host=' . Minhnhatdev_DB_HOST . ';dbname=' . Minhnhatdev_DB_NAME . ';charset=utf8mb4',
            Minhnhatdev_DB_USER,
            Minhnhatdev_DB_PASS,
            [
                PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
                PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
                PDO::ATTR_EMULATE_PREPARES => false,
            ]
        );
    }
    return $pdo;
}

function Minhnhatdev_init_schema(PDO $pdo): void {
    $pdo->exec("CREATE TABLE IF NOT EXISTS users (
        id INT AUTO_INCREMENT PRIMARY KEY,
        username VARCHAR(50) NOT NULL UNIQUE,
        email VARCHAR(190) NOT NULL UNIQUE,
        password_hash VARCHAR(255) NOT NULL,
        role ENUM('user','admin') NOT NULL DEFAULT 'user',
        daily_quota INT NOT NULL DEFAULT 100,
        banned TINYINT(1) NOT NULL DEFAULT 0,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci");

    $pdo->exec("CREATE TABLE IF NOT EXISTS check_logs (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        account VARCHAR(190) NOT NULL,
        status VARCHAR(20) NOT NULL,
        result_line MEDIUMTEXT,
        tinh_trang VARCHAR(100) DEFAULT '',
        detail TEXT,
        ip VARCHAR(45) DEFAULT '',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_user_date (user_id, created_at),
        INDEX idx_created (created_at),
        INDEX idx_status (status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci");

    $stmt = $pdo->query("SELECT COUNT(*) AS c FROM users WHERE role='admin'");
    if ((int)$stmt->fetch()['c'] === 0) {
        $ins = $pdo->prepare("INSERT INTO users (username, email, password_hash, role, daily_quota) VALUES (?, ?, ?, 'admin', 100000)");
        $ins->execute(['admin', 'admin@minhnhatdev.local', password_hash('admin123', PASSWORD_DEFAULT)]);
    }
}

function Minhnhatdev_current_user(): ?array {
    if (empty($_SESSION['Minhnhatdev_uid'])) return null;
    static $cache = null;
    if ($cache !== null) return $cache;
    $pdo = Minhnhatdev_db();
    $stmt = $pdo->prepare("SELECT id, username, email, role, daily_quota, banned, created_at FROM users WHERE id = ? LIMIT 1");
    $stmt->execute([(int)$_SESSION['Minhnhatdev_uid']]);
    $u = $stmt->fetch();
    if (!$u) {
        unset($_SESSION['Minhnhatdev_uid']);
        return null;
    }
    $cache = $u;
    return $cache;
}

function Minhnhatdev_require_login(): array {
    $u = Minhnhatdev_current_user();
    if (!$u) {
        header('Location: /login.php');
        exit;
    }
    if ((int)$u['banned'] === 1) {
        session_destroy();
        header('Location: /login.php?err=' . urlencode('Tài khoản của bạn đã bị khóa.'));
        exit;
    }
    return $u;
}

function Minhnhatdev_require_admin(): array {
    $u = Minhnhatdev_require_login();
    if ($u['role'] !== 'admin') {
        http_response_code(403);
        header('Location: /index.php?err=' . urlencode('Bạn không có quyền truy cập trang này.'));
        exit;
    }
    return $u;
}

function Minhnhatdev_quota_used(int $userId): int {
    $pdo = Minhnhatdev_db();
    $stmt = $pdo->prepare("SELECT COUNT(*) AS c FROM check_logs WHERE user_id = ? AND DATE(created_at) = CURDATE()");
    $stmt->execute([$userId]);
    return (int)$stmt->fetch()['c'];
}

function Minhnhatdev_quota_remaining(array $user): int {
    $used = Minhnhatdev_quota_used((int)$user['id']);
    return max(0, (int)$user['daily_quota'] - $used);
}

function Minhnhatdev_csrf_token(): string {
    if (empty($_SESSION['Minhnhatdev_csrf'])) {
        $_SESSION['Minhnhatdev_csrf'] = bin2hex(random_bytes(32));
    }
    return $_SESSION['Minhnhatdev_csrf'];
}

function Minhnhatdev_csrf_field(): string {
    return '<input type="hidden" name="csrf" value="' . Minhnhatdev_csrf_token() . '">';
}

function Minhnhatdev_csrf_verify(): void {
    $t = $_POST['csrf'] ?? '';
    if (!$t || !hash_equals($_SESSION['Minhnhatdev_csrf'] ?? '', $t)) {
        http_response_code(419);
        exit('CSRF token không hợp lệ. Tải lại trang và thử lại.');
    }
}

function e(?string $s): string {
    return htmlspecialchars((string)$s, ENT_QUOTES, 'UTF-8');
}

function Minhnhatdev_proxy_count(): int {
    if (!is_file(Minhnhatdev_proxy_path())) return 0;
    $n = 0;
    foreach (file(Minhnhatdev_proxy_path(), FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) ?: [] as $line) {
        $line = trim($line);
        if ($line !== '' && $line[0] !== '#') $n++;
    }
    return $n;
}

function Minhnhatdev_proxy_path(): string {
    return Minhnhatdev_PROXY_FILE;
}

function Minhnhatdev_proxy_is_enabled(): bool {
    return is_file(Minhnhatdev_proxy_flag());
}

function Minhnhatdev_proxy_set_enabled(bool $on): void {
    $flag = Minhnhatdev_proxy_flag_path();
    if ($on) {
        @file_put_contents($flag, '1');
    } else {
        @unlink($flag);
    }
}

function Minhnhatdev_proxy_flag_path(): string {
    return Minhnhatdev_PROXY_ENABLED;
}

function Minhnhatdev_proxy_read(): string {
    return is_file(Minhnhatdev_proxy_path()) ? (string)file_get_contents(Minhnhatdev_proxy_path()) : '';
}

function Minhnhatdev_proxy_save(string $content): int {
    $lines = preg_split('/\r\n|\r|\n/', $content);
    $clean = [];
    foreach ($lines as $line) {
        $line = trim($line);
        if ($line === '' || $line[0] === '#') continue;
        $clean[] = $line;
    }
    @file_put_contents(Minhnhatdev_proxy_path(), implode("\n", $clean) . (count($clean) ? "\n" : ''));
    return count($clean);
}

function Minhnhatdev_proxy_active_file(): string {
    if (!Minhnhatdev_proxy_is_enabled()) return '';
    if (Minhnhatdev_proxy_count() <= 0) return '';
    return Minhnhatdev_proxy_path();
}
