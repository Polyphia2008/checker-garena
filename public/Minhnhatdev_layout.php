<?php
require_once __DIR__ . '/Minhnhatdev_config.php';
require_once __DIR__ . '/Minhnhatdev_icons.php';

function Minhnhatdev_page_head(string $title, string $extraCss = ''): void {
    $user = Minhnhatdev_current_user();
    $Minhnhatdev_page = basename($_SERVER['SCRIPT_NAME']);
?>
<!doctype html>
<html lang="vi" class="h-full light" data-kt-theme="true" data-kt-theme-mode="light">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no" />
  <title><?= e($title) ?> - Minhnhatdev Checker</title>
  <meta name="description" content="Công cụ kiểm tra tài khoản Garena / Liên Quân Mobile">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet" />
  <link href="/assets/css/styles.css" rel="stylesheet" />
  <link href="/assets/css/Minhnhatdev_theme.css" rel="stylesheet" />
  <link href="https://cdn.jsdelivr.net/npm/toastify-js@1.12.0/src/toastify.min.css" rel="stylesheet" />
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
    .Minhnhatdev-table-wrap { width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; }
    .Minhnhatdev-table { width: 100%; min-width: 640px; border-collapse: collapse; font-size: 13px; }
    .Minhnhatdev-table th {
      text-align: left; padding: 10px 12px; font-size: 11px; font-weight: 700; color: #64748b;
      text-transform: uppercase; letter-spacing: .5px; border-bottom: 1px solid #e2e8f0; background: #f8fafc; white-space: nowrap;
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
    .Minhnhatdev-ic { display:inline-flex; align-items:center; justify-content:center; }
    .Minhnhatdev-side-link {
      display: flex; align-items: center; gap: 10px; text-decoration: none; color: #1e293b;
      font-weight: 600; font-size: 14px; padding: 9px 12px; border-radius: 10px; transition: background .15s;
    }
    .Minhnhatdev-side-link:hover { background: #f1f5f9; }
    .Minhnhatdev-side-link.Minhnhatdev-active { background: rgba(59,130,246,.1); color: #1d4ed8; }
    .Minhnhatdev-stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 14px; }
    @media (max-width: 640px) {
      main.main-content { padding: 16px 12px !important; }
      .Minhnhatdev-hitline { font-size: 11px; padding: 12px; }
      .Minhnhatdev-userchip { padding-right: 8px; }
      .Minhnhatdev-stat-grid { grid-template-columns: repeat(2, 1fr); }
    }
    @media (min-width: 641px) and (max-width: 1024px) {
      main.main-content { padding: 24px 16px !important; }
      .Minhnhatdev-stat-grid { grid-template-columns: repeat(3, 1fr); }
    }
    <?= $extraCss ?>
  </style>
</head>
<body>
  <div id="sidebar">
    <div style="display: flex; align-items: center; justify-content: space-between; padding: 20px; border-bottom: 1px solid #e2e8f0;">
      <span style="font-weight: 700; color: #1e293b; font-size: 15px;">MENU</span>
      <button onclick="MinhnhatdevToggleSidebar()" style="background: none; border: none; cursor: pointer; color: #64748b;">
        <?= Minhnhatdev_icon('cross', '', 20) ?>
      </button>
    </div>
    <div style="padding: 16px; display: flex; flex-direction: column; gap: 6px;">
      <a href="/index.php" class="Minhnhatdev-side-link <?= $Minhnhatdev_page === 'index.php' ? 'Minhnhatdev-active' : '' ?>">
        <span class="Minhnhatdev-ic" style="color:#3b82f6;"><?= Minhnhatdev_icon('shield-search', '', 17) ?></span> Check Tài Khoản
      </a>
      <?php if ($user): ?>
      <a href="/history.php" class="Minhnhatdev-side-link <?= $Minhnhatdev_page === 'history.php' ? 'Minhnhatdev-active' : '' ?>">
        <span class="Minhnhatdev-ic" style="color:#d97706;"><?= Minhnhatdev_icon('time', '', 17) ?></span> Lịch Sử Check
      </a>
      <?php if ($user['role'] === 'admin'): ?>
      <a href="/bulk.php" class="Minhnhatdev-side-link <?= $Minhnhatdev_page === 'bulk.php' ? 'Minhnhatdev-active' : '' ?>">
        <span class="Minhnhatdev-ic" style="color:#7c3aed;"><?= Minhnhatdev_icon('list', '', 17) ?></span> Check Hàng Loạt
      </a>
      <a href="/admin.php" class="Minhnhatdev-side-link <?= $Minhnhatdev_page === 'admin.php' ? 'Minhnhatdev-active' : '' ?>">
        <span class="Minhnhatdev-ic" style="color:#0284c7;"><?= Minhnhatdev_icon('settings', '', 17) ?></span> Quản Trị Admin
      </a>
      <?php endif; ?>
      <a href="/logout.php" class="Minhnhatdev-side-link" style="color:#b91c1c;">
        <span class="Minhnhatdev-ic" style="color:#b91c1c;"><?= Minhnhatdev_icon('logout', '', 17) ?></span> Đăng Xuất
      </a>
      <?php else: ?>
      <a href="/login.php" class="Minhnhatdev-side-link <?= $Minhnhatdev_page === 'login.php' ? 'Minhnhatdev-active' : '' ?>">
        <span class="Minhnhatdev-ic" style="color:#059669;"><?= Minhnhatdev_icon('user', '', 17) ?></span> Đăng Nhập
      </a>
      <a href="/register.php" class="Minhnhatdev-side-link <?= $Minhnhatdev_page === 'register.php' ? 'Minhnhatdev-active' : '' ?>">
        <span class="Minhnhatdev-ic" style="color:#3b82f6;"><?= Minhnhatdev_icon('plus', '', 17) ?></span> Đăng Ký
      </a>
      <?php endif; ?>
    </div>
  </div>
  <div id="sidebar-backdrop" onclick="MinhnhatdevToggleSidebar()"></div>

  <header id="header">
    <div class="header-container">
      <div style="display: flex; align-items: center; gap: 12px; min-width: 0;">
        <button onclick="MinhnhatdevToggleSidebar()" class="menu-toggle">
          <?= Minhnhatdev_icon('menu', '', 22) ?>
        </button>
        <a href="/index.php" class="logo-link">
          <span class="Minhnhatdev-ic" style="color:#3b82f6;"><?= Minhnhatdev_icon('shield-search', '', 24) ?></span>
          <span style="white-space: nowrap;">MINHNHATDEV <span style="color:#3b82f6;">CHECKER</span></span>
        </a>
      </div>
      <nav class="Minhnhatdev-nav hidden lg:flex">
        <?php if ($user): ?>
        <a href="/index.php" class="<?= $Minhnhatdev_page === 'index.php' ? 'Minhnhatdev-active' : '' ?>"><?= Minhnhatdev_icon('shield-search', '', 15) ?> CHECK ACC</a>
        <a href="/history.php" class="<?= $Minhnhatdev_page === 'history.php' ? 'Minhnhatdev-active' : '' ?>"><?= Minhnhatdev_icon('time', '', 15) ?> LỊCH SỬ</a>
        <?php if ($user['role'] === 'admin'): ?>
        <a href="/bulk.php" class="<?= $Minhnhatdev_page === 'bulk.php' ? 'Minhnhatdev-active' : '' ?>"><?= Minhnhatdev_icon('list', '', 15) ?> HÀNG LOẠT</a>
        <a href="/admin.php" class="<?= $Minhnhatdev_page === 'admin.php' ? 'Minhnhatdev-active' : '' ?>"><?= Minhnhatdev_icon('settings', '', 15) ?> ADMIN</a>
        <?php endif; ?>
        <span class="Minhnhatdev-userchip">
          <span class="Minhnhatdev-avatar"><?= e(mb_substr($user['username'], 0, 1)) ?></span>
          <?= e($user['username']) ?>
          <span class="<?= $user['role'] === 'admin' ? 'Minhnhatdev-badge-admin' : 'Minhnhatdev-badge-user' ?>"><?= strtoupper(e($user['role'])) ?></span>
        </span>
        <a href="/logout.php" style="color:#b91c1c;"><?= Minhnhatdev_icon('logout', '', 15) ?> THOÁT</a>
        <?php else: ?>
        <a href="/login.php" class="<?= $Minhnhatdev_page === 'login.php' ? 'Minhnhatdev-active' : '' ?>"><?= Minhnhatdev_icon('user', '', 15) ?> ĐĂNG NHẬP</a>
        <a href="/register.php" class="<?= $Minhnhatdev_page === 'register.php' ? 'Minhnhatdev-active' : '' ?>"><?= Minhnhatdev_icon('plus', '', 15) ?> ĐĂNG KÝ</a>
        <?php endif; ?>
      </nav>
      <?php if ($user): ?>
      <a href="/logout.php" class="flex lg:hidden" style="color:#b91c1c; align-items:center; gap:4px; font-size:12px; font-weight:700; text-decoration:none;"><?= Minhnhatdev_icon('logout', '', 16) ?></a>
      <?php endif; ?>
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
            <span class="Minhnhatdev-ic" style="color:#3b82f6;"><?= Minhnhatdev_icon('shield-search', '', 22) ?></span>
            <span>MINHNHATDEV CHECKER</span>
          </a>
          <p style="color: #64748b; font-size: 12px; line-height: 1.6; margin: 0;">
            Hệ thống kiểm tra tài khoản Garena / Liên Quân Mobile tự động. Mỗi tài khoản được <?= Minhnhatdev_DAILY_LIMIT ?> lượt check mỗi ngày.
          </p>
        </div>
        <div class="footer-col">
          <h4>Công cụ</h4>
          <div class="footer-links">
            <a href="/index.php"><?= Minhnhatdev_icon('arrow-right', '', 11) ?> Check tài khoản Garena</a>
            <a href="/history.php"><?= Minhnhatdev_icon('arrow-right', '', 11) ?> Lịch sử kiểm tra</a>
          </div>
        </div>
        <div class="footer-col">
          <h4>Tài khoản</h4>
          <div class="footer-links">
            <a href="/login.php"><?= Minhnhatdev_icon('arrow-right', '', 11) ?> Đăng nhập</a>
            <a href="/register.php"><?= Minhnhatdev_icon('arrow-right', '', 11) ?> Đăng ký</a>
          </div>
        </div>
      </div>
      <div class="footer-copyright">© <?= date('Y') ?> Minhnhatdev Checker. All rights reserved.</div>
    </div>
  </footer>

  <script src="https://cdn.jsdelivr.net/npm/toastify-js@1.12.0/src/toastify.min.js"></script>
  <script>
    function MinhnhatdevToggleSidebar() {
      document.getElementById('sidebar').classList.toggle('show');
      document.getElementById('sidebar-backdrop').classList.toggle('show');
    }
    const MinhnhatdevToastStyles = {
      success: 'linear-gradient(135deg,#059669,#10b981)',
      error:   'linear-gradient(135deg,#dc2626,#ef4444)',
      info:    'linear-gradient(135deg,#2563eb,#3b82f6)',
      warning: 'linear-gradient(135deg,#d97706,#f59e0b)'
    };
    function MinhnhatdevToast(message, type) {
      type = type || 'info';
      Toastify({
        text: message,
        duration: 3600,
        close: true,
        gravity: 'top',
        position: 'right',
        stopOnFocus: true,
        style: {
          background: MinhnhatdevToastStyles[type] || MinhnhatdevToastStyles.info,
          borderRadius: '12px',
          fontSize: '13px',
          fontWeight: '600',
          fontFamily: 'Inter, sans-serif',
          boxShadow: '0 10px 30px rgba(15,23,42,.18)',
          padding: '12px 18px'
        }
      }).showToast();
    }
  </script>
</body>
</html>
<?php
}
