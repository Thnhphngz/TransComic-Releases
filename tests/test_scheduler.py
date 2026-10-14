import asyncio
import time

import pytest

from transcomic.documents import decode_txt
from transcomic.providers import BatchResult
from transcomic.storage import Store
from transcomic.translation import Scheduler


class FakeProvider:
    def __init__(self):
        self.active = 0
        self.peak = 0
        self.calls = []

    async def translate(self, lines, source_lang, target_lang):
        self.active += 1
        self.peak = max(self.peak, self.active)
        self.calls.append([x["id"] for x in lines])
        await asyncio.sleep(0.03)
        self.active -= 1
        return BatchResult({x["id"]: "Dịch " + x["source"] for x in lines})


@pytest.mark.parametrize("concurrency", [1, 7, 30])
def test_concurrency_cap_and_no_duplicates(tmp_path, concurrency):
    store = Store(tmp_path / "s.db")
    doc, _ = store.import_document(tmp_path / "a.txt", decode_txt("\n".join(f"Line {i}" for i in range(90)).encode()))
    job = store.create_job(doc, "kira", "English", "Vietnamese", concurrency)
    fake = FakeProvider()
    scheduler = Scheduler(store, fake)
    scheduler.start(job)
    scheduler.join(10)
    assert scheduler._thread and not scheduler._thread.is_alive()
    assert fake.peak == concurrency
    assert len(fake.calls) == 30
    assert len({x for call in fake.calls for x in call}) == 90
    assert sum(x["state"] == "done" for x in store.lines(doc)) == 90
    store.close()


def test_pause_then_stop_does_not_dispatch_pending(tmp_path):
    store = Store(tmp_path / "s.db")
    doc, _ = store.import_document(tmp_path / "a.txt", decode_txt("\n".join(f"Line {i}" for i in range(90)).encode()))
    job = store.create_job(doc, "kira", "English", "Vietnamese", 2)
    fake = FakeProvider()
    scheduler = Scheduler(store, fake)
    scheduler.start(job)
    scheduler.pause()
    time.sleep(0.12)
    count = len(fake.calls)
    time.sleep(0.12)
    assert len(fake.calls) == count
    scheduler.stop()
    scheduler.join(5)
    assert len(store.batches(job, "pending")) >= 28
    assert store.job(job)["state"] == "stopped"
    store.close()
