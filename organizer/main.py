"""File Organizer - CLI entry point and core logic."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def setup_logging(log_file: Path) -> logging.Logger:
    """Configure logging to file and stdout."""
    logger = logging.getLogger("organizer")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    # File handler
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(console_handler)

    return logger


def load_default_config() -> dict[str, Any]:
    """Load default config from config.example.json."""
    example_path = Path("config.example.json")
    if example_path.exists():
        try:
            with example_path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"categories": {}, "keyword_rules": {}, "skip_extensions": [], "skip_folders": True}


def load_config(config_path: Path) -> dict[str, Any]:
    """Load and parse the JSON config file, merging with defaults."""
    # Load defaults first
    config = load_default_config()

    # Load user config (overrides defaults)
    if config_path.exists():
        try:
            with config_path.open("r", encoding="utf-8") as f:
                user_config = json.load(f)
        except json.JSONDecodeError as e:
            sys.exit(f"Invalid JSON in config: {e}")

        # Merge: user categories extend defaults, user skip_extensions extend defaults
        if "categories" in user_config:
            config["categories"] = {**config.get("categories", {}), **user_config["categories"]}
        if "keyword_rules" in user_config:
            config["keyword_rules"] = {**config.get("keyword_rules", {}), **user_config["keyword_rules"]}
        if "skip_extensions" in user_config:
            # Combine, avoiding duplicates
            default_skips = set(config.get("skip_extensions", []))
            user_skips = set(user_config["skip_extensions"])
            config["skip_extensions"] = list(default_skips | user_skips)
        if "skip_folders" in user_config:
            config["skip_folders"] = user_config["skip_folders"]
        if "source_folder" in user_config:
            config["source_folder"] = user_config["source_folder"]

    return config


def save_config(config_path: Path, config: dict[str, Any]) -> None:
    """Save config to JSON file."""
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with config_path.open("w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
    except OSError as e:
        sys.exit(f"Failed to save config: {e}")


def expand_path(path_str: str) -> Path:
    """Expand ~ and environment variables, return absolute Path."""
    return Path(path_str).expanduser().resolve()


def build_extension_map(categories: dict[str, Any]) -> dict[str, tuple[str, Path]]:
    """Build a mapping from extension to (category_name, destination_path)."""
    ext_map: dict[str, tuple[str, Path]] = {}
    for cat_name, cat_info in categories.items():
        destination = expand_path(cat_info["destination"])
        for ext in cat_info["extensions"]:
            ext_map[ext.lower()] = (cat_name, destination)
    return ext_map


def should_skip(file_path: Path, skip_extensions: list[str], skip_folders: bool) -> bool:
    """Check if a file should be skipped."""
    if skip_folders and file_path.is_dir():
        return True
    if file_path.suffix.lower() in [ext.lower() for ext in skip_extensions]:
        return True
    return False


def match_keyword_rules(filename: str, keyword_rules: dict[str, str], categories: dict[str, Any]) -> tuple[str, Path] | None:
    """Check if filename matches any keyword rule. Returns (category, destination) or None.

    keyword_rules format: {"invoice": "Finance", "receipt": "Finance", "lecture": "School"}
    """
    filename_lower = filename.lower()
    for keyword, category in keyword_rules.items():
        if keyword.lower() in filename_lower:
            if category in categories:
                dest = expand_path(categories[category]["destination"])
                return category, dest
    return None


def get_unique_destination(dest_dir: Path, filename: str) -> Path:
    """Return a non-existing path in dest_dir, adding (1), (2), etc. if needed."""
    dest_path = dest_dir / filename
    if not dest_path.exists():
        return dest_path

    stem = dest_path.stem
    suffix = dest_path.suffix
    counter = 1
    while True:
        new_name = f"{stem} ({counter}){suffix}"
        new_path = dest_dir / new_name
        if not new_path.exists():
            return new_path
        counter += 1


def prompt_for_category(
    ext: str,
    categories: dict[str, Any],
    config_path: Path,
    logger: logging.Logger,
) -> tuple[str, Path] | None:
    """Prompt user to choose or create a category for an unknown extension.

    Returns (category_name, destination_path) or None if user cancels.
    """
    print(f"\nUnknown extension: {ext}")
    print("Choose a category or create a new one:")

    # List existing categories (exclude internal keys like _skip_extensions)
    cat_names = [name for name in categories.keys() if not name.startswith("_") and isinstance(categories[name], dict) and "destination" in categories[name]]
    for i, name in enumerate(cat_names, 1):
        dest = categories[name]["destination"]
        print(f"  {i}. {name} ({dest})")

    print(f"  {len(cat_names) + 1}. Create new category")
    print("  0. Skip this file (and all others with this extension)")

    while True:
        try:
            choice = input("Enter choice: ").strip()
            if not choice:
                continue
            choice_num = int(choice)
        except ValueError:
            print("Please enter a number.")
            continue
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return None

        if choice_num == 0:
            # Skip this extension - add to skip_extensions
            skip_ext = categories.setdefault("_skip_extensions", [])
            if ext not in skip_ext:
                skip_ext.append(ext)
                save_config(config_path, categories)
                logger.info(f"Added {ext} to skip list")
            return None

        if 1 <= choice_num <= len(cat_names):
            # Existing category
            cat_name = cat_names[choice_num - 1]
            dest = expand_path(categories[cat_name]["destination"])
            # Add extension to this category
            if ext not in categories[cat_name]["extensions"]:
                categories[cat_name]["extensions"].append(ext)
                save_config(config_path, categories)
                logger.info(f"Added {ext} to category '{cat_name}'")
            return cat_name, dest

        if choice_num == len(cat_names) + 1:
            # Create new category
            return create_new_category(ext, categories, config_path, logger)

        print(f"Invalid choice. Enter 0-{len(cat_names) + 1}.")


def create_new_category(
    ext: str,
    categories: dict[str, Any],
    config_path: Path,
    logger: logging.Logger,
) -> tuple[str, Path] | None:
    """Prompt user to create a new category."""
    while True:
        try:
            name = input("New category name: ").strip()
            if not name:
                print("Category name cannot be empty.")
                continue
            if name in categories:
                print(f"Category '{name}' already exists.")
                continue
            break
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return None

    while True:
        try:
            dest = input(f"Destination folder for '{name}' (use ~ for home): ").strip()
            if not dest:
                print("Destination cannot be empty.")
                continue
            dest_path = expand_path(dest)
            break
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return None

    # Create the new category
    categories[name] = {
        "extensions": [ext],
        "destination": str(dest_path)
    }
    save_config(config_path, categories)
    logger.info(f"Created new category '{name}' with extension {ext} -> {dest_path}")

    return name, dest_path


def organize_file(
    file_path: Path,
    ext_map: dict[str, tuple[str, Path]],
    logger: logging.Logger,
    dry_run: bool = False,
    interactive: bool = False,
    categories: dict[str, Any] | None = None,
    config_path: Path | None = None,
    keyword_rules: dict[str, str] | None = None,
) -> bool:
    """Move a single file to its category folder. Returns True if moved."""
    ext = file_path.suffix.lower()

    # Skip files without extensions (dotfiles like .gitignore, .gitattributes)
    if not ext:
        logger.debug(f"Skipping file without extension: {file_path.name}")
        return False

    # Check keyword rules first (higher priority than extension)
    if keyword_rules and categories:
        keyword_match = match_keyword_rules(file_path.name, keyword_rules, categories)
        if keyword_match:
            category, dest_dir = keyword_match
        else:
            # Fall back to extension matching
            if ext not in ext_map:
                if interactive and categories is not None and config_path is not None:
                    # Prompt user for category
                    result = prompt_for_category(ext, categories, config_path, logger)
                    if result is None:
                        return False  # User chose to skip
                    cat_name, dest_dir = result
                    # Rebuild ext_map with new extension
                    ext_map[ext] = (cat_name, dest_dir)
                else:
                    return False
            category, dest_dir = ext_map[ext]
    else:
        # No keyword rules, use extension matching
        if ext not in ext_map:
            if interactive and categories is not None and config_path is not None:
                # Prompt user for category
                result = prompt_for_category(ext, categories, config_path, logger)
                if result is None:
                    return False  # User chose to skip
                cat_name, dest_dir = result
                # Rebuild ext_map with new extension
                ext_map[ext] = (cat_name, dest_dir)
            else:
                return False
        category, dest_dir = ext_map[ext]

    # Ensure destination directory exists
    if not dry_run:
        dest_dir.mkdir(parents=True, exist_ok=True)

    dest_path = get_unique_destination(dest_dir, file_path.name)

    action = "Would move" if dry_run else "Moved"
    logger.info(f"{action}: {file_path} -> {dest_path} [{category}]")

    if not dry_run:
        try:
            shutil.move(str(file_path), str(dest_path))
        except (PermissionError, OSError) as e:
            logger.error(f"Failed to move {file_path}: {e}")
            return False

    return True


def run_organizer(
    source: Path,
    config: dict[str, Any],
    logger: logging.Logger,
    dry_run: bool = False,
    interactive: bool = False,
    config_path: Path | None = None,
) -> tuple[int, int]:
    """Organize files in source folder according to config. Returns (moved_count, skipped_count)."""
    categories = config.get("categories", {})
    keyword_rules = config.get("keyword_rules", {})
    skip_extensions = config.get("skip_extensions", [])
    skip_folders = config.get("skip_folders", True)

    ext_map = build_extension_map(categories)

    moved = 0
    skipped = 0

    if not source.exists():
        logger.error(f"Source folder does not exist: {source}")
        return moved, skipped

    if not source.is_dir():
        logger.error(f"Source is not a directory: {source}")
        return moved, skipped

    for file_path in source.iterdir():
        if should_skip(file_path, skip_extensions, skip_folders):
            skipped += 1
            continue

        if organize_file(
            file_path, ext_map, logger, dry_run,
            interactive, categories, config_path, keyword_rules
        ):
            moved += 1
        else:
            skipped += 1

    return moved, skipped


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Organize files into category folders based on extension rules.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m organizer.main --dry-run
  python -m organizer.main
  python -m organizer.main --source "D:/Messy" --config my_rules.json
  python -m organizer.main --interactive
  python -m organizer.main --undo
        """,
    )
    parser.add_argument(
        "--source",
        type=str,
        help="Folder to organize (overrides config's source_folder)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config.json",
        help="Path to config file (default: config.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview moves without making changes",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Prompt for unknown extensions and save to config",
    )
    parser.add_argument(
        "--undo",
        action="store_true",
        help="Undo the last organization run by reading organizer_log.txt",
    )
    return parser.parse_args()


def undo_organizer(log_file: Path, logger: logging.Logger, dry_run: bool = False) -> tuple[int, int]:
    """Undo moves by reading the log file. Returns (undone_count, failed_count)."""
    if not log_file.exists():
        logger.error(f"Log file not found: {log_file}")
        return 0, 0

    undone = 0
    failed = 0

    with log_file.open("r", encoding="utf-8") as f:
        lines = f.readlines()

    # Parse log entries in reverse order (most recent first)
    # Log format: "2026-11-16 10:30:45,123 | Moved: source -> dest [Category]"
    for line in reversed(lines):
        line = line.strip()
        if " | Moved: " not in line:
            continue

        try:
            # Extract the move part: "Moved: source -> dest [Category]"
            move_part = line.split(" | Moved: ")[1]
            # Parse: "source -> dest [Category]"
            if " -> " not in move_part:
                continue
            source_str, rest = move_part.split(" -> ", 1)
            dest_str = rest.split(" [")[0]

            source_path = Path(source_str.strip())
            dest_path = Path(dest_str.strip())

            if not dest_path.exists():
                logger.warning(f"Destination file no longer exists: {dest_path}")
                failed += 1
                continue

            if not dry_run:
                # Ensure source directory exists
                source_path.parent.mkdir(parents=True, exist_ok=True)

                # Handle collision at source
                final_source = get_unique_destination(source_path.parent, source_path.name)

                try:
                    shutil.move(str(dest_path), str(final_source))
                    logger.info(f"Undid: {dest_path} -> {final_source}")
                except (PermissionError, OSError) as e:
                    logger.error(f"Failed to undo {dest_path}: {e}")
                    failed += 1
                    continue
            else:
                logger.info(f"Would undo: {dest_path} -> {source_path}")

            undone += 1

        except (IndexError, ValueError) as e:
            logger.debug(f"Failed to parse log line: {line}")
            continue

    return undone, failed


def main() -> int:
    """Main entry point."""
    args = parse_args()

    config_path = Path(args.config).expanduser().resolve()
    config = load_config(config_path)

    # Setup logging
    log_file = Path("organizer_log.txt").resolve()
    logger = setup_logging(log_file)

    # Handle undo command
    if args.undo:
        logger.info("=== File Organizer UNDO ===")
        logger.info(f"Reading log: {log_file}")
        if args.dry_run:
            logger.info("DRY RUN: No files will be moved")

        undone, failed = undo_organizer(log_file, logger, args.dry_run)
        logger.info(f"Done. Undone: {undone}, Failed: {failed}")
        if args.dry_run:
            logger.info("This was a dry run. Run without --dry-run to execute undo.")
        return 0

    # Determine source folder
    if args.source:
        source = expand_path(args.source)
    else:
        source = expand_path(config.get("source_folder", "~/Downloads"))

    mode = "DRY RUN" if args.dry_run else "LIVE RUN"
    logger.info(f"=== File Organizer {mode} ===")
    logger.info(f"Source: {source}")
    logger.info(f"Config: {config_path}")
    if args.interactive:
        logger.info("Interactive mode: ON")

    moved, skipped = run_organizer(
        source, config, logger, args.dry_run,
        args.interactive, config_path
    )

    logger.info(f"Done. Moved: {moved}, Skipped/No-match: {skipped}")

    if args.dry_run:
        logger.info("This was a dry run. No files were moved. Run without --dry-run to execute.")

    return 0


if __name__ == "__main__":
    sys.exit(main())