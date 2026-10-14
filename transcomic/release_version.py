"""TransComic release numbering; external updater SemVer remains unrestricted."""
from .update.metadata import SemVer, UpdateError


def validate_release_version(value):
    version = SemVer.parse(value)
    if version.pre or version.build or version.minor > 9 or version.patch > 9:
        raise UpdateError('TRANSCOMIC_VERSION_POLICY: stable MINOR/PATCH must be 0..9')
    return version


def bumped(current, choice='patch'):
    old = validate_release_version(current)
    if choice == 'patch':
        major, remainder = divmod(old.minor * 10 + old.patch + 1, 100)
        minor, patch = divmod(remainder, 10)
        result = f'{old.major + major}.{minor}.{patch}'
    elif choice == 'minor':
        carry, minor = divmod(old.minor + 1, 10)
        result = f'{old.major + carry}.{minor}.0'
    elif choice == 'major':
        result = f'{old.major + 1}.0.0'
    else:
        result = choice
    new = validate_release_version(result)
    if new <= old:
        raise UpdateError('New stable version must increase')
    return str(new)


def preview_version(current, choice='patch', record=None, remote=None, remote_known=True):
    """Pure proposal: never reserve or mutate a journal, never infer publish success."""
    validate_release_version(current)
    if not remote_known:
        raise UpdateError('RELEASE_STATE_UNCERTAIN: remote evidence unavailable')
    if record:
        validate_release_version(record['version'])
        state = record.get('state')
        if remote is not None:
            if (remote.get('tag') != 'v' + record['version'] or
                    remote.get('build_id') != record.get('build_id') or
                    remote.get('assets_verified') is not True):
                raise UpdateError('RELEASE_STATE_UNCERTAIN: journal/remote mismatch')
            if (remote.get('published') is True)==(remote.get('draft') is True):
                raise UpdateError('RELEASE_STATE_UNCERTAIN: conflicting remote flags')
            if remote.get('published') is True:
                return bumped(record['version'], choice)
            if remote.get('draft') is not True:
                raise UpdateError('RELEASE_STATE_UNCERTAIN: remote state invalid')
        elif state in ('PUBLISHED', 'UNKNOWN_REMOTE_OUTCOME', 'DRAFT_CREATED',
                       'ASSETS_UPLOADED', 'REMOTE_VERIFIED') or record.get('last_completed') in (
                       'PUBLISHED','DRAFT_CREATED','ASSETS_UPLOADED','REMOTE_VERIFIED'):
            raise UpdateError('RELEASE_STATE_UNCERTAIN: remote reconciliation required')
        if SemVer.parse(current) >= SemVer.parse(record['version']):
            raise UpdateError('RELEASE_STATE_UNCERTAIN: local version changed during reservation')
        return record['version']
    if remote is not None:
        # A release/tag alone is not independently verified journal evidence.
        raise UpdateError('RELEASE_STATE_UNCERTAIN: unjournaled remote release')
    return bumped(current, choice)
