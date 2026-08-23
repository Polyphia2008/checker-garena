"""Liên Quan Mobile itop (Garena) MSDK client.

Reverse-engineered from libMSDKCore.so (arm64, v6.10).

Wire protocol (all verified live against https://itop.kg.garena.vn):
  request:  GET /v2/auth/decrypt?channelid=10&gameid=1137&os=1&seq=1&ts=<ts>&version=1&sig=<sig>&itopencodeparam=<param>[&encrypt=1]
  param:    TEA(CBC-like outer) of plaintext command, key b'itopenckey123456' (forge_param)
  sig:      md5(ts + itopencodeparam + MSDK_SDK_KEY)
  ks:       md5("MSDK_ENCRYPT" + MSDK_SDK_KEY + sig)        # 32 hex chars
  body:     plaintext XOR ks  (repeating)  — for encrypt=1, body is base64 of that

Disassembly source of the keystream:
  0x20ce48 (decrypt) -> concat "MSDK_ENCRYPT" + Get("MSDK_SDK_KEY") + 32-char sig
                        -> 0x20d5c0 = md5(concat).hexdigest() -> 0x20d620 = XOR loop.

MSDK config keys present in the lib: MSDK_GAME_ID, MSDK_SDK_KEY, MSDK_URL,
MSDK_ACCOUNT_APP_ID, MSDK_ACCOUNT_SDK_KEY, MSDK_HTTP_PROTOCOL, MSDK_HTTPDNS_ENABLE,
MSDK_IPV6_ENABLE, MSDK_ENCRYPT_STORAGE, MSDK_GUEST_FROM_SDCARD_ENABLE, ...
Auth endpoints (client-side dispatch): auth/login, auth/auto_login,
auth/login_with_confirm_code, auth/restore, auth/bind, auth/check_and_login,
auth/check_login, auth/bind_with_confirm_code, auth/logout, auth/scan_login,
auth/decrypt, account/login, account/loginwithcode, profile/reset_guest, v2/conf/get_conf.
"""
import hashlib
import urllib.parse
import requests

MASK = 0xFFFFFFFF
DELTA = 0x9E3779B9
ITOP_KEY = b'itopenckey123456'
SDK_KEY = '4dfd535a3a2ef92644301c3e3ce87c9f'
HOST = 'https://itop.kg.garena.vn'
CHANNELID = 10
GAMEID = 1137


def tea_e(data8, key, de='big', ke='big'):
    kw = [int.from_bytes(key[i:i + 4], ke) for i in range(0, 16, 4)]
    w = [int.from_bytes(data8[i:i + 4], de) for i in range(0, 8, 4)]
    y, z = w[0], w[1]
    k0, k1, k2, k3 = kw
    s = 0
    for _ in range(16):
        s = (s + DELTA) & MASK
        y = (y + ((((z << 4) & MASK) + k0) ^ (z + s) ^ (((z >> 5) & MASK) + k1))) & MASK
        z = (z + ((((y << 4) & MASK) + k2) ^ (y + s) ^ (((y >> 5) & MASK) + k3))) & MASK
    return y.to_bytes(4, de) + z.to_bytes(4, de)


def tea_d(data8, key, de='big', ke='big'):
    kw = [int.from_bytes(key[i:i + 4], ke) for i in range(0, 16, 4)]
    w = [int.from_bytes(data8[i:i + 4], de) for i in range(0, 8, 4)]
    y, z = w[0], w[1]
    k0, k1, k2, k3 = kw
    s = (16 * DELTA) & MASK
    for _ in range(16):
        z = (z - ((((y << 4) & MASK) + k2) ^ (y + s) ^ (((y >> 5) & MASK) + k3))) & MASK
        y = (y - ((((z << 4) & MASK) + k0) ^ (z + s) ^ (((z >> 5) & MASK) + k1))) & MASK
        s = (s - DELTA) & MASK
    return y.to_bytes(4, de) + z.to_bytes(4, de)


def outer_e(pt: bytes, key: bytes, randseed: int = 1) -> bytes:
    pt_len = len(pt)
    pad = (8 - (pt_len + 10) % 8) % 8
    raw = bytearray()
    raw.append((randseed & 0xF8) | pad)
    fill = pad + 2
    for i in range(1, 1 + fill):
        raw.append((0x5A + i) & 0xFF)
    idx = 1 + fill
    for b in pt:
        raw.append(b)
        idx += 1
    while len(raw) % 8:
        raw.append(0)
    ct = b''
    w_prev = None
    for off in range(0, len(raw), 8):
        block = bytes(raw[off:off + 8])
        if off == 0:
            w = block
        else:
            w = bytes(a ^ b for a, b in zip(block, ct[-8:]))
        e = tea_e(w, key)
        if w_prev is None:
            ct += e
        else:
            ct += bytes(a ^ b for a, b in zip(e, w_prev))
        w_prev = w
    return ct


def outer_d(ct: bytes, key: bytes) -> bytes:
    ct_len = len(ct)
    sp10 = tea_d(ct[0:8], key)
    pad = sp10[0] & 7
    pt_len = ct_len - 1 - pad - 9
    skip = pad + 3
    pt = bytearray(sp10[skip:8])
    w_prev = sp10
    for i in range(1, ct_len // 8):
        w = tea_d(bytes(a ^ b for a, b in zip(w_prev, ct[i * 8:(i + 1) * 8])), key)
        base = i * 8
        for j in range(8):
            byte_idx = base + j - skip
            if 0 <= byte_idx < pt_len:
                pt.append(ct[(i - 1) * 8 + j] ^ w[j])
        w_prev = w
    return bytes(pt[:pt_len])


def forge_param(pt: bytes, randseed: int = 1) -> str:
    return outer_e(pt, ITOP_KEY, randseed).hex()


def sig_for(ts: int, param: str) -> str:
    return hashlib.md5((str(ts) + param + SDK_KEY).encode()).hexdigest()


def call(ts: int, param: str, seq: int = 1, encrypt: int = 0, timeout: int = 10, proxy=None):
    sig = sig_for(ts, param)
    url = '%s/v2/auth/decrypt?channelid=%d&gameid=%d&os=1&seq=%d&ts=%d&version=1&sig=%s&itopencodeparam=%s' % (
        HOST, CHANNELID, GAMEID, seq, ts, sig, urllib.parse.quote(param))
    if encrypt:
        url += '&encrypt=1'
    proxies = None
    if proxy:
        if isinstance(proxy, dict):
            proxies = proxy
        elif isinstance(proxy, str):
            p = proxy.strip()
            if not p.startswith("http"):
                p = f"http://{p}"
            proxies = {"http": p, "https": p}
    r = requests.get(url, timeout=timeout, proxies=proxies, verify=False)
    return r.status_code, r.text


def send(pt: bytes, ts: int, seq: int = 1, randseed: int = 1, encrypt: int = 0, timeout: int = 10, proxy=None):
    param = forge_param(pt, randseed)
    status, body = call(ts, param, seq, encrypt, timeout, proxy=proxy)
    return param, status, body


def cmd(pt: bytes, ts: int, seq: int = 1, randseed: int = 1, timeout: int = 10, proxy=None) -> str:
    """Send a plaintext command with encrypt=1 and return the decrypted response."""
    param, status, body = send(pt, ts, seq, randseed, encrypt=1, timeout=timeout, proxy=proxy)
    if status != 200:
        return 'HTTP %d: %s' % (status, body)
    return decrypt_response(body, ts, param)


def ks_for(ts: int, param: str) -> str:
    sig = sig_for(ts, param)
    return hashlib.md5(('MSDK_ENCRYPT' + SDK_KEY + sig).encode()).hexdigest()


def decrypt_response(body: str, ts: int, param: str, ks_hex: str = None) -> str:
    import base64
    if ks_hex is None:
        ks_hex = ks_for(ts, param)
    try:
        ct = base64.b64decode(body)
    except Exception:
        ct = body.encode()
    ks = ks_hex.encode()
    return bytes(ct[i] ^ ks[i % len(ks)] for i in range(len(ct))).decode('utf-8', 'replace')


if __name__ == '__main__':
    import time
    samples = [
        ('1787156262', 'd9b48147c3b809a2bebbd8b2e96c26f1', '3dffdae38090d1efdc0bd7ee6ea056f1'),
        ('1787154266', 'd9b48147c3b809a2bebbd8b2e96c26f1', 'f292b97f8659bfaad5fddd91630753af'),
        ('1787154818', '00000000000000000000000000000000', '6d8411c42744e6762cfe74efce659043'),
        ('1787154819', '646f6373', 'bc2ebe5cbee982f8b9e0e2ce4740bb55'),
        ('1787154820', '11111111111111111111111111111111', '306a2fbcd4398d72f1a2d1ef26cbf03b'),
        ('1787154821', '0123456789abcdef0123456789abcdef', '58ca854f29d2d5fd8e4b4a0bd7de19c7'),
        ('1', '00000000000000000000000000000000', 'f9f51f807f1f0299beafeada43de5eb9'),
        ('1000000000', '00000000000000000000000000000000', 'd0e927aa75889aa983b43b55238a16cd'),
    ]
    ok = all(ks_for(int(t), p) == o for t, p, o in samples)
    print('keystream samples:', 'ALL OK' if ok else 'FAIL')

    ts = int(time.time())
    for pt in [b'hello', b'get_guest_info']:
        param, st0, body0 = send(pt, ts, encrypt=0)
        print('encrypt=0:', st0, body0)
        print('cmd():    ', cmd(pt, ts))