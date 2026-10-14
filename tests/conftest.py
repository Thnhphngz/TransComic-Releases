import pytest


@pytest.fixture(autouse=True)
def confirm_test_window_close(monkeypatch):
    """Existing workflow tests accept close; confirmation itself has dedicated tests."""
    from transcomic.ui.main import MainWindow
    monkeypatch.setattr(MainWindow, "confirm_exit", lambda self, running: "safe" if running else "exit")
