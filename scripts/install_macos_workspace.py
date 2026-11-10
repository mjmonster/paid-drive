#!/usr/bin/env python3
"""Copy this clean source package into a new PaidDrive workspace on macOS."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import fnmatch
import os
from pathlib import Path
import shlex
import shutil
import stat
import sys


DEFAULT_DESTINATION = Path("/Users/mewtwo/Workspace/PaidDrive")
PROTECTED_IMAGES = Path("/Users/mewtwo/Images")
SOURCE_DIRECTORIES = {"app", "content", "deploy", "scripts", "tests", "docs"}
SOURCE_FILES = {
    "README.md", "VALIDATION.md", "requirements.txt", "requirements-dev.txt",
    "Dockerfile", "compose.yaml", "package.json", "pyproject.toml", "uv.lock",
    "LICENSE", ".env.example", ".gitignore", ".dockerignore",
}
REQUIRED = {"app/main.py", "app/static/index.html", "compose.yaml", "Dockerfile", "requirements.txt"}
EXCLUDED_NAMES = {
    "data", "outbox", "logs", "log", "secrets", "credentials", "screenshots",
    "__pycache__", "node_modules", "venv", "env", ".venv", ".git", ".openai",
    ".runtime", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".DS_Store",
}
EXCLUDED_PATTERNS = (
    "*.db", "*.db-*", "*.sqlite*", "*.pyc", "*.pyo", "*.log", "*.eml",
    "*.env", "*.env.*",
    "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore",
    "*credentials*", "*secret*", "id_rsa*", "id_ed25519*", "screenshot*",
)


@dataclass(frozen=True)
class CopyPlan:
    source: Path
    destination: Path
    files: tuple[Path, ...]
    size_bytes: int
    parent_exists: bool


def _excluded(name: str) -> bool:
    if name in {".env.example", ".gitignore", ".dockerignore"}:
        return False
    lower = name.casefold()
    return (
        lower in {part.casefold() for part in EXCLUDED_NAMES}
        or name.startswith(".")
        or any(fnmatch.fnmatch(lower, pattern) for pattern in EXCLUDED_PATTERNS)
    )


def _reject_symlink_path(path: Path) -> None:
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError(f"拒绝符号链接路径：{part}")


def _inside(path: Path, parent: Path) -> bool:
    # Most Mac volumes ignore case. Be conservative even on case-sensitive disks.
    parts = tuple(part.casefold() for part in path.parts)
    parent_parts = tuple(part.casefold() for part in parent.parts)
    return parts[:len(parent_parts)] == parent_parts


def prepare_copy(source: Path, destination: Path, *, dry_run: bool = False) -> CopyPlan:
    """Validate paths and inventory source files without changing either tree."""
    source = source.absolute()
    if not destination.is_absolute() or ".." in destination.parts:
        raise ValueError("目标目录必须使用不含 '..' 的绝对路径。")
    _reject_symlink_path(source)
    _reject_symlink_path(destination)
    source = source.resolve(strict=True)
    if not source.is_dir():
        raise ValueError("源项目目录不存在。")
    if os.path.lexists(destination):
        raise FileExistsError(f"目标已经存在；不会覆盖或合并：{destination}")
    parent_exists = destination.parent.is_dir()
    if not parent_exists and not dry_run:
        raise FileNotFoundError(f"请先确认工作区父目录存在：{destination.parent}")
    parent = destination.parent.resolve(strict=parent_exists)
    destination = parent / destination.name
    if _inside(destination, source) or _inside(source, destination):
        raise ValueError("目标不能是源项目自身、其子目录或其父目录。")
    if "soccer-match-analyzer" in {part.casefold() for part in destination.parts}:
        raise ValueError("不能将 PaidDrive 安装到 soccer-match-analyzer 项目内。")
    if _inside(destination, PROTECTED_IMAGES):
        raise ValueError("不能将 PaidDrive 安装到原始图片目录内。")

    files: list[Path] = []
    total = 0

    def visit(path: Path) -> None:
        nonlocal total
        if _excluded(path.name):
            return
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(f"源文件包含符号链接，已停止：{path.relative_to(source)}")
        if stat.S_ISDIR(info.st_mode):
            for child in sorted(path.iterdir(), key=lambda item: item.name):
                visit(child)
        elif stat.S_ISREG(info.st_mode):
            files.append(path.relative_to(source))
            total += info.st_size
        else:
            raise ValueError(f"源目录包含非常规文件，已停止：{path.relative_to(source)}")

    for name in sorted(SOURCE_DIRECTORIES | SOURCE_FILES):
        path = source / name
        if os.path.lexists(path):
            visit(path)
    missing = REQUIRED - {path.as_posix() for path in files}
    if missing:
        raise ValueError("当前目录不是完整的 PaidDrive 源包，缺少：" + ", ".join(sorted(missing)))
    return CopyPlan(source, destination, tuple(files), total, parent_exists)


def _copy_one(root_fd: int, relative: Path, target: Path) -> None:
    """Read every source component without following symlinks, then copy bytes."""
    directory_fd = os.dup(root_fd)
    try:
        for part in relative.parts[:-1]:
            child_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = child_fd
        file_fd = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
        with os.fdopen(file_fd, "rb") as source_file:
            info = os.fstat(source_file.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ValueError(f"源文件已改变，已停止：{relative}")
            with target.open("xb") as target_file:
                shutil.copyfileobj(source_file, target_file)
            os.chmod(target, stat.S_IMODE(info.st_mode) & 0o777)
    finally:
        os.close(directory_fd)


def _copy_new_tree(plan: CopyPlan) -> None:
    """Internal copy routine; the CLI enforces macOS before calling it."""
    _reject_symlink_path(plan.source)
    _reject_symlink_path(plan.destination.parent)
    if not plan.destination.parent.is_dir():
        raise FileNotFoundError(f"工作区父目录不存在：{plan.destination.parent}")
    # mkdir is exclusive: even a target created after planning is never replaced.
    plan.destination.mkdir(mode=0o700, exist_ok=False)
    owned = plan.destination.lstat()
    try:
        root_fd = os.open(plan.source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for relative in plan.files:
                target = plan.destination / relative
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                _copy_one(root_fd, relative, target)
        finally:
            os.close(root_fd)
        for directory, _, _ in os.walk(plan.destination):
            os.chmod(directory, 0o755)
    except BaseException:
        # Remove only the directory this invocation created, not a replacement.
        if not plan.destination.is_symlink() and plan.destination.exists():
            current = plan.destination.lstat()
            if (current.st_dev, current.st_ino) == (owned.st_dev, owned.st_ino):
                shutil.rmtree(plan.destination)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="将当前 PaidDrive 源包复制到 Mac 上全新的工作目录；不覆盖现有目录。")
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION, help="新的目标目录，必须是绝对路径")
    parser.add_argument("--dry-run", action="store_true", help="只检查并显示计划，不创建目录；可在其他系统运行")
    args = parser.parse_args(argv)
    if not args.dry_run and sys.platform != "darwin":
        parser.exit(1, "未执行：实际安装仅允许在 macOS 上运行。可使用 --dry-run 查看计划。\n")
    try:
        source = Path(__file__).absolute().parent.parent
        plan = prepare_copy(source, args.destination, dry_run=args.dry_run)
        print(f"源项目：{plan.source}")
        print(f"目标目录：{plan.destination}")
        print(f"复制内容：{len(plan.files)} 个文件，{plan.size_bytes:,} 字节")
        if args.dry_run:
            print("仅检查：未创建目录，也未修改任何文件。")
            if not plan.parent_exists:
                print(f"注意：当前环境找不到父目录 {plan.destination.parent}；实际安装要求该目录已存在。")
            return 0
        _copy_new_tree(plan)
    except (OSError, ValueError) as error:
        parser.exit(1, f"未完成安装：{error}\n")
    print(f"已创建：{plan.destination}")
    print("下一步（在 Mac 终端执行）：")
    print(f"  cd {shlex.quote(str(plan.destination))}")
    print("  python3.12 -m venv .venv")
    print("  source .venv/bin/activate")
    print("  python -m pip install -r requirements.txt")
    print("  python -m uvicorn app.main:app --host 127.0.0.1 --port 8000")
    print("浏览器打开：http://localhost:8000/（默认为演示模式，不会真实扣款）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
