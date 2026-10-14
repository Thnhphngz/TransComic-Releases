"""Active-version updater fixtures; historical release tests pass explicit baselines."""
from transcomic.version import VERSION as CURRENT
from transcomic.release_version import bumped
NEXT = bumped(CURRENT, 'minor')
