"""Explicit Stage 2 verification: one metadata GET and one public-line POST.

Never run either permission flag without the user's separate authorization.
Reservations are durable and cannot be reset by this script, even after failure.
Reads the user's key/cache without opening/migrating/recovering their database.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import httpx
from transcomic.gemini import GeminiProvider
from transcomic.security import unprotect_key
from transcomic.documents import decode_txt
from transcomic.storage import Store
from transcomic.translation import Scheduler
from transcomic.prompts import messages

OUT = Path('artifacts/live_gemini_stage2')
PUBLIC_LINE = 'Hôm nay trời rất đẹp'


def reserve(kind, metadata):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT/(kind+'.request-reserved.json')
    # FileExistsError blocks a second send, including crash/timeout/HTTP failures.
    with path.open('x', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2); f.flush(); os.fsync(f.fileno())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-model-list', action='store_true')
    parser.add_argument('--allow-translation', action='store_true')
    parser.add_argument('--model')
    parser.add_argument('--report-only', action='store_true', help='Read the saved result without HTTP or replay')
    parser.add_argument('--authorization', help='Reference to the user approval; never inferred from old Kira approval')
    args = parser.parse_args()
    if args.report_only:
        with sqlite3.connect((OUT/'verification.sqlite3').resolve().as_uri()+'?mode=ro', uri=True) as c:
            row = c.execute('SELECT j.model,b.diagnostics,b.error,l.state,l.translation,(SELECT COUNT(*) FROM request_attempts a WHERE a.original_batch_id=b.id) FROM jobs j JOIN batches b ON b.job_id=j.id JOIN lines l ON l.document_id=j.document_id ORDER BY j.rowid DESC LIMIT 1').fetchone()
        report = {'model': row[0], 'request_attempts': row[5], 'http_status': json.loads(row[1]).get('http_status'),
            'diagnostics': json.loads(row[1]), 'error': row[2], 'line_state': row[3], 'translation': row[4],
            'retry_count': 0, 'cost_vnd': None, 'usage': None,
            'cost_note': 'No usage returned; no observed bill. HTTP rejection is not assumed free.',
            'verification_success': row[3] == 'done' and bool(row[4])}
        (OUT/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False)); return 0
    if not args.allow_model_list and not args.allow_translation:
        print('Prepared only: one public Vietnamese line -> English; one POST max, output 256 tokens, no retry/fallback. Optional models.list: one separately authorized GET. No API request sent.')
        return 0
    if not args.authorization: parser.error('Separate explicit user authorization required')
    if args.allow_translation and not args.model: parser.error('Explicit authorized model required; no fallback')
    db = Path(os.environ['LOCALAPPDATA'])/'TransComic'/'transcomic.sqlite3'
    with sqlite3.connect(db.as_uri()+'?mode=ro', uri=True) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute('SELECT id,encrypted,project FROM gemini_keys ORDER BY priority,rowid LIMIT 1').fetchone()
        if row is None: raise ValueError('Add a Gemini key in the encrypted desktop API settings first')
        secret = unprotect_key(row['encrypted'])
        cached = connection.execute("SELECT value FROM settings WHERE key='gemini_models'").fetchone()
        models = json.loads(cached['value']).get('models', []) if cached else []
    if not models and (OUT/'models.json').exists():
        models = json.loads((OUT/'models.json').read_text(encoding='utf-8'))['models']
    key = {'id': row['id'], 'secret': secret, 'project': row['project']}
    provider = GeminiProvider([key], args.model or 'metadata-only', max_tokens=256, timeout=60)
    if args.allow_model_list:
        reserve('models', {'authorization': args.authorization, 'request_kind': 'model_list', 'max_gets': 1, 'key_alias': key['id']})
        listed = asyncio.run(provider.list_models(max_pages=1))
        (OUT/'models.json').write_text(json.dumps(listed, ensure_ascii=False, indent=2), encoding='utf-8')
        models = listed['models']
        print('Metadata GET completed; model names:', [m['name'] for m in models])
    if args.allow_translation:
        if args.model not in {m['name'] for m in models}: raise ValueError('Authorized model is absent from the cached/explicitly fetched text-model list')
        authorization = json.loads((OUT/'authorization.json').read_text(encoding='utf-8'))
        pricing = json.loads((OUT/'pricing-plan.json').read_text(encoding='utf-8'))
        if pricing['model'] != args.model or pricing['max_output_tokens'] != 256:
            raise ValueError('Official pricing must be checked for this exact model/output cap before sending')
        byte_upper = sum(len(m['content'].encode('utf-8')) for m in messages([{'id': '0'*36, 'source': PUBLIC_LINE}], 'Tiếng Việt', 'Tiếng Anh'))+128
        if byte_upper > pricing['input_byte_upper_budget']: raise ValueError('Public input exceeded the reviewed budget')
        estimate = (pricing['input_byte_upper_budget']*pricing['input_usd_per_million']+256*pricing['output_including_thinking_usd_per_million'])/1_000_000*pricing['conservative_fx_vnd_per_usd']*pricing['extra_cost_safety_multiplier']
        if estimate > authorization['total_cost_cap_vnd']: raise ValueError('Estimated cost exceeds user authorization')
        reserve('translation', {'authorization': args.authorization, 'request_kind': 'translation', 'model': args.model,
            'max_posts': 1, 'lines': 1, 'public_line': PUBLIC_LINE, 'max_output_tokens': 256, 'retry': False, 'key_alias': key['id']})
        source = OUT/'public-line.txt'; source.write_text(PUBLIC_LINE, encoding='utf-8')
        store = Store(OUT/'verification.sqlite3')
        try:
            doc, _ = store.import_document(source, decode_txt(source.read_bytes()), 'Tiếng Việt', 'Tiếng Anh')
            job = store.create_job(doc, args.model, 'Tiếng Việt', 'Tiếng Anh', 1, timeout=60, provider='gemini', retry_504=False, max_requests=1)
            scheduler = Scheduler(store, provider); scheduler.start(job); scheduler.join(90)
            wait_timeout = scheduler._thread.is_alive()
            if scheduler._thread.is_alive():
                scheduler.stop()
                while scheduler._thread.is_alive(): scheduler.join(5)
            batch = store.batches(job)[0]; line = store.lines(doc)[0]
            attempts = store.attempts(batch['id'])
            usage = (batch['diagnostics'] or {}).get('usage', {})
            token_cost_usd = (usage.get('prompt_tokens', 0)*pricing['input_usd_per_million']+(usage.get('completion_tokens', 0)+usage.get('reasoning_tokens', 0))*pricing['output_including_thinking_usd_per_million'])/1_000_000 if usage else None
            report = {'model': args.model, 'request_attempts': len(attempts), 'line_state': line['state'], 'translation': line['translation'],
                'diagnostics': batch['diagnostics'], 'retry_count': scheduler.retry_count, 'cost_vnd': None,
                'scheduler_wait_timeout': wait_timeout,
                'paid_tier_token_price_estimate_usd': token_cost_usd,
                'paid_tier_token_price_estimate_vnd_at_observed_fx': token_cost_usd*pricing['fx_observed_usd_sell_vnd'] if token_cost_usd is not None else None,
                'cost_note': 'No invented charge: usage is recorded when returned; reconcile official pricing/billing separately.'}
            (OUT/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(report, ensure_ascii=False))
        finally: store.close()
    return 0


if __name__ == '__main__':
    try: raise SystemExit(main())
    except (ValueError, OSError, sqlite3.Error, RuntimeError, httpx.HTTPError) as exc:
        print('Verification blocked/failed:', type(exc).__name__, '; no retry/key/model fallback.'); raise SystemExit(1)
