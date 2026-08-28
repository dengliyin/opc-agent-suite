#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DESTINATION = APP_ROOT / "runtime" / "hyperframes"


def package_key(source: Path) -> str:
    manifest = json.loads((source / "package.json").read_text(encoding="utf-8"))
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", str(manifest.get("name") or source.name)).strip("_")
    version = re.sub(r"[^A-Za-z0-9._-]+", "_", str(manifest.get("version") or "0")).strip("_")
    digest = hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:10]
    return f"{name}-{version}-{digest}"


def dependency_source(package: Path, name: str) -> Path | None:
    node_modules = next((parent for parent in package.parents if parent.name == "node_modules"), package.parent)
    candidate = node_modules / name
    if candidate.exists():
        return candidate.resolve()
    return None


def relative_symlink(target: Path, link: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(os.path.relpath(target, link.parent), target_is_directory=True)


def package_runtime(source: Path, destination: Path) -> Path:
    source = source.resolve()
    destination = destination.resolve()
    if not (source / "package.json").is_file():
        raise RuntimeError(f"HyperFrames package is invalid: {source}")
    if destination.exists():
        shutil.rmtree(destination)
    packages_dir = destination / "packages"
    packages_dir.mkdir(parents=True)
    packaged: dict[Path, Path] = {}

    def copy_package(package: Path) -> Path:
        package = package.resolve()
        if package in packaged:
            return packaged[package]
        target = packages_dir / package_key(package)
        packaged[package] = target
        target.mkdir(parents=True)

        for entry in package.iterdir():
            if entry.name == "node_modules":
                continue
            output = target / entry.name
            if entry.is_dir():
                shutil.copytree(entry, output, symlinks=False)
            else:
                shutil.copy2(entry, output, follow_symlinks=True)

        manifest = json.loads((package / "package.json").read_text(encoding="utf-8"))
        required = dict(manifest.get("dependencies") or {})
        optional = dict(manifest.get("optionalDependencies") or {})
        peers = dict(manifest.get("peerDependencies") or {})
        for name in sorted(set(required) | set(optional) | set(peers)):
            dependency = dependency_source(package, name)
            if dependency is None:
                if name in required:
                    raise RuntimeError(f"Missing dependency {name} for {package}")
                continue
            dependency_target = copy_package(dependency)
            relative_symlink(dependency_target, target / "node_modules" / name)
        return target

    root_package = copy_package(source)
    relative_symlink(root_package, destination / "package")
    (destination / "manifest.json").write_text(
        json.dumps(
            {
                "source": str(source),
                "root_package": root_package.name,
                "package_count": len(packaged),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return destination / "package" / "dist" / "cli.js"


def main() -> None:
    parser = argparse.ArgumentParser(description="Package an installed HyperFrames dependency graph for offline use.")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    args = parser.parse_args()
    cli = package_runtime(args.source, args.destination)
    print(cli)


if __name__ == "__main__":
    main()
