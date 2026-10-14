"""ONE authorized round. Durable reservations prevent repeats, including after a crash.

Authorization: user approved 3 calls (one per model), <=1,000 VND on 2026-10-13.
Never remove or reset the ledger to rerun. No retry/fallback or model discovery calls.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from datetime import datetime, timezone

import httpx
from lxml import html
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from transcomic.app import data_path
from transcomic.documents import ImportedText, TextLine
from transcomic.docx_document import import_docx
from transcomic.prompts import messages
from transcomic.providers import KiraProvider
from transcomic.security import unprotect_key
from transcomic.storage import Store
from transcomic.translation import Scheduler
from transcomic.ui.main import MainWindow
from transcomic.ui.window_state import show_initial

MODELS = ('coding-mimo-v2.6-flash', 'deepseek-v4.1-flash', 'glm-5.3-flash')
OUT = Path('artifacts/live_api_20261013')
SOURCE = Path(r'D:\word 50 cach\7-8.docx')


def save(path, value):
    temporary = path.with_suffix(path.suffix+'.tmp')
    with temporary.open('w', encoding='utf-8') as file:
        json.dump(value, file, ensure_ascii=False, indent=2)
        file.flush(); os.fsync(file.fileno())
    temporary.replace(path)


def public_prices():
    result = {}
    for model in MODELS:
        url = 'https://kiraai.vn/models/'+model+'/'
        response = httpx.get(url, timeout=25, follow_redirects=True)
        response.raise_for_status()
        tree = html.fromstring(response.text)
        rows = [' '.join(r.text_content().split()) for r in tree.xpath('//*[contains(@class, "mdp-price-raw")]/../..')]
        fields = {}
        for label, prefix in (('input', 'Đầu vào'), ('output', 'Đầu ra')):
            row = next(r for r in rows if r.startswith(prefix))
            numbers = [int(n.replace('.', '')) for n in re.findall(r'([\d.]+)đ', row)]
            fields[label+'_original_vnd_per_million'] = numbers[0]
            fields[label+'_sale_vnd_per_million'] = numbers[-1]
        result[model] = {'source': url, 'checked_at': datetime.now(timezone.utc).isoformat(), **fields}
    return result


def key_readonly():
    key = os.environ.get('KIRA_API_KEY')
    if key:
        return key
    with sqlite3.connect(data_path().resolve().as_uri()+'?mode=ro', uri=True) as db:
        row = db.execute("SELECT encrypted FROM secrets WHERE key='kira'").fetchone()
    if not row:
        raise RuntimeError('No stored Kira key')
    return unprotect_key(row[0])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ledger_path = OUT/'authorization-ledger.json'
    if ledger_path.exists():
        print('Round already reserved. Read artifacts/live_api_20261013; no new HTTP calls.')
        return
    imported = import_docx(SOURCE)
    fixture = json.loads(Path('tests/fixtures/review_7_8.json').read_text(encoding='utf-8'))
    digest = hashlib.sha256(imported.raw).hexdigest()
    assert digest == fixture['source_sha256'] and len(imported.units) == 125
    prices = public_prices()
    save(OUT/'public-prices.json', prices)
    key = key_readonly()  # No mutation or migration of the user's database.
    ledger = {'authorization_date': '2026-10-13', 'max_vnd': 1000, 'max_requests': 3,
              'max_requests_per_model': 1, 'retry_504': False, 'max_tokens': 512, 'max_request_chars': 4000,
              'source_sha256': digest, 'source_units': 125, 'reservations': [], 'results': []}
    # Exclusive creation is the global no-replay gate, before any paid call.
    with ledger_path.open('x', encoding='utf-8') as file:
        json.dump(ledger, file, ensure_ascii=False, indent=2); file.flush(); os.fsync(file.fileno())
    app = QApplication.instance() or QApplication([])
    store = Store(OUT/'test-results.sqlite3')
    window = MainWindow(store)
    show_initial(window)
    charged_bound = 0.0
    try:
        for model in MODELS:
            doc, _ = store.import_document(SOURCE, ImportedText(tuple(TextLine(u.text, '') for u in imported.units), 'docx', imported.raw),
                                          'Tiếng Việt', 'Tiếng Anh', document_format='docx', locators=[u.locator for u in imported.units])
            rows = store.lines(doc)
            target = rows[25]
            job = store.create_job(doc, model, 'Tiếng Việt', 'Tiếng Anh', 1, line_ids=[target['id']], retry_504=False, max_requests=1)
            batch = store.batches(job)[0]
            # Two neighboring source lines; one actual translation target.
            payload = batch['payload']
            payload[0]['context'] = [{'id': r['id'], 'source': r['source']} for r in (rows[24], rows[26])]
            with store.transaction():
                store.db.execute('UPDATE batches SET payload=? WHERE id=?', (json.dumps(payload, ensure_ascii=False), batch['id']))
            body = {'model': model, 'stream': False, 'messages': messages(payload, 'Tiếng Việt', 'Tiếng Anh'), 'max_tokens': 512}
            chars = len(json.dumps(body, ensure_ascii=False))
            assert chars <= 4000 and len(payload) == 1
            # UTF8 bytes + message overhead is deliberately conservative vs token estimates.
            input_bound = len(json.dumps(body, ensure_ascii=False).encode('utf-8'))+128
            p = prices[model]
            bound = (input_bound*p['input_original_vnd_per_million']+512*p['output_original_vnd_per_million'])/1_000_000
            assert charged_bound+bound <= 1000
            reservation = {'model': model, 'document_id': doc, 'job_id': job, 'batch_id': batch['id'],
                           'line_ids': [target['id']], 'ordinals': [26], 'context_ordinals': [25, 27], 'context_lines': 2,
                           'request_chars': chars, 'estimated_input_token_bound': input_bound,
                           'estimated_max_vnd_excluding_unreported_reasoning': round(bound, 6), 'state': 'reserved_before_dispatch'}
            ledger['reservations'].append(reservation)
            save(ledger_path, ledger)
            window.open_document(doc)
            window.scheduler = Scheduler(store, KiraProvider(key, model, timeout=90, max_tokens=512), window.bridge.changed.emit)
            window.current_job_ids = {target['id']}
            window.scheduler.start(job)
            while window.scheduler._thread.is_alive():
                app.processEvents()
                QTest.qWait(20)  # GUI pump only; no scheduler/request backoff.
            app.processEvents(); window.refresh()
            batch = store.batches(job)[0]
            diagnostics = batch.get('diagnostics') or {}
            usage = diagnostics.get('usage')
            actual_cost = ((usage.get('prompt_tokens', 0)*p['input_sale_vnd_per_million']+usage.get('completion_tokens', 0)*p['output_sale_vnd_per_million'])/1_000_000) if usage else None
            row = store.line(target['id'])
            result = {'model': model, 'http_status': diagnostics.get('http_status'), 'elapsed_seconds': diagnostics.get('elapsed_seconds'),
                      'failure_kind': diagnostics.get('failure_kind'), 'valid_ids': diagnostics.get('returned_valid_ids', 0),
                      'persisted_valid_ids': int(bool(row['translation'])), 'usage': usage, 'estimated_vnd_from_reported_usage': actual_cost,
                      'state': row['state'], 'error': batch['error'], 'attempts': len(store.attempts(batch['id'])),
                      'gui_received': any(e['event'] == 'gui_received' and e.get('job_id') == job for e in store.log.snapshot()),
                      'punctuation_warnings': [r['warnings'] for r in store.warning_rows(doc) if r['id'] == target['id']],
                      'semantic_reference_match': bool(row['translation'] and any(s in row['translation'].casefold() for s in ('say ah', 'say aah', 'open wide')))}
            ledger['results'].append(result); charged_bound += max(bound, actual_cost or 0)
            save(ledger_path, ledger)
            print(json.dumps(result, ensure_ascii=True))
            if usage and (usage.get('prompt_tokens', 0) > input_bound or usage.get('completion_tokens', 0) > 512 or (actual_cost or 0) > bound):
                ledger['stopped_reason'] = 'reported_usage_exceeded_configured_estimate'
                save(ledger_path, ledger); break
        assert SOURCE.read_bytes() == imported.raw
        ledger['source_unchanged'] = True
        ledger['estimated_total_vnd_reported_usage'] = sum(r['estimated_vnd_from_reported_usage'] or 0 for r in ledger['results'])
        ledger['unreported_charge_possible'] = any(not r['usage'] for r in ledger['results'])
        save(ledger_path, ledger)
        store.log.flush()
        store.log.export(OUT/'console-report.json')
        store.log.export(OUT/'console-report.txt')
        window.pages.setCurrentIndex(4); window.console.reload()
        window.grab().save(str(OUT/'console-native.png'))
    finally:
        window._exit_authorized = True; window.close()


if __name__ == '__main__':
    main()
