<?php
require_once __DIR__ . '/Minhnhatdev_layout.php';

$user = Minhnhatdev_require_login();
$pdo = Minhnhatdev_db();

$page = max(1, (int)($_GET['page'] ?? 1));
$perPage = 20;
$offset = ($page - 1) * $perPage;

$count = $pdo->prepare("SELECT COUNT(*) AS c FROM check_logs WHERE user_id = ?");
$count->execute([(int)$user['id']]);
$total = (int)$count->fetch()['c'];
$pages = max(1, (int)ceil($total / $perPage));

$stmt = $pdo->prepare("SELECT account, status, result_line, tinh_trang, detail, ip, created_at FROM check_logs WHERE user_id = ? ORDER BY id DESC LIMIT ? OFFSET ?");
$stmt->bindValue(1, (int)$user['id'], PDO::PARAM_INT);
$stmt->bindValue(2, $perPage, PDO::PARAM_INT);
$stmt->bindValue(3, $offset, PDO::PARAM_INT);
$stmt->execute();
$logs = $stmt->fetchAll();

Minhnhatdev_page_head('Lịch Sử Check');
?>
<div class="card-verify" style="max-width: 960px; text-align: left;">
  <div style="display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:10px; margin-bottom:20px;">
    <h3 style="font-weight: 800; color: #0f172a; margin: 0; font-size: 20px; display:flex; align-items:center; gap:8px;">
      <span style="color:#3b82f6; display:inline-flex;"><?= Minhnhatdev_icon('time', '', 22) ?></span> Lịch Sử Check Của Bạn
    </h3>
    <a href="/index.php" class="btn-submit" style="text-decoration:none; height:38px; font-size:13px;"><?= Minhnhatdev_icon('shield-search', '', 15) ?> Check tài khoản mới</a>
  </div>

  <?php if (!$logs): ?>
  <div class="Minhnhatdev-alert Minhnhatdev-alert-ok"><?= Minhnhatdev_icon('info', '', 16) ?> Bạn chưa check tài khoản nào. <a href="/index.php" style="font-weight:800;">Bắt đầu ngay!</a></div>
  <?php else: ?>
  <div class="Minhnhatdev-table-wrap" style="border:1px solid #e2e8f0; border-radius:14px;">
    <table class="Minhnhatdev-table">
      <thead>
        <tr>
          <th style="width:40px;">#</th>
          <th>Tài khoản</th>
          <th style="width:110px;">Trạng thái</th>
          <th style="width:130px;">Tình trạng</th>
          <th style="width:150px;">Thời gian</th>
          <th style="width:80px;">Chi tiết</th>
        </tr>
      </thead>
      <tbody>
        <?php foreach ($logs as $i => $log): ?>
        <?php
          $statusClass = $log['status'] === 'HIT' ? 'Minhnhatdev-status-hit' : (in_array($log['status'], ['MISS', 'INVALID']) ? 'Minhnhatdev-status-miss' : 'Minhnhatdev-status-other');
        ?>
        <tr>
          <td><?= $total - $offset - $i ?></td>
          <td style="font-family:monospace; font-weight:700;"><?= e($log['account']) ?></td>
          <td class="<?= $statusClass ?>"><?= e($log['status']) ?></td>
          <td><?= e($log['tinh_trang']) ?></td>
          <td style="color:#64748b; font-size:12px;"><?= e($log['created_at']) ?></td>
          <td>
            <?php if ($log['status'] === 'HIT' && $log['result_line']): ?>
            <button type="button" class="btn-submit" style="height:28px; padding:0 12px; font-size:11px;"
              onclick='MinhnhatdevShowLine(<?= json_encode($log["result_line"], JSON_UNESCAPED_UNICODE | JSON_HEX_APOS | JSON_HEX_QUOT) ?>)'>
              <?= Minhnhatdev_icon('eye', '', 13) ?> Xem
            </button>
            <?php elseif ($log['detail']): ?>
            <span title="<?= e($log['detail']) ?>" style="cursor:help; color:#94a3b8; display:inline-flex;"><?= Minhnhatdev_icon('info', '', 16) ?></span>
            <?php endif; ?>
          </td>
        </tr>
        <?php endforeach; ?>
      </tbody>
    </table>
  </div>

  <?php if ($pages > 1): ?>
  <div style="display:flex; gap:6px; justify-content:center; margin-top:18px;">
    <?php for ($p = 1; $p <= $pages; $p++): ?>
    <a href="?page=<?= $p ?>" class="btn-submit" style="height:34px; padding:0 14px; font-size:12px; text-decoration:none; <?= $p === $page ? 'background:#3b82f6; border-color:#3b82f6; color:#fff;' : '' ?>"><?= $p ?></a>
    <?php endfor; ?>
  </div>
  <?php endif; ?>
  <?php endif; ?>
</div>

<div id="MinhnhatdevModal" style="display:none; position:fixed; inset:0; z-index:10020; background:rgba(15,23,42,.45); backdrop-filter:blur(4px); align-items:center; justify-content:center; padding:20px;" onclick="if(event.target===this) this.style.display='none'">
  <div style="background:#fff; border-radius:20px; padding:24px; max-width:900px; width:100%; max-height:80vh; overflow:auto;">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;">
      <strong style="color:#0f172a; font-size:15px;">Kết quả chi tiết</strong>
      <button onclick="document.getElementById('MinhnhatdevModal').style.display='none'" style="background:none; border:none; cursor:pointer; color:#64748b; display:inline-flex;"><?= Minhnhatdev_icon('cross', '', 20) ?></button>
    </div>
    <div id="MinhnhatdevModalBody" class="Minhnhatdev-hitline"></div>
    <button type="button" class="btn-submit" style="margin-top:14px; height:36px; font-size:12px;" onclick="MinhnhatdevCopyModal()"><?= Minhnhatdev_icon('copy', '', 14) ?> Copy</button>
  </div>
</div>

<script>
function MinhnhatdevShowLine(line) {
  document.getElementById('MinhnhatdevModalBody').textContent = line;
  document.getElementById('MinhnhatdevModal').style.display = 'flex';
}
function MinhnhatdevCopyModal() {
  navigator.clipboard.writeText(document.getElementById('MinhnhatdevModalBody').textContent).then(function(){ MinhnhatdevToast('Đã copy kết quả!', 'success'); });
}
</script>
<?php Minhnhatdev_page_foot(); ?>
