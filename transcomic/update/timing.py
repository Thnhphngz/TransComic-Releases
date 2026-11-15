"""Local, best-effort stage timings. Never contain argv, tickets or user paths."""
from contextlib import contextmanager
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import re
import threading
import time
from uuid import uuid4
from ..version import VERSION


class UpdateTrace:
    def __init__(self,directory=None,component='app'):
        self.path=None;self.started=time.perf_counter();self.lock=threading.Lock();self.component=component
        if directory is not None:
            try:
                from ..release_adapters import safe_path
                root=safe_path(Path(directory));root.mkdir(parents=True,exist_ok=True)
                self.path=safe_path(root/('update-timing-'+uuid4().hex+'.jsonl'),root)
            except (OSError,ValueError):pass

    def event(self,stage,*,duration=None,error=None):
        if self.path is None:return
        if not re.fullmatch(r'[a-z_]{1,64}',stage):raise ValueError('Invalid timing stage')
        record=dict(stage=stage,component=self.component,version=VERSION,pid=os.getpid(),
                    utc=datetime.now(timezone.utc).isoformat(),elapsed_ms=round((time.perf_counter()-self.started)*1000,3))
        if duration is not None:record['duration_ms']=round(duration*1000,3)
        if error is not None:
            record['error_type']=type(error).__name__
            code=str(error)
            if re.fullmatch(r'[A-Z][A-Z0-9_]{0,95}',code):record['error_code']=code
        try:
            with self.lock,self.path.open('a',encoding='utf8') as stream:
                stream.write(json.dumps(record,separators=(',',':'))+'\n');stream.flush()
        except (OSError,ValueError):pass  # Diagnostic I/O cannot authorize/deny installation.

    @contextmanager
    def span(self,stage):
        start=time.perf_counter();self.event(stage+'_started')
        try:yield
        except BaseException as exc:
            self.event(stage+'_failed',duration=time.perf_counter()-start,error=exc);raise
        else:self.event(stage+'_finished',duration=time.perf_counter()-start)


def startup_trace(arguments,directory):
    tokens=[a.partition('=')[2] for a in arguments if a.startswith('--update-startup-token=')]
    if len(tokens)!=1 or not re.fullmatch('[0-9a-f]{64}',tokens[0]):return UpdateTrace()
    trace=UpdateTrace(directory,'startup');trace.event('app_entry');return trace
