"""No network/inference: explicit prompt selection affects new jobs only."""
import json
from transcomic.deepseek import MODEL, settings, selected_prompt
from transcomic.documents import decode_txt
from transcomic.storage import Store
from transcomic.translation_policy import VERSION, CANDIDATE_VERSION, V4_VERSION


def test_explicit_v4_selection_only_affects_new_frozen_jobs(tmp_path):
    store=Store(tmp_path/'isolated.sqlite3')
    try:
        assert settings(store)['prompt_version']==VERSION
        doc,_=store.import_document(tmp_path/'chapter.txt',decode_txt(b'Hello world\n'),'vi','en')
        old=store.create_job(doc,MODEL,'vi','en',1,provider='deepseek',config=settings(store))
        frozen=store.job(old)
        store.set_setting('deepseek_prompt_version',V4_VERSION)
        assert settings(store)['prompt_version']==V4_VERSION
        second,_=store.import_document(tmp_path/'second.txt',decode_txt(b'Another chapter\n'),'vi','en')
        new=store.create_job(second,MODEL,'vi','en',1,provider='deepseek',config=settings(store))
        assert store.job(new)['prompt_version']==V4_VERSION
        assert store.job(old)==frozen
        assert json.loads(store.job(new)['config'])['auto_retries']==0
        store.set_setting('deepseek_prompt_version',CANDIDATE_VERSION)
        assert settings(store)['prompt_version']==CANDIDATE_VERSION
        store.set_setting('deepseek_prompt_version','unrecognized-stale-value')
        assert settings(store)['prompt_version']==VERSION
        assert not store.db.execute('SELECT 1 FROM request_attempts').fetchone()
    finally:store.close()


def test_prompt_selector_persists_without_changing_existing_jobs(gui):
    app,store,w=gui
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    w.pages.setCurrentIndex(2);w.open_api_section('deepseek');app.processEvents()
    assert w.deepseek_prompt.currentData()==VERSION
    QTest.mouseClick(w.deepseek_prompt,Qt.LeftButton);app.processEvents()
    view=w.deepseek_prompt.view()
    index=view.model().index(w.deepseek_prompt.findData(V4_VERSION),0)
    QTest.qWait(80)
    assert view.isVisible() and view.viewport().rect().contains(view.visualRect(index).center())
    QTest.mouseMove(view.viewport(),view.visualRect(index).center())
    QTest.mouseClick(view.viewport(),Qt.LeftButton,pos=view.visualRect(index).center())
    app.processEvents()
    assert settings(store)['prompt_version']==V4_VERSION
    assert 'job' in w.deepseek_prompt.toolTip().lower()
    assert not store.jobs()


def test_prompt_preference_does_not_require_a_valid_price_catalog(tmp_path):
    store=Store(tmp_path/'settings.sqlite3')
    try:
        store.set_setting('deepseek_prompt_version',V4_VERSION)
        store.set_setting('deepseek_pricing','invalid-old-json')
        assert selected_prompt(store)==V4_VERSION
    finally:store.close()


# Reuse the isolated GUI with guarded HTTP; no production data or live key.
from test_deepseek_integration import gui
