from pathlib import Path
import sqlite3

import pytest

from transcomic.documents import decode_txt, render_export
from transcomic.storage import SCHEMA, Store


def fixture_store(tmp_path: Path):
    store = Store(tmp_path / "state.sqlite3")
    doc_id, _ = store.import_document(tmp_path / "source.txt", decode_txt("Alpha\r\nBeta\n...\nGamma".encode()))
    return store, doc_id


def test_duplicate_import_and_snapshot(tmp_path):
    store, doc_id = fixture_store(tmp_path)
    again, created = store.import_document(tmp_path / "source.txt", decode_txt("Alpha\r\nBeta\n...\nGamma".encode()))
    assert again != doc_id and created
    assert {r['id'] for r in store.lines(again)}.isdisjoint(r['id'] for r in store.lines(doc_id))
    assert all(r['translation'] is None for r in store.lines(again))
    assert store.document(doc_id)["snapshot"] == b"Alpha\r\nBeta\n...\nGamma"
    assert len(store.lines(doc_id)) == 4
    store.close()


def test_batch_ids_and_partial_result(tmp_path):
    store, doc_id = fixture_store(tmp_path)
    job_id = store.create_job(doc_id, "kira-2.5-flash", "English", "Vietnamese", 3)
    batches = store.batches(job_id)
    assert len(batches) == 1 and len(batches[0]["payload"]) == 3
    batch = batches[0]
    assert store.claim_batch(batch["id"])
    assert not store.claim_batch(batch["id"])
    ids = [item["id"] for item in batch["payload"]]
    store.finish_batch(batch["id"], {ids[2]: "Gamma dịch", ids[0]: "Alpha dịch"}, "Missing ID")
    rows = store.lines(doc_id)
    assert [r["translation"] for r in rows] == ["Alpha dịch", None, None, "Gamma dịch"]
    assert rows[1]["state"] == "error"
    assert store.batches(job_id)[0]["state"] == "partial"
    store.close()


def test_edit_blocks_stale_response(tmp_path):
    store, doc_id = fixture_store(tmp_path)
    job_id = store.create_job(doc_id, "kira-2.5-flash", "English", "Vietnamese", 1)
    batch = store.batches(job_id)[0]
    store.claim_batch(batch["id"])
    first = batch["payload"][0]["id"]
    second = batch["payload"][1]["id"]
    store.edit_line(first, "translation", "Bản dịch tay")
    store.edit_line(second, "source", "Beta edited")
    store.finish_batch(batch["id"], {x["id"]: "Old API" for x in batch["payload"]})
    rows = store.lines(doc_id)
    assert rows[0]["translation"] == "Bản dịch tay"
    assert rows[0]["state"] == "done"
    assert rows[1]["translation"] is None
    assert rows[1]["state"] == "pending"
    assert rows[3]["translation"] == "Old API"
    store.close()


def test_restart_marks_inflight_unknown_and_never_claims_it(tmp_path):
    store, doc_id = fixture_store(tmp_path)
    job = store.create_job(doc_id, "kira-2.5-flash", "English", "Vietnamese", 1)
    batch = store.batches(job)[0]
    store.claim_batch(batch["id"])
    store.close()
    reopened = Store(tmp_path / "state.sqlite3")
    assert reopened.batches(job)[0]["state"] == "unknown"
    assert reopened.job(job)["state"] == "ready"  # Never auto-started.
    assert not reopened.claim_batch(batch["id"])
    assert [r["state"] for r in reopened.lines(doc_id) if r["state"] == "unknown"] == ["unknown"] * 3
    reopened.close()


def test_line_edit_rejects_newline(tmp_path):
    store, doc_id = fixture_store(tmp_path)
    line_id = store.lines(doc_id)[0]["id"]
    with pytest.raises(ValueError):
        store.edit_line(line_id, "source", "new\nline")
    assert len(store.lines(doc_id)) == 4
    store.close()


def test_edit_before_dispatch_is_not_sent(tmp_path):
    store, doc_id = fixture_store(tmp_path)
    job = store.create_job(doc_id, "kira", "English", "Vietnamese", 1)
    first = store.batches(job)[0]["payload"][0]["id"]
    store.edit_line(first, "source", "Updated before dispatch")
    batch = store.batches(job)[0]
    claimed = store.claim_batch(batch["id"])
    assert len(claimed) == 2
    assert first not in {x["id"] for x in claimed}
    assert store.line(first)["state"] == "pending"
    store.close()


def test_result_is_persisted_before_ui_refresh(tmp_path):
    store, doc_id = fixture_store(tmp_path)
    job = store.create_job(doc_id, "kira", "English", "Vietnamese", 1)
    batch = store.batches(job)[0]
    store.claim_batch(batch["id"])
    store.finish_batch(batch["id"], {x["id"]: x["source"] + " VI" for x in batch["payload"]})
    store.close()
    reopened = Store(tmp_path / "state.sqlite3")
    assert [x["state"] for x in reopened.lines(doc_id)] == ["done", "done", "skip", "done"]
    assert reopened.batches(job)[0]["state"] == "done"
    reopened.close()


def test_legacy_database_migrates_without_losing_data(tmp_path):
    path = tmp_path / "legacy.db"
    db = sqlite3.connect(path)
    db.executescript(SCHEMA.replace(" format TEXT NOT NULL DEFAULT 'txt',\n", ""))
    db.execute("INSERT INTO documents(id,path,digest,snapshot,encoding,source_lang,target_lang) VALUES (?,?,?,?,?,?,?)",
               ("doc", "old.txt", "digest", b"Original", "utf-8", "English", "Vietnamese"))
    db.execute("INSERT INTO lines(id,document_id,ordinal,source,ending,state) VALUES (?,?,?,?,?,?)",
               ("line", "doc", 0, "Original", "", "done"))
    db.execute("UPDATE lines SET translation='Bản dịch' WHERE id='line'")
    db.execute("INSERT INTO settings(key,value) VALUES ('kira_model','kira-2.5-flash')")
    db.execute("INSERT INTO secrets(key,encrypted) VALUES ('kira',?)", (b"encrypted-key",))
    db.commit()
    db.close()
    store = Store(path)
    assert store.document("doc")["format"] == "txt"
    assert store.lines("doc")[0]["translation"] == "Bản dịch"
    assert store.setting("kira_model") == "kira-2.5-flash"
    assert store.load_key() == b"encrypted-key"
    assert store.db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "9"
    assert 'verified_translation_revision' in {r['name'] for r in store.db.execute('PRAGMA table_info(lines)')}
    store.close()
