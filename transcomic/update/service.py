"""Bounded HTTPS checks/downloads. No subprocess, shell or installer launch."""
from __future__ import annotations
import hashlib
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
import httpx
from ..version import RELEASE_REPOSITORY, VERSION
from .metadata import (UpdateError, Candidate, SemVer, MANIFEST_NAME, MAX_DOWNLOAD, NOT_READY,
                       release_identity, find_asset, candidate, strict_json, valid_network_url,
                       verify_signature, PRODUCTION_KEYS, asset_url)

LATEST_URL=f'https://api.github.com/repos/{RELEASE_REPOSITORY}/releases/latest'
DAY=86400

def update_directory():
    root=os.environ.get('LOCALAPPDATA') or str(Path.home()/'.local'/'share')
    return Path(root)/'TransComic'/'Updates'

@dataclass(frozen=True)
class CheckResult:
    state: str
    message: str
    checked_at: float
    candidate: Candidate | None = None
    cached: bool = False

@dataclass(frozen=True)
class Progress:
    downloaded: int
    total: int
    bytes_per_second: float

class Cancelled(UpdateError): pass

class UpdateService:
    def __init__(self, directory=None, client=None, clock=time.time, keys=None, testing=False):
        from ..release_adapters import safe_path
        self.directory=safe_path(Path(directory) if directory is not None else update_directory())
        if self.directory.resolve().is_relative_to(Path(__file__).resolve().parents[2]):
            raise UpdateError('Updates must be outside source/program directory')
        if self.directory.is_symlink(): raise UpdateError('Update directory may not be a symlink')
        self.client=client
        self.clock=clock
        self.keys=PRODUCTION_KEYS if keys is None else keys
        self.testing=testing
        self._lock=threading.Lock()
        self._download_lock=threading.Lock()
        self.cache_path=self.directory/'check-cache.json'

    def validate_candidate(self,release,envelope):
        return candidate(release,envelope,self.keys,self.testing)

    def verify_trust(self,item):
        if item.signature_status!='VERIFIED_ED25519' or verify_signature(item.payload,item.signature,self.keys)!='VERIFIED_ED25519':raise UpdateError(NOT_READY)

    def check_extra_assets(self,client,release,item,manifest,cancel):pass

    def _cache(self):
        try:
            from ..release_adapters import safe_path
            safe_path(self.cache_path,self.directory)
            if self.cache_path.is_symlink() or self.cache_path.stat().st_size>1024*1024: return {}
            data=strict_json(self.cache_path.read_bytes())
            return data if isinstance(data,dict) else {}
        except (OSError,UpdateError): return {}

    def _save(self, cache):
        from ..release_adapters import safe_path
        safe_path(self.directory)
        self.directory.mkdir(parents=True,exist_ok=True)
        safe_path(self.cache_path,self.directory)
        temp=safe_path(self.directory/(uuid.uuid4().hex+'.tmp'),self.directory)
        try:
            with temp.open('x',encoding='utf-8') as f:json.dump(cache,f);f.flush();os.fsync(f.fileno())
            safe_path(self.cache_path,self.directory)
            os.replace(temp,self.cache_path)
        finally:safe_path(temp,self.directory).unlink(missing_ok=True)

    def _client(self):
        return self.client or httpx.Client(timeout=httpx.Timeout(20,connect=8),follow_redirects=False,trust_env=False,
            headers={'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','User-Agent':'TransComic-Updater/'+VERSION})

    def _stream(self, client, url, cancel, limit, initial=True):
        valid_network_url(url,initial=initial)
        for _ in range(6):
            if cancel.is_set(): raise Cancelled('Download cancelled')
            with client.stream('GET',url,follow_redirects=False) as response:
                if response.status_code in (301,302,303,307,308):
                    url=str(response.url.join(response.headers.get('location','')))
                    valid_network_url(url)
                    continue
                if response.status_code!=200: raise UpdateError(f'Download HTTP {response.status_code}')
                length=response.headers.get('content-length')
                if length and (not length.isdigit() or int(length)>limit): raise UpdateError('Download too large')
                count=0
                for chunk in response.iter_bytes(chunk_size=65536):
                    if cancel.is_set(): raise Cancelled('Download cancelled')
                    count+=len(chunk)
                    if count>limit: raise UpdateError('Download too large')
                    yield chunk
                return
        raise UpdateError('Too many redirects')

    def _result(self, cache, cached=False):
        stamp=float(cache.get('checked_at',0))
        if cache.get('state') in ('NO_RELEASE','RATE_LIMITED','ERROR'):
            return CheckResult(cache['state'],cache.get('message',''),stamp,cached=cached)
        try:
            item=self.validate_candidate(cache['release'],cache['envelope'])
            state='UPDATE_AVAILABLE' if SemVer.parse(item.version)>SemVer.parse(VERSION) else 'UP_TO_DATE'
            return CheckResult(state,'Có phiên bản mới' if state=='UPDATE_AVAILABLE' else 'Đang dùng phiên bản hiện tại hoặc mới hơn',stamp,item,cached)
        except (KeyError,ValueError,TypeError): return CheckResult('ERROR','Metadata cập nhật không hợp lệ',stamp,cached=cached)

    def due(self):
        cache=self._cache();now=self.clock()
        try: return now>=float(cache.get('retry_after',0)) and (not cache.get('checked_at') or now-float(cache['checked_at'])>=DAY)
        except (TypeError,ValueError): return True

    def check(self, manual=False, cancel=None):
        cancel=cancel or threading.Event()
        if not self._lock.acquire(blocking=False): return CheckResult('CHECKING','Đang kiểm tra',self.clock())
        client=self._client()
        try:
            cache=self._cache();now=self.clock()
            try:
                if now<float(cache.get('retry_after',0)) or (not manual and not self.due()): return self._result(cache,True)
            except (ValueError,TypeError): cache={}
            headers={'If-None-Match':cache['etag']} if isinstance(cache.get('etag'),str) and '\n' not in cache['etag'] and '\r' not in cache['etag'] else {}
            if cancel.is_set(): raise Cancelled('Check cancelled')
            with client.stream('GET',LATEST_URL,headers=headers,follow_redirects=False) as response:
                status=response.status_code
                if status==304:
                    if 'release' not in cache or 'envelope' not in cache: raise UpdateError('304 without valid cache')
                    cache['checked_at']=now
                    result=self._result(cache,True)
                    if result.state=='ERROR': raise UpdateError('Invalid cached metadata')
                    self._save(cache);return result
                if status==404:
                    cache={'state':'NO_RELEASE','message':'Chưa có bản cập nhật được phát hành','checked_at':now}
                elif status in (403,429):
                    retry=response.headers.get('retry-after','86400')
                    delay=max(DAY,min(7*DAY,int(retry))) if retry.isdigit() else DAY
                    cache={'state':'RATE_LIMITED','message':'GitHub giới hạn lượt kiểm tra; hãy thử lại sau','checked_at':now,'retry_after':now+delay}
                elif status!=200: raise UpdateError(f'Update HTTP {status}')
                else:
                    raw=bytearray()
                    for chunk in response.iter_bytes(65536):
                        if cancel.is_set(): raise Cancelled('Check cancelled')
                        raw.extend(chunk)
                        if len(raw)>1024*1024: raise UpdateError('Release metadata too large')
                    release=strict_json(raw);_,tag=release_identity(release)
                    asset=find_asset(release,tag,MANIFEST_NAME)
                    if asset['size']>128*1024: raise UpdateError('Manifest too large')
                    raw=b''.join(self._stream(client,asset['browser_download_url'],cancel,128*1024))
                    if len(raw)!=asset['size']: raise UpdateError('Manifest size mismatch')
                    envelope=strict_json(raw);item=self.validate_candidate(release,envelope)
                    self.check_extra_assets(client,release,item,raw,cancel)
                    cache={'state':'VALID','checked_at':now,'etag':response.headers.get('etag',''),'release':release,'envelope':envelope}
            self._save(cache);return self._result(cache)
        except Cancelled:
            return CheckResult('CANCELLED','Đã hủy kiểm tra',self.clock())
        except Exception:
            # Never expose request URLs, proxy passwords, response bodies or tokens.
            cache={'state':'ERROR','checked_at':self.clock(),'message':'Không thể kiểm tra cập nhật: mạng hoặc metadata không hợp lệ'}
            try: self._save(cache)
            except OSError: pass
            return self._result(cache)
        finally:
            if self.client is None: client.close()
            self._lock.release()

    def verify_file(self,path,item):
        from ..release_adapters import safe_path
        path=safe_path(path,self.directory)
        if path.is_symlink() or not path.is_file() or path.stat().st_size!=item.size: raise UpdateError('Installer size mismatch')
        with path.open('rb') as f: digest=hashlib.file_digest(f,'sha256').hexdigest()
        if digest!=item.sha256: raise UpdateError('Installer checksum mismatch')
        p=item.payload
        if (p.get('installer_filename'),p.get('installer_size'),p.get('sha256'),p.get('release_tag'))!=(item.filename,item.size,item.sha256,item.tag):
            raise UpdateError('Download metadata changed')
        self.verify_trust(item)

    def download(self,item,progress=lambda p:None,cancel=None):
        from ..release_adapters import safe_path
        if not self._download_lock.acquire(blocking=False): raise UpdateError('Download already running')
        cancel=cancel or threading.Event();part=None;client=self._client()
        try:
            version=SemVer.parse(item.version)
            if version.pre or version.build or item.tag!='v'+str(version):raise UpdateError('Invalid stable download version')
            if (item.payload.get('version'),item.payload.get('installer_filename'),item.payload.get('installer_size'),item.payload.get('sha256'),item.payload.get('release_tag'))!=(item.version,item.filename,item.size,item.sha256,item.tag):
                raise UpdateError('Download metadata changed')
            expected=f'TransComic-Setup-{item.version}-windows-x64.'+('testdata' if self.testing else 'exe')
            if item.filename!=expected or item.download_url!=asset_url(item.tag,item.filename): raise UpdateError('Invalid download identity')
            self.verify_trust(item)
            if not 0<item.size<=MAX_DOWNLOAD: raise UpdateError('Download too large')
            safe_path(self.directory);self.directory.mkdir(parents=True,exist_ok=True)
            target=safe_path(self.directory/item.filename,self.directory)
            if target.exists():
                self.verify_file(target,item);return target
            part=safe_path(self.directory/(uuid.uuid4().hex+'.part'),self.directory)
            started=time.monotonic();count=0
            with part.open('xb') as file:
                for chunk in self._stream(client,item.download_url,cancel,item.size):
                    file.write(chunk);count+=len(chunk)
                    progress(Progress(count,item.size,count/max(.001,time.monotonic()-started)))
                file.flush();os.fsync(file.fileno())
            if cancel.is_set(): raise Cancelled('Download cancelled')
            self.verify_file(part,item)
            if cancel.is_set():raise Cancelled('Download cancelled')
            # Rename without replacing an already-existing installer on Windows.
            if target.exists(): raise UpdateError('Download destination already exists')
            safe_path(target,self.directory);safe_path(part,self.directory)
            part.rename(target);return target
        except httpx.HTTPError as exc: raise UpdateError('Download network failure') from exc
        finally:
            if part is not None:safe_path(part,self.directory).unlink(missing_ok=True)
            if self.client is None: client.close()
            self._download_lock.release()
