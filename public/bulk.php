<?php
require_once __DIR__ . '/Minhnhatdev_layout.php';

$admin = Minhnhatdev_require_admin();

function Minhnhatdev_bulk_json(array $d): void {
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($d, JSON_UNESCAPED_UNICODE);
    exit;
}

function Minhnhatdev_bulk_dir(): string {
    $dir = Minhnhatdev_BULK_DIR;
    if (!is_dir($dir)) {
        @mkdir($dir, 0775, true);
    }
    return $dir;
}

function Minhnhatdev_bulk_own_job(string $job): bool {
    return isset($_SESSION['Minhnhatdev_jobs'][$job]);
}

$Minhnhatdev_ajax = (string)($_REQUEST['ajax'] ?? '');

if ($Minhnhatdev_ajax === 'start' && $_SERVER['REQUEST_METHOD'] === 'POST') {
    Minhnhatdev_csrf_verify();
    $combo = (string)($_POST['combo'] ?? '');
    if (isset($_FILES['combo_file']) && is_uploaded_file($_FILES['combo_file']['tmp_name'])) {
        if ((int)$_FILES['combo_file']['size'] > 5 * 1024 * 1024) {
            Minhnhatdev_bulk_json(['ok' => false, 'detail' => 'File combo quá lớn (tối đa 5MB).']);
        }
        $combo .= "\n" . (string)file_get_contents($_FILES['combo_file']['tmp_name']);
    }
    $lines = preg_split('/\r\n|\r|\n/', $combo);
    $valid = 0;
    foreach ($lines as $ln) {
        $ln = trim($ln);
        if ($ln !== '' && (str_contains($ln, '|') || str_contains($ln, ':'))) $valid++;
    }
    if ($valid === 0) {
        Minhnhatdev_bulk_json(['ok' => false, 'detail' => 'Combo trống hoặc sai định dạng (mỗi dòng: taikhoan|matkhau hoặc taikhoan:matkhau).']);
    }
    if ($valid > 5000) {
        Minhnhatdev_bulk_json(['ok' => false, 'detail' => 'Tối đa 5000 dòng mỗi lần check hàng loạt.']);
    }

    $job = bin2hex(random_bytes(8));
    $dir = Minhnhatdev_bulk_dir();
    $comboPath = $dir . '/' . $job . '.combo.txt';
    $outPath = $dir . '/' . $job . '.ndjson';
    $pidPath = $dir . '/' . $job . '.pid';
    file_put_contents($comboPath, $combo);

    $cmd = 'cd ' . escapeshellarg(dirname(Minhnhatdev_BACKEND))
        . ' && nohup ' . escapeshellarg(Minhnhatdev_PYTHON) . ' ' . escapeshellarg(Minhnhatdev_BACKEND)
        . ' --bulk ' . escapeshellarg($comboPath);
    $proxyFile = Minhnhatdev_proxy_active_file();
    if ($proxyFile !== '') {
        $cmd .= ' --proxy ' . escapeshellarg($proxyFile);
    }
    $cmd .= ' > ' . escapeshellarg($outPath) . ' 2>/dev/null & echo $!';
    $pid = (int)trim((string)shell_exec($cmd));
    file_put_contents($pidPath, (string)$pid);

    $_SESSION['Minhnhatdev_jobs'][$job] = ['pid' => $pid, 'started' => time()];
    Minhnhatdev_bulk_json(['ok' => true, 'job' => $job, 'proxy' => $proxyFile !== '', 'lines' => $valid]);
}

if ($Minhnhatdev_ajax === 'status') {
    $job = preg_replace('/[^a-f0-9]/', '', (string)($_GET['job'] ?? ''));
    if (!$job || !Minhnhatdev_bulk_own_job($job)) {
        Minhnhatdev_bulk_json(['ok' => false, 'detail' => 'Job không hợp lệ.']);
    }
    $dir = Minhnhatdev_bulk_dir();
    $outPath = $dir . '/' . $job . '.ndjson';
    $pidPath = $dir . '/' . $job . '.pid';

    $events = [];
    $state = ['total' => 0, 'done' => 0, 'hits' => 0, 'fails' => 0, 'finished' => false, 'error' => ''];
    if (is_file($outPath)) {
        foreach (file($outPath, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) ?: [] as $line) {
            $ev = json_decode($line, true);
            if (!is_array($ev)) continue;
            $type = (string)($ev['type'] ?? '');
            if ($type === 'start') {
                $state['total'] = (int)($ev['total'] ?? 0);
            } elseif ($type === 'result') {
                $state['done'] = (int)($ev['done'] ?? 0);
                $state['total'] = (int)($ev['total'] ?? $state['total']);
                $state['hits'] = (int)($ev['hits'] ?? 0);
                $state['fails'] = (int)($ev['fails'] ?? 0);
                $events[] = [
                    'account' => (string)($ev['account'] ?? ''),
                    'status' => (string)($ev['status'] ?? ''),
                    'line' => (string)($ev['line'] ?? ''),
                    'tinh_trang' => (string)($ev['tinh_trang'] ?? ''),
                ];
            } elseif ($type === 'done') {
                $state['finished'] = true;
                $state['total'] = (int)($ev['total'] ?? $state['total']);
                $state['hits'] = (int)($ev['hits'] ?? $state['hits']);
                $state['fails'] = (int)($ev['fails'] ?? $state['fails']);
            } elseif ($type === 'error') {
                $state['error'] = (string)($ev['detail'] ?? 'unknown');
                $state['finished'] = true;
            }
        }
    }
    $running = false;
    if (!$state['finished'] && is_file($pidPath)) {
        $pid = (int)trim((string)file_get_contents($pidPath));
        $running = $pid > 0 && is_dir('/proc/' . $pid);
    }
    $state['ok'] = true;
    $state['running'] = $running;
    $state['results'] = array_slice($events, -300);
    Minhnhatdev_bulk_json($state);
}

if ($Minhnhatdev_ajax === 'stop' && $_SERVER['REQUEST_METHOD'] === 'POST') {
    Minhnhatdev_csrf_verify();
    $job = preg_replace('/[^a-f0-9]/', '', (string)($_POST['job'] ?? ''));
    if (!$job || !Minhnhatdev_bulk_own_job($job)) {
        Minhnhatdev_bulk_json(['ok' => false, 'detail' => 'Job không hợp lệ.']);
    }
    $pidPath = Minhnhatdev_bulk_dir() . '/' . $job . '.pid';
    if (is_file($pidPath)) {
        $pid = (int)trim((string)file_get_contents($pidPath));
        if ($pid > 0) {
            @shell_exec('kill ' . $pid . ' 2>/dev/null');
        }
    }
    Minhnhatdev_bulk_json(['ok' => true]);
}

$Minhnhatdev_proxyOn = Minhnhatdev_proxy_is_enabled() && Minhnhatdev_proxy_count() > 0;

Minhnhatdev_page_head('Check Hàng Loạt');
?>
<div class="card-verify" style="max-width: 1000px; text-align: left;">
  <div style="text-align: center; margin-bottom: 24px;">
    <div style="display: inline-flex; align-items: center; justify-content: center; padding: 16px; background-color: rgba(124,58,237,.08); border-radius: 20px; margin-bottom: 14px; color: #7c3aed; box-shadow: 0 10px 20px -5px rgba(124,58,237,.2);">
      <?= Minhnhatdev_icon('list', '', 32) ?>
    </div>
    <h3 style="font-weight: 800; color: #0f172a; margin: 0 0 6px 0; font-size: 20px;">Check Hàng Loạt (Combo File)</h3>
    <p style="color: #64748b; font-size: 13px; margin: 0;">Chỉ dành cho Admin — check nhiều tài khoản cùng lúc, realtime progress</p>
  </div>

  <div style="display:flex; gap:10px; flex-wrap:wrap; justify-content:center; margin-bottom:20px;">
    <span class="history-badge <?= $Minhnhatdev_proxyOn ? 'status-valid' : 'status-invalid' ?>" id="MinhnhatdevBulkProxyBadge">
      <?= Minhnhatdev_icon('proxy', '', 14) ?> Proxy: <strong><?= $Minhnhatdev_proxyOn ? Minhnhatdev_proxy_count() . ' proxy đang bật' : 'Tắt (IP trực tiếp)' ?></strong>
    </span>
    <?php if (!$Minhnhatdev_proxyOn): ?>
    <a href="/admin.php" class="history-badge" style="text-decoration:none;"><?= Minhnhatdev_icon('settings', '', 14) ?> Cấu hình proxy trong Admin</a>
    <?php endif; ?>
  </div>

  <div id="MinhnhatdevBulkSetup">
    <div style="margin-bottom: 14px;">
      <label style="display: block; font-size: 13px; font-weight: 700; color: #334155; margin-bottom: 8px;">
        <?= Minhnhatdev_icon('upload', '', 15) ?> Upload file combo (.txt) — hoặc dán trực tiếp bên dưới
      </label>
      <input id="MinhnhatdevComboFile" type="file" accept=".txt,text/plain" class="input-field" style="width:100%; border-radius:14px; padding:11px 16px; height:auto;">
    </div>
    <div style="margin-bottom: 16px;">
      <label style="display: block; font-size: 13px; font-weight: 700; color: #334155; margin-bottom: 8px;">Dán combo (mỗi dòng: <code>taikhoan|matkhau</code> hoặc <code>taikhoan:matkhau</code>)</label>
      <textarea id="MinhnhatdevComboText" rows="8" class="input-field" style="width:100%; border-radius:14px; padding:14px 16px; font-family:monospace; font-size:12px; height:auto; resize:vertical;" placeholder="acc1|pass1&#10;acc2:pass2&#10;u502376961|matkhau123"></textarea>
    </div>
    <button id="MinhnhatdevBulkStart" type="button" onclick="MinhnhatdevBulkStartJob()" class="btn-submit" style="width:100%; background:#7c3aed; border-color:#7c3aed; color:#fff; height:48px; font-size:14px;">
      <?= Minhnhatdev_icon('play', '', 16) ?> Bắt Đầu Check Hàng Loạt
    </button>
  </div>

  <div id="MinhnhatdevBulkRun" style="display:none; margin-top:4px;">
    <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:16px; padding:18px; margin-bottom:16px;">
      <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:12px;">
        <strong style="color:#0f172a; font-size:14px;" id="MinhnhatdevBulkStatusText">Đang khởi tạo...</strong>
        <div style="display:flex; gap:8px;">
          <button type="button" onclick="MinhnhatdevBulkStopJob()" id="MinhnhatdevBulkStopBtn" class="btn-submit" style="height:32px; padding:0 14px; font-size:11px; background:#fef2f2; border-color:#fecaca; color:#b91c1c;">
            <?= Minhnhatdev_icon('stop', '', 13) ?> Dừng
          </button>
          <button type="button" onclick="MinhnhatdevBulkReset()" class="btn-submit" style="height:32px; padding:0 14px; font-size:11px;">
            <?= Minhnhatdev_icon('refresh', '', 13) ?> Job mới
          </button>
        </div>
      </div>
      <div style="height:10px; background:#e2e8f0; border-radius:9999px; overflow:hidden;">
        <div id="MinhnhatdevBulkBar" style="height:100%; width:0%; background:linear-gradient(90deg,#7c3aed,#3b82f6); border-radius:9999px; transition:width .3s;"></div>
      </div>
      <div style="display:flex; gap:14px; flex-wrap:wrap; margin-top:12px; font-size:12px; font-weight:700;">
        <span style="color:#334155;">Tiến độ: <span id="MinhnhatdevBulkDone">0</span>/<span id="MinhnhatdevBulkTotal">0</span></span>
        <span style="color:#047857;">HIT: <span id="MinhnhatdevBulkHits">0</span></span>
        <span style="color:#b91c1c;">Fail: <span id="MinhnhatdevBulkFails">0</span></span>
      </div>
    </div>

    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; flex-wrap:wrap; gap:8px;">
      <strong style="color:#0f172a; font-size:13px;">Kết quả realtime</strong>
      <button type="button" onclick="MinhnhatdevBulkCopyHits()" class="btn-submit" style="height:32px; padding:0 14px; font-size:11px;">
        <?= Minhnhatdev_icon('copy', '', 13) ?> Copy tất cả HIT (<span id="MinhnhatdevBulkHitsCopy">0</span>)
      </button>
    </div>
    <div id="MinhnhatdevBulkResults" style="display:flex; flex-direction:column; gap:8px; max-height:480px; overflow-y:auto;"></div>
  </div>
</div>

<script>
var MinhnhatdevBulkJob = null;
var MinhnhatdevBulkPoll = null;
var MinhnhatdevBulkHitLines = [];
var MinhnhatdevBulkSvg = {
  hit: <?= Minhnhatdev_icon_js('double-check', 14) ?>,
  miss: <?= Minhnhatdev_icon_js('cross', 14) ?>,
  wait: <?= Minhnhatdev_icon_js('time', 14) ?>
};

function MinhnhatdevBulkEsc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}

function MinhnhatdevBulkStartJob() {
  var combo = document.getElementById('MinhnhatdevComboText').value;
  var fileInput = document.getElementById('MinhnhatdevComboFile');
  if (!combo.trim() && !fileInput.files.length) {
    MinhnhatdevToast('Vui lòng dán combo hoặc chọn file combo.', 'warning');
    return;
  }
  var fd = new FormData();
  fd.append('ajax', 'start');
  fd.append('combo', combo);
  fd.append('csrf', '<?= Minhnhatdev_csrf_token() ?>');
  if (fileInput.files.length) fd.append('combo_file', fileInput.files[0]);

  document.getElementById('MinhnhatdevBulkStart').disabled = true;
  fetch('/bulk.php', { method: 'POST', body: fd })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (!d.ok) {
        MinhnhatdevToast(d.detail || 'Không thể khởi tạo job.', 'error');
        document.getElementById('MinhnhatdevBulkStart').disabled = false;
        return;
      }
      MinhnhatdevBulkJob = d.job;
      MinhnhatdevBulkHitLines = [];
      document.getElementById('MinhnhatdevBulkSetup').style.display = 'none';
      document.getElementById('MinhnhatdevBulkRun').style.display = 'block';
      document.getElementById('MinhnhatdevBulkResults').innerHTML = '';
      MinhnhatdevToast('Đã khởi chạy job với ' + d.lines + ' dòng' + (d.proxy ? ' (đang dùng proxy)' : ''), 'success');
      MinhnhatdevBulkPoll = setInterval(MinhNhatdevBulkPollStatus, 1500);
      MinhnhatdevBulkPollStatus();
    })
    .catch(function (e) {
      MinhnhatdevToast('Lỗi kết nối: ' + e, 'error');
      document.getElementById('MinhnhatdevBulkStart').disabled = false;
    });
}

function MinhnhatdevBulkPollStatus() {
  if (!MinhnhatdevBulkJob) return;
  fetch('/bulk.php?ajax=status&job=' + MinhnhatdevBulkJob)
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (!d.ok) return;
      document.getElementById('MinhnhatdevBulkDone').textContent = d.done;
      document.getElementById('MinhnhatdevBulkTotal').textContent = d.total;
      document.getElementById('MinhnhatdevBulkHits').textContent = d.hits;
      document.getElementById('MinhnhatdevBulkFails').textContent = d.fails;
      document.getElementById('MinhnhatdevBulkHitsCopy').textContent = d.hits;
      var pct = d.total > 0 ? Math.round(d.done / d.total * 100) : 0;
      document.getElementById('MinhnhatdevBulkBar').style.width = pct + '%';
      document.getElementById('MinhnhatdevBulkStatusText').textContent = d.finished
        ? (d.error ? ('Lỗi: ' + d.error) : ('Hoàn tất! ' + d.hits + ' HIT / ' + d.total + ' tài khoản'))
        : ('Đang check... ' + pct + '%');

      MinhnhatdevBulkHitLines = [];
      var html = '';
      var results = (d.results || []).slice().reverse();
      for (var i = 0; i < results.length; i++) {
        var r = results[i];
        if (r.status === 'HIT' && r.line) MinhnhatdevBulkHitLines.push(r.line);
        var isHit = r.status === 'HIT';
        html += '<div style="padding:10px 14px; border-radius:12px; font-size:12px; border:1px solid '
          + (isHit ? 'rgba(16,185,129,.35); background:rgba(16,185,129,.06);' : 'rgba(226,232,240,.9); background:#fff;')
          + '"><div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">'
          + '<span style="display:inline-flex; color:' + (isHit ? '#047857' : '#b91c1c') + ';">' + (isHit ? MinhnhatdevBulkSvg.hit : MinhnhatdevBulkSvg.miss) + '</span>'
          + '<strong style="font-family:monospace;">' + MinhnhatdevBulkEsc(r.account) + '</strong>'
          + '<span style="font-weight:700; color:' + (isHit ? '#047857' : '#b91c1c') + ';">' + MinhnhatdevBulkEsc(r.status) + '</span>'
          + (r.tinh_trang ? '<span style="background:#d1fae5; color:#047857; border-radius:8px; padding:1px 8px; font-size:10px; font-weight:800;">' + MinhnhatdevBulkEsc(r.tinh_trang) + '</span>' : '')
          + '</div>'
          + (isHit && r.line ? '<div class="Minhnhatdev-hitline" style="margin-top:8px; padding:10px 12px; font-size:11px;">' + MinhnhatdevBulkEsc(r.line) + '</div>' : '')
          + '</div>';
      }
      document.getElementById('MinhnhatdevBulkResults').innerHTML = html;

      if (d.finished) {
        clearInterval(MinhNhatdevBulkPoll);
        document.getElementById('MinhnhatdevBulkStopBtn').disabled = true;
        MinhnhatdevToast(d.error ? ('Job lỗi: ' + d.error) : ('Check hàng loạt hoàn tất: ' + d.hits + ' HIT!'), d.error ? 'error' : 'success');
      }
    })
    .catch(function () {});
}

function MinhnhatdevBulkStopJob() {
  if (!MinhnhatdevBulkJob) return;
  var fd = new FormData();
  fd.append('ajax', 'stop');
  fd.append('job', MinhnhatdevBulkJob);
  fd.append('csrf', '<?= Minhnhatdev_csrf_token() ?>');
  fetch('/bulk.php', { method: 'POST', body: fd }).then(function () {
    MinhnhatdevToast('Đã gửi lệnh dừng job.', 'warning');
    setTimeout(MinhNhatdevBulkPollStatus, 1500);
  });
}

function MinhnhatdevBulkReset() {
  clearInterval(MinhNhatdevBulkPoll);
  MinhnhatdevBulkJob = null;
  document.getElementById('MinhnhatdevBulkRun').style.display = 'none';
  document.getElementById('MinhnhatdevBulkSetup').style.display = 'block';
  document.getElementById('MinhnhatdevBulkStart').disabled = false;
  document.getElementById('MinhnhatdevBulkStopBtn').disabled = false;
}

function MinhnhatdevBulkCopyHits() {
  if (!MinhnhatdevBulkHitLines.length) {
    MinhnhatdevToast('Chưa có HIT nào để copy.', 'warning');
    return;
  }
  navigator.clipboard.writeText(MinhNhatdevBulkHitLines.join('\n')).then(function () {
    MinhnhatdevToast('Đã copy ' + MinhnhatdevBulkHitLines.length + ' dòng HIT!', 'success');
  });
}
</script>
<?php Minhnhatdev_page_foot(); ?>
