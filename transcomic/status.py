"""Usable translation is independent from the latest request's status."""
from .documents import translatable


def usable(row):
    if not (row.get("translation") or '').strip() or not translatable(row["source"]):
        return False
    if "translation_source_revision" in row:
        return row["translation_source_revision"] == row["source_revision"]
    return row["state"] == "done"


def matches_filter(row, scope):
    if scope is None:
        return True
    if isinstance(scope, set):
        return row["state"] in scope
    if scope == "untranslated":
        return translatable(row["source"]) and not usable(row)
    if scope == "translated":
        return usable(row)
    if scope == "api_errors":
        return row["state"] in ("error", "unknown")
    if scope == "wrong_target_language":
        return row["state"] == scope
    if scope == "unknown":
        return row["state"] == "unknown"
    if scope == "edited":
        return row.get("attempt_kind") == "manual"
    if scope == "stale":
        return row["state"] == "stale" or bool(row.get("translation") and not usable(row))
    if scope == "review":
        from .quality import warnings
        return bool(warnings(row))
    return False
