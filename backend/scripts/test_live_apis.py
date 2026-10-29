import os
import json
import urllib.request

base = "http://127.0.0.1:8000"

# 1. Login
login_data = json.dumps({"email": "operator@nexafreight.dev", "password": os.environ.get("SEED_PASSWORD", "")}).encode()
req = urllib.request.Request(f"{base}/api/auth/login", data=login_data, headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req) as resp:
    token_resp = json.loads(resp.read().decode())
token = token_resp["access_token"]
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
print(f"[OK] Login successful for operator: role={token_resp['user']['role']}")

# 2. Ports
req = urllib.request.Request(f"{base}/api/map/ports", headers=headers)
with urllib.request.urlopen(req) as resp:
    ports = json.loads(resp.read().decode())
print(f"[OK] /api/map/ports -> {len(ports.get('features', []))} ports loaded")

# 3. Routes
req = urllib.request.Request(f"{base}/api/map/routes", headers=headers)
with urllib.request.urlopen(req) as resp:
    routes = json.loads(resp.read().decode())
print(f"[OK] /api/map/routes -> {len(routes.get('features', []))} route features loaded")

# 4. Shipments
req = urllib.request.Request(f"{base}/api/shipments?page=1&size=5", headers=headers)
with urllib.request.urlopen(req) as resp:
    shipments = json.loads(resp.read().decode())
print(f"[OK] /api/shipments -> {shipments.get('total')} total shipments in ledger")

# 5. Alerts & Disruptions
req = urllib.request.Request(f"{base}/api/alerts", headers=headers)
with urllib.request.urlopen(req) as resp:
    alerts = json.loads(resp.read().decode())
print(f"[OK] /api/alerts -> {len(alerts.get('alerts', []))} alerts active")

# 6. Analytics Summary
req = urllib.request.Request(f"{base}/api/analytics/summary?window=month", headers=headers)
with urllib.request.urlopen(req) as resp:
    analytics = json.loads(resp.read().decode())
print(f"[OK] /api/analytics/summary -> on_time_rate={analytics.get('on_time_delivery_rate')}, total_revenue=${analytics.get('total_revenue_usd'):,}")

# 7. Feed Health
req = urllib.request.Request(f"{base}/api/map/feed-health", headers=headers)
with urllib.request.urlopen(req) as resp:
    feeds = json.loads(resp.read().decode())
print(f"[OK] /api/map/feed-health -> {len(feeds.get('feeds', []))} telemetry adapters active")
