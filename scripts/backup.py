"""Back up a running SQLite database and immutable collection files.

The sqlite3 backup API captures committed WAL content. Mail outboxes, sessions
in logs, environment files and merchant credentials are not added separately.
The database itself contains customer/purchase data: keep the archive private.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import tarfile
import tempfile


def create_backup(database: Path, content: Path, output: Path, support_qr: Path | None = None) -> Path:
    database = database.resolve(strict=True)
    content = content.resolve(strict=True)
    output = output.resolve()
    if not database.is_file() or not content.is_dir():
        raise ValueError("Expected an existing SQLite file and content directory.")
    if output.exists():
        raise FileExistsError(f"Backup already exists: {output}")
    if output.is_relative_to(content):
        raise ValueError("Write the archive outside the content directory.")
    for path in content.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Content must not contain symlinks: {path}")
    if support_qr is not None:
        support_qr = support_qr.resolve(strict=True)
        if not support_qr.is_file():
            raise ValueError("Support QR must be a file.")

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="paiddrive-backup-") as work:
        snapshot = Path(work) / "paiddrive.sqlite3"
        source = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=30)
        target = sqlite3.connect(snapshot)
        try:
            source.backup(target, pages=1024)
            check = target.execute("PRAGMA integrity_check").fetchone()
            if check != ("ok",):
                raise RuntimeError("SQLite integrity check failed; no backup written.")
        finally:
            target.close()
            source.close()

        metadata = Path(work) / "backup.json"
        metadata.write_text(json.dumps({
            "format": "paiddrive-backup-v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "database": "data/paiddrive.sqlite3",
            "content": "content/",
            "note": "Keep the application version and secret configuration separately."
        }, indent=2) + "\n", encoding="utf-8")
        handle, temporary_name = tempfile.mkstemp(prefix=".paiddrive-", suffix=".partial", dir=output.parent)
        os.close(handle)
        temporary = Path(temporary_name)
        try:
            with tarfile.open(temporary, "w:gz", dereference=False) as archive:
                archive.add(snapshot, arcname="data/paiddrive.sqlite3")
                archive.add(content, arcname="content")
                archive.add(metadata, arcname="backup.json")
                if support_qr is not None and not support_qr.is_relative_to(content):
                    archive.add(support_qr, arcname="support/" + support_qr.name)
            os.chmod(temporary, 0o600)
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path(os.getenv("DATABASE_PATH", "data/paiddrive.sqlite3")))
    parser.add_argument("--content", type=Path, default=Path(os.getenv("CONTENT_ROOT", "content")))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--support-qr", type=Path)
    args = parser.parse_args()
    try:
        result = create_backup(args.database, args.content, args.output, args.support_qr)
    except (OSError, ValueError, sqlite3.Error, RuntimeError) as error:
        parser.exit(1, f"Backup failed: {error}\n")
    print(f"Backup created: {result}")


if __name__ == "__main__":
    main()
