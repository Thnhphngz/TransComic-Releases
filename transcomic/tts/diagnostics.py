"""Whitelisted TTS diagnostics, independent of Qt and translation state."""
import json
import re
import traceback
from pathlib import Path

def redact(value):
    text=str(value).replace(str(Path.home()),'<USER>')
    text=re.sub(r'(?i)(bearer\s+)[^\s\"\']+',r'\1<REDACTED>',text)
    text=re.sub(r'(?i)((?:api[_ -]?key|password|authorization|access[_ -]?token|secret)\s*[=:]\s*)[^\s,;]+',r'\1<REDACTED>',text)
    return re.sub(r'\b(?:sk|AIza)[A-Za-z0-9_-]{12,}\b','<REDACTED>',text)


def diagnostic(exc,stage,run,runtime,segment=None):
    # Whitelist technical metadata; never accept a Store/settings/config dump.
    return dict(type=type(exc).__name__,message=redact(exc),stage=stage,run=run,segment=segment,
                requested_backend='Auto',actual_backend=runtime.get('backend'),executable=redact(runtime.get('executable','')),
                onnx_version=runtime.get('runtimes'),providers=runtime.get('providers',[]),
                traceback=redact(getattr(exc,'technical_traceback',traceback.format_exc())))


