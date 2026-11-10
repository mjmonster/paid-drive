import hashlib
import json
from pathlib import Path
import re

from .db import Database


SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")
IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"}


def file_digest(path: Path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def safe_path(root: Path, relative: str):
    root = root.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("Collection file must be inside CONTENT_ROOT")
    if path.suffix.lower() not in IMAGE_TYPES:
        raise ValueError("Unsupported collection image type")
    return path


class Catalog:
    def __init__(self, root: Path, db: Database):
        self.root = Path(root).resolve()
        self.db = db
        raw = json.loads((self.root / "collections.json").read_text("utf-8"))
        if not isinstance(raw, dict) or not isinstance(raw.get("collections"), list) or not raw["collections"]:
            raise ValueError("collections.json must contain a nonempty collections array")
        self.current = {}
        self.slugs = {}
        for entry in raw["collections"]:
            collection = dict(entry)
            for field in ("id", "slug", "version"):
                if not SAFE_ID.fullmatch(str(collection.get(field, ""))):
                    raise ValueError(f"Invalid collection {field}")
            if collection["id"] in self.current or collection["slug"] in self.slugs:
                raise ValueError("Collection IDs and slugs must be unique")
            price = collection.get("price_cents")
            if type(price) is not int or not 1 <= price <= 100_000_000:
                raise ValueError("price_cents must be a positive integer")
            if collection.get("currency", "CNY") != "CNY":
                raise ValueError("This ZPay adapter supports CNY only")
            collection["currency"] = "CNY"
            collection.setdefault("creator", "PaidDrive 创作组")
            collection.setdefault("subtitle", "值得收藏的一组图片")
            collection.setdefault("description", "")
            if not collection.get("title"):
                raise ValueError("Collection title is required")
            items = collection.get("items", [])
            preview_count = collection.get("preview_count", 3)
            if type(preview_count) is not int or not 0 <= preview_count < len(items):
                raise ValueError("A collection needs paid items beyond its free previews")
            collection["preview_count"] = preview_count
            seen = set()
            for item in items:
                if not SAFE_ID.fullmatch(str(item.get("id", ""))) or item["id"] in seen:
                    raise ValueError("Item IDs must be unique and URL-safe")
                seen.add(item["id"])
                path = safe_path(self.root, item["file"])
                if not path.is_file():
                    raise ValueError(f"Missing collection image: {item['file']}")
                item["sha256"] = file_digest(path)
                item["size_bytes"] = path.stat().st_size
                item.setdefault("title", path.stem)
                item.setdefault("width", 1200)
                item.setdefault("height", 1500)
            # Price and copy may change for future orders. The sold image set,
            # its sequence and preview boundary may not change under a version.
            frozen = {"items": [{k: i[k] for k in ("id", "file", "sha256")} for i in items], "preview_count": preview_count}
            digest = hashlib.sha256(json.dumps(frozen, sort_keys=True).encode()).hexdigest()
            with db.transaction() as con:
                existing = con.execute("SELECT content_hash FROM collection_versions WHERE collection_id=? AND version=?", (collection["id"], collection["version"])).fetchone()
                if existing and existing["content_hash"] != digest:
                    raise ValueError(f"Collection {collection['id']} version {collection['version']} is immutable. Keep its original files and create a new version.")
                con.execute("INSERT INTO collection_versions(collection_id,version,manifest_json,content_hash) VALUES(?,?,?,?) ON CONFLICT(collection_id,version) DO UPDATE SET manifest_json=excluded.manifest_json", (collection["id"], collection["version"], json.dumps(collection), digest))
            self.current[collection["id"]] = collection
            self.slugs[collection["slug"]] = collection["id"]

    def get(self, collection_id: str, version: str | None = None):
        if version is None:
            return self.current.get(collection_id)
        with self.db.connection() as con:
            row = con.execute("SELECT manifest_json FROM collection_versions WHERE collection_id=? AND version=?", (collection_id, version)).fetchone()
        return json.loads(row["manifest_json"]) if row else None

    def for_slug(self, slug: str | None):
        if not slug:
            return next(iter(self.current.values()))
        cid = self.slugs.get(slug)
        return self.current.get(cid) if cid else None

    def checked_file(self, item):
        path = safe_path(self.root, item["file"])
        if not path.is_file() or file_digest(path) != item["sha256"]:
            raise FileNotFoundError("The purchased file is unavailable or has changed. Contact support.")
        return path
