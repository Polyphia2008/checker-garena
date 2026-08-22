<?php
require_once __DIR__ . '/Minhnhatdev_layout.php';

$Minhnhatdev_err = trim((string)($_GET['err'] ?? ''));

if (Minhnhatdev_current_user()) {
    header('Location: /index.php');
    exit;
}

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    Minhnhatdev_csrf_verify();
    $username = trim($_POST['username'] ?? '');
    $password = (string)($_POST['password'] ?? '');

    $pdo = Minhnhatdev_db();
    Minhnhatdev_init_schema($pdo);
    $stmt = $pdo->prepare("SELECT id, username, password_hash, role, banned FROM users WHERE username = ? OR email = ? LIMIT 1");
    $stmt->execute([$username, $username]);
    $u = $stmt->fetch();

    if (!$u || !password_verify($password, $u['password_hash'])) {
        $Minhnhatdev_err = 'Sai tên đăng nhập hoặc mật khẩu.';
    } elseif ((int)$u['banned'] === 1) {
        $Minhnhatdev_err = 'Tài khoản của bạn đã bị khóa bởi quản trị viên.';
    } else {
        session_regenerate_id(true);
        $_SESSION['Minhnhatdev_uid'] = (int)$u['id'];
        header('Location: /index.php');
        exit;
    }
}

Minhnhatdev_page_head('Đăng Nhập');
?>
<div class="card-verify" style="max-width: 460px;">
  <div style="text-align: center; margin-bottom: 26px;">
    <div style="display: inline-flex; align-items: center; justify-content: center; padding: 16px; background-color: rgba(59,130,246,.08); border-radius: 20px; margin-bottom: 14px; color: #3b82f6; box-shadow: 0 10px 20px -5px rgba(59,130,246,.2);">
      <i class="ki-filled ki-user" style="display: block; font-size: 2rem; line-height: 1;"></i>
    </div>
    <h3 style="font-weight: 800; color: #0f172a; margin: 0 0 6px 0; font-size: 20px;">Đăng Nhập Hệ Thống</h3>
    <p style="color: #64748b; font-size: 13px; margin: 0;">Đăng nhập để bắt đầu check tài khoản Garena</p>
  </div>

  <?php if ($Minhnhatdev_err): ?><div class="Minhnhatdev-alert Minhnhatdev-alert-err"><i class="ki-filled ki-information-2"></i> <?= e($Minhnhatdev_err) ?></div><?php endif; ?>

  <form method="post" action="/login.php">
    <?= Minhnhatdev_csrf_field() ?>
    <div style="margin-bottom: 14px;">
      <label style="display: block; font-size: 13px; font-weight: 700; color: #334155; margin-bottom: 8px;">Tên đăng nhập hoặc Email</label>
      <input name="username" type="text" class="input-field" style="width:100%; border-radius:14px;" placeholder="Tên đăng nhập / email" required>
    </div>
    <div style="margin-bottom: 18px;">
      <label style="display: block; font-size: 13px; font-weight: 700; color: #334155; margin-bottom: 8px;">Mật khẩu</label>
      <input name="password" type="password" class="input-field" style="width:100%; border-radius:14px;" placeholder="Mật khẩu" required>
    </div>
    <button type="submit" class="btn-submit" style="width:100%; background:#3b82f6; border-color:#3b82f6; color:#fff;">
      <i class="ki-filled ki-right"></i> Đăng Nhập
    </button>
  </form>
  <p style="text-align:center; color:#64748b; font-size:13px; margin-top:16px;">Chưa có tài khoản? <a href="/register.php" style="color:#3b82f6; font-weight:700; text-decoration:none;">Đăng ký miễn phí</a></p>
</div>
<?php Minhnhatdev_page_foot(); ?>
