"""EncodeParam helper: runs camp-security-oversea (Tencent Chaos VM) in a dedicated
background thread to avoid greenlet thread-switch issues with Playwright sync API.
"""
from __future__ import annotations

import atexit
import os
import queue
import threading
from typing import List, Tuple

_JS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "camp-security-oversea.0.1.0.js")
_JS_CACHE = None

_req_queue: queue.Queue = queue.Queue()
_worker_thread = None
_thread_lock = threading.Lock()
_stop_sentinel = object()


def _get_js_content():
    global _JS_CACHE
    if _JS_CACHE is None and os.path.exists(_JS_PATH):
        with open(_JS_PATH, "r", encoding="utf-8") as f:
            _JS_CACHE = f.read()
    return _JS_CACHE or ""


def _vm_worker():
    """Dedicated worker thread for all Playwright lifecycle and evaluations."""
    js_code = _get_js_content()
    if not js_code:
        return

    playwright_mgr = None
    browser = None
    page = None

    def _init_page():
        nonlocal playwright_mgr, browser, page
        try:
            from playwright.sync_api import sync_playwright
            if playwright_mgr is None:
                playwright_mgr = sync_playwright().start()
            if browser is None or not browser.is_connected():
                launch_args = [
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-accelerated-2d-canvas",
                    "--disable-gpu",
                    "--js-flags=--max-old-space-size=48",
                    "--blink-settings=imagesEnabled=false",
                    "--disable-remote-fonts",
                    "--disable-background-networking",
                    "--disable-extensions",
                    "--mute-audio",
                    "--no-default-browser-check",
                    "--no-first-run",
                ]
                edge_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
                try:
                    if os.path.exists(edge_path):
                        browser = playwright_mgr.chromium.launch(executable_path=edge_path, headless=True, args=launch_args)
                    else:
                        browser = playwright_mgr.chromium.launch(channel="msedge", headless=True, args=launch_args)
                except Exception:
                    browser = playwright_mgr.chromium.launch(headless=True, args=launch_args)

            if page is None or page.is_closed():
                page = browser.new_page()
                page.route(
                    "https://kg-camp.mobagarena.com/**",
                    lambda route: route.fulfill(
                        status=200,
                        content_type="text/html",
                        body="<!DOCTYPE html><html><head><meta charset='utf-8'></head><body></body></html>",
                    ),
                )
                page.goto("https://kg-camp.mobagarena.com/app", timeout=5000)
                page.evaluate('''(code) => {
                    let s = document.createElement('script');
                    s.textContent = code;
                    document.head.appendChild(s);
                }''', js_code)
            return page
        except Exception:
            return None

    while True:
        try:
            item = _req_queue.get()
            if item is _stop_sentinel:
                break
            encryption, role_id, count, resp_event, result_box = item
            try:
                p = _init_page()
                if p is None:
                    result_box.append([])
                else:
                    res = p.evaluate('''(args) => {
                        let { encryption, roleId, count } = args;
                        if (!window.__TCSJ__ || typeof window.__TCSJ__.setLoginRes !== 'function') {
                            return [];
                        }
                        try {
                            window.__TCSJ__.setLoginRes(encryption);
                            let list = [];
                            for (let i = 0; i < count; i++) {
                                let param = window.__TCSJ__.getEncodeParam(roleId);
                                if (param) {
                                    list.push(param);
                                }
                            }
                            return list;
                        } catch(e) {
                            return [];
                        }
                    }''', {'encryption': encryption, 'roleId': role_id, 'count': count})
                    if isinstance(res, list):
                        result_box.append(res)
                    else:
                        result_box.append([])
            except Exception:
                try:
                    if page and not page.is_closed():
                        page.close()
                except Exception:
                    pass
                page = None
                result_box.append([])
            finally:
                resp_event.set()
        except Exception:
            pass

    # Cleanup
    try:
        if page and not page.is_closed():
            page.close()
    except Exception:
        pass
    try:
        if browser and browser.is_connected():
            browser.close()
    except Exception:
        pass
    try:
        if playwright_mgr:
            playwright_mgr.stop()
    except Exception:
        pass


def _ensure_worker_started():
    global _worker_thread
    with _thread_lock:
        if _worker_thread is None or not _worker_thread.is_alive():
            _worker_thread = threading.Thread(target=_vm_worker, daemon=True, name="TencentVM-Worker")
            _worker_thread.start()


def _cleanup():
    global _worker_thread
    if _worker_thread and _worker_thread.is_alive():
        _req_queue.put(_stop_sentinel)


atexit.register(_cleanup)


def get_encode_params(encryption: str, role_id: str, count: int = 1, timeout: float = 15.0) -> List[str]:
    """Generate fresh single-use EncodeParam nonces via the dedicated thread-safe worker."""
    if not encryption or not role_id:
        return []
    if count < 1:
        count = 1

    _ensure_worker_started()

    resp_event = threading.Event()
    result_box: List[List[str]] = []
    _req_queue.put((encryption, role_id, count, resp_event, result_box))

    if resp_event.wait(timeout=timeout):
        if result_box and isinstance(result_box[0], list):
            return result_box[0]
    return []


def get_encode_param(encryption: str, role_id: str, timeout: float = 15.0) -> str:
    params = get_encode_params(encryption, role_id, 1, timeout)
    return params[0] if params else ""