#!/usr/bin/env python3
"""End-to-end checks against an installed platform, through the real TLS proxy. Standard library only.

usage: smoke.py BASE_URL CA_FILE USERNAME PASSWORD_FILE
Exits non-zero on the first failed check.
"""

import base64
import hashlib
import hmac
import http.cookiejar
import json
import ssl
import struct
import sys
import time
import urllib.error
import urllib.request

BASE, CA, USER, PW_FILE = sys.argv[1:5]
PASSWORD = open(PW_FILE).read().strip()
ctx = ssl.create_default_context(cafile=CA)
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx),
                                     urllib.request.HTTPCookieProcessor(jar))
failures = 0


def check(cond: bool, what: str) -> None:
    global failures
    print(("  PASS " if cond else "  FAIL ") + what)
    if not cond:
        failures += 1


def csrf() -> str:
    return next((c.value for c in jar if c.name.endswith("opsbrain_csrf")), "")


def call(method: str, path: str, body: object | None = None) -> tuple[int, dict, object]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if method not in ("GET", "HEAD"):
        req.add_header("X-CSRF-Token", csrf())
    try:
        with opener.open(req, timeout=20) as r:
            raw = r.read()
            ctype = r.headers.get("Content-Type", "")
            return r.status, dict(r.headers), json.loads(raw) if "json" in ctype else raw.decode()
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            payload: object = json.loads(raw)
        except ValueError:
            payload = raw.decode(errors="replace")
        return e.code, dict(e.headers), payload


def totp(secret: str, offset: int = 0) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    counter = int(time.time()) // 30 + offset
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = digest[-1] & 0x0F
    return f"{(struct.unpack('>I', digest[o:o + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


print("TLS, headers and static UI")
status, headers, body = call("GET", "/")
check(status == 200 and "<div id=\"root\">" in str(body), "UI served over HTTPS with the internal CA")
h = {k.lower(): v for k, v in headers.items()}
check("max-age" in h.get("strict-transport-security", ""), "HSTS header present")
check("frame-ancestors 'none'" in h.get("content-security-policy", ""), "CSP header present")
check(h.get("x-frame-options") == "DENY", "X-Frame-Options DENY")
check("server" not in h, "Server header removed")
status, _, _ = call("GET", "/api/metrics")
check(status == 404, "/api/metrics is not reachable from outside")
status, _, body = call("GET", "/api/health/ready")
check(status == 200 and body == {"status": "ok"}, "API ready through the proxy")
status, _, _ = call("GET", "/api/v1/users")
check(status == 401, "API requires authentication")
status, _, _ = call("GET", "/logging/explorer")
check(status == 200, "SPA deep links fall back to index.html")

print("Sign-in of the first administrator (MFA enrolment enforced)")
status, _, body = call("POST", "/api/v1/auth/login", {"username": USER, "password": "wrong-password-123"})
check(status == 401, "wrong password rejected")
status, _, body = call("POST", "/api/v1/auth/login", {"username": USER, "password": PASSWORD})
check(status == 200, "password accepted")
state = body.get("state") if isinstance(body, dict) else None
if state == "mfa_enrollment_required":
    status, _, setup = call("POST", "/api/v1/auth/mfa/setup")
    check(status == 200 and "secret" in setup, "authenticator setup issued")
    secret = setup["secret"]
    status, _, body = call("POST", "/api/v1/auth/mfa/enable", {"code": totp(secret)})
    check(status == 200 and body.get("state") == "full", "MFA enrolled, session complete")
    with open(PW_FILE + ".totp", "w") as f:
        f.write(secret)
elif state == "mfa_required":
    secret = open(PW_FILE + ".totp").read().strip()
    # Avoid reusing the code of the previous run within the same 30 s window.
    time.sleep(31 - time.time() % 30)
    status, _, body = call("POST", "/api/v1/auth/mfa/verify", {"code": totp(secret)})
    check(status == 200 and body.get("state") == "full", "MFA code accepted")
else:
    check(False, f"unexpected sign-in state {state}")

print("Administration API")
status, _, users = call("GET", "/api/v1/users")
check(status == 200 and any(u["username"] == USER for u in users), "users listed")
status, _, roles = call("GET", "/api/v1/roles")
check(status == 200 and {"Admin", "DevOps", "NOC", "Developer", "Viewer", "Auditor"} <= {r["name"] for r in roles},
      "six built-in roles present")
status, _, health = call("GET", "/api/v1/system/health")
comps = {c["component"]: c["status"] for c in health.get("checks", [])} if isinstance(health, dict) else {}
check(comps.get("database") == "ok" and comps.get("redis") == "ok", "database and Valkey healthy")
deadline = time.time() + 90
while comps.get("worker") != "ok" and time.time() < deadline:
    time.sleep(5)
    _, _, health = call("GET", "/api/v1/system/health")
    comps = {c["component"]: c["status"] for c in health["checks"]}
check(comps.get("worker") == "ok", "background worker heartbeat received")
check(comps.get("tls") == "ok", "TLS certificate check ok")
status, _, mods = call("GET", "/api/v1/system/modules")
installed = {m["key"] for m in mods["modules"] if m["installed"]} if isinstance(mods, dict) else set()
check(installed == {"core"}, "only the core module is reported installed")
status, _, verify = call("POST", "/api/v1/audit/verify")
check(status == 200 and verify.get("ok") is True, "audit hash chain verifies")
status, _, page = call("GET", "/api/v1/audit?action=auth.login")
check(status == 200 and any(i["result"] == "failure" for i in page["items"]), "failed sign-in is in the audit log")

print("FAILED" if failures else "ALL CHECKS PASSED")
sys.exit(1 if failures else 0)
