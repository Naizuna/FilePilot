# File Organizer

A Python tool that sorts a messy folder (like Downloads) into categorized folders. Rules and destinations live in a JSON config, so you can send each file type to any folder you want, even on another drive, without touching the code.

## Features

- **Config-driven rules** — category, extensions, and destination folder
- **Dry-run mode** — preview every move before anything changes
- **Collision-safe renaming** — `report.pdf` becomes `report (1).pdf` instead of overwriting
- **Skips folders and unfinished downloads** — `.crdownload`, `.part`, `.tmp`, `.download`
- **Logs every move** — timestamped entries in `organizer_log.txt`
- **Cross-platform paths** — use `~` or forward slashes on Windows, Mac, and Linux
- **Standard library only** — no external dependencies for core functionality

### Advanced Features

- **Interactive mode** (`--interactive`) — prompts for unknown extensions and saves your choice to config
- **Keyword rules** — filename keywords override extensions (e.g., "invoice" → Finance folder)
- **Undo command** (`--undo`) — reverses the last run by reading `organizer_log.txt`
- **GUI** (`--gui`) — Tkinter interface with folder pickers, options, and live output log
- **AI categorization** (`--ai-categorize`) — privacy-first:
  - **Local-first**: Ollama by default (zero data leaves your machine)
  - **PII redaction** — credit cards, SSN, emails, phones, passwords, API keys stripped before sending
  - **Cloud opt-in** — OpenAI/Anthropic via environment variables only
  - **Size & extension limits** — only processes small text-based files

## Requirements

- Python 3.9 or newer
- Standard library only (no external dependencies for core functionality)

### Optional Dependencies (for AI categorization)

```bash
pip install pymupdf python-docx
# - pymupdf (fitz): PDF text extraction
# - python-docx: DOCX text extraction
```

## Installation

```bash
git clone https://github.com/YOUR-USERNAME/file-organizer.git
cd file-organizer
python -m venv .venv

# Windows
.venv\Scripts\activate
# Mac/Linux
source .venv/bin/activate
```

## Quick Start

### GUI (Easiest)

Double-click `file-organizer-gui.exe` (in `dist/`) or run:

```bash
python -m organizer.main --gui
```

### CLI

Always preview first:

```bash
python -m organizer.main --dry-run --source "~/Downloads"
```

If the output looks right, run for real:

```bash
python -m organizer.main --source "~/Downloads"
```

### With AI Categorization

```bash
# Enable in config.json first, or use flag
python -m organizer.main --ai-categorize --source "~/Downloads"
```

### Undo Last Run

```bash
# Preview what would be undone
python -m organizer.main --undo --dry-run

# Actually undo
python -m organizer.main --undo
```

## Configuration

Copy the example config and edit it to match your folders:

```bash
cp config.example.json config.json
```

### Config Structure

```json
{
  "source_folder": "~/Downloads",
  "categories": {
    "Images": {
      "extensions": [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".heic"],
      "destination": "~/Pictures/Sorted"
    },
    "Documents": {
      "extensions": [".pdf", ".docx", ".doc", ".txt", ".md", ".rtf", ".odt"],
      "destination": "~/Documents/Sorted"
    },
    "Finance": {
      "extensions": [],
      "destination": "~/Documents/Finance"
    }
  },
  "keyword_rules": {
    "invoice": "Finance",
    "receipt": "Finance",
    "bill": "Finance",
    "lecture": "Documents",
    "screenshot": "Images",
    "photo": "Images"
  },
  "ai_categorization": {
    "enabled": false,
    "provider": "local",
    "model": "llama3.2:3b",
    "api_key_env": "OPENAI_API_KEY",
    "allowed_extensions": [".txt", ".md", ".pdf", ".docx"],
    "max_file_size_kb": 50,
    "max_chars": 5000
  },
  "skip_extensions": [".crdownload", ".part", ".tmp", ".download"],
  "skip_folders": true
}
```

### Key Concepts

| Field | Description |
|-------|-------------|
| `source_folder` | Default folder to organize (overridden by `--source`) |
| `categories` | Maps category name → extensions + destination |
| `keyword_rules` | Filename substring → category (checked before extensions) |
| `ai_categorization` | AI settings (disabled by default) |
| `skip_extensions` | Extensions to ignore (unfinished downloads) |
| `skip_folders` | Skip subdirectories |

**Paths**: Use `~` for home directory, forward slashes `/` on all OSes. Categories without extensions (like `Finance` above) work only via keyword rules or AI.

## CLI Reference

```bash
python -m organizer.main [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--source PATH` | Folder to organize (overrides config's `source_folder`) |
| `--config PATH` | Config file path (default: `config.json`) |
| `--dry-run` | Preview moves without making changes |
| `--interactive` | Prompt for unknown extensions, save to config |
| `--undo` | Reverse last run using `organizer_log.txt` |
| `--gui` | Launch graphical interface |
| `--ai-categorize` | Enable AI categorization for ambiguous files |

### Priority Order (when categorizing)

1. **Keyword rules** — explicit filename matches
2. **AI categorization** — if enabled, for ambiguous files
3. **Extension rules** — from `categories.extensions`
4. **Interactive prompt** — if `--interactive`, asks user

## Pre-built Executables

In `dist/` after building:

| File | Description |
|------|-------------|
| `file-organizer.exe` | CLI version |
| `file-organizer-gui.exe` | GUI (double-click to open) |

### Build Your Own

```bash
pip install pyinstaller

# CLI
pyinstaller --onefile --name file-organizer --add-data "config.example.json;." organizer/main.py

# GUI (double-click opens interface)
pyinstaller --onefile --windowed --name file-organizer-gui \
  --add-data "config.example.json;." \
  --hidden-import=fitz --hidden-import=docx \
  --hidden-import=tkinter --hidden-import=tkinter.ttk \
  --hidden-import=tkinter.filedialog --hidden-import=tkinter.messagebox \
  organizer/main.py
```

## Running Tests

```bash
pip install pytest
python -m pytest
```

40 tests covering: config loading, extension mapping, collision handling, keyword rules, interactive mode, undo, and AI categorization.

## Safety Tips

- **Always use `--dry-run` first** — preview before committing
- **Test on a copy** — try on a duplicate folder before real files
- **Check the log** — `organizer_log.txt` shows exactly what moved where
- **Undo if needed** — `--undo` reverses the last run
- **Never run on system folders** — Documents, Pictures, etc. are destinations, not sources

## AI Categorization — Privacy First

| Safeguard | Description |
|-----------|-------------|
| **Disabled by default** | Must explicitly enable in config or use `--ai-categorize` |
| **Local-first** | Default provider: `local` (Ollama) — no data leaves machine |
| **PII redaction** | Strips credit cards, SSN, emails, phones, passwords, API keys |
| **File limits** | Max 50 KB, only `.txt`, `.md`, `.pdf`, `.docx` by default |
| **Content truncation** | First 5000 characters only |
| **API keys from env** | Never in config — `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` |
| **Explicit logging** | Logs when AI used, provider, and returned category |

### Enable Cloud AI (Opt-in)

```json
"ai_categorization": {
  "enabled": true,
  "provider": "openai",
  "model": "gpt-4o-mini",
  "api_key_env": "OPENAI_API_KEY"
}
```

Then set environment variable:
```bash
# Windows
set OPENAI_API_KEY=your-key
# Mac/Linux
export OPENAI_API_KEY=your-key
```

## Roadmap — All Complete ✅

- [x] Prompt for unknown extensions and save to config
- [x] Filename keyword rules (e.g. "invoice" → Finance)
- [x] Undo command based on the log
- [x] Simple GUI for choosing folders
- [x] Optional AI categorization for ambiguous files

## License

MIT