import pytest


@pytest.fixture(autouse=True)
def _isolated_history(tmp_path, monkeypatch):
    """Keep tests from writing run snapshots into the real home directory."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
