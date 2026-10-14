"""Schema policy contract; does not migrate or restore a user database."""
from .metadata import UpdateError


def schema_compatible(database_version, minimum, maximum):
    if not minimum <= database_version <= maximum:
        raise UpdateError('Database schema incompatible; preserve data and stop')
    return True


def rollback_policy(migration_committed):
    return 'manual_recovery_from_verified_backup' if migration_committed else 'previous_binary_with_compatible_schema'
