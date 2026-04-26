"""Unit tests for shared.secrets.load_host_secrets.

Pure-Python — uses tmp_path for the bind-mounted file substitute and
monkeypatch for the os.environ side effects.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from shared.secrets import DEFAULT_OSCAR_ENV_PATH, load_host_secrets


class TestLoadHostSecrets:
    def test_reads_simple_key_value_pairs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OSCAR_TEST_FOO", raising=False)
        monkeypatch.delenv("OSCAR_TEST_BAR", raising=False)
        env_file = tmp_path / "oscar.env"
        env_file.write_text("OSCAR_TEST_FOO=value-foo\nOSCAR_TEST_BAR=value-bar\n")

        loaded = load_host_secrets(path=env_file)

        assert loaded == 2
        assert os.environ["OSCAR_TEST_FOO"] == "value-foo"
        assert os.environ["OSCAR_TEST_BAR"] == "value-bar"

    def test_skips_blank_lines_and_comments(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OSCAR_TEST_FOO", raising=False)
        env_file = tmp_path / "oscar.env"
        env_file.write_text(
            "\n"
            "# top-level comment\n"
            "  # indented comment\n"
            "OSCAR_TEST_FOO=foo\n"
            "\n"
        )

        loaded = load_host_secrets(path=env_file)

        assert loaded == 1
        assert os.environ["OSCAR_TEST_FOO"] == "foo"

    def test_strips_quotes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OSCAR_TEST_DOUBLE", raising=False)
        monkeypatch.delenv("OSCAR_TEST_SINGLE", raising=False)
        monkeypatch.delenv("OSCAR_TEST_BARE", raising=False)
        env_file = tmp_path / "oscar.env"
        env_file.write_text(
            'OSCAR_TEST_DOUBLE="quoted"\n'
            "OSCAR_TEST_SINGLE='quoted'\n"
            "OSCAR_TEST_BARE=unquoted\n"
        )

        load_host_secrets(path=env_file)

        assert os.environ["OSCAR_TEST_DOUBLE"] == "quoted"
        assert os.environ["OSCAR_TEST_SINGLE"] == "quoted"
        assert os.environ["OSCAR_TEST_BARE"] == "unquoted"

    def test_default_does_not_override_existing_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Developer-local OSCAR_* (e.g. shell export) wins by default."""
        monkeypatch.setenv("OSCAR_TEST_FOO", "preset-from-shell")
        env_file = tmp_path / "oscar.env"
        env_file.write_text("OSCAR_TEST_FOO=value-from-host-file\n")

        load_host_secrets(path=env_file)

        assert os.environ["OSCAR_TEST_FOO"] == "preset-from-shell"

    def test_override_true_replaces_existing_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OSCAR_TEST_FOO", "preset")
        env_file = tmp_path / "oscar.env"
        env_file.write_text("OSCAR_TEST_FOO=replaced\n")

        load_host_secrets(path=env_file, override=True)

        assert os.environ["OSCAR_TEST_FOO"] == "replaced"

    def test_missing_file_raises_with_actionable_message(
        self, tmp_path: Path
    ) -> None:
        missing = tmp_path / "does-not-exist.env"
        with pytest.raises(FileNotFoundError, match="ADR 025"):
            load_host_secrets(path=missing)

    def test_malformed_line_logged_and_skipped(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.delenv("OSCAR_TEST_FOO", raising=False)
        env_file = tmp_path / "oscar.env"
        env_file.write_text(
            "OSCAR_TEST_FOO=foo\n"
            "this-line-has-no-equals-sign\n"
            "=empty-key\n"
        )

        with caplog.at_level("WARNING", logger="shared.secrets"):
            loaded = load_host_secrets(path=env_file)

        assert loaded == 1  # only OSCAR_TEST_FOO
        assert os.environ["OSCAR_TEST_FOO"] == "foo"
        # Both malformed lines should produce warnings.
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert any("no '='" in r.message for r in warnings)
        assert any("empty key" in r.message for r in warnings)

    def test_default_path_constant_matches_adr_025(self) -> None:
        """Sanity: the default path the loader uses matches what ADR 025
        and Phase 0 addendum § 7.2 promise."""
        assert str(DEFAULT_OSCAR_ENV_PATH) == "/etc/oscar/oscar.env"
