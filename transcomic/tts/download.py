"""Pinned HTTPS assets, bounded retries and validated Range resume. No installers."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import threading
from urllib.parse import urlsplit
import httpx


class SetupCancelled(InterruptedError):pass


def check_cancel(cancel):
    if cancel.is_set():raise SetupCancelled('Đã hủy chuẩn bị Kokoro; dữ liệu đã xác minh được giữ.')


def verified(path,record):
    if not path.is_file() or path.stat().st_size!=record['size']:return False
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()==record['sha256']


def fetch(client,record,target,cancel=None,progress=lambda *args:None,attempts=3):
    from .output import safe_path
    cancel=cancel or threading.Event();target=safe_path(Path(target));target.parent.mkdir(parents=True,exist_ok=True)
    if not re.fullmatch('[0-9a-f]{64}',record['sha256']) or not 0<record['size']<=4*1024**3:raise ValueError('Invalid pinned asset')
    url=record['url'];host=urlsplit(url).hostname
    if urlsplit(url).scheme!='https' or host not in ('files.pythonhosted.org','www.python.org','huggingface.co'):raise ValueError('Untrusted asset URL')
    if verified(target,record):progress(record['size'],record['size']);return target
    part=safe_path(target.with_name(target.name+'.download.part'));last=None
    for attempt in range(attempts):
        check_cancel(cancel);offset=part.stat().st_size if part.exists() else 0
        if offset==record['size'] and verified(part,record):os.replace(part,target);progress(offset,offset);return target
        if offset>=record['size']:part.unlink();offset=0
        if shutil.disk_usage(target.parent).free<record['size']-offset+32*1024**2:raise OSError(28,'Không đủ dung lượng để tải Kokoro')
        try:
            with client.stream('GET',url,headers={'Range':f'bytes={offset}-','Accept-Encoding':'identity'} if offset else {'Accept-Encoding':'identity'},follow_redirects=True) as response:
                response.raise_for_status()
                if response.url.scheme!='https':raise ValueError('Insecure asset redirect')
                if response.status_code==206:
                    match=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',response.headers.get('Content-Range',''))
                    if not match or int(match[1])!=offset or int(match[3])!=record['size'] or int(match[2])!=record['size']-1:raise ValueError('Invalid resume range')
                elif response.status_code==200:offset=0
                else:raise ValueError('Unsupported download response')
                with part.open('ab' if offset else 'wb') as stream:
                    count=offset
                    for block in response.iter_bytes(262144):
                        check_cancel(cancel);count+=len(block)
                        if count>record['size']:raise ValueError('Asset exceeds pinned size')
                        stream.write(block);progress(count,record['size'])
                    stream.flush();os.fsync(stream.fileno())
            if not verified(part,record):
                part.unlink();raise ValueError('Checksum tải xuống không khớp')
            os.replace(part,target);return target
        except (httpx.TransportError,httpx.HTTPStatusError) as exc:
            last=exc
            if isinstance(exc,httpx.HTTPStatusError) and exc.response.status_code not in (408,416,429,500,502,503,504):raise
            if isinstance(exc,httpx.HTTPStatusError) and exc.response.status_code==416 and part.exists():part.unlink()
            if attempt+1<attempts and cancel.wait(.2*(attempt+1)):check_cancel(cancel)
    raise last
