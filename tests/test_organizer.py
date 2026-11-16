"""Tests for the file organizer."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Import the module functions
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "organizer"))

from main import (
    build_extension_map,
    expand_path,
    get_unique_destination,
    load_config,
    organize_file,
    run_organizer,
    save_config,
    should_skip,
)


class TestExpandPath:
    def test_expand_tilde(self):
        result = expand_path("~/Documents")
        assert result.is_absolute()
        assert "Documents" in str(result)

    def test_expand_relative(self):
        result = expand_path("./test")
        assert result.is_absolute()


class TestLoadConfig:
    def test_load_valid_config(self, tmp_path: Path):
        config = {
            "source_folder": "~/Downloads",
            "categories": {
                "Images": {"extensions": [".jpg"], "destination": "~/Pictures"}
            },
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config))

        result = load_config(config_file)
        # User config should be present
        assert result["source_folder"] == "~/Downloads"
        assert "Images" in result["categories"]
        assert result["categories"]["Images"]["extensions"] == [".jpg"]
        # Defaults should also be merged in
        assert "Documents" in result["categories"]

    def test_load_missing_config_returns_defaults(self, tmp_path: Path):
        # Missing config should return defaults, not raise
        result = load_config(tmp_path / "nonexistent.json")
        assert "categories" in result
        assert "Images" in result["categories"]  # from defaults

    def test_load_invalid_json(self, tmp_path: Path):
        config_file = tmp_path / "bad.json"
        config_file.write_text("{ invalid }")
        with pytest.raises(SystemExit) as exc:
            load_config(config_file)
        assert exc.value.code != 0


class TestSaveConfig:
    def test_save_config(self, tmp_path: Path):
        config = {"categories": {"Test": {"extensions": [".txt"], "destination": "/dest"}}}
        config_file = tmp_path / "config.json"
        save_config(config_file, config)

        with config_file.open() as f:
            saved = json.load(f)
        assert saved == config

    def test_save_config_creates_parent_dirs(self, tmp_path: Path):
        config = {"test": "value"}
        config_file = tmp_path / "subdir" / "config.json"
        save_config(config_file, config)
        assert config_file.exists()


class TestBuildExtensionMap:
    def test_basic_mapping(self, tmp_path: Path):
        dest_img = tmp_path / "dest" / "img"
        dest_docs = tmp_path / "dest" / "docs"
        categories = {
            "Images": {"extensions": [".jpg", ".png"], "destination": str(dest_img)},
            "Docs": {"extensions": [".pdf"], "destination": str(dest_docs)},
        }
        ext_map = build_extension_map(categories)

        assert ext_map[".jpg"] == ("Images", dest_img.resolve())
        assert ext_map[".png"] == ("Images", dest_img.resolve())
        assert ext_map[".pdf"] == ("Docs", dest_docs.resolve())

    def test_case_insensitive(self, tmp_path: Path):
        dest = tmp_path / "dest"
        categories = {"Images": {"extensions": [".JPG", ".Png"], "destination": str(dest)}}
        ext_map = build_extension_map(categories)

        assert ".jpg" in ext_map
        assert ".png" in ext_map


class TestShouldSkip:
    def test_skip_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "subdir"
            folder.mkdir()
            assert should_skip(folder, [], True) is True

    def test_skip_extension(self):
        with tempfile.NamedTemporaryFile(suffix=".crdownload", delete=False) as f:
            path = Path(f.name)
        try:
            assert should_skip(path, [".crdownload"], False) is True
        finally:
            path.unlink(missing_ok=True)

    def test_dont_skip_normal_file(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            path = Path(f.name)
        try:
            assert should_skip(path, [".crdownload"], True) is False
        finally:
            path.unlink(missing_ok=True)


class TestGetUniqueDestination:
    def test_no_collision(self, tmp_path: Path):
        dest = get_unique_destination(tmp_path, "newfile.txt")
        assert dest == tmp_path / "newfile.txt"

    def test_collision_renames(self, tmp_path: Path):
        (tmp_path / "file.txt").write_text("original")
        dest = get_unique_destination(tmp_path, "file.txt")
        assert dest == tmp_path / "file (1).txt"

    def test_multiple_collisions(self, tmp_path: Path):
        (tmp_path / "file.txt").write_text("1")
        (tmp_path / "file (1).txt").write_text("2")
        dest = get_unique_destination(tmp_path, "file.txt")
        assert dest == tmp_path / "file (2).txt"


class TestOrganizeFile:
    def test_moves_matching_file(self, tmp_path: Path):
        source = tmp_path / "source"
        source.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()

        test_file = source / "photo.jpg"
        test_file.write_text("fake image")

        ext_map = {".jpg": ("Images", dest)}
        logger = type("MockLogger", (), {"info": lambda *a: None, "error": lambda *a: None})()

        result = organize_file(test_file, ext_map, logger, dry_run=False)
        assert result is True
        assert not test_file.exists()
        assert (dest / "photo.jpg").exists()

    def test_dry_run_does_not_move(self, tmp_path: Path):
        source = tmp_path / "source"
        source.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()

        test_file = source / "photo.jpg"
        test_file.write_text("fake image")

        ext_map = {".jpg": ("Images", dest)}
        logger = type("MockLogger", (), {"info": lambda *a: None, "error": lambda *a: None})()

        result = organize_file(test_file, ext_map, logger, dry_run=True)
        assert result is True
        assert test_file.exists()
        assert not (dest / "photo.jpg").exists()

    def test_skips_unknown_extension(self, tmp_path: Path):
        source = tmp_path / "source"
        source.mkdir()

        test_file = source / "unknown.xyz"
        test_file.write_text("data")

        ext_map = {".jpg": ("Images", tmp_path / "dest")}
        logger = type("MockLogger", (), {"info": lambda *a: None, "error": lambda *a: None})()

        result = organize_file(test_file, ext_map, logger, dry_run=False)
        assert result is False
        assert test_file.exists()

    def test_handles_permission_error(self, tmp_path: Path):
        source = tmp_path / "source"
        source.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()

        test_file = source / "photo.jpg"
        test_file.write_text("fake image")

        if sys.platform == "win32":
            import stat
            dest.chmod(stat.S_IREAD)

        ext_map = {".jpg": ("Images", dest)}
        logger = type("MockLogger", (), {"info": lambda *a: None, "error": lambda *a: None})()

        result = organize_file(test_file, ext_map, logger, dry_run=False)
        assert isinstance(result, bool)

    def test_interactive_adds_to_existing_category(self, tmp_path: Path):
        """Test that interactive mode prompts and adds extension to existing category."""
        source = tmp_path / "source"
        source.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()

        test_file = source / "document.xyz"
        test_file.write_text("data")

        categories = {
            "Documents": {"extensions": [".pdf"], "destination": str(dest)}
        }
        config_path = tmp_path / "config.json"

        ext_map = {".pdf": ("Documents", dest)}
        logger = type("MockLogger", (), {"info": lambda *a: None, "error": lambda *a: None})()

        # Mock user input: choose option 1 (existing category "Documents")
        with patch("builtins.input", side_effect=["1"]):
            result = organize_file(
                test_file, ext_map, logger, dry_run=False,
                interactive=True, categories=categories, config_path=config_path
            )

        assert result is True
        assert not test_file.exists()
        assert (dest / "document.xyz").exists()
        # Check config was updated
        assert ".xyz" in categories["Documents"]["extensions"]

    def test_interactive_creates_new_category(self, tmp_path: Path):
        """Test that interactive mode can create a new category."""
        source = tmp_path / "source"
        source.mkdir()
        dest_existing = tmp_path / "dest"
        dest_existing.mkdir()
        dest_new = tmp_path / "newcat"
        dest_new.mkdir()

        test_file = source / "file.xyz"
        test_file.write_text("data")

        categories = {
            "Documents": {"extensions": [".pdf"], "destination": str(dest_existing)}
        }
        config_path = tmp_path / "config.json"

        ext_map = {".pdf": ("Documents", dest_existing)}
        logger = type("MockLogger", (), {"info": lambda *a: None, "error": lambda *a: None})()

        # Mock user input: choose option 2 (create new), then name "Custom", then destination
        with patch("builtins.input", side_effect=["2", "Custom", str(dest_new)]):
            result = organize_file(
                test_file, ext_map, logger, dry_run=False,
                interactive=True, categories=categories, config_path=config_path
            )

        assert result is True
        assert not test_file.exists()
        assert (dest_new / "file.xyz").exists()
        # Check new category was created
        assert "Custom" in categories
        assert ".xyz" in categories["Custom"]["extensions"]
        assert categories["Custom"]["destination"] == str(dest_new)

    def test_interactive_skip_extension(self, tmp_path: Path):
        """Test that interactive mode can skip an extension."""
        source = tmp_path / "source"
        source.mkdir()

        test_file = source / "file.xyz"
        test_file.write_text("data")

        categories = {
            "Documents": {"extensions": [".pdf"], "destination": str(tmp_path / "dest")}
        }
        config_path = tmp_path / "config.json"

        ext_map = {".pdf": ("Documents", tmp_path / "dest")}
        logger = type("MockLogger", (), {"info": lambda *a: None, "error": lambda *a: None})()

        # Mock user input: choose option 0 (skip)
        with patch("builtins.input", side_effect=["0"]):
            result = organize_file(
                test_file, ext_map, logger, dry_run=False,
                interactive=True, categories=categories, config_path=config_path
            )

        assert result is False
        assert test_file.exists()
        # Check extension was added to skip list
        assert "_skip_extensions" in categories
        assert ".xyz" in categories["_skip_extensions"]


class TestRunOrganizer:
    def test_organizes_multiple_files(self, tmp_path: Path):
        source = tmp_path / "source"
        source.mkdir()
        dest_img = tmp_path / "dest" / "Images"
        dest_doc = tmp_path / "dest" / "Documents"

        (source / "photo.jpg").write_text("img")
        (source / "doc.pdf").write_text("pdf")
        (source / "readme.txt").write_text("txt")

        config = {
            "categories": {
                "Images": {"extensions": [".jpg"], "destination": str(dest_img)},
                "Documents": {"extensions": [".pdf", ".txt"], "destination": str(dest_doc)},
            },
            "skip_extensions": [],
            "skip_folders": True,
        }

        logger = type("MockLogger", (), {"info": lambda *a: None, "error": lambda *a: None})()

        moved, skipped = run_organizer(source, config, logger, dry_run=False)
        assert moved == 3
        assert skipped == 0
        assert (dest_img / "photo.jpg").exists()
        assert (dest_doc / "doc.pdf").exists()
        assert (dest_doc / "readme.txt").exists()

    def test_skips_folders_when_enabled(self, tmp_path: Path):
        source = tmp_path / "source"
        source.mkdir()
        (source / "subfolder").mkdir()
        (source / "file.txt").write_text("txt")

        config = {
            "categories": {"Documents": {"extensions": [".txt"], "destination": str(tmp_path / "dest")}},
            "skip_extensions": [],
            "skip_folders": True,
        }

        logger = type("MockLogger", (), {"info": lambda *a: None, "error": lambda *a: None})()

        moved, skipped = run_organizer(source, config, logger, dry_run=False)
        assert moved == 1
        assert skipped == 1

    def test_skips_extensions_in_skip_list(self, tmp_path: Path):
        source = tmp_path / "source"
        source.mkdir()
        (source / "file.crdownload").write_text("partial")
        (source / "file.txt").write_text("txt")

        config = {
            "categories": {"Documents": {"extensions": [".txt"], "destination": str(tmp_path / "dest")}},
            "skip_extensions": [".crdownload"],
            "skip_folders": True,
        }

        logger = type("MockLogger", (), {"info": lambda *a: None, "error": lambda *a: None})()

        moved, skipped = run_organizer(source, config, logger, dry_run=False)
        assert moved == 1
        assert skipped == 1

    def test_handles_missing_source(self, tmp_path: Path):
        config = {
            "categories": {"Documents": {"extensions": [".txt"], "destination": str(tmp_path / "dest")}},
            "skip_extensions": [],
            "skip_folders": True,
        }

        logger = type("MockLogger", (), {"info": lambda *a: None, "error": lambda *a: None})()

        moved, skipped = run_organizer(tmp_path / "nonexistent", config, logger, dry_run=False)
        assert moved == 0
        assert skipped == 0

    def test_interactive_mode_processes_unknown_extensions(self, tmp_path: Path):
        """Test run_organizer in interactive mode with unknown extensions."""
        source = tmp_path / "source"
        source.mkdir()
        dest = tmp_path / "dest"
        dest.mkdir()

        (source / "known.pdf").write_text("pdf")
        (source / "unknown.xyz").write_text("xyz")

        config = {
            "categories": {
                "Documents": {"extensions": [".pdf"], "destination": str(dest)}
            },
            "skip_extensions": [],
            "skip_folders": True,
        }
        config_path = tmp_path / "config.json"

        logger = type("MockLogger", (), {"info": lambda *a: None, "error": lambda *a: None})()

        # Mock user choosing to add .xyz to Documents
        with patch("builtins.input", side_effect=["1"]):
            moved, skipped = run_organizer(
                source, config, logger, dry_run=False,
                interactive=True, config_path=config_path
            )

        assert moved == 2
        assert skipped == 0
        assert (dest / "known.pdf").exists()
        assert (dest / "unknown.xyz").exists()
        assert ".xyz" in config["categories"]["Documents"]["extensions"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])