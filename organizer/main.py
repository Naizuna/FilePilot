"""File Organizer - CLI entry point and core logic."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def get_resource_path(relative_path: str) -> Path:
    """Get path to resource, works for dev, tests, and PyInstaller frozen app."""
    if hasattr(sys, '_MEIPASS'):
        # Running in PyInstaller bundle
        return Path(sys._MEIPASS) / relative_path
    # Running in development or tests - check multiple locations
    # 1. Current working directory (where config.example.json usually is)
    cwd_path = Path.cwd() / relative_path
    if cwd_path.exists():
        return cwd_path
    # 2. Parent of this file (organizer/ directory)
    file_parent = Path(__file__).parent / relative_path
    if file_parent.exists():
        return file_parent
    # 3. Grandparent (project root)
    grandparent = Path(__file__).parent.parent / relative_path
    if grandparent.exists():
        return grandparent
    # Fallback: return path relative to this file (for error messages)
    return Path(__file__).parent / relative_path


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
    example_path = get_resource_path("config.example.json")
    if example_path.exists():
        try:
            with example_path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"categories": {}, "keyword_rules": {}, "ai_categorization": {}, "skip_extensions": [], "skip_folders": True}


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
        if "ai_categorization" in user_config:
            config["ai_categorization"] = {**config.get("ai_categorization", {}), **user_config["ai_categorization"]}
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
    """Expand ~ and environment variables, return absolute Path.

    Uses .absolute() instead of .resolve() to avoid following symlinks,
    preventing potential directory traversal via symlink attacks.
    """
    return Path(path_str).expanduser().absolute()


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


# ===== AI Categorization (Privacy-First) =====

# PII patterns to redact before sending to AI
PII_PATTERNS = [
    (r'\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b', '[CREDIT_CARD]'),
    (r'\b\d{3}-\d{2}-\d{4}\b', '[SSN]'),
    (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL]'),
    (r'\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b', '[PHONE]'),
    (r'password\s*[:=]\s*\S+', 'password=[REDACTED]', re.IGNORECASE),
    (r'api[_-]?key\s*[:=]\s*\S+', 'api_key=[REDACTED]', re.IGNORECASE),
    (r'secret\s*[:=]\s*\S+', 'secret=[REDACTED]', re.IGNORECASE),
    (r'token\s*[:=]\s*\S+', 'token=[REDACTED]', re.IGNORECASE),
]


def redact_pii(text: str) -> str:
    """Redact PII from text before sending to AI."""
    import re
    result = text
    for pattern, replacement in PII_PATTERNS:
        if isinstance(pattern, str):
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
        else:
            result = pattern.sub(replacement, result)
    return result


def extract_text_from_file(file_path: Path, max_chars: int = 5000) -> str | None:
    """Extract text content from file for AI categorization.

    Supports: .txt, .md, .pdf, .docx
    Returns None if extraction fails or file too large.
    """
    ext = file_path.suffix.lower()

    try:
        if ext in ('.txt', '.md', '.py', '.js', '.json', '.xml', '.yaml', '.yml', '.csv', '.log'):
            # Plain text files
            content = file_path.read_text(encoding='utf-8', errors='ignore')
            return content[:max_chars]

        elif ext == '.pdf':
            # PDF - try to extract text
            try:
                import fitz  # PyMuPDF
                doc = fitz.open(file_path)
                text = ""
                for page in doc:
                    text += page.get_text()
                    if len(text) > max_chars:
                        break
                doc.close()
                return text[:max_chars]
            except ImportError:
                logger = logging.getLogger("organizer")
                logger.warning("PyMuPDF not installed, cannot extract PDF text")
                return None
            except Exception as e:
                logger = logging.getLogger("organizer")
                logger.warning(f"Failed to extract PDF text: {e}")
                return None

        elif ext == '.docx':
            # Word documents
            try:
                from docx import Document
                doc = Document(file_path)
                text = "\n".join([p.text for p in doc.paragraphs])
                return text[:max_chars]
            except ImportError:
                logger = logging.getLogger("organizer")
                logger.warning("python-docx not installed, cannot extract DOCX text")
                return None
            except Exception as e:
                logger = logging.getLogger("organizer")
                logger.warning(f"Failed to extract DOCX text: {e}")
                return None

    except Exception as e:
        logger = logging.getLogger("organizer")
        logger.warning(f"Failed to extract text from {file_path}: {e}")

    return None


def build_ai_prompt(categories: dict[str, Any], filename: str, content: str) -> str:
    """Build the prompt for AI categorization."""
    cat_list = [name for name in categories.keys() if not name.startswith("_") and isinstance(categories[name], dict) and "destination" in categories[name]]

    # Redact filename to prevent PII leakage (e.g., "john_doe_tax_return.pdf")
    safe_filename = redact_pii(filename)

    prompt = f"""Categorize this file into ONE of these categories: {', '.join(cat_list)}

File name: {safe_filename}
Content preview:
{content}

Rules:
- Return ONLY the category name, nothing else
- Must be exactly one of: {', '.join(cat_list)}
- If uncertain, pick the closest match
"""
    return prompt


def categorize_with_local_ai(prompt: str, model: str = "llama3.2:3b") -> str | None:
    """Call local Ollama API for categorization. No data leaves the machine."""
    try:
        import urllib.request
        import json

        url = "http://localhost:11434/api/generate"
        data = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 50}
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )

        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))
            category = result.get('response', '').strip()
            return category if category else None

    except urllib.error.ConnectionRefusedError:
        logger = logging.getLogger("organizer")
        logger.error("Ollama not running. Start with: ollama serve")
        return None
    except urllib.error.URLError as e:
        logger = logging.getLogger("organizer")
        logger.error(f"Ollama connection failed: {e}")
        return None
    except Exception as e:
        logger = logging.getLogger("organizer")
        logger.error(f"Local AI categorization failed: {e}")
        return None


def categorize_with_cloud_ai(prompt: str, provider: str, model: str, api_key: str) -> str | None:
    """Call cloud AI API (OpenAI/Anthropic). Only if user explicitly enables."""
    logger = logging.getLogger("organizer")
    logger.warning(f"Using cloud AI ({provider}) - file content will be sent to external API")

    try:
        import urllib.request
        import json

        if provider == "openai":
            url = "https://api.openai.com/v1/chat/completions"
            headers = {
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            }
            data = {
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are a file categorization assistant. Return only the category name."},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 50,
                "temperature": 0.1
            }
        elif provider == "anthropic":
            url = "https://api.anthropic.com/v1/messages"
            headers = {
                'x-api-key': api_key,
                'Content-Type': 'application/json',
                'anthropic-version': '2023-06-01'
            }
            data = {
                "model": model,
                "max_tokens": 50,
                "temperature": 0.1,
                "messages": [
                    {"role": "user", "content": prompt}
                ]
            }
        else:
            logger.error(f"Unknown AI provider: {provider}")
            return None

        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode('utf-8'),
            headers=headers
        )

        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))

            if provider == "openai":
                category = result['choices'][0]['message']['content'].strip()
            elif provider == "anthropic":
                category = result['content'][0]['text'].strip()
            else:
                return None

            return category if category else None

    except urllib.error.HTTPError as e:
        logger.error(f"Cloud AI API error: {e.code} - {e.read().decode()}")
        return None
    except Exception as e:
        logger.error(f"Cloud AI categorization failed: {e}")
        return None


def categorize_with_ai(
    file_path: Path,
    categories: dict[str, Any],
    ai_config: dict[str, Any],
    logger: logging.Logger
) -> tuple[str, Path] | None:
    """Categorize file using AI with privacy safeguards.

    Returns (category, destination) or None if AI unavailable/disabled.
    """
    # Check if AI categorization is enabled
    if not ai_config.get("enabled", False):
        return None

    # Check file extension allowlist
    allowed_exts = ai_config.get("allowed_extensions", [".txt", ".md", ".pdf", ".docx"])
    if file_path.suffix.lower() not in allowed_exts:
        return None

    # Check file size limit
    max_size_kb = ai_config.get("max_file_size_kb", 50)
    if file_path.stat().st_size > max_size_kb * 1024:
        logger.debug(f"File too large for AI: {file_path.name} ({file_path.stat().st_size} bytes)")
        return None

    # Extract text content
    content = extract_text_from_file(file_path, max_chars=ai_config.get("max_chars", 5000))
    if not content or len(content.strip()) < 10:
        return None

    # Redact PII
    content = redact_pii(content)

    # Build prompt
    prompt = build_ai_prompt(categories, file_path.name, content)

    # Determine provider
    provider = ai_config.get("provider", "local")
    model = ai_config.get("model", "llama3.2:3b" if provider == "local" else "gpt-4o-mini")

    category = None
    if provider == "local":
        category = categorize_with_local_ai(prompt, model)
    elif provider in ("openai", "anthropic"):
        # API key MUST come from environment variable
        api_key_env = ai_config.get("api_key_env", "OPENAI_API_KEY" if provider == "openai" else "ANTHROPIC_API_KEY")
        api_key = os.environ.get(api_key_env)
        if not api_key:
            logger.error(f"AI enabled but {api_key_env} environment variable not set")
            return None
        category = categorize_with_cloud_ai(prompt, provider, model, api_key)
    else:
        logger.error(f"Unknown AI provider: {provider}")
        return None

    if not category:
        return None

    # Validate category exists in config
    if category not in categories:
        logger.warning(f"AI returned unknown category: {category}")
        return None

    dest = expand_path(categories[category]["destination"])
    logger.info(f"AI categorized '{file_path.name}' as '{category}' (provider: {provider})")
    return category, dest


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
    ai_config: dict[str, Any] | None = None,
) -> bool:
    """Move a single file to its category folder. Returns True if moved."""
    ext = file_path.suffix.lower()

    # Skip files without extensions (dotfiles like .gitignore, .gitattributes)
    if not ext:
        logger.debug(f"Skipping file without extension: {file_path.name}")
        return False

    # Priority 1: Keyword rules (check if explicitly provided, not just truthy)
    if keyword_rules is not None and categories:
        keyword_match = match_keyword_rules(file_path.name, keyword_rules, categories)
        if keyword_match:
            category, dest_dir = keyword_match
        else:
            # No keyword match - fall through to AI/extension/interactive
            pass
    else:
        # No keyword rules provided - fall through to AI/extension/interactive
        pass

    # Priority 2: AI categorization (if enabled)
    if 'category' not in locals():
        ai_match = None
        if ai_config and categories:
            ai_match = categorize_with_ai(file_path, categories, ai_config, logger)

        if ai_match:
            category, dest_dir = ai_match
        else:
            # Priority 3: Extension matching
            if ext not in ext_map:
                # Priority 4: Interactive prompt
                if interactive and categories is not None and config_path is not None:
                    result = prompt_for_category(ext, categories, config_path, logger)
                    if result is None:
                        return False  # User chose to skip
                    cat_name, dest_dir = result
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
    use_ai: bool = False,
) -> tuple[int, int]:
    """Organize files in source folder according to config. Returns (moved_count, skipped_count)."""
    categories = config.get("categories", {})
    keyword_rules = config.get("keyword_rules", {})
    ai_config = config.get("ai_categorization", {})
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
            interactive, categories, config_path, keyword_rules,
            ai_config if use_ai else None
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
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch graphical interface",
    )
    parser.add_argument(
        "--ai-categorize",
        action="store_true",
        help="Enable AI categorization for ambiguous files (requires config)",
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


def run_gui() -> int:
    """Launch the GUI interface."""
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except ImportError:
        print("tkinter not available. Install python3-tk (Linux) or use standard Python (Windows/Mac).")
        return 1

    class OrganizerGUI:
        def __init__(self, root):
            self.root = root
            self.root.title("File Organizer")
            self.root.geometry("600x500")
            self.root.minsize(500, 400)

            # Variables
            self.source_var = tk.StringVar()
            self.config_var = tk.StringVar(value="config.json")
            self.dry_run_var = tk.BooleanVar(value=True)
            self.interactive_var = tk.BooleanVar(value=False)
            self.undo_var = tk.BooleanVar(value=False)
            self.ai_var = tk.BooleanVar(value=False)
            self._running = False
            self._run_button = None

            self.build_ui()

        def build_ui(self):
            # Main frame with padding
            main_frame = ttk.Frame(self.root, padding="10")
            main_frame.pack(fill=tk.BOTH, expand=True)

            # Source folder
            ttk.Label(main_frame, text="Source Folder:").grid(row=0, column=0, sticky=tk.W, pady=5)
            source_frame = ttk.Frame(main_frame)
            source_frame.grid(row=0, column=1, sticky=tk.EW, pady=5)
            main_frame.columnconfigure(1, weight=1)

            ttk.Entry(source_frame, textvariable=self.source_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
            ttk.Button(source_frame, text="Browse...", command=self.browse_source).pack(side=tk.LEFT, padx=(5, 0))

            # Config file
            ttk.Label(main_frame, text="Config File:").grid(row=1, column=0, sticky=tk.W, pady=5)
            config_frame = ttk.Frame(main_frame)
            config_frame.grid(row=1, column=1, sticky=tk.EW, pady=5)

            ttk.Entry(config_frame, textvariable=self.config_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
            ttk.Button(config_frame, text="Browse...", command=self.browse_config).pack(side=tk.LEFT, padx=(5, 0))

            # Options frame
            options_frame = ttk.LabelFrame(main_frame, text="Options", padding="10")
            options_frame.grid(row=2, column=0, columnspan=2, sticky=tk.EW, pady=10)

            ttk.Checkbutton(options_frame, text="Dry Run (preview only)", variable=self.dry_run_var).pack(anchor=tk.W, pady=2)
            ttk.Checkbutton(options_frame, text="Interactive (prompt for unknown extensions)", variable=self.interactive_var).pack(anchor=tk.W, pady=2)
            ttk.Checkbutton(options_frame, text="Undo last run", variable=self.undo_var, command=self.toggle_undo).pack(anchor=tk.W, pady=2)
            ttk.Checkbutton(options_frame, text="AI Categorization (requires config)", variable=self.ai_var).pack(anchor=tk.W, pady=2)

            # Run button
            button_frame = ttk.Frame(main_frame)
            button_frame.grid(row=3, column=0, columnspan=2, pady=10)
            self._run_button = ttk.Button(button_frame, text="Run Organizer", command=self.run_organizer, style="Accent.TButton")
            self._run_button.pack(side=tk.LEFT, padx=5)
            ttk.Button(button_frame, text="View Log", command=self.view_log).pack(side=tk.LEFT, padx=5)
            ttk.Button(button_frame, text="Open Config", command=self.open_config).pack(side=tk.LEFT, padx=5)

            # Output log
            ttk.Label(main_frame, text="Output:").grid(row=4, column=0, sticky=tk.NW, pady=(10, 5))
            log_frame = ttk.Frame(main_frame)
            log_frame.grid(row=5, column=0, columnspan=2, sticky=tk.NSEW, pady=5)
            main_frame.rowconfigure(5, weight=1)

            self.log_text = tk.Text(log_frame, height=15, wrap=tk.WORD, state=tk.DISABLED)
            scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
            self.log_text.configure(yscrollcommand=scrollbar.set)
            self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

            # Status bar
            self.status_var = tk.StringVar(value="Ready")
            ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W).pack(fill=tk.X, side=tk.BOTTOM, padx=10, pady=5)

        def toggle_undo(self):
            if self.undo_var.get():
                self.dry_run_var.set(False)
                self.interactive_var.set(False)
                self.source_var.set("")  # Not needed for undo

        def browse_source(self):
            folder = filedialog.askdirectory(title="Select Source Folder")
            if folder:
                self.source_var.set(folder)

        def browse_config(self):
            file = filedialog.askopenfilename(title="Select Config File", filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
            if file:
                self.config_var.set(file)

        def log(self, message):
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, message + "\n")
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)

        def run_organizer(self):
            if self._running:
                return
            if self.undo_var.get():
                self.run_undo()
            else:
                self.run_normal()

        def run_normal(self):
            if self._running:
                return
            source = self.source_var.get().strip()
            if not source:
                messagebox.showerror("Error", "Please select a source folder")
                return

            config = self.config_var.get().strip()
            if not config:
                messagebox.showerror("Error", "Please select a config file")
                return

            self._running = True
            self._run_button.config(state=tk.DISABLED)
            self.status_var.set("Running...")
            self.log(f"=== File Organizer {'DRY RUN' if self.dry_run_var.get() else 'LIVE RUN'} ===")
            self.log(f"Source: {source}")
            self.log(f"Config: {config}")

            # Run in thread to keep UI responsive
            import threading
            thread = threading.Thread(target=self._run_organizer_thread, args=(source, config))
            thread.daemon = True
            thread.start()

        def _run_organizer_thread(self, source, config):
            try:
                # Import here to avoid circular imports
                import sys
                sys.path.insert(0, str(Path(__file__).parent))
                from main import run_organizer, load_config, setup_logging, expand_path

                config_path = Path(config).expanduser().resolve()
                cfg = load_config(config_path)
                source_path = expand_path(source)
                log_file = Path("organizer_log.txt").resolve()

                # Capture logger output
                class GUILogger:
                    def __init__(self, gui):
                        self.gui = gui
                    def info(self, msg):
                        self.gui.root.after(0, lambda: self.gui.log(msg))
                    def error(self, msg):
                        self.gui.root.after(0, lambda: self.gui.log(f"ERROR: {msg}"))
                    def warning(self, msg):
                        self.gui.root.after(0, lambda: self.gui.log(f"WARNING: {msg}"))

                logger = GUILogger(self)

                moved, skipped = run_organizer(
                    source_path, cfg, logger,
                    self.dry_run_var.get(),
                    self.interactive_var.get(),
                    config_path,
                    self.ai_var.get()
                )

                self.root.after(0, lambda: self._run_complete(moved, skipped))
            except Exception as e:
                self.root.after(0, lambda: self._run_error(str(e)))

        def _run_complete(self, moved, skipped):
            self._running = False
            self._run_button.config(state=tk.NORMAL)
            self.status_var.set("Done")
            self.log(f"Done. Moved: {moved}, Skipped/No-match: {skipped}")
            if self.dry_run_var.get():
                self.log("This was a dry run. No files were moved. Uncheck 'Dry Run' to execute.")

        def _run_error(self, error):
            self._running = False
            self._run_button.config(state=tk.NORMAL)
            self.status_var.set("Error")
            self.log(f"ERROR: {error}")
            messagebox.showerror("Error", error)

        def run_undo(self):
            config = self.config_var.get().strip()
            if not config:
                messagebox.showerror("Error", "Please select a config file")
                return

            self.status_var.set("Undoing...")
            self.log("=== File Organizer UNDO ===")
            self.log(f"Config: {config}")

            import threading
            thread = threading.Thread(target=self._run_undo_thread, args=(config,))
            thread.daemon = True
            thread.start()

        def _run_undo_thread(self, config):
            try:
                import sys
                sys.path.insert(0, str(Path(__file__).parent))
                from main import undo_organizer, load_config
                from pathlib import Path

                config_path = Path(config).expanduser().resolve()
                cfg = load_config(config_path)
                log_file = Path("organizer_log.txt").resolve()

                class GUILogger:
                    def __init__(self, gui):
                        self.gui = gui
                    def info(self, msg):
                        self.gui.root.after(0, lambda: self.gui.log(msg))
                    def error(self, msg):
                        self.gui.root.after(0, lambda: self.gui.log(f"ERROR: {msg}"))
                    def warning(self, msg):
                        self.gui.root.after(0, lambda: self.gui.log(f"WARNING: {msg}"))

                logger = GUILogger(self)

                undone, failed = undo_organizer(log_file, logger, self.dry_run_var.get())

                self.root.after(0, lambda: self._undo_complete(undone, failed))
            except Exception as e:
                self.root.after(0, lambda: self._run_error(str(e)))

        def _undo_complete(self, undone, failed):
            self.status_var.set("Done")
            self.log(f"Done. Undone: {undone}, Failed: {failed}")
            if self.dry_run_var.get():
                self.log("This was a dry run. No files were moved. Uncheck 'Dry Run' to execute.")

        def view_log(self):
            log_file = Path("organizer_log.txt").resolve()
            if log_file.exists():
                import subprocess
                import sys
                if sys.platform == "win32":
                    os.startfile(log_file)
                elif sys.platform == "darwin":
                    subprocess.run(["open", log_file])
                else:
                    subprocess.run(["xdg-open", log_file])
            else:
                messagebox.showinfo("Log", "No log file found yet. Run the organizer first.")

        def open_config(self):
            config = self.config_var.get().strip()
            if config:
                config_path = Path(config).expanduser().resolve()
                if config_path.exists():
                    import subprocess
                    import sys
                    if sys.platform == "win32":
                        os.startfile(config_path)
                    elif sys.platform == "darwin":
                        subprocess.run(["open", config_path])
                    else:
                        subprocess.run(["xdg-open", config_path])
                else:
                    messagebox.showinfo("Config", f"Config file not found: {config_path}")
            else:
                messagebox.showinfo("Config", "No config file specified")

    root = tk.Tk()
    app = OrganizerGUI(root)
    root.mainloop()
    return 0


def main() -> int:
    """Main entry point."""
    # Auto-launch GUI when frozen (double-clicked) with no args
    if hasattr(sys, '_MEIPASS') and len(sys.argv) == 1:
        return run_gui()

    args = parse_args()

    # Handle GUI command
    if args.gui:
        return run_gui()

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
        args.interactive, config_path, args.ai_categorize
    )

    logger.info(f"Done. Moved: {moved}, Skipped/No-match: {skipped}")

    if args.dry_run:
        logger.info("This was a dry run. No files were moved. Run without --dry-run to execute.")

    return 0


if __name__ == "__main__":
    # Required for PyInstaller --windowed on Windows
    import multiprocessing
    multiprocessing.freeze_support()
    sys.exit(main())