<?php
require_once __DIR__ . '/Minhnhatdev_layout.php';

$Minhnhatdev_err = trim((string)($_GET['err'] ?? ''));
$Minhnhatdev_user = Minhnhatdev_require_login();
$Minhnhatdev_remaining = Minhnhatdev_quota_remaining($Minhnhatdev_user);
$Minhnhatdev_used = Minhnhatdev_quota_used((int)$Minhnhatdev_user['id']);
$Minhnhatdev_proxy_count = Minhnhatdev_proxy_is_enabled() ? Minhnhatdev_proxy_count() : 0;

Minhnhatdev_page_head('Check Tài Khoản Garena');
?>
<div class="card-verify Minhnhatdev-card-main" style="max-width: 860px;">
  <div style="text-align: center; margin-bottom: 26px;">
    <div style="display: inline-flex; align-items: center; justify-content: center; padding: 18px; background-color: rgba(59, 130, 246, 0.08); border-radius: 20px; margin-bottom: 16px; color: #3b82f6; box-shadow: 0 10px 20px -5px rgba(59, 130, 246, 0.2);">
      <?= Minhnhatdev_icon('shield-search', '', 40) ?>
    </div>
    <h3 style="font-weight: 800; color: #0f172a; margin: 0 0 8px 0; font-size: 22px; letter-spacing: -0.5px;">Check Tài Khoản Garena / Liên Quân</h3>
    <p style="color: #64748b; font-size: 13.5px; margin: 0; line-height: 1.5;">Nhập tài khoản Garena để bóc tách thông tin: Rank, Skin, Sò, Quân Huy, Bảo mật, Lịch sử đấu...</p>
  </div>

  <div style="display: flex; gap: 10px; flex-wrap: wrap; justify-content: center; margin-bottom: 22px;">
    <span class="history-badge <?= $Minhnhatdev_remaining > 0 ? 'status-valid' : 'status-invalid' ?>">
      <?= Minhnhatdev_icon('time', '', 14) ?> Còn lại hôm nay: <strong><?= $Minhnhatdev_remaining ?></strong> / <?= (int)$Minhnhatdev_user['daily_quota'] ?> lượt
    </span>
    <span class="history-badge">
      <?= Minhnhatdev_icon('double-check', '', 14) ?> Đã dùng: <strong><?= $Minhnhatdev_used ?></strong> lượt
    </span>
    <span class="history-badge <?= $Minhnhatdev_proxy_count > 0 ? 'status-valid' : '' ?>">
      <?= Minhnhatdev_icon('proxy', '', 14) ?> Proxy: <strong><?= $Minhnhatdev_proxy_count > 0 ? $Minhnhatdev_proxy_count . ' proxy đang bật' : 'Tắt (IP trực tiếp)' ?></strong>
    </span>
  </div>

  <?php if ($Minhnhatdev_err): ?>
  <div class="Minhnhatdev-alert Minhnhatdev-alert-err"><?= Minhnhatdev_icon('info', '', 16) ?> <?= e($Minhnhatdev_err) ?></div>
  <script>window.addEventListener('load', function(){ MinhnhatdevToast(<?= json_encode($Minhnhatdev_err) ?>, 'error'); });</script>
  <?php endif; ?>

  <form id="MinhnhatdevCheckForm" onsubmit="return MinhnhatdevSubmitCheck(event)">
    <div style="margin-bottom: 14px;">
      <label style="display: block; font-size: 13px; font-weight: 700; color: #334155; margin-bottom: 8px;">Tài khoản Garena</label>
      <input id="MinhnhatdevAccount" type="text" class="input-field" style="width:100%; border-radius:14px;" placeholder="vd: u502376961 hoặc nhatminh3001" autocomplete="off" required <?= $Minhnhatdev_remaining <= 0 ? 'disabled' : '' ?>>
    </div>
    <div style="margin-bottom: 18px;">
      <label style="display: block; font-size: 13px; font-weight: 700; color: #334155; margin-bottom: 8px;">Mật khẩu</label>
      <div class="input-group-responsive">
        <input id="MinhnhatdevPassword" type="password" class="input-field" placeholder="Mật khẩu tài khoản" autocomplete="off" required <?= $Minhnhatdev_remaining <= 0 ? 'disabled' : '' ?>>
        <button id="MinhnhatdevBtn" type="submit" class="btn-submit" <?= $Minhnhatdev_remaining <= 0 ? 'disabled style="opacity:.5; cursor:not-allowed;"' : '' ?>>
          <?= Minhnhatdev_icon('shield-search', '', 16) ?> <span class="btn-text">Check Ngay</span>
        </button>
      </div>
    </div>

    <?php if ($Minhnhatdev_remaining <= 0): ?>
    <div class="Minhnhatdev-alert Minhnhatdev-alert-err">
      <?= Minhnhatdev_icon('info', '', 16) ?> Bạn đã dùng hết <?= (int)$Minhnhatdev_user['daily_quota'] ?> lượt check hôm nay. Quay lại vào ngày mai hoặc liên hệ admin để nâng hạn mức.
    </div>
    <?php endif; ?>

    <div id="MinhnhatdevLoader" style="display: none; width: 100%; flex-direction: column; gap: 12px; padding: 20px; border-radius: 16px; background-color: #f8fafc; border: 1px solid #edf2f7; box-sizing: border-box; margin-top: 20px;">
      <div style="display: flex; align-items: center; gap: 10px;">
        <div class="shimmer-bg" style="width: 24px; height: 24px; border-radius: 50%;"></div>
        <div style="font-size: 13px; color: #64748b; font-weight: 600;">Đang đăng nhập &amp; bóc tách dữ liệu tài khoản... <span id="MinhnhatdevTimer">0</span>s (có thể mất 30-120 giây)</div>
      </div>
      <div style="display: flex; flex-direction: column; gap: 10px; border-top: 1px dashed rgba(226,232,240,0.8); padding-top: 16px;">
        <div class="shimmer-bg" style="width: 90%; height: 12px; border-radius: 4px;"></div>
        <div class="shimmer-bg" style="width: 70%; height: 12px; border-radius: 4px;"></div>
        <div class="shimmer-bg" style="width: 80%; height: 12px; border-radius: 4px;"></div>
      </div>
    </div>

    <div id="MinhnhatdevResult" style="display: none; margin-top: 20px;"></div>
  </form>

  <div style="margin-top: 25px; padding: 18px; border-radius: 16px; background-color: #f8fafc; border: 1px solid rgba(226, 232, 240, 0.8); box-sizing: border-box;">
    <h6 style="font-weight: 700; color: #1e293b; font-size: 13px; margin: 0 0 8px 0; display: flex; align-items: center; gap: 6px;">
      <span style="color:#3b82f6; display:inline-flex;"><?= Minhnhatdev_icon('info', '', 16) ?></span> Lưu ý quan trọng
    </h6>
    <p style="color: #64748b; font-size: 12px; margin: 0; line-height: 1.65;">
      Mỗi lượt check sẽ trừ 1 trong <?= Minhnhatdev_DAILY_LIMIT ?> lượt miễn phí mỗi ngày của bạn (kể cả check thất bại do sai mật khẩu). Dữ liệu tài khoản chỉ được dùng cho mục đích kiểm tra thông tin, không lưu mật khẩu vào hệ thống.
    </p>
  </div>
</div>

<script>
var MinhnhatdevTimerInt = null;
var MinhnhatdevSvg = {
  quota: <?= Minhnhatdev_icon_js('time', 14) ?>,
  hit: <?= Minhnhatdev_icon_js('double-check', 20) ?>,
  err: <?= Minhnhatdev_icon_js('cross', 18) ?>,
  copy: <?= Minhnhatdev_icon_js('copy', 14) ?>
};

function MinhnhatdevSubmitCheck(ev) {
  ev.preventDefault();
  var btn = document.getElementById('MinhnhatdevBtn');
  var loader = document.getElementById('MinhnhatdevLoader');
  var result = document.getElementById('MinhnhatdevResult');
  var acc = document.getElementById('MinhnhatdevAccount').value.trim();
  var pw = document.getElementById('MinhnhatdevPassword').value;
  if (!acc || !pw) return false;

  btn.disabled = true;
  btn.style.opacity = '.5';
  loader.style.display = 'flex';
  result.style.display = 'none';
  var t0 = Date.now();
  MinhnhatdevTimerInt = setInterval(function () {
    document.getElementById('MinhnhatdevTimer').textContent = Math.floor((Date.now() - t0) / 1000);
  }, 1000);

  var fd = new FormData();
  fd.append('account', acc);
  fd.append('password', pw);
  fd.append('csrf', '<?= Minhnhatdev_csrf_token() ?>');

  fetch('/check.php', { method: 'POST', body: fd })
    .then(function (r) { return r.json(); })
    .then(function (d) { MinhnhatdevRenderResult(d); })
    .catch(function (e) {
      MinhnhatdevRenderResult({ ok: false, status: 'ERROR', detail: 'Lỗi kết nối máy chủ: ' + e });
    })
    .finally(function () {
      clearInterval(MinhnhatdevTimerInt);
      btn.disabled = false;
      btn.style.opacity = '1';
      loader.style.display = 'none';
    });
  return false;
}

function MinhnhatdevRenderResult(d) {
  var box = document.getElementById('MinhnhatdevResult');
  var quota = document.querySelector('.history-badge.status-valid, .history-badge.status-invalid');
  if (typeof d.remaining !== 'undefined' && quota) {
    quota.innerHTML = MinhnhatdevSvg.quota + ' Còn lại hôm nay: <strong>' + d.remaining + '</strong> / ' + d.quota + ' lượt';
    quota.className = 'history-badge ' + (d.remaining > 0 ? 'status-valid' : 'status-invalid');
  }
  var html = '';
  if (d.status === 'HIT') {
    MinhnhatdevToast('HIT! Đăng nhập thành công tài khoản ' + (d.account || ''), 'success');
    html = '<div style="padding: 16px; border-radius: 16px; background: rgba(16,185,129,.06); border: 1px solid rgba(16,185,129,.3);">'
      + '<div style="display:flex; align-items:center; gap:8px; margin-bottom:12px; color:#047857; font-weight:800; font-size:15px; flex-wrap:wrap;">'
      + '<span style="display:inline-flex;">' + MinhnhatdevSvg.hit + '</span> HIT - Đăng nhập thành công! '
      + (d.tinh_trang ? '<span style="background:#d1fae5; color:#047857; border-radius:8px; padding:2px 10px; font-size:11px;">' + MinhnhatdevEsc(d.tinh_trang) + '</span>' : '')
      + '</div>'
      + '<div class="Minhnhatdev-hitline">' + MinhnhatdevEsc(d.line || '(không có dữ liệu)') + '</div>'
      + '<button type="button" onclick="MinhnhatdevCopyLine()" class="btn-submit" style="margin-top:12px; height:36px; font-size:12px; display:inline-flex; align-items:center; gap:6px;"><span style="display:inline-flex;">' + MinhnhatdevSvg.copy + '</span> Copy kết quả</button>'
      + '</div>';
  } else {
    var msg = d.detail || d.line || d.status || 'Không rõ lỗi';
    var label = { MISS: 'Sai tài khoản hoặc mật khẩu', INVALID: 'Tài khoản không hợp lệ', CAPTCHA: 'Bị chặn Captcha', TIMEOUT: 'Hết thời gian chờ', ERROR: 'Lỗi hệ thống', QUOTA: 'Hết lượt check' }[d.status] || d.status;
    MinhnhatdevToast(label + ': ' + (d.account || ''), 'error');
    html = '<div style="padding: 16px; border-radius: 16px; background: rgba(239,68,68,.06); border: 1px solid rgba(239,68,68,.3);">'
      + '<div style="display:flex; align-items:center; gap:8px; margin-bottom:8px; color:#b91c1c; font-weight:800; font-size:14px;">'
      + '<span style="display:inline-flex;">' + MinhnhatdevSvg.err + '</span> ' + MinhnhatdevEsc(label) + '</div>'
      + '<div style="font-size:12.5px; color:#7f1d1d; word-break:break-all;">' + MinhnhatdevEsc(msg) + '</div>'
      + '</div>';
  }
  box.innerHTML = html;
  box.style.display = 'block';
  window.MinhnhatdevLastLine = d.line || '';
}

function MinhnhatdevEsc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}

function MinhnhatdevCopyLine() {
  if (!window.MinhnhatdevLastLine) return;
  navigator.clipboard.writeText(window.MinhnhatdevLastLine).then(function () {
    MinhnhatdevToast('Đã copy kết quả vào clipboard!', 'success');
  });
}
</script>
<?php Minhnhatdev_page_foot(); ?>
