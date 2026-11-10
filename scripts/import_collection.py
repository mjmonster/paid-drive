#!/usr/bin/env python3
"""Copy a local image folder into a fixed, explicitly ordered collection.

Never edits the source folder or overwrites a previously imported version.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile


ROOT = Path(__file__).resolve().parent.parent
SAFE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")
FORMATS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def natural_key(path):
    return [int(p) if p.isdigit() else p.casefold() for p in re.split(r"(\d+)", path.name)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--price-cents", type=int, required=True)
    parser.add_argument("--version", default="v1")
    parser.add_argument("--creator", default="PaidDrive 创作组")
    parser.add_argument("--description", default="一组值得收藏的图片，购买后可反复查看和下载。")
    parser.add_argument("--preview-count", type=int, default=3)
    parser.add_argument("--content-root", type=Path, default=ROOT / "content")
    parser.add_argument("--files", nargs="+", help="Optional exact filenames in the desired order; otherwise natural filename order is used")
    args = parser.parse_args()
    source = args.source.expanduser().resolve()
    if not source.is_dir():
        parser.error(f"Image folder not found: {source}")
    if not SAFE.fullmatch(args.slug) or not SAFE.fullmatch(args.version):
        parser.error("Slug and version must contain lowercase letters, digits, hyphens or underscores")
    if args.price_cents <= 0 or args.price_cents > 100_000_000:
        parser.error("--price-cents must be a positive integer, at most 100000000")
    if args.files:
        files = [source / filename for filename in args.files]
        if len(set(str(p.resolve()) for p in files)) != len(files):
            parser.error("Do not list the same file more than once")
    else:
        files = sorted((p for p in source.iterdir() if not p.name.startswith(".") and p.suffix.lower() in FORMATS), key=natural_key)
    for path in files:
        if not path.resolve().is_relative_to(source) or not path.is_file() or path.is_symlink() or path.suffix.lower() not in FORMATS:
            parser.error(f"Unsupported or missing image: {path.name}")
    if not 0 <= args.preview_count < len(files):
        parser.error(f"Found {len(files)} images; need more than {args.preview_count} for a paid collection")
    content = args.content_root.expanduser().resolve()
    content.mkdir(parents=True, exist_ok=True)
    config_path = content / "collections.json"
    config = json.loads(config_path.read_text("utf-8")) if config_path.exists() else {"collections": []}
    existing = next((c for c in config["collections"] if c["id"] == args.slug), None)
    if existing and existing["version"] == args.version:
        parser.error("This collection version already exists. Use a new --version and preserve the old files.")
    relative = Path("images") / f"{args.slug}-{args.version}"
    target = content / relative
    if target.exists():
        parser.error(f"Destination already exists: {target}. Choose a new version.")
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".import-", dir=target.parent))
    items = []
    try:
        for index, path in enumerate(files, start=1):
            ident = f"{index:03d}"
            filename = ident + path.suffix.lower()
            shutil.copyfile(path, stage / filename)
            width, height = 1200, 1500
            # Pillow is optional for native imports; image decoding is not
            # required by the server or Docker runtime.
            try:
                from PIL import Image
                with Image.open(path) as image:
                    width, height = image.size
            except ImportError:
                pass
            except OSError:
                parser.error(f"Cannot decode image: {path.name}")
            items.append({"id": ident, "file": (relative / filename).as_posix(), "title": path.stem, "width": width, "height": height})
        collection = {"id": args.slug, "slug": args.slug, "version": args.version, "title": args.title,
                      "subtitle": "值得收藏的一组图片。", "description": args.description, "creator": args.creator,
                      "price_cents": args.price_cents, "currency": "CNY", "preview_count": args.preview_count, "items": items}
        config["collections"] = [collection if c["id"] == args.slug else c for c in config["collections"]]
        if not existing:
            config["collections"].append(collection)
        # Persist files before the manifest points at them; never alter an old
        # folder. Imports are operator actions performed while restarting app.
        stage.rename(target)
        draft = config_path.with_suffix(".json.tmp")
        draft.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", "utf-8")
        draft.replace(config_path)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    print(f"Imported {len(items)} images into {target}")
    print(f"First {args.preview_count} images are public previews. Restart PaidDrive, then open /c/{args.slug}.")
    print("Keep this version's files unchanged after selling it. Source images were not modified.")


if __name__ == "__main__":
    main()
