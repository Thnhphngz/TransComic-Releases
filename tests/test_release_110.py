from scripts.release_source import allowed
from transcomic.release import version_outputs
from transcomic.update.internal import manifest, candidate, verify_checksums
from transcomic.update.metadata import canonical, asset_url, release_url, SemVer, UpdateError
import hashlib
import pytest


def test_tts_release_inputs_are_exactly_classified():
    for name in ('requirements-tts-cuda.lock', 'transcomic/tts/setup-catalog.json', 'transcomic/tts/calibration.json'):
        assert allowed(name)
    for name in ('transcomic/tts/user.json', 'transcomic/tts/gpu-pack.json', 'secrets.json', 'runtime/audio.wav'):
        assert not allowed(name)


def test_110_metadata_keeps_baseline_protocol_with_extra_source_assets():
    version='1.1.0'; tag='v'+version; filename=version_outputs(version)['installer']
    assert filename=='TransComic-Setup-1.1.0-windows-x64.exe'
    assert SemVer.parse(version)>SemVer.parse('1.0.4')
    installer=b'synthetic installer fixture'
    digest=hashlib.sha256(installer).hexdigest()
    envelope=manifest(version,filename,len(installer),digest,'2026-10-17T00:00:00Z')
    raw=canonical(envelope)
    sums=(digest+'  '+filename+'\n'+hashlib.sha256(raw).hexdigest()+'  transcomic-update.json\n').encode('ascii')
    assets=[(filename,installer),('transcomic-update.json',raw),('SHA256SUMS.txt',sums),('TransComic-1.1.0-ThirdParty-Sources.zip',b'source')]
    release=dict(tag_name=tag,draft=False,prerelease=False,html_url=release_url(tag),published_at='2026-10-17T00:00:00Z',assets=[dict(name=n,size=len(data),state='uploaded',browser_download_url=asset_url(tag,n)) for n,data in assets])
    item=candidate(release,envelope)
    verify_checksums(sums,item,raw)
    with pytest.raises(UpdateError):
        verify_checksums(sums+b'0'*64+b'  extra.zip\n',item,raw)
