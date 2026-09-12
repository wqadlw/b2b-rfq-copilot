"""Environment bootstrap check: verifies toolchain per docs/adr/0001 (frozen stack).

Every subprocess call uses a fully literal argv (fixed commands, no shell, no
interpolation) — this script only reports versions, it never executes user input.
"""

from __future__ import annotations

import subprocess
import sys

REQUIRED = {
    "uv": "https://docs.astral.sh/uv/ (Python 3.12 + dependency management)",
    "node": "https://nodejs.org (>= 20 LTS)",
    "pnpm": "corepack enable && corepack prepare pnpm@latest --activate",
    "git": "https://git-scm.com",
}


def _probe_versions() -> dict[str, str]:
    """Probe each tool with its own literal argv; failures are reported as absent."""
    found: dict[str, str] = {}

    try:
        out = subprocess.run(["uv", "--version"], capture_output=True, text=True, timeout=30, shell=False)
        line = out.stdout.strip().splitlines()[0] if out.returncode == 0 else ""
        if line:
            found["uv"] = line
    except (OSError, subprocess.TimeoutExpired):
        pass

    try:
        out = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=30, shell=False)
        line = out.stdout.strip().splitlines()[0] if out.returncode == 0 else ""
        if line:
            found["node"] = line
    except (OSError, subprocess.TimeoutExpired):
        pass

    try:
        out = subprocess.run(["pnpm", "--version"], capture_output=True, text=True, timeout=30, shell=False)
        line = out.stdout.strip().splitlines()[0] if out.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        line = ""
    if not line:
        # Windows installs pnpm as a .cmd shim; CreateProcess needs the explicit extension
        try:
            out = subprocess.run(["pnpm.cmd", "--version"], capture_output=True, text=True, timeout=30, shell=False)
            line = out.stdout.strip().splitlines()[0] if out.returncode == 0 else ""
        except (OSError, subprocess.TimeoutExpired):
            line = ""
    if line:
        found["pnpm"] = line

    try:
        out = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=30, shell=False)
        line = out.stdout.strip().splitlines()[0] if out.returncode == 0 else ""
        if line:
            found["git"] = line
    except (OSError, subprocess.TimeoutExpired):
        pass

    return found


def _managed_python_version() -> str | None:
    try:
        out = subprocess.run(
            ["uv", "run", "python", "--version"], capture_output=True, text=True, timeout=60, shell=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def main() -> int:
    found = _probe_versions()
    missing: list[str] = []
    for tool, hint in REQUIRED.items():
        # probe success is authoritative: on Windows pnpm lives behind a .cmd shim
        if tool not in found:
            missing.append(tool)
            print(f"MISSING  {tool:8s} -> {hint}")
        else:
            print(f"OK       {tool:8s} {found[tool]}")

    py = _managed_python_version() or ""
    if py and not py.startswith("Python 3.12"):
        print(f"WARN     managed python is '{py}', ADR-0001 freezes 3.12")

    print()
    if missing:
        print("bootstrap: install the missing tools above, then re-run.")
        return 1
    print("bootstrap: run `uv sync --extra dev && cd frontend && pnpm install` to finish setup.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
