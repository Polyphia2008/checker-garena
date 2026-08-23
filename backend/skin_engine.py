# -*- coding: utf-8 -*-
"""
Module Phân Loại Trang Phục & Tướng Liên Quân Mobile (AOV Skin & Hero Engine).
- Tải 1 lần duy nhất từ điển skin_tiers_map.json, skin_id_map.json, hero_id_map.json vào RAM.
- Chuẩn hóa phân bậc 1-1 không sai lệch, khóa cứng bậc A cho skin tân thủ.
- Đếm tướng chuẩn hóa (Canonical Hero Names) tránh đếm trùng alias ID.
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Set, Tuple

# In-memory dictionaries
SKIN_SSS: Dict[str, str] = {}
SKIN_SS: Dict[str, str] = {}
SKIN_ANIME: Dict[str, str] = {}
SKIN_HUUHAN: Dict[str, str] = {}
SKIN_SSM: Dict[str, str] = {}
SKIN_TUYETSAC: Dict[str, str] = {}
SKIN_CHUYENSAC: Dict[str, str] = {}
SKIN_EVO: Dict[str, str] = {}
SKIN_S_PLUS: Dict[str, str] = {}
SKIN_S: Dict[str, str] = {}
SKIN_A: Dict[str, str] = {}
SKIN_SPECIAL: Dict[str, str] = {}
SKIN_OTHER: Dict[str, str] = {}
_SKIN_ALL: Dict[str, str] = {}
_HERO_ALL: Dict[str, str] = {}
_BASE_HERO_IDS: Set[str] = set()
_SKIN_ALL_LOADED: bool = False


def _find_json(fname: str) -> str:
    root_dir = os.path.dirname(os.path.abspath(__file__))
    res_dir = os.path.join(root_dir, "res")
    p1 = os.path.join(root_dir, fname)
    if os.path.isfile(p1):
        return p1
    p2 = os.path.join(res_dir, fname)
    if os.path.isfile(p2):
        return p2
    return p1


def load_full_skin_maps() -> None:
    """Load toàn bộ skin và hero map từ folder gốc hoặc res/*.json vào memory."""
    global SKIN_SSS, SKIN_SS, SKIN_ANIME, SKIN_HUUHAN, SKIN_SSM, SKIN_TUYETSAC
    global SKIN_CHUYENSAC, SKIN_EVO, SKIN_S_PLUS, SKIN_S, SKIN_A, SKIN_SPECIAL
    global SKIN_OTHER, _SKIN_ALL, _HERO_ALL, _BASE_HERO_IDS, _SKIN_ALL_LOADED
    if _SKIN_ALL_LOADED:
        return
    _SKIN_ALL_LOADED = True

    # 1) Hero ID -> Hero Name
    try:
        with open(_find_json("hero_id_map.json"), encoding="utf-8") as f:
            d = json.load(f)
            if isinstance(d, dict):
                _HERO_ALL.update({str(k): str(v) for k, v in d.items()})
    except Exception:
        pass

    # 2) Skin Tiers (SSS, SS, Anime, HuuHan, SSM, TuyetSac, ChuyenSac, EVO, S+, S, A, Special)
    try:
        with open(_find_json("skin_tiers_map.json"), encoding="utf-8") as f:
            st = json.load(f)
            if isinstance(st, dict):
                SKIN_SSS.update({str(k): str(v) for k, v in (st.get("SSS") or {}).items()})
                SKIN_SS.update({str(k): str(v) for k, v in (st.get("SS") or {}).items()})
                SKIN_ANIME.update({str(k): str(v) for k, v in (st.get("Anime") or st.get("ANIME") or {}).items()})
                SKIN_HUUHAN.update({str(k): str(v) for k, v in (st.get("HuuHan") or {}).items()})
                SKIN_SSM.update({str(k): str(v) for k, v in (st.get("SSM") or {}).items()})
                SKIN_TUYETSAC.update({str(k): str(v) for k, v in (st.get("TuyetSac") or {}).items()})
                SKIN_CHUYENSAC.update({str(k): str(v) for k, v in (st.get("ChuyenSac") or {}).items()})
                SKIN_EVO.update({str(k): str(v) for k, v in (st.get("EVO") or {}).items()})
                SKIN_S_PLUS.update({str(k): str(v) for k, v in (st.get("S_PLUS") or {}).items()})
                SKIN_S.update({str(k): str(v) for k, v in (st.get("S") or {}).items()})
                SKIN_A.update({str(k): str(v) for k, v in (st.get("A") or {}).items()})
                SKIN_SPECIAL.update({str(k): str(v) for k, v in (st.get("Special") or st.get("OTHER") or {}).items()})
                SKIN_OTHER.update(SKIN_SPECIAL)
    except Exception:
        pass

    # 3) Full Skin Database (chỉ nạp skin thực tế, lọc bỏ model mặc định index 00 hoặc trùng tên tướng)
    try:
        with open(_find_json("skin_id_map.json"), encoding="utf-8") as f:
            d = json.load(f)
            if isinstance(d, dict):
                for k, v in d.items():
                    k_str = str(k).strip()
                    v_str = str(v).strip()
                    if not k_str.isdigit():
                        continue
                    n = int(k_str)
                    # Ghi nhận ID model mặc định (n % 100 == 0)
                    if n % 100 == 0:
                        _BASE_HERO_IDS.add(k_str)
                        continue
                    # Bỏ qua nếu tên skin trùng 100% tên tướng (placeholder)
                    hid = str(n // 100)
                    hname = _HERO_ALL.get(hid, "")
                    if hname and v_str.lower() == hname.lower():
                        _BASE_HERO_IDS.add(k_str)
                        continue
                    _SKIN_ALL[k_str] = v_str
    except Exception:
        pass


def get_hero_name(hero_id) -> str:
    """Tra cứu tên tướng tiếng Việt chuẩn từ ID."""
    if not _SKIN_ALL_LOADED:
        load_full_skin_maps()
    return _HERO_ALL.get(str(hero_id).strip(), "")


def get_skin_name(skin_id) -> str:
    """Tra cứu tên trang phục từ ID."""
    if not _SKIN_ALL_LOADED:
        load_full_skin_maps()
    return _SKIN_ALL.get(str(skin_id).strip(), "")


def skin_hero_id(skin_id) -> str:
    """Trích xuất ID tướng từ Skin item ID (hero*100 + skin_index) hoặc Hero ID."""
    sid = str(skin_id).strip()
    if not sid.isdigit():
        return sid
    n = int(sid)
    if n >= 10000:
        return str(n // 100)
    return sid


def skin_id_to_name(skin_id) -> str:
    """Map skin item id -> tên skin qua các bậc, fallback full database."""
    if not _SKIN_ALL_LOADED:
        load_full_skin_maps()
    sid = str(skin_id).strip()
    for d in (SKIN_SSS, SKIN_ANIME, SKIN_SS, SKIN_HUUHAN, SKIN_SSM, SKIN_TUYETSAC,
              SKIN_CHUYENSAC, SKIN_EVO, SKIN_S_PLUS, SKIN_S, SKIN_A, SKIN_SPECIAL):
        if sid in d:
            return d[sid]
    return get_skin_name(sid)


def _norm_item_id(val) -> str:
    """Normalize mixed raw item IDs (int, float, str) into clean integer string."""
    if val is None:
        return ""
    if isinstance(val, (int, float)):
        try:
            return str(int(val))
        except Exception:
            return ""
    s = str(val).strip()
    if not s or s.lower() in ("none", "null", ""):
        return ""
    # Support '11101.0' or '11101'
    try:
        if "." in s:
            return str(int(float(s)))
        if s.isdigit():
            return str(int(s))
    except Exception:
        pass
    return re.sub(r"\D", "", s)


def classify_skins(owned_ids: list, cp: int = 0) -> dict:
    """Classify owned skin IDs into all 12 tiers and count unique champions with strict deduplication."""
    if not _SKIN_ALL_LOADED:
        load_full_skin_maps()

    sss_list, ss_list, anime_list, huuhan_list = [], [], [], []
    ssm_list, tuyetsac_list, chuyensac_list, evo_list = [], [], [], []
    s_plus_list, s_list, a_list, special_list = [], [], [], []
    hero_names: Set[str] = set()

    # Normalize and deduplicate raw owned IDs
    cleaned_ids = []
    if isinstance(owned_ids, dict):
        owned_iter = owned_ids.keys()
    elif isinstance(owned_ids, str):
        owned_iter = [x.strip() for x in owned_ids.split(",") if x.strip()]
    elif isinstance(owned_ids, (list, tuple, set)):
        owned_iter = owned_ids
    else:
        owned_iter = [owned_ids] if owned_ids else []

    for raw in owned_iter:
        nid = _norm_item_id(raw)
        if nid and nid != "0":
            cleaned_ids.append(nid)

    unique_owned = list(dict.fromkeys(cleaned_ids))

    for sid in unique_owned:
        if not sid.isdigit():
            continue

        n = int(sid)

        # 1) Trường hợp là Tướng (Hero ID < 10000), Base model (n % 100 == 0) hoặc Placeholder trùng tên tướng
        # -> Ghi nhận tướng sở hữu, TUYỆT ĐỐI KHÔNG tính vào danh sách skin hay total_skins!
        if n < 10000 or (n % 100 == 0) or sid in _BASE_HERO_IDS:
            hid = str(n) if n < 10000 else str(n // 100)
            hname = get_hero_name(hid)
            if hname:
                hero_names.add(hname.replace("’", "'").replace("`", "'").strip())
            elif hid in _HERO_ALL:
                hero_names.add(_HERO_ALL[hid].replace("’", "'").replace("`", "'").strip())
            else:
                hero_names.add(str(hid))
            continue

        # 2) Trường hợp là Trang phục (Skin index >= 1, n >= 10000 và không phải base model)
        hid = str(n // 100)
        hname = get_hero_name(hid)

        # Ghi nhận tướng sở hữu tương ứng từ trang phục sở hữu
        if hname:
            hero_names.add(hname.replace("’", "'").replace("`", "'").strip())
        elif hid in _HERO_ALL:
            hero_names.add(_HERO_ALL[hid].replace("’", "'").replace("`", "'").strip())
        elif hid:
            hero_names.add(str(hid))

        # Phân loại bậc theo thứ tự ưu tiên: SSS > Anime > SS > HuuHan > SSM > TuyetSac > ChuyenSac > EVO > S+ > S > A > Special
        if sid in SKIN_SSS:
            sss_list.append(SKIN_SSS[sid])
        elif sid in SKIN_ANIME:
            anime_list.append(SKIN_ANIME[sid])
        elif sid in SKIN_SS:
            ss_list.append(SKIN_SS[sid])
        elif sid in SKIN_HUUHAN:
            huuhan_list.append(SKIN_HUUHAN[sid])
        elif sid in SKIN_SSM:
            ssm_list.append(SKIN_SSM[sid])
        elif sid in SKIN_TUYETSAC:
            tuyetsac_list.append(SKIN_TUYETSAC[sid])
        elif sid in SKIN_CHUYENSAC:
            chuyensac_list.append(SKIN_CHUYENSAC[sid])
        elif sid in SKIN_EVO:
            evo_list.append(SKIN_EVO[sid])
        elif sid in SKIN_S_PLUS:
            s_plus_list.append(SKIN_S_PLUS[sid])
        elif sid in SKIN_S:
            s_list.append(SKIN_S[sid])
        elif sid in SKIN_A:
            a_list.append(SKIN_A[sid])
        elif sid in SKIN_SPECIAL:
            special_list.append(SKIN_SPECIAL[sid])
        elif sid in _SKIN_ALL:
            name = _SKIN_ALL[sid]
            low = name.lower()
            if any(k in low for k in ['tiến hóa', 'evo']):
                evo_list.append(name)
            elif any(k in low for k in ['tuyệt sắc']):
                tuyetsac_list.append(name)
            elif any(k in low for k in ['chuyển sắc', 'chroma']):
                chuyensac_list.append(name)
            else:
                a_list.append(name)
        elif hid in _HERO_ALL:
            # Skin mới của tướng trong game nhưng chưa có tên trong từ điển
            hero_display = hname or _HERO_ALL.get(hid) or f"Hero {hid}"
            a_list.append(f"{hero_display} Skin")
        else:
            # ID vật phẩm khác (avatar, frame, hiệu ứng, điệu nhảy, mảnh ngọc...) -> Bỏ qua
            continue

    def _dedup(l):
        return list(dict.fromkeys(l))

    sss_clean = _dedup(sss_list)
    ss_clean = _dedup(ss_list)
    anime_clean = _dedup(anime_list)
    huuhan_clean = _dedup(huuhan_list)
    ssm_clean = _dedup(ssm_list)
    tuyetsac_clean = _dedup(tuyetsac_list)
    chuyensac_clean = _dedup(chuyensac_list)
    evo_clean = _dedup(evo_list)
    s_plus_clean = _dedup(s_plus_list)
    s_clean = _dedup(s_list)
    a_clean = _dedup(a_list)
    special_clean = _dedup(special_list)

    total_skins_count = (
        len(sss_clean) + len(ss_clean) + len(anime_clean) + len(huuhan_clean) +
        len(ssm_clean) + len(tuyetsac_clean) + len(chuyensac_clean) + len(evo_clean) +
        len(s_plus_clean) + len(s_clean) + len(a_clean) + len(special_clean)
    )

    return {
        'total_skins': total_skins_count,
        'total_champs': len(hero_names),
        'cp': cp,
        'sss': len(sss_clean), 'sss_list': sss_clean,
        'ss': len(ss_clean), 'ss_list': ss_clean,
        'anime': len(anime_clean), 'anime_list': anime_clean,
        'huuhan': len(huuhan_clean), 'huuhan_list': huuhan_clean,
        'ssm': len(ssm_clean), 'ssm_list': ssm_clean,
        'tuyetsac': len(tuyetsac_clean), 'tuyetsac_list': tuyetsac_clean,
        'chuyensac': len(chuyensac_clean), 'chuyensac_list': chuyensac_clean,
        'evo': len(evo_clean), 'evo_list': evo_clean,
        's_plus': len(s_plus_clean), 's_plus_list': s_plus_clean,
        's': len(s_clean), 's_list': s_clean,
        'a': len(a_clean), 'a_list': a_clean,
        'special': len(special_clean), 'special_list': special_clean,
        'other': len(special_clean), 'other_list': special_clean,
    }


# Auto-load on import for instant queries
load_full_skin_maps()
