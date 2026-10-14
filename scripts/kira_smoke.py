"""One-request Kira smoke test. Run only after explicit batch authorization."""
from __future__ import annotations

import asyncio
import sqlite3
import uuid

from transcomic.app import data_path
from transcomic.providers import KiraProvider
from transcomic.security import unprotect_key


async def main():
    path = data_path()
    if not path.exists():
        raise SystemExit("Save a Kira API key in the application first.")
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        row = db.execute("SELECT encrypted FROM secrets WHERE key='kira'").fetchone()
    encrypted = row[0] if row else None
    if not encrypted:
        raise SystemExit("Save a Kira API key in the application first.")
    key = unprotect_key(encrypted)
    samples = ["Hello, friend.", "The moon is bright.", "Please wait here."]
    lines = [{"id": str(uuid.uuid4()), "source": text} for text in samples]
    # Exactly one request, at most three short lines, no retries, capped output.
    provider = KiraProvider(key, "kira-2.5-flash", max_tokens=256)
    result = await provider.translate(lines, "English", "Vietnamese")
    print("requests_sent=1, lines_sent=3, output_cap=256_tokens")
    print("result=unknown" if result.unknown else "result=error" if result.error else "result=success")
    print(f"valid_lines={len(result.values)}")
    if result.usage:
        print(f"usage={result.usage}")
    if result.error:
        print(f"error={result.error}")


if __name__ == "__main__":
    asyncio.run(main())
