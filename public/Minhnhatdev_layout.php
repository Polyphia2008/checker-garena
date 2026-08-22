<?php
require_once __DIR__ . '/Minhnhatdev_config.php';

function Minhnhatdev_page_head(string $title, string $extraCss = ''): void {
    $user = Minhnhatdev_current_user();
?>
<!doctype html>
<html lang="vi" class="h-full light" data-kt-theme="true" data-kt-theme-mode="light">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no" />
  <title><?= e($title) ?> - Minhnhatdev Checker</title>
  <meta name="description" content="Công cụ kiểm tra tài khoản Garena / Liên Quân Mobile">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet" />
  <link href="/assets/vendors/keenicons/styles.bundle.css" rel="stylesheet" />
  <link href="/assets/css/styles.css" rel="stylesheet" />
  <link href="/assets/css/Minhnhatdev_theme.css" rel="stylesheet" />
  <style>
    .Minhnhatdev-nav { display: flex; align-items: center; gap: 10px; }
    .Minhnhatdev-nav a {
      display: inline-flex; align-items: center; gap: 6px; text-decoration: none;
      font-size: 13px; font-weight: 700; color: #334155; padding: 8px 14px;
      border-radius: 9999px; transition: all .2s;
    }
    .Minhnhatdev-nav a:hover { background: #f1f5f9; color: #0f172a; }
    .Minhnhatdev-nav a.Minhnhatdev-active { background: rgba(59,130,246,.1); color: #1d4ed8; }
    .Minhnhatdev-userchip {
      display: inline-flex; align-items: center; gap: 8px; padding: 6px 14px 6px 6px;
      border: 1px solid #e2e8f0; border-radius: 9999px; background: #fff;
      font-size: 13px; font-weight: 600; color: #0f172a;
    }
    .Minhnhatdev-avatar {
      width: 28px; height: 28px; border-radius: 50%; display: inline-flex; align-items: center;
      justify-content: center; background: linear-gradient(135deg, #3b82f6, #8b5cf6);
      color: #fff; font-size: 12px; font-weight: 800; text-transform: uppercase;
    }
    .Minhnhatdev-badge-admin { background:#fef3c7; color:#b45309; border:1px solid #fde68a; border-radius:8px; padding:1px 8px; font-size:10px; font-weight:800; }
    .Minhnhatdev-badge-user { background:#e0f2fe; color:#0369a1; border:1px solid #bae6fd; border-radius:8px; padding:1px 8px; font-size:10px; font-weight:800; }
    .Minhnhatdev-table { width: 100%; border-collapse: collapse; font-size: 13px; }
    .Minhnhatdev-table th {
      text-align: left; padding: 10px 12px; font-size: 11px; font-weight: 700; color: #64748b;
      text-transform: uppercase; letter-spacing: .5px; border-bottom: 1px solid #e2e8f0; background: #f8fafc;
    }
    .Minhnhatdev-table td { padding: 10px 12px; border-bottom: 1px solid #f1f5f9; color: #1e293b; vertical-align: top; }
    .Minhnhatdev-table tr:hover td { background: #f8fafc; }
    .Minhnhatdev-status-hit { color:#047857; font-weight:700; }
    .Minhnhatdev-status-miss, .Minhnhatdev-status-invalid { color:#b91c1c; font-weight:700; }
    .Minhnhatdev-status-other { color:#b45309; font-weight:700; }
    .Minhnhatdev-hitline {
      font-family: monospace; font-size: 12px; word-break: break-all; white-space: pre-wrap;
      background: #0f172a; color: #a5f3fc; padding: 16px; border-radius: 12px; line-height: 1.7;
    }
    .Minhnhatdev-alert { border-radius: 12px; padding: 12px 16px; font-size: 13px; font-weight: 600; margin-bottom: 16px; }
    .Minhnhatdev-alert-err { background: rgba(239,68,68,.07); border: 1px solid rgba(239,68,68,.25); color: #b91c1c; }
    .Minhnhatdev-alert-ok { background: rgba(16,185,129,.07); border: 1px solid rgba(16,185,129,.25); color: #047857; }
    <?= $extraCss ?>
  </style>
</head>
<body>
  <div id="sidebar">
    <div style="display: flex; align-items: center; justify-content: space-between; padding: 20px; border-bottom: 1px solid #e2e8f0;">
      <span style="font-weight: 700; color: #1e293b; font-size: 15px;">MENU</span>
      <button onclick="MinhnhatdevToggleSidebar()" style="background: none; border: none; cursor: pointer; color: #64748b;">
        <i class="ki-filled ki-cross fs-4"></i>
      </button>
    </div>
    <div style="padding: 20px; display: flex; flex-direction: column; gap: 15px;">
      <a href="/index.php" style="display: flex; align-items: center; gap: 10px; text-decoration: none; color: #1e293b; font-weight: 600; font-size: 14px;">
        <i class="ki-filled ki-shield-search text-primary" style="font-size: 16px;"></i> Check Tài Khoản
      </a>
      <?php if ($user): ?>
      <a href="/history.php" style="display: flex; align-items: center; gap: 10px; text-decoration: none; color: #1e293b; font-weight: 600; font-size: 14px;">
        <i class="ki-filled ki-time text-warning" style="font-size: 16px;"></i> Lịch Sử Check
      </a>
      <?php if ($user['role'] === 'admin'): ?>
      <a href="/admin.php" style="display: flex; align-items: center; gap: 10px; text-decoration: none; color: #1e293b; font-weight: 600; font-size: 14px;">
        <i class="ki-filled ki-setting-4 text-info" style="font-size: 16px;"></i> Quản Trị Admin
      </a>
      <?php endif; ?>
      <a href="/logout.php" style="display: flex; align-items: center; gap: 10px; text-decoration: none; color: #b91c1c; font-weight: 600; font-size: 14px;">
        <i class="ki-filled ki-right text-danger" style="font-size: 16px;"></i> Đăng Xuất
      </a>
      <?php else: ?>
      <a href="/login.php" style="display: flex; align-items: center; gap: 10px; text-decoration: none; color: #1e293b; font-weight: 600; font-size: 14px;">
        <i class="ki-filled ki-user text-success" style="font-size: 16px;"></i> Đăng Nhập
      </a>
      <a href="/register.php" style="display: flex; align-items: center; gap: 10px; text-decoration: none; color: #1e293b; font-weight: 600; font-size: 14px;">
        <i class="ki-filled ki-plus text-primary" style="font-size: 16px;"></i> Đăng Ký
      </a>
      <?php endif; ?>
    </div>
  </div>
  <div id="sidebar-backdrop" onclick="MinhnhatdevToggleSidebar()"></div>

  <header id="header">
    <div class="header-container">
      <div style="display: flex; align-items: center; gap: 12px;">
        <button onclick="MinhnhatdevToggleSidebar()" class="menu-toggle">
          <i class="ki-filled ki-textalign-left fs-2 text-dark"></i>
        </button>
        <a href="/index.php" class="logo-link">
          <i class="ki-filled ki-shield-search text-primary" style="font-size: 26px;"></i>
          <span>MINHNHATDEV <span style="color:#3b82f6;">CHECKER</span></span>
        </a>
      </div>
      <nav class="Minhnhatdev-nav hidden lg:flex">
        <?php if ($user): ?>
        <a href="/index.php"><i class="ki-filled ki-shield-search text-primary"></i> CHECK ACC</a>
        <a href="/history.php"><i class="ki-filled ki-time text-warning"></i> LỊCH SỬ</a>
        <?php if ($user['role'] === 'admin'): ?>
        <a href="/admin.php"><i class="ki-filled ki-setting-4 text-info"></i> ADMIN</a>
        <?php endif; ?>
        <span class="Minhnhatdev-userchip">
          <span class="Minhnhatdev-avatar"><?= e(mb_substr($user['username'], 0, 1)) ?></span>
          <?= e($user['username']) ?>
          <span class="<?= $user['role'] === 'admin' ? 'Minhnhatdev-badge-admin' : 'Minhnhatdev-badge-user' ?>"><?= strtoupper(e($user['role'])) ?></span>
        </span>
        <a href="/logout.php" style="color:#b91c1c;"><i class="ki-filled ki-right"></i> THOÁT</a>
        <?php else: ?>
        <a href="/login.php"><i class="ki-filled ki-user text-primary"></i> ĐĂNG NHẬP</a>
        <a href="/register.php"><i class="ki-filled ki-plus text-success"></i> ĐĂNG KÝ</a>
        <?php endif; ?>
      </nav>
    </div>
  </header>

  <main class="main-content" style="align-items: flex-start; padding-top: 40px;">
<?php
}

function Minhnhatdev_page_foot(): void {
?>
  </main>

  <footer class="site-footer">
    <div class="footer-container">
      <div class="footer-grid">
        <div class="footer-col">
          <a href="/index.php" style="display: flex; align-items: center; gap: 10px; text-decoration: none; font-weight: 800; color: #1e293b; font-size: 18px; margin-bottom: 15px;">
            <i class="ki-filled ki-shield-search text-primary" style="font-size: 22px;"></i>
            <span>MINHNHATDEV CHECKER</span>
          </a>
          <p style="color: #64748b; font-size: 12px; line-height: 1.6; margin: 0;">
            Hệ thống kiểm tra tài khoản Garena / Liên Quân Mobile tự động. Mỗi tài khoản được <?= Minhnhatdev_DAILY_LIMIT ?> lượt check mỗi ngày.
          </p>
        </div>
        <div class="footer-col">
          <h4>Công cụ</h4>
          <div class="footer-links">
            <a href="/index.php"><i class="ki-filled ki-right" style="font-size: 10px;"></i> Check tài khoản Garena</a>
            <a href="/history.php"><i class="ki-filled ki-right" style="font-size: 10px;"></i> Lịch sử kiểm tra</a>
          </div>
        </div>
        <div class="footer-col">
          <h4>Tài khoản</h4>
          <div class="footer-links">
            <a href="/login.php"><i class="ki-filled ki-right" style="font-size: 10px;"></i> Đăng nhập</a>
            <a href="/register.php"><i class="ki-filled ki-right" style="font-size: 10px;"></i> Đăng ký</a>
          </div>
        </div>
      </div>
      <div class="footer-copyright">© <?= date('Y') ?> Minhnhatdev Checker. All rights reserved.</div>
    </div>
  </footer>

  <script>
    function MinhnhatdevToggleSidebar() {
      document.getElementById('sidebar').classList.toggle('show');
      document.getElementById('sidebar-backdrop').classList.toggle('show');
    }
  </script>
</body>
</html>
<?php
}
