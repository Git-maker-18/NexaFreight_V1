"""CI grep-gate test: ensure no plaintext password literals exist in backend/scripts/."""

import re
from pathlib import Path

# Forbidden literal passwords that were previously used
FORBIDDEN_LITERALS = [
    "admin123",
    "operator123",
    "viewer123",
    "changeme123",
]

# Patterns for hardcoded password assignments
PASSWORD_ASSIGNMENT_PATTERN = re.compile(
    r'(?:password|pwd)\s*[:=]\s*["\'](?!os\.environ|secrets|dummy_hash|\$)[^"\']{4,}["\']',
    re.IGNORECASE,
)


def test_no_plaintext_password_literals_in_scripts():
    """Ensure all scripts in backend/scripts read SEED_PASSWORD or generate random tokens."""
    scripts_dir = Path(__file__).parent.parent.parent / "scripts"
    assert scripts_dir.is_dir(), f"Scripts directory not found: {scripts_dir}"

    violations = []

    for py_file in scripts_dir.glob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        lines = content.splitlines()

        in_docstring = False
        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            # Toggle multi-line docstrings
            if stripped.startswith('"""') or stripped.startswith("'''"):
                if stripped.count('"""') == 1 or stripped.count("'''") == 1:
                    in_docstring = not in_docstring
                continue
            if in_docstring or stripped.startswith("#"):
                continue

            for forbidden in FORBIDDEN_LITERALS:
                if f'"{forbidden}"' in line or f"'{forbidden}'" in line:
                    violations.append(f"{py_file.name}:{idx}: contains forbidden literal password '{forbidden}'")

            if PASSWORD_ASSIGNMENT_PATTERN.search(line):
                # Allow dummy passwords in verification/probe scripts explicitly marked as tests
                if "verify" in py_file.name or "test" in py_file.name:
                    continue
                violations.append(f"{py_file.name}:{idx}: suspected hardcoded password assignment: {stripped}")

    assert not violations, "Found password literals in scripts:\n" + "\n".join(violations)

