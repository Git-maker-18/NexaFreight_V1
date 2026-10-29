"""Build sanitized review_bundle.md for external AI review.

Strict sanitization rules:
- Redact passwords in all database URLs (postgresql://user:REDACTED@host...)
- Redact any Google API keys (AIzaSy...)
- Redact passwords in scripts/configs
- Exclude all .env / .env.local files
- Strip local user paths
- Clean trailing output
"""

import re
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent.parent
bundle_files = [
    "backend/src/nexafreight/dependencies.py",
    "backend/src/nexafreight/main.py",
    "backend/src/nexafreight/config.py",
    "backend/src/nexafreight/database.py",
    "backend/src/nexafreight/api/routes/alerts.py",
    "backend/src/nexafreight/api/routes/decisions.py",
    "backend/src/nexafreight/services/decision_executor.py",
    "backend/src/nexafreight/services/disruption_detector.py",
    "backend/src/nexafreight/services/reroute_engine.py",
    "backend/src/nexafreight/services/financial_engine.py",
    "backend/scripts/seed_user.py",
    "frontend/next.config.ts",
    "frontend/src/middleware.ts",
    "docker/Dockerfile.backend",
    "docker/Dockerfile.frontend",
    "docker-compose.yml",
    "render.yaml",
    "backend/src/nexafreight/api/routes/internal.py",
    "backend/src/nexafreight/jobs/fx.py",
    "backend/src/nexafreight/jobs/http.py",
    "backend/src/nexafreight/jobs/runner.py",
    "backend/src/nexafreight/jobs/__init__.py",
    "backend/src/nexafreight/models/external_event.py",
    "backend/src/nexafreight/routers/map.py",
    ".github/workflows/ci.yml",
    ".github/workflows/nightly.yml",
    # Audit & Hardening Remediation additions
    "backend/src/nexafreight/api/routes/copilot.py",
    "backend/src/nexafreight/api/routes/shipments.py",
    "backend/src/nexafreight/ml/eta_model.py",
    "backend/migrations/versions/20261029_1400_a1b2c3d4e5f6_immutable_audit_logs_trigger.py",
    "frontend/src/hooks/useSSEPositions.ts",
    "frontend/src/lib/nexafreight/client.ts",
    "backend/eval/LEAKAGE_AND_QUANTILE_AUDIT.md",
    "backend/eval/AUDIT2.md",
    "README.md",
    "backend/scripts/derive_lane_quantiles.py",
    "backend/tests/unit/test_eta_serves_lane_quantiles.py",
]


def sanitize_content(text: str) -> str:
    # 1. Redact passwords in DB URLs
    text = re.sub(
        r'(postgres(?:ql)?(?:\+[a-z0-9]+)?://[^:]+:)(?:[^@\s]+)(@)',
        r'\g<1>REDACTED\2',
        text,
        flags=re.IGNORECASE,
    )

    # 2. Redact Google API keys
    text = re.sub(r'AIza[0-9A-Za-z-_]{35}', 'AIzaSyREDACTED_API_KEY_FOR_REVIEW', text)

    # 3. Redact common cleartext passwords in seed/config
    text = re.sub(
        r'("password"\s*:\s*)"[^"]+"',
        r'\1"REDACTED"',
        text,
    )
    text = re.sub(
        r'(password=)[^\s,\)]+',
        r'\1REDACTED',
        text,
    )
    text = re.sub(
        r'(\$\{POSTGRES_PASSWORD:-)[^\}]+\}',
        r'\g<1>REDACTED}',
        text,
    )

    # 4. Scrub Windows username / local paths
    text = re.sub(r'[A-Za-z]:\\[Uu]sers\\[^\\]+\\[^\s]+', '/workspace/path', text)
    text = text.replace("RAJ KUMAR MERUGU", "developer")

    return text


def build_bundle():
    sections = []
    for rel_path in bundle_files:
        full_path = repo_root / rel_path
        if not full_path.exists():
            print(f"Warning: File not found: {rel_path}")
            continue

        content = full_path.read_text(encoding="utf-8", errors="replace")
        sanitized = sanitize_content(content)

        section = f"===== {rel_path} =====\n\n{sanitized.strip()}\n"
        sections.append(section)

    bundle_text = "\n".join(sections) + "\n"

    # Targets: write both inside NexaFreight-fresh and to parent nexagithub
    targets = [
        repo_root / "review_bundle.md",
        repo_root.parent / "review_bundle.md",
    ]

    for target in targets:
        target.write_text(bundle_text, encoding="utf-8")
        print(f"Wrote sanitized review bundle to: {target} ({len(bundle_text.splitlines())} lines)")


if __name__ == "__main__":
    build_bundle()
