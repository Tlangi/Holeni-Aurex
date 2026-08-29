from pathlib import Path

from forexbot.startup import missing_dependency_message


def test_missing_dependency_message_is_actionable(tmp_path):
    (tmp_path / ".venv" / "Scripts").mkdir(parents=True)
    (tmp_path / ".venv" / "Scripts" / "python.exe").touch()

    message = missing_dependency_message("joblib", Path(tmp_path))

    assert "Required Python package 'joblib'" in message
    assert "requirements-dev.txt" in message
    assert "Activate.ps1" in message
    assert ".venv\\Scripts\\python.exe" in message
