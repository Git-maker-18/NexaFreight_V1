import os
"""Test live SSE connection to /api/map/positions/stream."""

from __future__ import annotations

import json
import urllib.request

token = None
for cred in [
    {"email": "operator@nexafreight.local", "password": "operator123"},
    {"email": "operator@nexafreight.dev", "password": os.environ.get("SEED_PASSWORD", "operator123")},
]:
    try:
        req = urllib.request.Request(
            "http://localhost:8000/api/auth/login",
            data=json.dumps(cred).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req)
        token = json.loads(resp.read().decode("utf-8"))["access_token"]
        break
    except Exception:
        continue

if not token:
    raise RuntimeError("Login failed with seed credentials. Ensure backend is running and seeded.")

req_sse = urllib.request.Request(
    "http://localhost:8000/api/map/positions/stream",
    headers={"Authorization": f"Bearer {token}"},
)

with urllib.request.urlopen(req_sse, timeout=10) as sse_resp:
    print("SSE connected! Reading first 5 lines:")
    for _ in range(5):
        line = sse_resp.readline().decode("utf-8")
        print("SSE line:", line.strip())
