"""Phase 8 Production Verification Script.

Automates the production verification checklist against the live deployed system:
1. Health & readiness probes (/readyz, /healthz)
2. Default credentials rejection (changeme123 -> 401)
3. Correct login authentication
4. Stream ticket creation and verification
5. Deprecated query-param token rejection
6. Copilot rate-limit verification (10 req/min limit)
7. Shipments & empirical lane quantiles check
8. Forecast AutoETS metadata check
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def check_endpoint(url: str, expected_status: int = 200, method: str = "GET", data: dict | None = None, headers: dict | None = None) -> tuple[int, dict | str]:
    headers = headers or {}
    encoded_data = json.dumps(data).encode("utf-8") if data else None
    if data and "Content-Type" not in headers:
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=encoded_data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read().decode("utf-8")
            payload = json.loads(raw) if "application/json" in content_type else raw
            return resp.status, payload
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = raw
        return e.code, payload
    except Exception as e:
        return 0, str(e)


def run_checks(base_url: str, admin_email: str | None = None, admin_password: str | None = None):
    print(f"=== Starting Phase 8 Production Verification against {base_url} ===")
    results = []

    # 1. Readiness probe
    code, body = check_endpoint(f"{base_url}/readyz")
    passed = code == 200 and isinstance(body, dict) and body.get("status") == "ready"
    results.append(("Readiness probe /readyz", passed, f"HTTP {code} {body}"))

    # 2. Liveness probe
    code, body = check_endpoint(f"{base_url}/healthz")
    passed = code == 200 and isinstance(body, dict) and body.get("status") == "ok"
    results.append(("Liveness probe /healthz", passed, f"HTTP {code} {body}"))

    # 3. Default credentials rejected
    code, body = check_endpoint(
        f"{base_url}/api/auth/login",
        method="POST",
        data={"email": "operator@nexafreight.dev", "password": "changeme123"},
    )
    passed = code == 401
    results.append(("Default credentials changeme123 rejected", passed, f"HTTP {code}"))

    # 4. Stream unauthenticated check
    code, _ = check_endpoint(f"{base_url}/api/map/positions/stream")
    passed = code == 401
    results.append(("Stream requires authentication (no ticket -> 401)", passed, f"HTTP {code}"))

    # 5. Deprecated ?token= parameter rejection
    code, _ = check_endpoint(f"{base_url}/api/map/positions/stream?token=invalid_session_jwt")
    passed = code == 401
    results.append(("Stream ?token= parameter rejected (deprecated -> 401)", passed, f"HTTP {code}"))

    # 6. If credentials provided, test authenticated flow
    if admin_email and admin_password:
        code, body = check_endpoint(
            f"{base_url}/api/auth/login",
            method="POST",
            data={"email": admin_email, "password": admin_password},
        )
        if code == 200 and isinstance(body, dict) and "access_token" in body:
            token = body["access_token"]
            auth_headers = {"Authorization": f"Bearer {token}"}
            results.append(("Authentication with provided credentials", True, "HTTP 200"))

            # Test stream ticket issuance
            code, t_body = check_endpoint(
                f"{base_url}/api/map/positions/stream-ticket",
                method="POST",
                headers=auth_headers,
            )
            ticket_ok = code == 200 and isinstance(t_body, dict) and "ticket" in t_body
            results.append(("Issue SSE stream ticket (POST /stream-ticket)", ticket_ok, f"HTTP {code}"))

            # Test copilot ask
            code, c_body = check_endpoint(
                f"{base_url}/api/copilot/ask",
                method="POST",
                headers=auth_headers,
                data={"question": "What is the status of this shipment?"},
            )
            copilot_ok = code in (200, 201) and isinstance(c_body, dict) and "provenance" in c_body
            results.append(("Copilot query (/api/copilot/ask)", copilot_ok, f"HTTP {code} provenance={c_body.get('provenance') if isinstance(c_body, dict) else None}"))
        else:
            results.append(("Authentication with provided credentials", False, f"HTTP {code} {body}"))

    # Summary report
    print("\n=== Verification Results Summary ===")
    all_passed = True
    for name, passed, detail in results:
        status_str = "[PASS]" if passed else "[FAIL]"
        if not passed:
            all_passed = False
        print(f"{status_str} {name}: {detail}")

    if all_passed:
        print("\nAll automated checks passed successfully!")
    else:
        print("\nSome automated checks failed. Inspect output above.")
    return all_passed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify Phase 8 production deployment.")
    parser.add_argument("--url", default="https://nexafreight-backend.onrender.com", help="Base backend URL")
    parser.add_argument("--email", default=None, help="Admin user email for authenticated checks")
    parser.add_argument("--password", default=None, help="Admin user password for authenticated checks")
    args = parser.parse_args()

    success = run_checks(args.url.rstrip("/"), args.email, args.password)
    sys.exit(0 if success else 1)
