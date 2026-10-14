try:
    from scripts.test_runtime import TemporaryDirectory
except ModuleNotFoundError:
    from test_runtime import TemporaryDirectory
"""Offline measurements against copied, previously verified results; never sends HTTP."""
import json
import sqlite3
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from transcomic.storage import Store
from transcomic.language_validator import validator, export_faults


def timed(fn, n=5):
    samples=[]
    for _ in range(n):
        start=time.perf_counter(); fn(); samples.append(time.perf_counter()-start)
    return round(statistics.median(samples)*1000, 4)


def run():
    with TemporaryDirectory() as directory:
        source=sqlite3.connect(f'file:{(ROOT / "artifacts/wrong-language/live/verified.sqlite3").as_posix()}?mode=ro', uri=True)
        copy=sqlite3.connect(Path(directory)/'benchmark.db'); source.backup(copy); copy.close(); source.close()
        store=Store(Path(directory)/'benchmark.db')
        doc=store.documents()[0]; rows=store.lines(doc['id'])[:125]
        check=lambda r: validator.validate(r['source'],r['translation'],doc['source_lang'],doc['target_lang'],r['id'])
        result={'rows':len(rows), 'validator_line_ms':timed(lambda:check(rows[0]),100),
                'validator_batch_ms':timed(lambda:[check(r) for r in rows[:3]],30),
                'validator_document_ms':timed(lambda:[check(r) for r in rows]),
                'export_guard_ms':timed(lambda:export_faults(doc,rows)),
                'history_check_ms':timed(lambda:store.validate_document_language(doc['id'])),
                'warning_poll_ms':timed(lambda:store.warning_rows(doc['id']))}
        store.close()
    output=ROOT/'artifacts/performance'/f'{sys.argv[1] if len(sys.argv)>1 else "after"}-benchmark.json'
    output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))

if __name__=='__main__':run()
