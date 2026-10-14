"""Bounded Qt waits that let Python I/O workers run between GUI callbacks."""
from PySide6.QtCore import QEventLoop, QTimer, Qt


def wait_until(condition, timeout_ms, interval_ms=20):
    if condition():
        return True
    loop = QEventLoop()
    poll = QTimer()
    poll.setTimerType(Qt.PreciseTimer)
    poll.setInterval(interval_ms)
    deadline = QTimer()
    deadline.setTimerType(Qt.PreciseTimer)
    deadline.setSingleShot(True)
    errors = []

    def check():
        try:
            if condition():
                loop.quit()
        except BaseException as error:
            errors.append(error)
            loop.quit()

    poll.timeout.connect(check)
    deadline.timeout.connect(loop.quit)
    poll.start()
    deadline.start(timeout_ms)
    try:
        # Unlike repeated qWait calls, exec releases the Python GIL for the
        # duration of the native event loop, including worker I/O completion.
        loop.exec()
    finally:
        poll.stop()
        deadline.stop()
    if errors:
        raise errors[0]
    return bool(condition())
