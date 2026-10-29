"""Complete automated walk-through of all NexaFreight Chartroom surfaces and click flows."""

import asyncio
import base64
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
import websockets

ARTIFACT_DIR = Path(os.environ.get("ARTIFACT_DIR", Path(__file__).resolve().parent / "artifacts"))
CDP_PORT = 9230

class ChromeWalkthrough:
    def __init__(self, ws_url: str):
        self.ws_url = ws_url
        self.ws = None
        self._msg_id = 0

    async def connect(self):
        self.ws = await websockets.connect(self.ws_url, max_size=50 * 1024 * 1024)

    async def send(self, method: str, params: dict | None = None) -> dict:
        self._msg_id += 1
        call_id = self._msg_id
        payload = {"id": call_id, "method": method, "params": params or {}}
        await self.ws.send(json.dumps(payload))
        while True:
            resp = await self.ws.recv()
            data = json.loads(resp)
            if data.get("id") == call_id:
                return data.get("result", {})

    async def evaluate(self, expression: str):
        res = await self.send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True
        })
        return res.get("result", {}).get("value")

    async def screenshot(self, filename: str) -> Path:
        res = await self.send("Page.captureScreenshot", {"format": "png"})
        data = base64.b64decode(res["data"])
        out_path = ARTIFACT_DIR / filename
        out_path.write_bytes(data)
        print(f"[Screenshot] Captured: {out_path.name} ({len(data)} bytes)")
        return out_path

    async def wait_for(self, js_condition: str, timeout: float = 10.0, interval: float = 0.3):
        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < timeout:
            res = await self.evaluate(js_condition)
            if res:
                return res
            await asyncio.sleep(interval)
        raise TimeoutError(f"Condition not met within {timeout}s: {js_condition}")


async def main():
    print("=== Starting NexaFreight Chartroom Click & Visibility Walkthrough ===")
    temp_profile = tempfile.mkdtemp(prefix="chrome_walkthrough_")
    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    chrome_proc = subprocess.Popen([
        chrome_path,
        "--headless=new",
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={temp_profile}",
        "--window-size=1440,900",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank"
    ])
    print(f"Started Chrome (PID: {chrome_proc.pid}) on CDP port {CDP_PORT}")

    chrome = None
    screenshots = []

    try:
        # Wait for CDP
        ws_url = None
        for _ in range(30):
            try:
                req = urllib.request.Request(f"http://localhost:{CDP_PORT}/json/new?about:blank", method="PUT")
                with urllib.request.urlopen(req, timeout=1.0) as resp:
                    page_info = json.loads(resp.read().decode())
                    ws_url = page_info["webSocketDebuggerUrl"]
                    break
            except Exception:
                await asyncio.sleep(0.3)

        if not ws_url:
            raise RuntimeError("Failed to connect to Chrome on CDP port")

        chrome = ChromeWalkthrough(ws_url)
        await chrome.connect()
        await chrome.send("Page.enable")
        await chrome.send("Runtime.enable")
        await chrome.send("Emulation.setDeviceMetricsOverride", {
            "width": 1440,
            "height": 900,
            "deviceScaleFactor": 1,
            "mobile": False
        })

        # ─── Frame 1: Login Page ─────────────────────────────────────────────
        print("\n[Flow 1] Loading /login...")
        await chrome.send("Page.navigate", {"url": "http://localhost:3000/login"})
        await chrome.wait_for("document.readyState === 'complete'")
        await asyncio.sleep(1.2)
        s1 = await chrome.screenshot("chartroom_01_login_initial.png")
        screenshots.append(s1)

        # ─── Frame 2: Submit Auth & Enter Dashboard ───────────────────────────
        print("\n[Flow 2] Authenticating operator credentials...")
        await chrome.evaluate("document.getElementById('nf-submit').click()")
        await chrome.wait_for("window.location.pathname === '/'", timeout=8.0)
        await asyncio.sleep(3.0)  # Map tiles and data load
        s2 = await chrome.screenshot("chartroom_02_dashboard_overview.png")
        screenshots.append(s2)

        # ─── Frame 3: Click Alert Center Button ───────────────────────────────
        print("\n[Flow 3] Clicking Alert Center (A) button...")
        clicked_alerts = await chrome.evaluate("""
            (() => {
                const btn = document.querySelector('button[title="Alert center (A)"]');
                if (btn) { btn.click(); return true; }
                return false;
            })()
        """)
        print("Clicked Alert Center:", clicked_alerts)
        await asyncio.sleep(1.5)
        s3 = await chrome.screenshot("chartroom_03_alert_center_drawer.png")
        screenshots.append(s3)

        # Close Alert Center before next panel
        await chrome.evaluate("""
            (() => {
                const btn = document.querySelector('button[title="Alert center (A)"]');
                if (btn) btn.click();
            })()
        """)
        await asyncio.sleep(0.5)

        # ─── Frame 4: Click Analytics Button ─────────────────────────────────
        print("\n[Flow 4] Clicking Analytics Dashboard (G) button...")
        clicked_analytics = await chrome.evaluate("""
            (() => {
                const btn = document.querySelector('button[title="Analytics (G)"]');
                if (btn) { btn.click(); return true; }
                return false;
            })()
        """)
        print("Clicked Analytics:", clicked_analytics)
        await asyncio.sleep(1.5)
        s4 = await chrome.screenshot("chartroom_04_analytics_dashboard.png")
        screenshots.append(s4)

        # Close Analytics
        await chrome.evaluate("""
            (() => {
                const btn = document.querySelector('button[title="Analytics (G)"]');
                if (btn) btn.click();
            })()
        """)
        await asyncio.sleep(0.5)

        # ─── Frame 5: Click Search Button ────────────────────────────────────
        print("\n[Flow 5] Clicking Search (S) button...")
        clicked_search = await chrome.evaluate("""
            (() => {
                const btn = document.querySelector('button[title="Search (S)"]');
                if (btn) { btn.click(); return true; }
                return false;
            })()
        """)
        print("Clicked Search:", clicked_search)
        await asyncio.sleep(1.0)
        s5 = await chrome.screenshot("chartroom_05_search_bar.png")
        screenshots.append(s5)

        # Close Search
        await chrome.evaluate("""
            (() => {
                const btn = document.querySelector('button[title="Search (S)"]');
                if (btn) btn.click();
            })()
        """)
        await asyncio.sleep(0.5)

        # ─── Frame 6: Trigger Keyboard Shortcuts Modal ────────────────────────
        print("\n[Flow 6] Triggering Keyboard Shortcut '?'...")
        await chrome.evaluate("""
            (() => {
                window.dispatchEvent(new KeyboardEvent('keydown', { key: '?', code: 'Slash', shiftKey: true, bubbles: true }));
            })()
        """)
        await asyncio.sleep(1.0)
        s6 = await chrome.screenshot("chartroom_06_keyboard_shortcuts.png")
        screenshots.append(s6)

        # Close modal
        await chrome.evaluate("""
            (() => {
                window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', bubbles: true }));
            })()
        """)
        await asyncio.sleep(0.5)

        # ─── Frame 7: Validation Matrix Route ─────────────────────────────────
        print("\n[Flow 7] Navigating to /validation (Calibration Matrix)...")
        await chrome.send("Page.navigate", {"url": "http://localhost:3000/validation"})
        await chrome.wait_for("document.readyState === 'complete'")
        await asyncio.sleep(2.0)
        s7 = await chrome.screenshot("chartroom_07_validation_matrix.png")
        screenshots.append(s7)

        print("\nAll 7 walkthrough frames successfully captured!")

    finally:
        if chrome and chrome.ws:
            try:
                await chrome.ws.close()
            except Exception:
                pass
        try:
            chrome_proc.terminate()
            chrome_proc.wait(timeout=3.0)
        except Exception:
            try:
                chrome_proc.kill()
            except Exception:
                pass
        print("Chrome process exited.")

    # ─── 8. Generate Animated WebP Walkthrough using Node Sharp ──────────────
    print("\n--- Generating Animated WebP Walkthrough ---")
    node_script = """
    const sharp = require('sharp');
    const path = require('path');
    const fs = require('fs');

    const dir = 'C:\\\\Users\\\\RAJ KUMAR MERUGU\\\\.gemini\\\\antigravity-ide\\\\brain\\\\9f66dd52-de1b-4d62-80f9-6a2a1189294c';
    const files = [
        'chartroom_01_login_initial.png',
        'chartroom_02_dashboard_overview.png',
        'chartroom_03_alert_center_drawer.png',
        'chartroom_04_analytics_dashboard.png',
        'chartroom_05_search_bar.png',
        'chartroom_06_keyboard_shortcuts.png',
        'chartroom_07_validation_matrix.png'
    ];

    async function buildAnimated() {
        // Read buffers
        const buffers = files.map(f => fs.readFileSync(path.join(dir, f)));
        
        // Resize all to 1080x675 for high-efficiency WebP playback
        const resized = [];
        for (const b of buffers) {
            const r = await sharp(b).resize(1080, 675, { fit: 'inside' }).toBuffer();
            resized.push(r);
        }

        // Animated WebP with 1800ms delay per frame
        const animated = await sharp(resized[0], { animated: true })
            .webp({ loop: 0, delay: [2000, 2500, 2200, 2200, 1800, 1800, 2500] })
            .toFile(path.join(dir, 'chartroom_walkthrough.webp'));
        
        console.log('Successfully generated animated WebP:', animated);
    }
    buildAnimated().catch(err => console.error('Sharp error:', err));
    """
    
    script_path = ARTIFACT_DIR / "build_animation.js"
    script_path.write_text(node_script, encoding="utf-8")
    
    node_proc = subprocess.run(["node", str(script_path)], cwd=str(Path(__file__).resolve().parents[2] / "frontend"), capture_output=True, text=True)
    print("Node animation builder output:", node_proc.stdout)
    if node_proc.stderr:
        print("Node animation builder err:", node_proc.stderr)

if __name__ == "__main__":
    asyncio.run(main())
