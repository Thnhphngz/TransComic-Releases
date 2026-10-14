"""Internal build identity and explicit public disclosure policy."""
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib
import json
import re
from .version import RELEASE_REPOSITORY
from .update.metadata import UpdateError


@dataclass(frozen=True)
class SourceIdentity:
    root: str
    commit: str | None
    branch: str | None
    dirty: bool
    untracked_build_files: tuple = ()
    repository: str | None = None
    private: bool | None = None
    verified: bool = False

    def require_clean(self):
        if not self.verified or not re.fullmatch('[0-9a-f]{40}', self.commit or ''):
            raise UpdateError('SOURCE_PROVENANCE_NOT_READY')
        if self.dirty or self.untracked_build_files:
            raise UpdateError('SOURCE_DIRTY_OR_UNTRACKED_BUILD_INPUT')
        if self.repository is not None and not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',self.repository):
            raise UpdateError('SOURCE_REPOSITORY_IDENTITY_MUST_NOT_CONTAIN_URL_OR_CREDENTIALS')
        if self.repository == RELEASE_REPOSITORY:
            raise UpdateError('SOURCE_AND_DISTRIBUTION_IDENTITIES_CONFLICT')


def build_identity(source, version, versions, artifact_sha256):
    source.require_clean()
    if not re.fullmatch('[0-9a-f]{64}', artifact_sha256):
        raise UpdateError('ARTIFACT_HASH_REQUIRED')
    stamp=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    internal={'source_commit':source.commit,'source_tree_state':'clean',
              'source_repository':source.repository,'source_private':source.private,
              'build_timestamp':stamp,'version':version,'platform':'windows','architecture':'x64',
              'toolchain_versions':versions,'artifact_sha256':artifact_sha256}
    internal['build_id']=hashlib.sha256(json.dumps(internal,sort_keys=True).encode()).hexdigest()
    return internal


def public_provenance(internal, approved_source_fields=frozenset()):
    # No source URL/name/commit/root by default, even if the repo later becomes public.
    permitted={'source_commit','source_repository','source_tree_state'}
    if not set(approved_source_fields)<=permitted:
        raise UpdateError('Unapproved public provenance field')
    fields={'build_id','build_timestamp','version','platform','architecture','toolchain_versions','artifact_sha256'}|set(approved_source_fields)
    result={k:internal[k] for k in fields if k in internal}
    validate_public_provenance(result,approved_source_fields)
    return result


def validate_public_provenance(value,approved_source_fields=frozenset()):
    allowed={'build_id','build_timestamp','version','platform','architecture','toolchain_versions','artifact_sha256'}|set(approved_source_fields)
    if not isinstance(value,dict) or not set(value)<=allowed:raise UpdateError('PUBLIC_PROVENANCE_NOT_APPROVED')
    if 'build_id' not in value or not re.fullmatch('[0-9a-f]{64}',value['build_id']):raise UpdateError('PUBLIC_BUILD_ID_REQUIRED')
    for key,item in value.items():
        if key=='toolchain_versions':
            if not isinstance(item,dict) or any(not re.fullmatch(r'[A-Za-z0-9_-]{1,40}',k) or not isinstance(v,str) or not re.fullmatch(r'[0-9]+(?:\.[0-9A-Za-z]+){0,5}',v) for k,v in item.items()):raise UpdateError('UNSAFE_TOOLCHAIN_PROVENANCE')
        elif not isinstance(item,str) or len(item)>160 or any(c in item for c in ('@','\\','\n','\r')) or re.search(r'gh[oopsu]_|github_pat_|AIza|sk-',item):raise UpdateError('UNSAFE_PUBLIC_PROVENANCE')
    return True
