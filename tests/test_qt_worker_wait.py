import threading
import time
import pytest
from PySide6.QtWidgets import QApplication
from qt_wait import wait_until


def test_event_loop_allows_worker_io_without_extending_deadline():
    app = QApplication.instance() or QApplication([])
    done = threading.Event()
    def work():
        for _ in range(40):
            time.sleep(.01)
        done.set()
    thread = threading.Thread(target=work)
    thread.start()
    try:
        assert wait_until(done.is_set, 900, 30)
    finally:
        thread.join(2)


def test_wait_deadline_and_predicate_exception():
    app = QApplication.instance() or QApplication([])
    start = time.monotonic()
    assert not wait_until(lambda: False, 40)
    assert time.monotonic()-start < .5
    def broken():
        raise ValueError('predicate failed')
    with pytest.raises(ValueError, match='predicate failed'):
        wait_until(broken, 40)
