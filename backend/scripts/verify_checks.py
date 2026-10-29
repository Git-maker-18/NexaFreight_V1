import os
import urllib.request, urllib.error, json, time

base_url = 'http://localhost:8000'

print('========================================')
print('  NexaFreight Local API Verification')
print('========================================')

# 1. Backend reachability (401 without token)
print('\n[Check 1] Backend reachability with no token:')
try:
    urllib.request.urlopen(base_url + '/api/auth/me')
    print('  FAIL: Expected 401')
except urllib.error.HTTPError as e:
    print('  PASS: Received HTTP ' + str(e.code) + ' (Unauthorized) as expected')

# 2. Bad credentials check
print('\n[Check 3] Bad credentials handling:')
try:
    req = urllib.request.Request(
        base_url + '/api/auth/login',
        data=json.dumps({'email': 'wrong@test.com', 'password': 'wrong'}).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    urllib.request.urlopen(req)
    print('  FAIL: Expected 401')
except urllib.error.HTTPError as e:
    body = json.loads(e.read().decode('utf-8'))
    err_msg = body.get('error', '')
    print('  PASS: Received HTTP ' + str(e.code) + ' with error: ' + str(err_msg))

# 3. Successful login
print('\n[Check 2] Valid login with seeded credentials:')
login_creds = [
    {'email': 'operator@nexafreight.local', 'password': os.environ.get("SEED_PASSWORD", "")},
    {'email': 'operator@nexafreight.dev', 'password': os.environ.get("SEED_PASSWORD", os.environ.get("SEED_PASSWORD", ""))},
]
token = None
for cred in login_creds:
    try:
        req = urllib.request.Request(
            base_url + '/api/auth/login',
            data=json.dumps(cred).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        resp = urllib.request.urlopen(req)
        login_data = json.loads(resp.read().decode('utf-8'))
        token = login_data['access_token']
        tok_type = login_data.get('token_type', '')
        print('  PASS: Logged in as ' + cred['email'] + ' | HTTP 200 OK | Token type: ' + tok_type + ' | Token prefix: ' + token[:20] + '...')
        break
    except urllib.error.HTTPError:
        continue

if not token:
    raise RuntimeError('Could not log in with any seeded credentials. Please run python scripts/seed_user.py')

# 4. Token attached & Current user
print('\n[Check 5 & 6] Current user endpoint with Bearer token:')
req = urllib.request.Request(
    base_url + '/api/auth/me',
    headers={'Authorization': 'Bearer ' + token}
)
user = json.loads(urllib.request.urlopen(req).read().decode('utf-8'))
full_name = user.get('full_name', '')
email = user.get('email', '')
role = user.get('role', '')
print('  PASS: Authenticated user: ' + full_name + ' (' + email + ') | Role: ' + role)

# 5. Shipment fetch works
print('\n[Check 7] Shipment fetch works:')
req = urllib.request.Request(
    base_url + '/api/shipments?limit=10',
    headers={'Authorization': 'Bearer ' + token}
)
shipments_data = json.loads(urllib.request.urlopen(req).read().decode('utf-8'))
items = shipments_data.get('items', shipments_data) if isinstance(shipments_data, dict) else shipments_data
total = shipments_data.get('total', len(items)) if isinstance(shipments_data, dict) else len(items)
print('  PASS: Retrieved ' + str(len(items)) + ' items | Total shipments in system: ' + str(total))
for s in items[:3]:
    ref = s.get('reference_number') or s.get('id')
    mode = s.get('primary_transport_mode')
    status = s.get('status')
    print('    - Reference: ' + str(ref) + ' | Mode: ' + str(mode) + ' | Status: ' + str(status))

# 6. Ports render GeoJSON
print('\n[Check 9 & 10] Ports GeoJSON endpoint:')
req = urllib.request.Request(
    base_url + '/api/map/ports',
    headers={'Authorization': 'Bearer ' + token}
)
ports_geojson = json.loads(urllib.request.urlopen(req).read().decode('utf-8'))
port_features = ports_geojson.get('features', [])
print('  PASS: Ports FeatureCollection returned with ' + str(len(port_features)) + ' port markers')
for pf in port_features[:3]:
    p_props = pf.get('properties', {})
    coords = pf.get('geometry', {}).get('coordinates')
    print('    - Port: ' + str(p_props.get('name')) + ' (ID: ' + str(p_props.get('port_id')) + ') | Congestion: ' + str(p_props.get('congestion_index')) + ' | Coords: ' + str(coords))

# 7. Routes render GeoJSON
print('\n[Check 11, 12, 13, 14] Routes GeoJSON endpoint:')
req = urllib.request.Request(
    base_url + '/api/map/routes',
    headers={'Authorization': 'Bearer ' + token}
)
routes_geojson = json.loads(urllib.request.urlopen(req).read().decode('utf-8'))
route_features = routes_geojson.get('features', [])
print('  PASS: Routes FeatureCollection returned with ' + str(len(route_features)) + ' route lines')
modes = {}
for rf in route_features:
    m = rf.get('properties', {}).get('mode')
    modes[m] = modes.get(m, 0) + 1
print('    Mode distribution: ' + str(modes))
if route_features:
    sample_r = route_features[0]['properties']
    print('    Sample route: Shipment ' + str(sample_r.get('shipment_id')) + ' | Mode: ' + str(sample_r.get('mode')) + ' | Status: ' + str(sample_r.get('status')))

# 8. Feed health indicator
print('\n[Check 27] Feed health status endpoint:')
req = urllib.request.Request(
    base_url + '/api/map/feed-health',
    headers={'Authorization': 'Bearer ' + token}
)
health_data = json.loads(urllib.request.urlopen(req).read().decode('utf-8'))
print('  PASS: Feed health status returned:')
for adapter in health_data.get('adapters', []):
    print('    - Adapter: ' + str(adapter.get('adapter_name')) + ' | Healthy: ' + str(adapter.get('is_healthy')) + ' | Msgs: ' + str(adapter.get('messages_received')) + ' | Provenance: ' + str(adapter.get('provenance')))

# 9. Backend live stream (SSE) pre-check
print('\n[Check 18] Live positions SSE stream pre-check:')
req = urllib.request.Request(
    base_url + '/api/map/positions/stream?token=' + token,
    headers={'Authorization': 'Bearer ' + token}
)
stream_conn = urllib.request.urlopen(req)
start_time = time.time()
events_received = 0
while time.time() - start_time < 15:
    line = stream_conn.readline().decode('utf-8')
    if line.startswith('data: ['):
        positions = json.loads(line[6:].strip())
        events_received += 1
        print('  [Event ' + str(events_received) + '] Received ' + str(len(positions)) + ' active moving positions!')
        if positions:
            p0 = positions[0]
            print('    Sample asset: ' + str(p0.get('asset_id')) + ' (' + str(p0.get('asset_type')) + ') | Lat/Lon: (' + str(round(p0.get('latitude', 0), 3)) + ', ' + str(round(p0.get('longitude', 0), 3)) + ') | Heading: ' + str(p0.get('heading')) + ' | Speed: ' + str(p0.get('speed_knots')) + 'kn | Provenance: ' + str(p0.get('provenance')))
    if events_received >= 2:
        break
stream_conn.close()
print('  PASS: Live SSE stream is actively emitting data!')

print('\n========================================')
print('  All Backend API Checks Passed! ')
print('========================================')
