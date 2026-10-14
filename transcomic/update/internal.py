"""Explicit Internal policy. Hashes check consistency, not publisher identity."""
from dataclasses import replace
import hashlib
from .metadata import (candidate as signed_candidate,UpdateError,canonical,release_url,
                       APP_ID,MAX_DOWNLOAD,find_asset)

INTERNAL_VERIFIED='VERIFIED_INTERNAL_HTTPS_SHA256'


def candidate(release,envelope,testing=False):
    if not isinstance(envelope,dict) or set(envelope)!={'payload'}:raise UpdateError('Internal manifest required; signed policy cannot be downgraded')
    p=envelope['payload']
    if not isinstance(p,dict) or p.get('distribution_policy')!='internal' or p.get('channel')!='internal' or p.get('metadata_format')!=2:raise UpdateError('Internal policy mismatch')
    # Reuse existing immutable release/platform/name/size/hash/time validation.
    # This never relaxes the signed verifier: only an explicitly constructed Internal client uses this path.
    validated=signed_candidate(release,{'payload':dict(p,channel='stable',signed_at=p.get('generated_at')),'signature':{}},keys={},testing=testing)
    find_asset(release,validated.tag,'SHA256SUMS.txt')
    return replace(validated,signature_status=INTERNAL_VERIFIED,payload=dict(p),signature={})


def manifest(version,filename,size,sha256,created_at,provenance=None):
    from ..release import version_outputs
    expected=version_outputs(version)['installer']
    if filename!=expected or not 0<size<=MAX_DOWNLOAD:raise UpdateError('Internal release identity invalid')
    p={'app_id':APP_ID,'version':version,'release_tag':'v'+version,'release_url':release_url('v'+version),
       'distribution_policy':'internal','channel':'internal','os':'windows','architecture':'x64',
       'installer_filename':filename,'installer_size':size,'sha256':sha256,'metadata_format':2,
       'generated_at':created_at,'minimum_windows':'10','minimum_updater_version':'0.1.0'}
    if provenance is not None:p['provenance']=provenance
    return {'payload':p}


def verify_checksums(raw,item,manifest_bytes):
    try:
        lines=raw.decode('ascii').splitlines()
        expected={item.filename:item.sha256,'transcomic-update.json':hashlib.sha256(manifest_bytes).hexdigest()}
        pairs=[line.split('  ') for line in lines]
        if len(pairs)!=2 or any(len(pair)!=2 for pair in pairs) or dict((name,sha) for sha,name in pairs)!=expected:raise ValueError()
    except (ValueError,UnicodeError):raise UpdateError('Internal checksum inventory mismatch') from None


from .service import UpdateService


class InternalUpdateService(UpdateService):
    def __init__(self,*args,**kwargs):
        if kwargs.get('keys') is not None:raise UpdateError('Internal client does not accept signing trust overrides')
        super().__init__(*args,**kwargs)
        self.cache_path=self.directory/'internal-check-cache.json'
        self.verified_release=None

    def validate_candidate(self,release,envelope):
        item=candidate(release,envelope,self.testing)
        self.verified_release=release
        self.verified_payload=canonical(item.payload)
        return item

    def check_extra_assets(self,client,release,item,manifest,cancel):
        asset=find_asset(release,item.tag,'SHA256SUMS.txt')
        if asset['size']>4096:raise UpdateError('Checksum size limit')
        raw=b''.join(self._stream(client,asset['browser_download_url'],cancel,4096))
        if len(raw)!=asset['size']:raise UpdateError('Checksum size mismatch')
        verify_checksums(raw,item,manifest)

    def verify_trust(self,item):
        if self.verified_release is None or canonical(item.payload)!=self.verified_payload:raise UpdateError('Internal release verification required')
        expected=candidate(self.verified_release,{'payload':item.payload},self.testing)
        if expected!=item or item.signature_status!=INTERNAL_VERIFIED:raise UpdateError('Internal download identity changed')

    def confirm_install(self,item,cancel=None):
        """Fresh HTTPS tag/manifest/checksums, never authorize from disk cache.

        The helper repeats this before READY. Rate limits/offline fail closed;
        they do not fall back to locally editable unsigned cached metadata.
        """
        import threading
        from ..version import RELEASE_REPOSITORY
        from .metadata import strict_json,MANIFEST_NAME,SemVer
        from .service import Cancelled
        cancel=cancel or threading.Event()
        if item.tag!='v'+str(SemVer.parse(item.version)):raise UpdateError('INSTALL_RELEASE_IDENTITY_INVALID')
        client=self._client()
        try:
            url='https://api.github.com/repos/'+RELEASE_REPOSITORY+'/releases/tags/'+item.tag
            with client.stream('GET',url,follow_redirects=False) as response:
                if response.status_code!=200:raise UpdateError('INSTALL_RELEASE_RECHECK_FAILED')
                raw=bytearray()
                for chunk in response.iter_bytes(65536):
                    if cancel.is_set():raise Cancelled('Install verification cancelled')
                    raw.extend(chunk)
                    if len(raw)>1024*1024:raise UpdateError('INSTALL_RELEASE_SIZE_LIMIT')
            release=strict_json(raw)
            asset=find_asset(release,item.tag,MANIFEST_NAME)
            if asset['size']>128*1024:raise UpdateError('INSTALL_MANIFEST_SIZE_LIMIT')
            raw=b''.join(self._stream(client,asset['browser_download_url'],cancel,128*1024))
            if len(raw)!=asset['size']:raise UpdateError('INSTALL_MANIFEST_SIZE_MISMATCH')
            envelope=strict_json(raw);verified=candidate(release,envelope,self.testing)
            self.check_extra_assets(client,release,verified,raw,cancel)
            if verified!=item:raise UpdateError('INSTALL_RELEASE_CHANGED')
            return verified
        finally:
            if self.client is None:client.close()
