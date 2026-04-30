"""Tests for config management: init, config get/set/add/remove, _find_config."""

from __future__ import annotations

import pathlib
from pathlib import Path

import pytest
import toml
from typer.testing import CliRunner

from keppi.cli.main import app
from keppi.parser.config import _find_config

runner = CliRunner()


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """Redirect Path.home() to a temp directory so tests never touch ~/.keppi."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: home))
    return home


@pytest.fixture
def vault(tmp_path):
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    return vault_dir


class TestFindConfig:
    def test_home_config_takes_priority(self, fake_home, vault):
        """~/.keppi/keppi.toml is returned before a vault-root keppi.toml."""
        home_cfg = fake_home / ".keppi" / "keppi.toml"
        home_cfg.parent.mkdir(parents=True)
        home_cfg.write_text("[vault]\npath = '/home-vault'\n")
        (vault / "keppi.toml").write_text("[vault]\npath = '/vault-root'\n")

        assert _find_config(vault) == home_cfg

    def test_falls_back_to_vault_walk(self, fake_home, vault):
        """Falls back to vault-root keppi.toml when no home config exists."""
        vault_cfg = vault / "keppi.toml"
        vault_cfg.write_text("[vault]\npath = '.'\n")

        assert _find_config(vault) == vault_cfg

    def test_walks_up_from_subdir(self, fake_home, vault):
        """Walks up from a subdirectory to find the vault-root config."""
        (vault / "keppi.toml").write_text("[vault]\npath = '.'\n")
        subdir = vault / "notes" / "deep"
        subdir.mkdir(parents=True)

        assert _find_config(subdir) == vault / "keppi.toml"

    def test_returns_none_when_not_found(self, fake_home, tmp_path):
        """Returns None when no config exists at home or in the directory tree."""
        empty = tmp_path / "empty"
        empty.mkdir()
        assert _find_config(empty) is None


class TestInit:
    def test_creates_home_config(self, fake_home, vault):
        result = runner.invoke(app, ["init", str(vault), "--quick"])
        assert result.exit_code == 0, result.output
        assert (fake_home / ".keppi" / "keppi.toml").exists()

    def test_sets_vault_path_absolute(self, fake_home, vault):
        runner.invoke(app, ["init", str(vault), "--quick"])
        raw = toml.loads((fake_home / ".keppi" / "keppi.toml").read_text())
        assert raw["vault"]["path"] == str(vault.resolve())

    def test_does_not_write_to_vault_root(self, fake_home, vault):
        runner.invoke(app, ["init", str(vault), "--quick"])
        assert not (vault / "keppi.toml").exists()

    def test_quick_overwrites_without_prompt(self, fake_home, vault):
        config_file = fake_home / ".keppi" / "keppi.toml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("[vault]\npath = '/old'\n")

        result = runner.invoke(app, ["init", str(vault), "--quick"])
        assert result.exit_code == 0
        raw = toml.loads(config_file.read_text())
        assert raw["vault"]["path"] == str(vault.resolve())

    def test_migrates_old_vault_config(self, fake_home, vault):
        """When user confirms migration, old vault-root config content is preserved."""
        (vault / "keppi.toml").write_text(
            "[vault]\npath = '.'\n[graph]\ndefault_depth = 7\n"
        )

        result = runner.invoke(app, ["init", str(vault)], input="y\n")
        assert result.exit_code == 0, result.output
        raw = toml.loads((fake_home / ".keppi" / "keppi.toml").read_text())
        assert raw["graph"]["default_depth"] == 7
        assert raw["vault"]["path"] == str(vault.resolve())

    def test_no_migrate_when_declined(self, fake_home, vault):
        """When user declines migration, default config is written instead."""
        (vault / "keppi.toml").write_text("[vault]\npath = '.'\n[graph]\ndefault_depth = 7\n")

        # "n" to migrate, then "n" to overwrite (config doesn't exist yet — just confirm migration=no)
        result = runner.invoke(app, ["init", str(vault)], input="n\n")
        assert result.exit_code == 0
        raw = toml.loads((fake_home / ".keppi" / "keppi.toml").read_text())
        # default_depth should be 2 (the default), not 7 from the old config
        assert raw["graph"]["default_depth"] == 2


def _setup_home_config(fake_home: Path, content: str) -> Path:
    cfg = fake_home / ".keppi" / "keppi.toml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(content)
    return cfg


class TestConfigGet:
    def test_get_scalar(self, fake_home):
        _setup_home_config(fake_home, "[graph]\ndefault_depth = 3\n")
        result = runner.invoke(app, ["config", "get", "graph.default_depth"])
        assert result.exit_code == 0
        assert "3" in result.output

    def test_get_list(self, fake_home):
        _setup_home_config(fake_home, '[vault]\nexclude_dirs = [".obsidian", ".git"]\n')
        result = runner.invoke(app, ["config", "get", "vault.exclude_dirs"])
        assert result.exit_code == 0
        assert ".obsidian" in result.output

    def test_get_full_config(self, fake_home):
        _setup_home_config(fake_home, "[graph]\ndefault_depth = 2\n")
        result = runner.invoke(app, ["config", "get"])
        assert result.exit_code == 0
        assert "default_depth" in result.output

    def test_get_missing_key_exits_nonzero(self, fake_home):
        _setup_home_config(fake_home, "[graph]\ndefault_depth = 2\n")
        result = runner.invoke(app, ["config", "get", "vault.nonexistent_key"])
        assert result.exit_code != 0

    def test_get_no_config_exits_nonzero(self, fake_home):
        result = runner.invoke(app, ["config", "get", "graph.default_depth"])
        assert result.exit_code != 0
        assert "keppi init" in result.output


class TestConfigSet:
    def test_set_integer(self, fake_home):
        cfg = _setup_home_config(fake_home, "[graph]\ndefault_depth = 2\n")
        result = runner.invoke(app, ["config", "set", "graph.default_depth", "5"])
        assert result.exit_code == 0
        assert toml.loads(cfg.read_text())["graph"]["default_depth"] == 5

    def test_set_float(self, fake_home):
        cfg = _setup_home_config(fake_home, "[graph]\nrelevance_threshold = 0.3\n")
        runner.invoke(app, ["config", "set", "graph.relevance_threshold", "0.5"])
        assert toml.loads(cfg.read_text())["graph"]["relevance_threshold"] == pytest.approx(0.5)

    def test_set_list(self, fake_home):
        cfg = _setup_home_config(fake_home, '[vault]\nexclude_dirs = [".obsidian"]\n')
        runner.invoke(app, ["config", "set", "vault.exclude_dirs", '[".obsidian", ".git"]'])
        assert ".git" in toml.loads(cfg.read_text())["vault"]["exclude_dirs"]

    def test_set_no_config_exits_nonzero(self, fake_home):
        result = runner.invoke(app, ["config", "set", "graph.default_depth", "5"])
        assert result.exit_code != 0


class TestConfigAdd:
    def test_add_to_list(self, fake_home):
        cfg = _setup_home_config(fake_home, '[vault]\nexclude_dirs = [".obsidian"]\n')
        result = runner.invoke(app, ["config", "add", "vault.exclude_dirs", "attachments"])
        assert result.exit_code == 0
        assert "attachments" in toml.loads(cfg.read_text())["vault"]["exclude_dirs"]

    def test_add_no_duplicate(self, fake_home):
        cfg = _setup_home_config(fake_home, '[vault]\nexclude_dirs = [".obsidian"]\n')
        runner.invoke(app, ["config", "add", "vault.exclude_dirs", ".obsidian"])
        dirs = toml.loads(cfg.read_text())["vault"]["exclude_dirs"]
        assert dirs.count(".obsidian") == 1

    def test_add_to_non_list_exits_nonzero(self, fake_home):
        _setup_home_config(fake_home, "[graph]\ndefault_depth = 2\n")
        result = runner.invoke(app, ["config", "add", "graph.default_depth", "5"])
        assert result.exit_code != 0

    def test_add_no_config_exits_nonzero(self, fake_home):
        result = runner.invoke(app, ["config", "add", "vault.exclude_dirs", "foo"])
        assert result.exit_code != 0


class TestConfigRemove:
    def test_remove_from_list(self, fake_home):
        cfg = _setup_home_config(fake_home, '[vault]\nexclude_dirs = [".obsidian", "templates"]\n')
        result = runner.invoke(app, ["config", "remove", "vault.exclude_dirs", "templates"])
        assert result.exit_code == 0
        dirs = toml.loads(cfg.read_text())["vault"]["exclude_dirs"]
        assert "templates" not in dirs
        assert ".obsidian" in dirs

    def test_remove_nonexistent_value_is_idempotent(self, fake_home):
        _setup_home_config(fake_home, '[vault]\nexclude_dirs = [".obsidian"]\n')
        result = runner.invoke(app, ["config", "remove", "vault.exclude_dirs", "nonexistent"])
        assert result.exit_code == 0

    def test_remove_non_list_exits_nonzero(self, fake_home):
        _setup_home_config(fake_home, "[graph]\ndefault_depth = 2\n")
        result = runner.invoke(app, ["config", "remove", "graph.default_depth", "2"])
        assert result.exit_code != 0

    def test_remove_no_config_exits_nonzero(self, fake_home):
        result = runner.invoke(app, ["config", "remove", "vault.exclude_dirs", "foo"])
        assert result.exit_code != 0
