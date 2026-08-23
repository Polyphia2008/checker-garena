<?php
require_once __DIR__ . '/Minhnhatdev_layout.php';

$admin = Minhnhatdev_require_admin();
$pdo = Minhnhatdev_db();
Minhnhatdev_init_schema($pdo);

$Minhnhatdev_msg = '';
$Minhnhatdev_msgErr = false;

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    Minhnhatdev_csrf_verify();
    $action = (string)($_POST['action'] ?? '');
    $targetId = (int)($_POST['user_id'] ?? 0);

    if ($action === 'save_proxy') {
        $content = (string)($_POST['proxy_list'] ?? '');
        $n = Minhnhatdev_proxy_save($content);
        $Minhnhatdev_msg = "Đã lưu {$n} proxy vào hệ thống.";
    } elseif ($action === 'toggle_proxy') {
        $on = (int)($_POST['enabled'] ?? 0) === 1;
        Minhnhatdev_proxy_set_enabled($on);
        if ($on && Minhnhatdev_proxy_count() <= 0) {
            $Minhnhatdev_msg = 'Đã bật proxy nhưng danh sách đang trống — hãy lưu proxy trước.';
            $Minhnhatdev_msgErr = true;
        } else {
            $Minhnhatdev_msg = $on ? 'Đã BẬT chế độ dùng proxy cho mọi lượt check.' : 'Đã TẮT proxy — check bằng IP trực tiếp.';
        }
    } else {
        $tStmt = $pdo->prepare("SELECT id, username, role FROM users WHERE id = ? LIMIT 1");
        $tStmt->execute([$targetId]);
        $target = $tStmt->fetch();

        if (!$target) {
            $Minhnhatdev_msg = 'Không tìm thấy người dùng.';
            $Minhnhatdev_msgErr = true;
        } elseif ((int)$target['id'] === (int)$admin['id'] && in_array($action, ['ban', 'unban', 'delete', 'demote'], true)) {
            $Minhnhatdev_msg = 'Bạn không thể tự thao tác trên chính tài khoản admin của mình.';
            $Minhnhatdev_msgErr = true;
        } else {
            switch ($action) {
                case 'ban':
                    $pdo->prepare("UPDATE users SET banned = 1 WHERE id = ?")->execute([$targetId]);
                    $Minhnhatdev_msg = "Đã khóa tài khoản {$target['username']}.";
                    break;
                case 'unban':
                    $pdo->prepare("UPDATE users SET banned = 0 WHERE id = ?")->execute([$targetId]);
                    $Minhnhatdev_msg = "Đã mở khóa tài khoản {$target['username']}.";
                    break;
                case 'delete':
                    $pdo->prepare("DELETE FROM check_logs WHERE user_id = ?")->execute([$targetId]);
                    $pdo->prepare("DELETE FROM users WHERE id = ?")->execute([$targetId]);
                    $Minhnhatdev_msg = "Đã xóa vĩnh viễn tài khoản {$target['username']}.";
                    break;
                case 'set_quota':
                    $q = max(0, min(1000000, (int)($_POST['quota'] ?? Minhnhatdev_DAILY_LIMIT)));
                    $pdo->prepare("UPDATE users SET daily_quota = ? WHERE id = ?")->execute([$q, $targetId]);
                    $Minhnhatdev_msg = "Đã đặt hạn mức {$q} lượt/ngày cho {$target['username']}.";
                    break;
                case 'promote':
                    $pdo->prepare("UPDATE users SET role = 'admin' WHERE id = ?")->execute([$targetId]);
                    $Minhnhatdev_msg = "Đã nâng {$target['username']} lên quyền ADMIN.";
                    break;
                case 'demote':
                    $pdo->prepare("UPDATE users SET role = 'user' WHERE id = ?")->execute([$targetId]);
                    $Minhnhatdev_msg = "Đã hạ {$target['username']} xuống quyền USER.";
                    break;
                default:
                    $Minhnhatdev_msg = 'Hành động không hợp lệ.';
                    $Minhnhatdev_msgErr = true;
            }
        }
    }
}

$statUsers = (int)$pdo->query("SELECT COUNT(*) AS c FROM users")->fetch()['c'];
$statAdmins = (int)$pdo->query("SELECT COUNT(*) AS c FROM users WHERE role='admin'")->fetch()['c'];
$statBanned = (int)$pdo->query("SELECT COUNT(*) AS c FROM users WHERE banned=1")->fetch()['c'];
$statChecksToday = (int)$pdo->query("SELECT COUNT(*) AS c FROM check_logs WHERE DATE(created_at) = CURDATE()")->fetch()['c'];
$statChecksTotal = (int)$pdo->query("SELECT COUNT(*) AS c FROM check_logs")->fetch()['c'];
$statHitsTotal = (int)$pdo->query("SELECT COUNT(*) AS c FROM check_logs WHERE status='HIT'")->fetch()['c'];
$statHitsToday = (int)$pdo->query("SELECT COUNT(*) AS c FROM check_logs WHERE status='HIT' AND DATE(created_at) = CURDATE()")->fetch()['c'];

$users = $pdo->query("SELECT u.id, u.username, u.email, u.role, u.daily_quota, u.banned, u.created_at,
    (SELECT COUNT(*) FROM check_logs cl WHERE cl.user_id = u.id AND DATE(cl.created_at) = CURDATE()) AS used_today,
    (SELECT COUNT(*) FROM check_logs cl WHERE cl.user_id = u.id) AS total_checks
    FROM users u ORDER BY u.id ASC")->fetchAll();

$recentLogs = $pdo->query("SELECT cl.account, cl.status, cl.tinh_trang, cl.created_at, u.username
    FROM check_logs cl JOIN users u ON u.id = cl.user_id ORDER BY cl.id DESC LIMIT 15")->fetchAll();

$Minhnhatdev_proxyOn = Minhnhatdev_proxy_is_enabled();
$Minhnhatdev_proxyCount = Minhnhatdev_proxy_count();
$Minhnhatdev_proxyRaw = Minhnhatdev_proxy_read();

Minhnhatdev_page_head('Quản Trị Admin');
?>
<div class="card-verify" style="max-width: 1100px; text-align: left;">
  <div style="display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:10px; margin-bottom:18px;">
    <h3 style="font-weight: 800; color: #0f172a; margin: 0; font-size: 20px; display:flex; align-items:center; gap:8px;">
      <span style="color:#0284c7; display:inline-flex;"><?= Minhnhatdev_icon('settings', '', 22) ?></span> Bảng Điều Khiển Admin
    </h3>
    <a href="/bulk.php" class="btn-submit" style="text-decoration:none; height:38px; font-size:13px; background:#ede9fe; border-color:#ddd6fe; color:#6d28d9;">
      <?= Minhnhatdev_icon('list', '', 15) ?> Check Hàng Loạt
    </a>
  </div>

  <?php if ($Minhnhatdev_msg): ?>
  <div class="Minhnhatdev-alert <?= $Minhnhatdev_msgErr ? 'Minhnhatdev-alert-err' : 'Minhnhatdev-alert-ok' ?>">
    <?= Minhnhatdev_icon('info', '', 16) ?> <?= e($Minhnhatdev_msg) ?>
  </div>
  <script>window.addEventListener('load', function(){ MinhnhatdevToast(<?= json_encode($Minhnhatdev_msg) ?>, <?= $Minhnhatdev_msgErr ? "'error'" : "'success'" ?>); });</script>
  <?php endif; ?>

  <div class="Minhnhatdev-stat-grid" style="margin-bottom:24px;">
    <?php
    $cards = [
        ['Tổng user', $statUsers, 'user', '#3b82f6'],
        ['Admin', $statAdmins, 'crown', '#8b5cf6'],
        ['Đang khóa', $statBanned, 'ban', '#ef4444'],
        ['Check hôm nay', $statChecksToday, 'time', '#f59e0b'],
        ['Tổng lượt check', $statChecksTotal, 'shield-search', '#0ea5e9'],
        ['HIT hôm nay', $statHitsToday, 'double-check', '#10b981'],
        ['Tổng HIT', $statHitsTotal, 'star', '#059669'],
    ];
    foreach ($cards as [$label, $val, $icon, $color]): ?>
    <div style="background:#fff; border:1px solid #e2e8f0; border-radius:16px; padding:16px; text-align:center;">
      <span style="display:inline-flex; color:<?= $color ?>;"><?= Minhnhatdev_icon($icon, '', 24) ?></span>
      <div style="font-size:22px; font-weight:800; color:#0f172a; margin-top:6px;"><?= number_format($val) ?></div>
      <div style="font-size:11px; color:#64748b; font-weight:700; text-transform:uppercase; letter-spacing:.5px;"><?= $label ?></div>
    </div>
    <?php endforeach; ?>
  </div>

  <div style="background:#fff; border:1px solid #e2e8f0; border-radius:16px; padding:20px; margin-bottom:26px;">
    <h4 style="font-weight:800; color:#0f172a; font-size:15px; margin:0 0 6px 0; display:flex; align-items:center; gap:8px;">
      <span style="color:#7c3aed; display:inline-flex;"><?= Minhnhatdev_icon('proxy', '', 18) ?></span> Cấu Hình Proxy
      <span class="history-badge <?= $Minhnhatdev_proxyOn && $Minhnhatdev_proxyCount > 0 ? 'status-valid' : 'status-invalid' ?>" style="margin-left:6px;">
        <?= $Minhnhatdev_proxyOn && $Minhnhatdev_proxyCount > 0 ? 'ĐANG BẬT' : 'ĐANG TẮT' ?> · <?= $Minhnhatdev_proxyCount ?> proxy
      </span>
    </h4>
    <p style="color:#64748b; font-size:12px; margin:0 0 14px 0; line-height:1.6;">
      Mỗi dòng 1 proxy. Hỗ trợ: <code>ip:port</code>, <code>ip:port:user:pass</code>, <code>http(s)://ip:port</code>, <code>socks5://ip:port</code>.
      Khi bật, mọi lượt check (cả check lẻ và hàng loạt) sẽ xoay proxy tự động.
    </p>
    <form method="post" style="margin-bottom:12px;">
      <?= Minhnhatdev_csrf_field() ?>
      <input type="hidden" name="action" value="save_proxy">
      <textarea name="proxy_list" rows="6" class="input-field" style="width:100%; border-radius:14px; padding:14px 16px; font-family:monospace; font-size:12px; height:auto; resize:vertical;" placeholder="1.2.3.4:8080&#10;5.6.7.8:3128:user:pass&#10;socks5://9.9.9.9:1080"><?= e($Minhnhatdev_proxyRaw) ?></textarea>
      <div style="display:flex; gap:8px; flex-wrap:wrap; margin-top:10px;">
        <button type="submit" class="btn-submit" style="height:38px; font-size:12px;">
          <?= Minhnhatdev_icon('check', '', 15) ?> Lưu danh sách proxy
        </button>
      </div>
    </form>
    <form method="post" style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
      <?= Minhnhatdev_csrf_field() ?>
      <input type="hidden" name="action" value="toggle_proxy">
      <input type="hidden" name="enabled" value="<?= $Minhnhatdev_proxyOn ? 0 : 1 ?>">
      <button type="submit" class="btn-submit" style="height:38px; font-size:12px; <?= $Minhnhatdev_proxyOn ? 'background:#fef2f2; border-color:#fecaca; color:#b91c1c;' : 'background:#ecfdf5; border-color:#a7f3d0; color:#047857;' ?>">
        <?= Minhnhatdev_icon($Minhnhatdev_proxyOn ? 'stop' : 'play', '', 15) ?> <?= $Minhnhatdev_proxyOn ? 'Tắt proxy' : 'Bật proxy' ?>
      </button>
      <span style="font-size:12px; color:#64748b;">Trạng thái hiện tại: <strong><?= $Minhnhatdev_proxyOn ? 'BẬT' : 'TẮT' ?></strong></span>
    </form>
  </div>

  <h4 style="font-weight:800; color:#0f172a; font-size:15px; margin:0 0 12px 0; display:flex; align-items:center; gap:8px;">
    <span style="color:#3b82f6; display:inline-flex;"><?= Minhnhatdev_icon('users', '', 18) ?></span> Quản Lý Người Dùng (<?= count($users) ?>)
  </h4>
  <div class="Minhnhatdev-table-wrap" style="border:1px solid #e2e8f0; border-radius:14px; margin-bottom:26px;">
    <table class="Minhnhatdev-table">
      <thead>
        <tr>
          <th>ID</th><th>Username</th><th>Email</th><th>Quyền</th><th>Lượt hôm nay</th><th>Hạn mức/ngày</th><th>Tổng check</th><th>Trạng thái</th><th style="min-width:260px;">Hành động</th>
        </tr>
      </thead>
      <tbody>
        <?php foreach ($users as $u): ?>
        <tr style="<?= (int)$u['banned'] ? 'opacity:.55;' : '' ?>">
          <td><?= (int)$u['id'] ?></td>
          <td style="font-weight:700;"><?= e($u['username']) ?><?= (int)$u['id'] === (int)$admin['id'] ? ' <span style="color:#94a3b8; font-size:11px;">(bạn)</span>' : '' ?></td>
          <td style="color:#64748b;"><?= e($u['email']) ?></td>
          <td><span class="<?= $u['role'] === 'admin' ? 'Minhnhatdev-badge-admin' : 'Minhnhatdev-badge-user' ?>"><?= strtoupper(e($u['role'])) ?></span></td>
          <td><?= (int)$u['used_today'] ?></td>
          <td>
            <form method="post" style="display:flex; gap:6px; align-items:center;">
              <?= Minhnhatdev_csrf_field() ?>
              <input type="hidden" name="action" value="set_quota">
              <input type="hidden" name="user_id" value="<?= (int)$u['id'] ?>">
              <input type="number" name="quota" value="<?= (int)$u['daily_quota'] ?>" min="0" max="1000000"
                style="width:80px; height:30px; border:1px solid #cbd5e1; border-radius:8px; padding:0 8px; font-size:12px;">
              <button type="submit" class="btn-submit" style="height:30px; padding:0 10px; font-size:11px;">Lưu</button>
            </form>
          </td>
          <td><?= (int)$u['total_checks'] ?></td>
          <td><?= (int)$u['banned'] ? '<span style="color:#b91c1c; font-weight:700;">Bị khóa</span>' : '<span style="color:#047857; font-weight:700;">Hoạt động</span>' ?></td>
          <td>
            <?php if ((int)$u['id'] !== (int)$admin['id']): ?>
            <div style="display:flex; gap:6px; flex-wrap:wrap;">
              <form method="post" onsubmit="return confirm('<?= (int)$u['banned'] ? 'Mở khóa' : 'Khóa' ?> tài khoản <?= e($u['username']) ?>?')">
                <?= Minhnhatdev_csrf_field() ?>
                <input type="hidden" name="action" value="<?= (int)$u['banned'] ? 'unban' : 'ban' ?>">
                <input type="hidden" name="user_id" value="<?= (int)$u['id'] ?>">
                <button type="submit" class="btn-submit" style="height:30px; padding:0 10px; font-size:11px; <?= (int)$u['banned'] ? '' : 'background:#fef2f2; border-color:#fecaca; color:#b91c1c;' ?>">
                  <?= (int)$u['banned'] ? 'Mở khóa' : 'Khóa' ?>
                </button>
              </form>
              <form method="post" onsubmit="return confirm('<?= $u['role'] === 'admin' ? 'Hạ xuống USER' : 'Nâng lên ADMIN' ?> cho <?= e($u['username']) ?>?')">
                <?= Minhnhatdev_csrf_field() ?>
                <input type="hidden" name="action" value="<?= $u['role'] === 'admin' ? 'demote' : 'promote' ?>">
                <input type="hidden" name="user_id" value="<?= (int)$u['id'] ?>">
                <button type="submit" class="btn-submit" style="height:30px; padding:0 10px; font-size:11px;">
                  <?= $u['role'] === 'admin' ? 'Hạ User' : 'Nâng Admin' ?>
                </button>
              </form>
              <form method="post" onsubmit="return confirm('XÓA VĨNH VIỄN tài khoản <?= e($u['username']) ?> và toàn bộ lịch sử?')">
                <?= Minhnhatdev_csrf_field() ?>
                <input type="hidden" name="action" value="delete">
                <input type="hidden" name="user_id" value="<?= (int)$u['id'] ?>">
                <button type="submit" class="btn-submit" style="height:30px; padding:0 10px; font-size:11px; background:#ef4444; border-color:#ef4444; color:#fff;">Xóa</button>
              </form>
            </div>
            <?php else: ?>
            <span style="color:#94a3b8; font-size:12px;">—</span>
            <?php endif; ?>
          </td>
        </tr>
        <?php endforeach; ?>
      </tbody>
    </table>
  </div>

  <h4 style="font-weight:800; color:#0f172a; font-size:15px; margin:0 0 12px 0; display:flex; align-items:center; gap:8px;">
    <span style="color:#d97706; display:inline-flex;"><?= Minhnhatdev_icon('time', '', 18) ?></span> Hoạt Động Gần Đây (toàn hệ thống)
  </h4>
  <div class="Minhnhatdev-table-wrap" style="border:1px solid #e2e8f0; border-radius:14px;">
    <table class="Minhnhatdev-table">
      <thead><tr><th>User</th><th>Tài khoản check</th><th>Trạng thái</th><th>Tình trạng</th><th>Thời gian</th></tr></thead>
      <tbody>
        <?php foreach ($recentLogs as $log): ?>
        <?php $cls = $log['status'] === 'HIT' ? 'Minhnhatdev-status-hit' : (in_array($log['status'], ['MISS','INVALID']) ? 'Minhnhatdev-status-miss' : 'Minhnhatdev-status-other'); ?>
        <tr>
          <td style="font-weight:700;"><?= e($log['username']) ?></td>
          <td style="font-family:monospace;"><?= e($log['account']) ?></td>
          <td class="<?= $cls ?>"><?= e($log['status']) ?></td>
          <td><?= e($log['tinh_trang']) ?></td>
          <td style="color:#64748b; font-size:12px;"><?= e($log['created_at']) ?></td>
        </tr>
        <?php endforeach; ?>
        <?php if (!$recentLogs): ?>
        <tr><td colspan="5" style="text-align:center; color:#94a3b8;">Chưa có hoạt động nào.</td></tr>
        <?php endif; ?>
      </tbody>
    </table>
  </div>
</div>
<?php Minhnhatdev_page_foot(); ?>
