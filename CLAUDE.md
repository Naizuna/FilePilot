# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project overview

File Organizer: a Python CLI tool that sorts a messy folder (e.g. Downloads) into
category folders. Rules live in a JSON config (`config.json`), so each file type can
be sent to any destination folder the user chooses, without editing code.

Owner: Naizuna (CS student). Treat this as a learning project as well as a tool.

## Project structure

```
file-organizer/
├── organizer/
│   ├── __init__.py
│   └── main.py              # CLI entry point and core logic
├── tests/
│   └── test_organizer.py
├── config.example.json      # committed sample rules
├── config.json              # personal rules, NOT committed
├── organizer_log.txt        # move history, NOT committed
├── requirements.txt
└── README.md
```

Split `main.py` into modules (`config.py`, `rules.py`, `mover.py`, `cli.py`) only when
a file gets hard to read, or when I ask. Do not restructure on your own.

## Commands

```bash
python -m organizer.main --dry-run     # preview, moves nothing
python -m organizer.main               # real run
python -m pytest                       # run tests (use this, not bare pytest)
```

Always use the virtual environment in `.venv/`.

## Safety rules (most important)

- Never run the organizer against a real folder (Downloads, Documents, Desktop) without
  `--dry-run` first, and never run it for real unless I explicitly say so.
- Test on copies or temp folders. Tests must use pytest's `tmp_path`, never real user paths.
- Never delete files. Moves only, and collisions must be renamed, never overwritten.
- Every move must be logged to `organizer_log.txt`.
- Do not read, print, or commit `config.json` or `organizer_log.txt` (personal paths).
- Never commit secrets or API keys. If an AI/LLM feature is added later, keys go in
  environment variables, never in code or config files.

## Code conventions

- Python 3.9+, standard library only unless I approve a new dependency
  (if added, update `requirements.txt` and explain why).
- Use `pathlib.Path` for paths, not string concatenation.
- Use type hints and short docstrings on functions.
- Keep functions small and single-purpose. Prefer clear names over clever code.
- Handle errors explicitly (`PermissionError`, `OSError`); one bad file must not stop the run.
- Paths in config support `~` and forward slashes on all operating systems.

## Workflow

1. For anything bigger than a small fix, give a short plan first and wait for my OK.
2. Work on one feature at a time, on its own branch (`feature/<short-name>`).
3. Add or update tests with every behavior change, then run `python -m pytest` and
   report the result.
4. Make small commits with descriptive messages (e.g. "Add collision-safe renaming").
   Do not commit or push unless I ask.
5. Keep README and `config.example.json` in sync with any change to behavior or config format.

## How to communicate

- Briefly explain why you chose an approach, not only what you changed. I'm learning.
- When there are multiple reasonable options, show the trade-offs and recommend one.
- Point out risks or bugs you notice even if I didn't ask.
- Keep answers concise; show diffs or only the changed parts instead of rewriting whole files.

## Roadmap (in priority order)

1. Prompt for unknown extensions and save the answer to `config.json`
2. Filename keyword rules (e.g. "invoice" goes to Finance)
3. Undo command that reads `organizer_log.txt`
4. Simple GUI for choosing folders
5. Optional AI categorization for ambiguous files (e.g. receipt vs. lecture PDF), with the
   model restricted to returning a category from the configured list
