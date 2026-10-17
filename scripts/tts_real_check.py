"""Explicit developer-only local Kokoro check, never run by release tests.

Usage: python scripts/tts_real_check.py --models EXTERNAL_CACHE --output ARTIFACTS
Downloads require --install; no translation service is used.
"""
import argparse
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--models',required=True);parser.add_argument('--output',required=True);parser.add_argument('--install',action='store_true');parser.add_argument('--benchmark',action='store_true')
    args=parser.parse_args()
    from transcomic.tts.models import ModelManager
    from transcomic.tts.engine import KokoroEngine
    from transcomic.tts.catalog import LANGUAGES,voice_names,REVISION
    from transcomic.tts.audio import encode,validate
    from transcomic.tts.devices import benchmark
    import psutil
    import importlib.metadata as meta
    out=Path(args.output);out.mkdir(parents=True,exist_ok=True);manager=ModelManager(args.models)
    if args.install:manager.install()
    report=dict(revision=REVISION,versions={n:meta.version(n) for n in ('kokoro-onnx','soundfile','lameenc','numpy','misaki')},cases={},cpu={},memory={})
    start=time.perf_counter();engine=KokoroEngine(manager);report['cpu']['load_seconds']=time.perf_counter()-start
    cases=[('wav','Hello. This is an offline audio test.','af_heart','en-us',1,'wav'),
           ('mp3','This is a real MP3, encoded using LAME.','af_heart','en-us',1,'mp3'),
           ('slow','The sun is shining. This is a voice preview.','af_heart','en-us',.5,'wav'),
           ('fast','The sun is shining. This is a voice preview.','af_heart','en-us',2,'wav'),
           ('long',('A quiet morning brings a fresh beginning. '*25),'af_heart','en-us',1,'wav')]
    for lang,(name,prefix,text) in LANGUAGES.items():cases.append(('language-'+lang,text,voice_names(lang)[0],lang,1,'wav'))
    for name,text,voice,lang,speed,format in cases:
        start=time.perf_counter()
        try:
            info=encode(out/(name+'.'+format),engine.synthesize(text,voice,speed,lang),format)
            elapsed=time.perf_counter()-start;report['cases'][name]=dict(info,seconds=elapsed,throughput=info['duration']/elapsed,voice=voice,speed=speed,language=lang,characters=len(text))
        except Exception as exc:report['cases'][name]=dict(error=f'{type(exc).__name__}: {exc}')
        report['memory']['rss_bytes']=psutil.Process().memory_info().rss
        (out/'real-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(name,report['cases'][name],flush=True)
    assert report['cases']['slow']['duration']>report['cases']['fast']['duration']
    del engine
    if args.benchmark:
        report['benchmark']=benchmark(manager)
        (out/'real-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    if any('error' in item for item in report['cases'].values()):return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
