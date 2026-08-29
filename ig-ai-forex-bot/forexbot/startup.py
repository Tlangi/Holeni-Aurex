from __future__ import annotations

from pathlib import Path
import sys


PACKAGE_NAMES = {
    "yaml": "PyYAML",
    "dotenv": "python-dotenv",
    "sklearn": "scikit-learn",
    "lightstreamer": "lightstreamer-client-lib",
}


def missing_dependency_message(module_name: str, project_root: Path | None = None) -> str:
    """Return a safe, actionable startup error without exposing environment values."""
    root = (project_root or Path.cwd()).resolve()
    package = PACKAGE_NAMES.get(module_name.split(".")[0], module_name.split(".")[0])
    venv_python = root / ".venv" / "Scripts" / "python.exe"
    lines = [
        f"ERROR: Required Python package '{package}' is not installed for the active interpreter.",
        f"Active interpreter: {sys.executable}",
        "The project virtual environment is probably not active.",
        "",
        "Run these commands from the project directory:",
        r"  .\.venv\Scripts\Activate.ps1",
        "  python -m pip install -r requirements-dev.txt",
        "  python -m forexbot.cli cache-status",
    ]
    if venv_python.exists():
        lines.extend([
            "",
            "Or use the project interpreter directly:",
            r"  .\.venv\Scripts\python.exe -m forexbot.cli cache-status",
        ])
    return "\n".join(lines)
