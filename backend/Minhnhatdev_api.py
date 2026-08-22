import sys
import os
import json
import warnings

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import contextlib
import io

sys.stdout = io.StringIO()
sys.stderr = io.StringIO()

_real_stdout = sys.__stdout__


def Minhnhatdev_emit(payload: dict) -> None:
    _real_stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    _real_stdout.flush()


def Minhnhatdev_run(account: str, password: str) -> dict:
    try:
        import garena
        from hit_logger import format_hit_line, _derive_tinh_trang
    except Exception as e:
        return {"ok": False, "status": "ERROR", "detail": f"import_error: {e}"}

    try:
        r = garena.check_login(account, password, fetch_info=True, debug=False)
    except Exception as e:
        return {"ok": False, "status": "ERROR", "detail": f"check_error: {e}"}

    out = {
        "ok": True,
        "status": str(r.get("status") or "ERROR"),
        "detail": str(r.get("detail") or ""),
        "account": account,
        "uid": str(r.get("uid") or ""),
        "line": "",
        "tinh_trang": "",
    }

    if r.get("status") == "HIT":
        try:
            out["tinh_trang"] = _derive_tinh_trang(r)
            out["line"] = format_hit_line(r)
        except Exception as e:
            out["line"] = ""
            out["detail"] = f"{out['detail']} format_error: {e}".strip()
    else:
        out["line"] = out["detail"] or out["status"]

    return out


def main() -> int:
    if len(sys.argv) < 3:
        Minhnhatdev_emit({"ok": False, "status": "ERROR", "detail": "usage: Minhnhatdev_api.py <account> <password>"})
        return 2

    account = sys.argv[1].strip()
    password = sys.argv[2]

    if not account or not password:
        Minhnhatdev_emit({"ok": False, "status": "ERROR", "detail": "empty credentials"})
        return 2

    payload = Minhnhatdev_run(account, password)
    Minhnhatdev_emit(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
