#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Clone an existing TDLib database into additional slots."
    )
    parser.add_argument("count", type=int, help="Number of new TDLib DBs to create.")
    parser.add_argument(
        "base_dir",
        nargs="?",
        default="/app/tdlib_user",
        help="Source TDLib database directory.",
    )
    parser.add_argument(
        "--config",
        default="/app/config_local.py",
        help="Live config file to update with the new TDLib pool.",
    )
    return parser.parse_args()


def _next_index(base_dir: Path, taken: set[str]) -> int:
    start = 2 if base_dir.name == "tdlib_user" else 1
    while f"{base_dir.name}_{start}" in taken or (base_dir.parent / f"{base_dir.name}_{start}").exists():
        start += 1
    return start


def _read_paths(config_path: Path) -> list[str]:
    if not config_path.exists():
        return []
    text = config_path.read_text()
    match = re.search(
        r"(?ms)^TDLIB_USER_DB_PATHS\s*=\s*\[(.*?)^\]",
        text,
    )
    if not match:
        return []
    block = match.group(1)
    return re.findall(r'"([^"]+)"', block)


def _write_paths(config_path: Path, paths: list[str]) -> None:
    if not config_path.exists():
        raise FileNotFoundError(config_path)
    text = config_path.read_text()
    new_block = "TDLIB_USER_DB_PATHS = [\n"
    for path in paths:
        new_block += f'    "{path}",\n'
    new_block += "]"
    if re.search(r"(?ms)^TDLIB_USER_DB_PATHS\s*=\s*\[.*?^\]", text):
        text = re.sub(
            r"(?ms)^TDLIB_USER_DB_PATHS\s*=\s*\[.*?^\]",
            new_block,
            text,
            count=1,
        )
    else:
        text += "\n" + new_block + "\n"
    config_path.write_text(text)


def main():
    args = parse_args()
    base_dir = Path(args.base_dir)
    config_path = Path(args.config)

    if args.count < 1:
        raise SystemExit("count must be at least 1")
    if not base_dir.exists():
        raise SystemExit(f"base TDLib directory not found: {base_dir}")

    existing_paths = _read_paths(config_path)
    taken = set(existing_paths)
    created = []
    start = _next_index(base_dir, taken)

    for index in range(start, start + args.count):
        target = base_dir.parent / f"{base_dir.name}_{index}"
        if target.exists():
            continue
        shutil.copytree(base_dir, target)
        created.append(target.name)
        taken.add(target.name)
        print(f"CLONED {base_dir} -> {target}")

    merged = existing_paths[:]
    for name in created:
        if name not in merged:
            merged.append(name)

    if merged != existing_paths:
        _write_paths(config_path, merged)
        print(f"UPDATED {config_path}")

    print("\nTDLIB_USER_DB_PATHS = [")
    for name in merged:
        print(f'    "{name}",')
    print("]")


if __name__ == "__main__":
    main()
