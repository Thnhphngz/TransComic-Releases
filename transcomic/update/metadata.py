"""Strict SemVer, release identity and signed manifest validation."""
from __future__ import annotations
import base64
import json
import re
from dataclasses import dataclass
from functools import total_ordering
from urllib.parse import urlsplit, quote
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from ..version import APP_ID, CHANNEL, PLATFORM, ARCH, RELEASE_REPOSITORY, UPDATER_VERSION

MAX_DOWNLOAD = 512 * 1024 * 1024
MANIFEST_NAME = 'transcomic-update.json'
NOT_READY = 'NOT_READY_FOR_PRODUCTION_INSTALL'
# Intentionally empty: only a reviewed Stage B source change may add production keys.
PRODUCTION_KEYS: dict[str, bytes] = {}
PRODUCTION_KEY_STATUS: dict[str, str] = {}  # reviewed active / retiring / revoked records only

class UpdateError(ValueError): pass

@total_ordering
@dataclass(frozen=True, eq=False)
class SemVer:
    major: int
    minor: int
    patch: int
    pre: tuple[str, ...] = ()
    build: str = ''

    @classmethod
    def parse(cls, value: str, tag=False):
        if not isinstance(value,str): raise UpdateError('Invalid version')
        if tag and value.startswith('v'): value=value[1:]
        m=re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?',value)
        if not m: raise UpdateError('Invalid SemVer')
        pre=tuple(m[4].split('.')) if m[4] else ()
        if any(x.isdigit() and len(x)>1 and x.startswith('0') for x in pre): raise UpdateError('Invalid prerelease')
        return cls(int(m[1]),int(m[2]),int(m[3]),pre,m[5] or '')

    def key(self):
        return (self.major,self.minor,self.patch,not self.pre,tuple((0,int(x)) if x.isdigit() else (1,x) for x in self.pre))
    def __lt__(self,other): return self.key()<other.key() if isinstance(other,SemVer) else NotImplemented
    def __eq__(self,other): return isinstance(other,SemVer) and self.key()==other.key()
    def __hash__(self): return hash(self.key())
    def __str__(self):
        return f'{self.major}.{self.minor}.{self.patch}'+('-'+'.'.join(self.pre) if self.pre else '')+('+'+self.build if self.build else '')

def bumped(current, choice):
    v=SemVer.parse(current)
    result={'patch':f'{v.major}.{v.minor}.{v.patch+1}', 'minor':f'{v.major}.{v.minor+1}.0', 'major':f'{v.major+1}.0.0'}.get(choice,choice)
    new=SemVer.parse(result)
    if new<=v or new.pre: raise UpdateError('New stable version must increase')
    return str(new)

def release_url(tag): return f'https://github.com/{RELEASE_REPOSITORY}/releases/tag/{quote(tag,safe="")}'
def asset_url(tag,name): return f'https://github.com/{RELEASE_REPOSITORY}/releases/download/{quote(tag,safe="")}/{quote(name,safe="")}'

def valid_network_url(url, initial=False):
    p=urlsplit(str(url))
    if p.scheme!='https' or p.username or p.password or p.port not in (None,443) or p.fragment:
        raise UpdateError('Untrusted HTTPS source')
    if p.hostname=='github.com':
        if not p.path.startswith(f'/{RELEASE_REPOSITORY}/releases/download/') or p.query:
            raise UpdateError('Untrusted repository')
    elif initial or p.hostname!='release-assets.githubusercontent.com':
        raise UpdateError('Untrusted redirect')

def strict_json(raw):
    def unique(pairs):
        obj={}
        for key,value in pairs:
            if key in obj: raise UpdateError('Duplicate metadata key')
            obj[key]=value
        return obj
    try: return json.loads(raw,object_pairs_hook=unique)
    except (ValueError,UnicodeError) as exc: raise UpdateError('Invalid JSON metadata') from exc

def canonical(payload): return json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')

@dataclass(frozen=True)
class Candidate:
    version: str
    tag: str
    url: str
    changelog: str
    filename: str
    size: int
    sha256: str
    download_url: str
    signature_status: str
    payload: dict
    signature: dict

def release_identity(release):
    if not isinstance(release,dict) or release.get('draft') is not False or release.get('prerelease') is not False:
        raise UpdateError('Not a published Stable release')
    tag=release.get('tag_name');v=SemVer.parse(tag,tag=True)
    if v.pre or v.build or tag!='v'+str(v): raise UpdateError('Stable tag must be vMAJOR.MINOR.PATCH')
    if release.get('html_url')!=release_url(tag) or not release.get('published_at'):
        raise UpdateError('Release identity mismatch')
    assets=release.get('assets')
    if not isinstance(assets,list): raise UpdateError('Missing assets')
    names=[a.get('name') for a in assets if isinstance(a,dict)]
    if len(names)!=len(assets) or len(set(names))!=len(names): raise UpdateError('Duplicate or invalid assets')
    return str(v),tag

def find_asset(release,tag,name):
    matches=[a for a in release['assets'] if a.get('name')==name]
    if len(matches)!=1: raise UpdateError('Missing mandatory asset')
    asset=matches[0]
    if asset.get('state')!='uploaded' or asset.get('browser_download_url')!=asset_url(tag,name): raise UpdateError('Asset identity mismatch')
    if type(asset.get('size')) is not int or not 0<asset['size']<=MAX_DOWNLOAD: raise UpdateError('Invalid asset size')
    return asset

def verify_signature(payload,signature,keys):
    if keys is PRODUCTION_KEYS and isinstance(signature,dict):
        key_id=signature.get('key_id','')
        status=PRODUCTION_KEY_STATUS.get(key_id)
        if status=='revoked':raise UpdateError('Production signing key revoked')
        if not isinstance(key_id,str) or key_id.startswith('test-') or status not in ('active','retiring'):return NOT_READY
    if not isinstance(signature,dict) or signature.get('algorithm')!='ed25519' or signature.get('key_id') not in keys:
        return NOT_READY
    try:
        sig=base64.b64decode(signature['value'],validate=True)
        Ed25519PublicKey.from_public_bytes(keys[signature['key_id']]).verify(sig,canonical(payload))
    except Exception as exc: raise UpdateError('Manifest signature invalid') from exc
    return 'VERIFIED_ED25519'

def candidate(release,envelope,keys=None,testing=False):
    version,tag=release_identity(release)
    if not isinstance(envelope,dict) or set(envelope)!={'payload','signature'}: raise UpdateError('Invalid manifest envelope')
    p=envelope['payload'];s=envelope['signature']
    if not isinstance(p,dict): raise UpdateError('Invalid manifest payload')
    expected={'app_id':APP_ID,'version':version,'channel':CHANNEL,'os':PLATFORM,'architecture':ARCH,'release_tag':tag,'release_url':release_url(tag)}
    if any(p.get(k)!=v for k,v in expected.items()): raise UpdateError('Manifest/release/platform mismatch')
    if p.get('minimum_windows')!='10':
        raise UpdateError('Invalid publish metadata')
    if p.get('metadata_format') == 2:
        # GitHub supplies published_at only at publication. Signer time is not server time.
        # Published identity, stable tag, payload signature and asset hash remain mandatory.
        from datetime import datetime
        signed_at=p.get('signed_at')
        try:
            if not isinstance(signed_at,str) or not signed_at.endswith('Z'):raise ValueError()
            datetime.fromisoformat(signed_at[:-1]+'+00:00')
        except ValueError:raise UpdateError('Invalid signing timestamp') from None
    elif p.get('metadata_format') not in (None,1) or not p.get('published_at') or p['published_at']!=release['published_at']:
        raise UpdateError('Invalid publish metadata')
    if SemVer.parse(p.get('minimum_updater_version',''))>SemVer.parse(UPDATER_VERSION): raise UpdateError('Updater upgrade required')
    suffix='testdata' if testing else 'exe'
    filename=f'TransComic-Setup-{version}-windows-x64.{suffix}'
    if p.get('installer_filename')!=filename: raise UpdateError('Invalid installer filename')
    size=p.get('installer_size');sha=p.get('sha256')
    if type(size) is not int or not 0<size<=MAX_DOWNLOAD or not isinstance(sha,str) or not re.fullmatch('[0-9a-f]{64}',sha): raise UpdateError('Missing size/hash')
    asset=find_asset(release,tag,filename)
    if asset['size']!=size: raise UpdateError('Release size mismatch')
    return Candidate(version,tag,release_url(tag),str(release.get('body') or '')[:32000],filename,size,sha,asset['browser_download_url'],verify_signature(p,s,PRODUCTION_KEYS if keys is None else keys),p,s)
