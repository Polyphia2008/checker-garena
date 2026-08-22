# -*- coding: utf-8 -*-
"""
Data integrity for Garena checker:
  - chặn fake / rác field (rank số thuần, error string, empty HIT)
  - save an toàn (lock + flush + fsync + optional JSONL dump)
  - dedupe trong session
  - quality flags: _data_quality, _fake_fields_stripped
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import unicodedata
from typing import Any, Dict, Optional, Set

_SAVE_LOCK = threading.RLock()
_DEDUP_LOCK = threading.Lock()
_SAVED_LINE_HASHES: Set[str] = set()
_MAX_DEDUP_ENTRIES = 2_000_000

_FAKE_RANK_RE = re.compile(
    r"^(?:\d+|null|none|undefined|unknown|n/?a|error|fail|timeout|captcha|"
    r"login|password|username|user|pass|admin|test|demo|sample)$",
    re.I,
)
_REAL_RANK_HINT = re.compile(
    r"(dong|đồng|bac|bạc|vang|vàng|bach\s*kim|b\.?\s*kim|kim\s*cuong|k\.?\s*cuong|"
    r"tinh\s*anh|t\.?\s*anh|cao\s*thu|chien\s*tuong|chien\s*than|thach\s*dau|"
    r"bronze|silver|gold|platinum|diamond|master|conqueror|commander)",
    re.I,
)
_ERR_MSG_HINT = re.compile(
    r"(error|exception|traceback|timeout|proxy|forbidden|denied|not\s*found|"
    r"invalid|captcha|rate.?limit|html>|<!doctype)",
    re.I,
)


def _fold(s: str) -> str:
    t = unicodedata.normalize("NFKD", str(s or "").lower()).encode("ascii", "ignore").decode("ascii")
    t = re.sub(r"[_\-]+", " ", t)
    t = re.sub(r"[^a-z0-9.\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def is_real_rank_name(name) -> bool:
    """True only if looks like a real AOV rank label (not id / error)."""
    if name is None:
        return False
    s = str(name).strip()
    if not s or len(s) > 80:
        return False
    if s.isdigit():
        return False
    if _FAKE_RANK_RE.match(s):
        return False
    if _ERR_MSG_HINT.search(s):
        return False
    f = _fold(s)
    if _REAL_RANK_HINT.search(f):
        return True
    if re.search(r"[a-zàáạảãâăèéêìíòóôơùúưýđ]", s, re.I) and not s.isdigit():
        letters = re.sub(r"[\d\s\*★☆sao\.]", "", s, flags=re.I)
        if len(letters) >= 2 and "@" not in s and "://" not in s and "/" not in s:
            return True
    return False


def is_plausible_player_name(name) -> bool:
    if name is None:
        return False
    s = str(name).strip()
    if not s or len(s) > 64 or len(s) < 1:
        return False
    if s.isdigit():
        return False
    if _ERR_MSG_HINT.search(s):
        return False
    if s.lower() in ("null", "none", "undefined", "unknown"):
        return False
    if "://" in s:
        return False
    return True


def is_plausible_mask(s, kind: str = "email") -> bool:
    if s is None:
        return False
    t = str(s).strip()
    if not t or t.lower() in ("null", "none", "undefined"):
        return False
    if kind == "email":
        return "@" in t and len(t) >= 5
    if kind == "phone":
        digits = re.sub(r"\D", "", t)
        if t.startswith("+"):
            return len(digits) >= 8
        return len(digits) >= 6 or ("*" in t and len(t) >= 6)
    return len(t) >= 2


def strip_fake_rank_fields(result: dict) -> dict:
    """Remove fake rank display; keep rank_id for later resolve."""
    if not isinstance(result, dict):
        return result
    rank = str(result.get("aov_rank") or "").strip()
    if rank and not is_real_rank_name(rank):
        if rank.isdigit() and result.get("aov_rank_id") is None:
            try:
                result["aov_rank_id"] = int(rank)
            except Exception:
                pass
        result["aov_rank"] = ""
        if not is_real_rank_name(result.get("aov_rank") or ""):
            result["_fake_rank_stripped"] = True
    # clean empty after strip
    if not is_real_rank_name(result.get("aov_rank") or ""):
        result["aov_rank"] = str(result.get("aov_rank") or "").strip()
        if not result["aov_rank"]:
            try:
                stars = int(result.get("aov_rank_stars") or 0)
            except Exception:
                stars = 0
            if stars and not result.get("aov_rank_id"):
                result["aov_rank_stars"] = 0

    name = result.get("aov_name")
    if name and not is_plausible_player_name(name):
        result["aov_name"] = ""
        result["_fake_name_stripped"] = True
    return result


def sanitize_hit_result(result: dict) -> dict:
    """
    Chuẩn hoá HIT trước save/print:
      - bỏ field fake
      - gắn _data_quality: ok | partial | incomplete | invalid
      - không bịa status HIT nếu thiếu account/password
    """
    if not isinstance(result, dict):
        return {}
    out = dict(result)
    acc = str(out.get("account") or "").strip()
    pw = str(out.get("password") or "").strip()
    if not acc or not pw:
        out["status"] = "ERROR"
        out["detail"] = (out.get("detail") or "") + " | missing_account_or_password"
        out["_data_quality"] = "invalid"
        return out

    strip_fake_rank_fields(out)

    if out.get("masked_email") and not is_plausible_mask(out.get("masked_email"), "email"):
        out["masked_email"] = ""
    if out.get("masked_phone") and not is_plausible_mask(out.get("masked_phone"), "phone"):
        out["masked_phone"] = ""
    if out.get("aov_prefill_mobile") and not is_plausible_mask(out.get("aov_prefill_mobile"), "phone"):
        out["aov_prefill_mobile"] = ""

    gc = str(out.get("garena_created") or "")
    if "1970" in gc or "1969" in gc:
        out.pop("garena_created", None)
        out.pop("garena_created_ts", None)

    sk = out.get("aov_skins")
    if isinstance(sk, dict):
        def _si(v, d=0):
            try:
                if v is None:
                    return d
                if isinstance(v, str) and v.strip().lower() in ("none", "null", ""):
                    return d
                return int(float(v))
            except Exception:
                return d

        sk["cp"] = _si(sk.get("cp"), 0)
        sk["total_skins"] = _si(sk.get("total_skins"), 0)
        sk["total_champs"] = _si(sk.get("total_champs"), 0)
        tot = sk["total_skins"]
        if tot <= 0 and not sk.get("ownedItemIdList") and not sk.get("cp"):
            out["_skins_empty"] = True
        out["aov_skins"] = sk

    shells_raw = out.get("shells")
    if shells_raw is None or str(shells_raw).lower() in ("none", "null"):
        out["shells"] = 0
    else:
        try:
            out["shells"] = int(float(shells_raw or 0))
        except Exception:
            out["shells"] = 0

    status = out.get("status") or ""
    if status != "HIT":
        out["_data_quality"] = out.get("_data_quality") or "non_hit"
        return out

    has_sec = bool(out.get("_acct_sec_ok"))
    has_tcp_sec = bool(out.get("_tcp_acct_ok"))

    try:
        _sk_tot = int((out.get("aov_skins") or {}).get("total_skins") or 0) if isinstance(out.get("aov_skins"), dict) else 0
    except Exception:
        _sk_tot = 0
    try:
        _lv = int(out.get("aov_level") or 0)
    except Exception:
        _lv = 0

    has_game = bool(
        is_real_rank_name(out.get("aov_rank") or "")
        or is_plausible_player_name(out.get("aov_name") or "")
        or _sk_tot > 0
        or _lv > 0
        or str(out.get("aov_server") or "").strip()
        or out.get("recent_games")
        or out.get("recent_game_names")
    )
    has_bind = bool(
        is_plausible_mask(out.get("masked_email"), "email")
        or is_plausible_mask(out.get("masked_phone"), "phone")
        or is_plausible_mask(out.get("aov_prefill_mobile"), "phone")
        or out.get("fb_linked")
        or out.get("password_set")
        or str(out.get("idcard") or "").replace("*", "").strip()
    )

    incomplete = bool(out.get("_info_fetch_incomplete"))
    if incomplete or (not has_sec and not has_tcp_sec and not has_bind and not has_game):
        out["_data_quality"] = "incomplete"
        out["_fetch_incomplete"] = True
    elif has_sec or has_tcp_sec:
        out["_data_quality"] = "ok"
        out["_fetch_incomplete"] = False
    else:
        out["_data_quality"] = "partial"
        out["_acct_sec_missing"] = True
        out["_fetch_incomplete"] = False

    # ban uncertain if no kientuong payload
    ban = out.get("aov_banned")
    if ban is None or str(ban).strip() == "":
        if not out.get("_kt_player"):
            out["aov_banned"] = "NO"
            out["_ban_uncertain"] = True

    if out.get("aov_reg_time") is None:
        pass

    out["_sanitized_at"] = int(time.time())
    return out


def hit_is_saveable(result: dict) -> bool:
    """HIT có account:pass tối thiểu — luôn save được (tránh mất data)."""
    if not isinstance(result, dict):
        return False
    if result.get("status") != "HIT":
        return True
    acc = str(result.get("account") or "").strip()
    pw = str(result.get("password") or "").strip()
    return bool(acc and pw)


def quality_tag(result: dict) -> str:
    q = result.get("_data_quality")
    return str(q) if q else "unknown"


def _line_hash(filename: str, line: str) -> str:
    raw = f"{filename}\0{line}".encode("utf-8", errors="replace")
    return hashlib.sha1(raw).hexdigest()


def safe_append_line(path: str, line: str, dedupe: bool = True, fsync: bool = True) -> bool:
    """
    Append 1 line an toàn. Return False nếu skip (dup) hoặc fail.
    """
    text = line if line.endswith("\n") else line + "\n"
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)

    h = _line_hash(path, text) if dedupe else None
    if h:
        with _DEDUP_LOCK:
            if h in _SAVED_LINE_HASHES:
                return False
            if len(_SAVED_LINE_HASHES) > _MAX_DEDUP_ENTRIES:
                # drop ~half oldest (set has no order — clear half randomly via pop)
                for _ in range(len(_SAVED_LINE_HASHES) // 2):
                    try:
                        _SAVED_LINE_HASHES.pop()
                    except KeyError:
                        break
            _SAVED_LINE_HASHES.add(h)

    try:
        with _SAVE_LOCK:
            with open(path, "a", encoding="utf-8", newline="\n") as f:
                f.write(text)
                f.flush()
                if fsync:
                    try:
                        os.fsync(f.fileno())
                    except Exception:
                        pass
        return True
    except Exception:
        if h:
            with _DEDUP_LOCK:
                _SAVED_LINE_HASHES.discard(h)
        return False


def safe_append_jsonl(path: str, obj: dict, dedupe_key: str = "") -> bool:
    """Append full HIT object as JSONL for recovery (không mất field)."""
    try:
        # meta flags luôn giữ (kể cả tên bắt đầu _)
        _KEEP_META = {
            "_acct_sec_ok",
            "_tcp_acct_ok",
            "_info_fetch_incomplete",
            "_data_quality",
            "_fetch_incomplete",
            "_fetch_blocked",
            "_skins_fetch_incomplete",
            "_needs_proxy_recheck",
            "aov_rank_source",
            "_extra_fields_applied",
            "_sanitized_at",
            "_kgcamp_season",
        }
        clean: Dict[str, Any] = {}
        for k, v in (obj or {}).items():
            if k.startswith("_tcp") or k in ("debug", "_kt_player", "aov_user_info", "_extra_discovered"):
                if k in _KEEP_META:
                    clean[k] = v
                continue
            if k.startswith("_") and k not in _KEEP_META:
                # bỏ dump path / internal noise — không bỏ account data
                if k in ("_api_dump_paths", "_info_fetch_order", "_info_fetch_error",
                         "_login_method", "_http_session_key", "_sale_redirect",
                         "_kgcamp_rank", "_last_login_meta"):
                    if k == "_info_fetch_error" and v:
                        clean[k] = str(v)[:200]
                    elif k in ("_login_method",) and v:
                        clean[k] = v
                continue
            if isinstance(v, (str, int, float, bool)) or v is None:
                clean[k] = v
            elif isinstance(v, dict):
                if k == "aov_skins":
                    clean[k] = {
                        kk: v.get(kk)
                        for kk in (
                            "total_skins", "total_champs", "ss", "sss", "anime",
                            "other", "cp", "_skins_ok",
                            "new_skins_count", "recent_skins_count",
                        )
                        if kk in v
                    }
                elif k == "aov_rank_entry" and isinstance(v, dict):
                    clean[k] = {kk: v.get(kk) for kk in ("name", "id", "stars", "star") if kk in v}
                elif k == "_kgcamp_season":
                    clean[k] = {
                        kk: v.get(kk)
                        for kk in (
                            "season_rank", "season_rank_id", "season_stars",
                            "season_winrate", "season_battles", "season_wins",
                            "season_mvp", "season_heroes_count",
                        )
                        if kk in v
                    }
                    _th = v.get("top_heroes")
                    if isinstance(_th, list) and _th:
                        clean[k]["top_heroes"] = _th[:6]
            elif isinstance(v, (list, tuple)):
                if k in ("recent_game_names", "login_history", "sensitive_ops"):
                    clean[k] = list(v)[:10]
        # guarantee identity
        if "account" not in clean and obj.get("account"):
            clean["account"] = obj.get("account")
        if "password" not in clean and obj.get("password"):
            clean["password"] = obj.get("password")
        if "status" not in clean:
            clean["status"] = obj.get("status") or "HIT"
        line = json.dumps(clean, ensure_ascii=False, separators=(",", ":"))
        return safe_append_line(path, line, dedupe=True, fsync=True)
    except Exception:
        return False


def classify_rank_bucket(rank_raw: str) -> str:
    """
    Return stable bucket or '' if not classifiable (prevents fake file dumps).
    """
    if not is_real_rank_name(rank_raw):
        return ""
    f = _fold(rank_raw)
    if "chien tuong" in f:
        return "chien_tuong"
    if "chien than" in f or "thach dau" in f:
        return "chien_than"
    if "cao thu" in f:
        return "cao_thu"
    if "tinh anh" in f or re.search(r"\bt\s*\.?\s*anh\b", f):
        return "tinh_anh"
    if "kim cuong" in f or re.search(r"\bk\s*\.?\s*cuong\b", f):
        return "kim_cuong"
    if "bach kim" in f or re.search(r"\bb\s*\.?\s*kim\b", f):
        return "bach_kim"
    if "vang" in f:
        return "vang"
    if re.search(r"\bbac\b", f):
        return "bac"
    if "dong" in f:
        return "dong"
    return "other"
