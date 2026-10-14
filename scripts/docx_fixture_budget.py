"""Bound the three authorized offline tests of the user's Word document."""
import json
import os
from pathlib import Path
from datetime import datetime, timezone

LEDGER = Path(__file__).resolve().parents[1]/'artifacts'/'final'/'docx-test-ledger.json'


def reserve(label):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    guard = LEDGER.with_suffix('.lock')
    descriptor = os.open(guard, os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    try:
        data = json.loads(LEDGER.read_text(encoding='utf-8'))
        if len(data['passes']) >= data['limit']: return None
        number = len(data['passes'])+1
        data['passes'].append({'number':number,'label':label,'status':'reserved','time':datetime.now(timezone.utc).isoformat()})
        LEDGER.write_text(json.dumps(data,indent=2),encoding='utf-8')
        return number
    finally:
        os.close(descriptor); guard.unlink()


def complete(number):
    data=json.loads(LEDGER.read_text(encoding='utf-8'))
    data['passes'][number-1]['status']='passed'
    LEDGER.write_text(json.dumps(data,indent=2),encoding='utf-8')
