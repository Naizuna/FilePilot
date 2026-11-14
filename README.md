# File Organizer

A small Python tool that sorts a messy folder (like Downloads) into categorized folders. Rules and destinations live in a JSON config, so you can send each file type to any folder you want, even on another drive, without touching the code.

## Features

- Config-driven rules: category, extensions, and destination folder
- Dry-run mode to preview every move before anything changes
- Collision-safe renaming (`report.pdf` becomes `report (1).pdf` instead of overwriting)
- Skips folders and unfinished downloads (`.crdownload`, `.part`, `.tmp`)
- Logs every move to `organizer_log.txt`
- Standard library only, no dependencies

## Requirements

- Python 3.9 or newer

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

## Setup

Copy the example config and edit it to match your folders:

```bash
cp config.example.json config.json
```

Example rule:

```json
"Documents": {
  "extensions": [".pdf", ".docx", ".txt"],
  "destination": "D:/School/Docs"
}
```

Use forward slashes (or `~` for your home folder) on every operating system.

## Usage

Always preview first:

```bash
python -m organizer.main --dry-run
```

If the output looks right, run it for real:

```bash
python -m organizer.main
```

Other options:

```bash
python -m organizer.main --source "D:/Messy" --config my_rules.json
```

| Option | Description |
| --- | --- |
| `--source` | Folder to organize (overrides the config) |
| `--config` | Path to a rules file (default: `config.json`) |
| `--dry-run` | Print planned moves without moving anything |

## Running the tests

```bash
pip install pytest
python -m pytest
```

## Safety tips

- Try it on a copy of a folder before pointing it at your real files.
- Check `organizer_log.txt` to see exactly what was moved and where.

## Roadmap

- [ ] Prompt for unknown extensions and save the answer to the config
- [ ] Filename keyword rules (e.g. "invoice" goes to Finance)
- [ ] Undo command based on the log
- [ ] Simple GUI for choosing folders
- [ ] Optional AI categorization for ambiguous files

## License

MIT
