# -*- coding: utf-8 -*-
"""
Module Định Dạng & Lưu Kết Quả (HIT Logger & Result Writer).
- Định dạng dòng HIT chuẩn 100% theo mẫu với đánh số thứ tự --- Tài khoản #N ---
- Thread-safe file saving với fsync() và tích hợp data_guard.py.
"""
from __future__ import annotations

import os
import re
import threading
from typing import Any, Dict

import data_guard
from skin_engine import get_hero_name

_SAVE_LOCK = threading.RLock()
_HIT_COUNTER_LOCK = threading.Lock()
_HIT_COUNTER: int = 0


def _get_next_hit_idx(hit_path: str) -> int:
    global _HIT_COUNTER
    with _HIT_COUNTER_LOCK:
        if _HIT_COUNTER == 0 and os.path.isfile(hit_path):
            try:
                with open(hit_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if line.startswith("--- Tài khoản #"):
                            m = re.search(r"--- Tài khoản #(\d+) ---", line)
                            if m:
                                _HIT_COUNTER = max(_HIT_COUNTER, int(m.group(1)))
            except Exception:
                pass
        _HIT_COUNTER += 1
        return _HIT_COUNTER


def _normalize_fb_uid(val) -> str:
    s = str(val or "").strip()
    if not s or s.lower() in ("null", "none", "no", "false", "0", ""):
        return ""
    digits = re.sub(r"\D", "", s)
    return digits if len(digits) >= 5 else ""


def _derive_tinh_trang(h: dict) -> str:
    """Xác định tình trạng tài khoản: Acc Trắng, Ẩn Thông Tin, Clean hay Full Info."""
    # Check phone
    sdt_bound = bool(h.get('mobile_bound') or h.get('aov_prefill_mobile') or h.get('masked_phone'))
    # Check email
    email_bound = bool(h.get('email_verified') or h.get('masked_email') or int(h.get('email_v', 0) or 0) > 0)
    # Check fb
    fb_uid = _normalize_fb_uid(h.get('fb_uid') or h.get('fb_uid_login') or '')
    fb_bound = bool(fb_uid or h.get('fb_linked') or h.get('fb_account_name'))
    # Check cccd
    cccd_raw = str(h.get('idcard') or '').strip().replace('*', '').replace('-', '')
    cccd_bound = bool(cccd_raw)
    # Check 2fa
    two_fa = bool(h.get('two_step_verify') or h.get('authenticator_enable'))

    bound_count = sum([sdt_bound, email_bound, fb_bound, cccd_bound, two_fa])

    if bound_count == 0:
        return "Acc Trắng"
    if bound_count >= 3 or (sdt_bound and email_bound and cccd_bound):
        return "Full Info"
    if cccd_bound and not sdt_bound and not email_bound:
        return "Dính CCCD (Trắng SDT/Mail)"
    if not cccd_bound and not fb_bound and (sdt_bound or email_bound):
        return "Có Thể Đổi TT"
    return "Full Info"


def format_hit_line(h: dict) -> str:
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
    rank_base = aov_rank if aov_rank else "Chưa có"
    stars = int(h.get('aov_rank_stars', 0) or 0)
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
    tot_skins = int(sk.get('total_skins', 0) or 0)

    # Skin tiers
    skin_tier_parts = []
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
    count_only_tiers = {'a', 's', 's_plus', 'ssm'}
    for tier_key, label in tier_meta:
        cnt = int(sk.get(tier_key, 0) or 0)
        if cnt:
            if tier_key in count_only_tiers:
                skin_tier_parts.append(f"{label}({cnt})")
            else:
                names = ', '.join(str(x) for x in (sk.get(f'{tier_key}_list') or []))
                skin_tier_parts.append(f"{label}({cnt}): {names}")

    # Season & Vinh danh
    _season = h.get('_kgcamp_season') or {}
    season_rank_str = "Chưa có"
    season_battles = 0
    season_wins = 0
    season_mvp = 0
    season_winrate = "0"
    top_heroes_str = "Chưa có"
    if isinstance(_season, dict) and _season:
        _sr = (_season.get('season_rank') or '').strip()
        _ss = int(_season.get('season_stars') or 0)
        if _sr:
            season_rank_str = f"{_sr} ({_ss}s)" if _ss > 0 else _sr
        season_battles = int(_season.get('season_battles') or 0)
        season_wins = int(_season.get('season_wins') or 0)
        season_mvp = int(_season.get('season_mvp') or 0)
        _swr = _season.get('season_winrate')
        if _swr is not None:
            season_winrate = str(_swr)
        _heroes = _season.get('top_heroes') or []
        if _heroes:
            h_parts = []
            for item in _heroes:
                if isinstance(item, dict) and item.get('hero_id') is not None:
                    hid = item.get('hero_id')
                    hname = get_hero_name(hid) or str(hid)
                    wr = item.get('win_rate', 0)
                    bt = item.get('battles', 0)
                    h_parts.append(f"{hname} ({wr}% {bt} trận)")
            if h_parts:
                top_heroes_str = ', '.join(h_parts)

    # Fallback RANK CAO NHẤT: ưu tiên aov_max_rank, fallback rank hiện tại
    if not season_rank_str or season_rank_str == "Chưa có":
        max_r = str(h.get('aov_max_rank') or '').strip()
        if max_r:
            season_rank_str = max_r
        elif rank_cur_str and rank_cur_str != "Chưa có":
            season_rank_str = rank_cur_str
        else:
            season_rank_str = "Chưa có"

    # BAN
    is_ban = h.get('aov_banned') in (True, 'YES', 'yes', '1', 1)
    ban_display = "BAN" if is_ban else "OK"

    # TÌNH TRẠNG
    tinh_trang = _derive_tinh_trang(h)

    swr_display = season_winrate if str(season_winrate).endswith('%') else f"{season_winrate}%"

    line_parts = [
        acc_pw,
        f"UID : {uid}",
        f"NAME GARENA: {name_gr}",
        f"NAME GAME: {name_game}",
        f"LV: {lv}",
        f"RANK HIỆN TẠI: {rank_cur_str}",
        f"QH: {cp}",
        f"SÒ: {shells}",
        f"EMAIL: {email_str}",
        f"SĐT: {sdt_str}",
        f"PASS: {pass_str}",
        f"AUTHEN: {authen_str}",
        f"FB: {fb_str}, CCCD: {cccd_str}",
        f"TƯỚNG: {tot_champs}",
        f"SKIN: {tot_skins}",
    ]
    if skin_tier_parts:
        line_parts.extend(skin_tier_parts)
    line_parts.extend([
        f"RANK CAO NHẤT: {season_rank_str}",
        f"TỔNG SỐ TRẬN ĐÃ CHƠI MÙA NÀY: {season_battles}",
        f"SỐ TRẬN THẮNG MÙA NÀY: {season_wins}",
        f"SỐ TRẬN ĐẠT MVP MÙA NÀY: {season_mvp}",
        f"TỈ LỆ THẮNG: {swr_display}",
        f"TƯỚNG TỦ MÙA NÀY: {top_heroes_str}",
        f"BAN: {ban_display}",
        f"TÌNH TRẠNG: {tinh_trang}",
    ])
    return " | ".join(line_parts)


def save_hit_result(r: dict, res_dir: str = "res", hit_filename: str = "hit.txt") -> bool:
    """Lưu kết quả HIT vào res/hit.txt một cách an toàn và có khóa thread-safe."""
    if not isinstance(r, dict):
        return False
    status = r.get("status", "") or ""
    if status != "HIT":
        return False

    hit_line = format_hit_line(r)
    if not hit_line:
        return False

    os.makedirs(res_dir, exist_ok=True)
    hit_path = os.path.join(res_dir, hit_filename)

    idx = _get_next_hit_idx(hit_path)
    block = f"--- Tài khoản #{idx} ---\n{hit_line}\n\n"

    with _SAVE_LOCK:
        with open(hit_path, "a", encoding="utf-8", newline="\n") as f:
            f.write(block)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
    return True
