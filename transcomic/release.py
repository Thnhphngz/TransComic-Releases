"""Recoverable release orchestration. All effects in B1 are concrete fakes.

No production activation flag, subprocess or network client exists here.
Ledger is a mock journal in a caller-supplied test directory, never app data.
"""
from __future__ import annotations
import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass, asdict
from pathlib import Path
from uuid import uuid4
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from .version import VERSION, APP_ID, RELEASE_REPOSITORY
from .update.metadata import bumped, SemVer, UpdateError, canonical, candidate, MANIFEST_NAME, release_url, asset_url
from .update.signing import sign_payload, TrustPolicy

PHASES = ('preflight', 'test', 'build', 'package', 'sign', 'verify', 'draft', 'upload', 'remote_verify', 'publish', 'published_verify', 'ledger')


@dataclass(frozen=True)
class Provenance:
    source_repository: str
    source_commit: str
    distribution_commit: str

    def validate(self):
        # Exact IDs, no credentials/URLs/branch aliases; distribution SHA never substitutes source SHA.
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', self.source_repository):
            raise UpdateError('Exact source repository required')
        if self.source_repository == RELEASE_REPOSITORY:
            raise UpdateError('Distribution repository cannot stand in for source repository')
        if any(not re.fullmatch('[0-9a-f]{40}', sha) for sha in (self.source_commit, self.distribution_commit)):
            raise UpdateError('Verified exact source/distribution commit required')


def version_outputs(version):
    parsed = SemVer.parse(version)
    if parsed.pre or parsed.build:
        raise UpdateError('Canonical stable version required')
    return {'version': version, 'tag': 'v'+version, 'name': 'TransComic '+version,
            'installer': f'TransComic-Setup-{version}-windows-x64.exe',
            'iss': f'#define MyAppVersion "{version}"\n',
            'exe_tuple': (parsed.major, parsed.minor, parsed.patch, 0)}


class MockLedger:
    def __init__(self, path):
        self.path = Path(path)
        self.fail_final = False

    def load(self):
        if not self.path.exists():
            return None
        try:
            value = json.loads(self.path.read_text(encoding='utf-8'))
            if value['mock'] is not True or value['repository'] != RELEASE_REPOSITORY:
                raise ValueError()
            version_outputs(value['version'])
            Provenance(**value['provenance']).validate()
            return value
        except (ValueError, KeyError, TypeError):
            raise UpdateError('Release journal invalid; reconciliation required') from None

    def save(self, record):
        if self.fail_final and record['state'] == 'RELEASED':
            raise OSError('Mock local final save failure')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        part = self.path.with_name(self.path.name+'.'+uuid4().hex+'.part')
        try:
            with part.open('x', encoding='utf-8') as stream:
                json.dump(record, stream, sort_keys=True)
                stream.flush()
                __import__('os').fsync(stream.fileno())
            part.replace(self.path)
        finally:
            part.unlink(missing_ok=True)


class FakePublisher:
    """In-memory remote including independent downloaded asset verification."""
    repository = RELEASE_REPOSITORY

    def __init__(self):
        self.releases = {}
        self.tags = {}
        self.calls = []
        self.fail = None
        self.publish_unknown = False

    def read(self, tag):
        self.calls.append(('read', tag))
        if self.fail == 'read':
            raise UpdateError('Mock remote read unavailable')
        return deepcopy(self.releases.get(tag))

    def draft(self, record):
        tag = 'v'+record['version']
        self.calls.append(('draft', tag))
        if self.fail == 'draft':
            raise UpdateError('Mock draft failure')
        if tag in self.releases:
            raise UpdateError('No release overwrite')
        sha = record['provenance']['distribution_commit']
        if tag in self.tags and self.tags[tag] != sha:
            raise UpdateError('Tag belongs to a different distribution commit')
        self.tags[tag] = sha
        self.releases[tag] = {'draft': True, 'provenance': record['provenance'], 'assets': {},
                              'version': record['version'], 'distribution_commit': sha}

    def upload(self, tag, assets):
        release = self.releases[tag]
        if not release['draft']:
            raise UpdateError('Published release immutable')
        for index, (name, data) in enumerate(assets.items()):
            self.calls.append(('upload', name))
            if self.fail == 'upload' and index == 1:
                raise UpdateError('Mock interrupted upload')
            if name in release['assets'] and release['assets'][name] != data:
                raise UpdateError('Remote asset conflict; never overwrite')
            release['assets'][name] = data

    def verify(self, tag, record, published=False):
        remote = self.read(tag)
        if not remote or remote['draft'] == published or remote['provenance'] != record['provenance']:
            raise UpdateError('Remote release/provenance/state mismatch')
        if self.tags.get(tag) != record['provenance']['distribution_commit'] or remote['distribution_commit'] != self.tags[tag]:
            raise UpdateError('Remote tag commit mismatch')
        if set(remote['assets']) != set(record['assets']):
            raise UpdateError('Remote asset names mismatch')
        for name, data in remote['assets'].items():
            if {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()} != record['assets'][name]:
                raise UpdateError('Remote downloaded asset mismatch')
        if self.fail == 'remote_verify':
            raise UpdateError('Mock remote verification failure')
        return remote

    def publish(self, tag):
        self.calls.append(('publish', tag))
        if self.fail == 'publish':
            raise UpdateError('Mock publish failure')
        self.releases[tag]['draft'] = False
        if self.publish_unknown:
            raise UpdateError('Mock publish outcome unknown; read before retry')


class FakePipeline:
    def __init__(self):
        self.key = Ed25519PrivateKey.generate()
        self.keys = {'ephemeral-test': self.key.public_key().public_bytes_raw()}
        self.fail = None
        self.calls = []
        self.corrupt = None

    def step(self, phase):
        self.calls.append(phase)
        if self.fail == phase:
            raise UpdateError('Mock '+phase+' failure')

    def artifacts(self, record):
        for phase in ('preflight', 'test', 'build', 'package', 'sign'):
            self.step(phase)
        version = record['version']
        tag = 'v'+version
        filename = f'TransComic-Setup-{version}-windows-x64.testdata'
        data = canonical({'mock_package': True, 'version': version, 'source': record['provenance']})
        payload = {'app_id': APP_ID, 'version': version, 'release_tag': tag,
                   'release_url': release_url(tag), 'channel': 'stable', 'os': 'windows', 'architecture': 'x64',
                   'installer_filename': filename, 'installer_size': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                   'minimum_updater_version': VERSION, 'minimum_windows': '10',
                   'metadata_format': 2, 'signed_at': '2026-10-14T00:00:00Z', 'provenance': record['provenance']}
        envelope = sign_payload(payload, 'ephemeral-test', self.key)
        if self.corrupt == 'manifest_version': envelope['payload']['version'] = '9.0.0'
        if self.corrupt == 'signature': envelope['signature']['value'] = 'AAAA'
        if self.corrupt == 'provenance': envelope['payload']['provenance'] = {'source_commit': 'c'*40}
        if self.corrupt == 'data': data = b'x'*len(data)
        assets = {filename: data, MANIFEST_NAME: canonical(envelope)}
        assets['SHA256SUMS.txt'] = ''.join(hashlib.sha256(v).hexdigest()+'  '+k+'\n' for k, v in assets.items()).encode()
        self.step('verify')
        TrustPolicy(self.keys).verify(envelope)
        if hashlib.sha256(data).hexdigest() != envelope['payload']['sha256'] or envelope['payload']['provenance'] != record['provenance']:
            raise UpdateError('Build bytes or provenance mismatch')
        release = {'tag_name': tag, 'draft': False, 'prerelease': False, 'html_url': release_url(tag),
                   'published_at': '2026-10-14T00:00:03Z', 'assets': [
                       {'name': n, 'size': len(v), 'state': 'uploaded', 'browser_download_url': asset_url(tag, n)} for n, v in assets.items()]}
        candidate(release, envelope, keys=self.keys, testing=True)
        return assets


class ReleaseWorkflow:
    def __init__(self, ledger, publisher, pipeline):
        if type(ledger) is not MockLedger or type(publisher) is not FakePublisher or type(pipeline) is not FakePipeline:
            raise UpdateError('B1 release effects require concrete fake adapters')
        self.ledger, self.publisher, self.pipeline = ledger, publisher, pipeline

    def simulate(self, provenance, current=VERSION, choice='patch'):
        provenance.validate()
        record = self.ledger.load()
        if record:
            # Always readonly reconciliation before any retry, even after final local save failed.
            tag = 'v'+record['version']
            remote = self.publisher.read(tag)
            if remote and not remote['draft']:
                self.publisher.verify(tag, record, published=True)
                record['state'] = 'RELEASED'
                self.ledger.save(record)
                if asdict(provenance) == record['provenance']:
                    return record
                if current != record['version']:
                    raise UpdateError('Next release source version must equal confirmed published version')
                record = None  # confirmed previous publish; reserve next version from updated source
            elif record['provenance'] != asdict(provenance):
                raise UpdateError('Pending release source identity changed')
            if record and record['state'] == 'RELEASED':
                raise UpdateError('Published remote missing; reconciliation required')
        if record is None:
            version = bumped(current, choice)
            version_outputs(version)
            if any(SemVer.parse(t, tag=True) >= SemVer.parse(version) for t in self.publisher.releases):
                raise UpdateError('Duplicate or older remote version')
            record = {'mock': True, 'repository': RELEASE_REPOSITORY, 'version': version,
                      'provenance': asdict(provenance), 'state': 'PENDING', 'assets': {}}
            self.ledger.save(record)  # reserve version BEFORE any action; failed/unknown never double bumps
        assets = self.pipeline.artifacts(record)
        hashes = {n: {'size': len(v), 'sha256': hashlib.sha256(v).hexdigest()} for n, v in assets.items()}
        if record['assets'] and record['assets'] != hashes:
            raise UpdateError('Resume artifacts changed; explicit reconciliation required')
        record['assets'] = hashes
        self.ledger.save(record)
        tag = 'v'+record['version']
        remote = self.publisher.read(tag)
        if remote:
            if remote['provenance'] != record['provenance'] or not remote['draft']:
                raise UpdateError('Conflicting draft or published release')
        else:
            self.publisher.draft(record)
        self.publisher.upload(tag, assets)
        self.publisher.verify(tag, record)
        record['state'] = 'PUBLISH_PENDING'
        self.ledger.save(record)
        self.publisher.publish(tag)
        self.publisher.verify(tag, record, published=True)
        record['state'] = 'RELEASED'
        self.ledger.save(record)
        return record
