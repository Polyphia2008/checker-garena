<?php
require_once __DIR__ . '/Minhnhatdev_layout.php';

$Minhnhatdev_err = '';
$Minhnhatdev_ok = '';

if (Minhnhatdev_current_user()) {
    header('Location: /index.php');
    exit;
}

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    Minhnhatdev_csrf_verify();
    $username = trim($_POST['username'] ?? '');
    $email = trim($_POST['email'] ?? '');
    $password = (string)($_POST['password'] ?? '');
    $password2 = (string)($_POST['password2'] ?? '');

    if (!preg_match('/^[a-zA-Z0-9_.]{3,30}$/', $username)) {
        $Minhnhatdev_err = 'Tên đăng nhập phải từ 3-30 ký tự, chỉ gồm chữ, số, dấu _ và .';
    } elseif (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
        $Minhnhatdev_err = 'Email không hợp lệ.';
    } elseif (strlen($password) < 6) {
        $Minhnhatdev_err = 'Mật khẩu phải có ít nhất 6 ký tự.';
    } elseif ($password !== $password2) {
        $Minhnhatdev_err = 'Mật khẩu nhập lại không khớp.';
    } else {
        $pdo = Minhnhatdev_db();
        Minhnhatdev_init_schema($pdo);
        $chk = $pdo->prepare("SELECT id FROM users WHERE username = ? OR email = ? LIMIT 1");
        $chk->execute([$username, $email]);
        if ($chk->fetch()) {
            $Minhnhatdev_err = 'Tên đăng nhập hoặc email đã tồn tại.';
        } else {
            $ins = $pdo->prepare("INSERT INTO users (username, email, password_hash, role, daily_quota) VALUES (?, ?, ?, 'user', ?)");
            $ins->execute([$username, $email, password_hash($password, PASSWORD_DEFAULT), Minhnhatdev_DAILY_LIMIT]);
            $Minhnhatdev_ok = 'Đăng ký thành công! Bạn có thể đăng nhập ngay.';
        }
    }
}

Minhnhatdev_page_head('Đăng Ký');
?>
<div class="card-verify" style="max-width: 460px;">
  <div style="text-align: center; margin-bottom: 26px;">
    <div style="display: inline-flex; align-items: center; justify-content: center; padding: 16px; background-color: rgba(16,185,129,.08); border-radius: 20px; margin-bottom: 14px; color: #10b981; box-shadow: 0 10px 20px -5px rgba(16,185,129,.2);">
      <i class="ki-filled ki-plus" style="display: block; font-size: 2rem; line-height: 1;"></i>
    </div>
    <h3 style="font-weight: 800; color: #0f172a; margin: 0 0 6px 0; font-size: 20px;">Tạo Tài Khoản Mới</h3>
    <p style="color: #64748b; font-size: 13px; margin: 0;">Mỗi tài khoản được <?= Minhnhatdev_DAILY_LIMIT ?> lượt check miễn phí mỗi ngày</p>
  </div>

  <?php if ($Minhnhatdev_err): ?><div class="Minhnhatdev-alert Minhnhatdev-alert-err"><i class="ki-filled ki-information-2"></i> <?= e($Minhnhatdev_err) ?></div><?php endif; ?>
  <?php if ($Minhnhatdev_ok): ?><div class="Minhnhatdev-alert Minhnhatdev-alert-ok"><i class="ki-filled ki-double-check"></i> <?= e($Minhnhatdev_ok) ?> <a href="/login.php" style="color:#047857; font-weight:800;">Đăng nhập ngay</a></div><?php endif; ?>

  <form method="post" action="/register.php">
    <?= Minhnhatdev_csrf_field() ?>
    <div style="margin-bottom: 14px;">
      <label style="display: block; font-size: 13px; font-weight: 700; color: #334155; margin-bottom: 8px;">Tên đăng nhập</label>
      <input name="username" type="text" class="input-field" style="width:100%; border-radius:14px;" placeholder="vd: minhnhat2008" required value="<?= e($_POST['username'] ?? '') ?>">
    </div>
    <div style="margin-bottom: 14px;">
      <label style="display: block; font-size: 13px; font-weight: 700; color: #334155; margin-bottom: 8px;">Email</label>
      <input name="email" type="email" class="input-field" style="width:100%; border-radius:14px;" placeholder="you@example.com" required value="<?= e($_POST['email'] ?? '') ?>">
    </div>
    <div style="margin-bottom: 14px;">
      <label style="display: block; font-size: 13px; font-weight: 700; color: #334155; margin-bottom: 8px;">Mật khẩu</label>
      <input name="password" type="password" class="input-field" style="width:100%; border-radius:14px;" placeholder="Tối thiểu 6 ký tự" required>
    </div>
    <div style="margin-bottom: 18px;">
      <label style="display: block; font-size: 13px; font-weight: 700; color: #334155; margin-bottom: 8px;">Nhập lại mật khẩu</label>
      <input name="password2" type="password" class="input-field" style="width:100%; border-radius:14px;" placeholder="Nhập lại mật khẩu" required>
    </div>
    <button type="submit" class="btn-submit" style="width:100%; background:#10b981; border-color:#10b981; color:#fff;">
      <i class="ki-filled ki-plus"></i> Đăng Ký
    </button>
  </form>
  <p style="text-align:center; color:#64748b; font-size:13px; margin-top:16px;">Đã có tài khoản? <a href="/login.php" style="color:#3b82f6; font-weight:700; text-decoration:none;">Đăng nhập</a></p>
</div>
<?php Minhnhatdev_page_foot(); ?>
