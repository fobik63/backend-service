#!/usr/bin/env python3
"""Pre-launch audit: console logs and hardcoded / test API secrets.

Run from backend root:
  python deploy/preflight_audit.py
  python deploy/preflight_audit.py --root .
Exit code 0 = clean, 1 = findings.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Application source only — tests may use fake keys by design.
DEFAULT_SCAN_DIRS = ("app", "admin_microservice")

# CLI entrypoints that intentionally print to stdout/stderr.
ALLOWLIST_PATHS = frozenset(
    {
        "admin_microservice/mint_token.py",
        "deploy/preflight_audit.py",
        "deploy/autoscale.py",
    }
)

PRINT_RE = re.compile(
    r"(?m)^(?P<indent>\s*)(?P<stmt>print\s*\(|pprint\s*\()"
)
CONSOLE_RE = re.compile(r"console\.(log|debug|info|warn|error)\s*\(")
BREAKPOINT_RE = re.compile(r"(?m)^\s*(breakpoint\s*\(|pdb\.set_trace\s*\()")

# High-confidence secret literals (not env lookups / empty defaults).
HARDCODED_SECRET_RE = re.compile(
    r"""(?ix)
    (?:
        (?:api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|
           password|private[_-]?key)\s*=\s*
        (['"])(?!replace_with_|changeme|your_|xxx|TODO|PLACEHOLDER)
            [^'"]{16,}\1
      | (['"])(?:sk-ant-|sk-proj-|sk_live_|sk_test_|AKIA)[A-Za-z0-9_\-]{12,}\2
      | (['"])Bearer\s+[A-Za-z0-9\-_.]{20,}\3
    )
    """
)

TEST_KEY_MARKERS = (
    "test-api-key",
    "test_api_key",
    "sk-test-",
    "sk_test_",
    "fake-secret-key-for-tests",
    "provider-key-do-not-ship",
)

SKIP_NAME_PARTS = {
    ".venv",
    "venv",
    "__pycache__",
    ".git",
    "node_modules",
    ".pytest_cache",
    "uploads",
}

SCAN_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".yml", ".yaml", ".toml"}


@dataclass(frozen=True, slots=True)
class Finding:
    path: str
    line: int
    kind: str
    snippet: str


def _should_skip(path: Path) -> bool:
    return any(part in SKIP_NAME_PARTS for part in path.parts)


def _iter_files(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            if root.suffix in SCAN_SUFFIXES and not _should_skip(root):
                files.append(root)
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in SCAN_SUFFIXES:
                continue
            if _should_skip(path):
                continue
            files.append(path)
    return sorted(files)


def scan_text(relative_path: str, text: str) -> list[Finding]:
    """Scan a single file body for launch blockers."""

    findings: list[Finding] = []
    lines = text.splitlines()
    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("//"):
            continue

        if PRINT_RE.search(line):
            findings.append(
                Finding(relative_path, idx, "console_print", stripped[:160])
            )
        if CONSOLE_RE.search(line):
            findings.append(
                Finding(relative_path, idx, "console_log", stripped[:160])
            )
        if BREAKPOINT_RE.search(line):
            findings.append(
                Finding(relative_path, idx, "debugger", stripped[:160])
            )

        lower = line.lower()
        for marker in TEST_KEY_MARKERS:
            if marker in lower:
                findings.append(
                    Finding(
                        relative_path,
                        idx,
                        "test_api_key_marker",
                        stripped[:160],
                    )
                )
                break

        secret_match = HARDCODED_SECRET_RE.search(line)
        if secret_match is not None:
            findings.append(
                Finding(relative_path, idx, "hardcoded_secret", stripped[:160])
            )

    return findings


def audit_tree(backend_root: Path, scan_dirs: tuple[str, ...] = DEFAULT_SCAN_DIRS) -> list[Finding]:
    """Audit application trees under backend_root."""

    roots = [backend_root / name for name in scan_dirs]
    findings: list[Finding] = []
    for path in _iter_files(roots):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = str(path.relative_to(backend_root)).replace("\\", "/")
        if rel in ALLOWLIST_PATHS:
            continue
        findings.extend(scan_text(rel, text))
    return findings


def format_report(findings: list[Finding]) -> str:
    if not findings:
        return "Preflight audit: OK (no console prints / test API keys in app code)."
    lines = [f"Preflight audit: FAILED ({len(findings)} finding(s))", ""]
    for item in findings:
        lines.append(f"  [{item.kind}] {item.path}:{item.line}")
        lines.append(f"    {item.snippet}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Backend root (default: parent of deploy/)",
    )
    parser.add_argument(
        "--dirs",
        nargs="+",
        default=list(DEFAULT_SCAN_DIRS),
        help="Relative dirs to scan",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    findings = audit_tree(root, tuple(args.dirs))
    print(format_report(findings))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
