"""Unit tests for startup Alembic auto-migrate helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.main import _is_database_connection_error, apply_alembic_migrations


def test_is_database_connection_error_detects_common_failures() -> None:
    assert _is_database_connection_error(ConnectionRefusedError("refused"))
    assert _is_database_connection_error(TimeoutError("timed out"))
    assert _is_database_connection_error(OSError("could not connect to server"))
    assert not _is_database_connection_error(ValueError("revision missing"))


def test_apply_alembic_migrations_swallows_connection_errors() -> None:
    command = SimpleNamespace(upgrade=MagicMock(side_effect=ConnectionRefusedError("offline")))
    with patch("app.main._load_alembic_upgrade_api", return_value=(command, MagicMock)):
        apply_alembic_migrations()
    command.upgrade.assert_called_once()


def test_apply_alembic_migrations_reraises_non_connection_errors() -> None:
    command = SimpleNamespace(upgrade=MagicMock(side_effect=RuntimeError("bad revision")))
    with patch("app.main._load_alembic_upgrade_api", return_value=(command, MagicMock)):
        with pytest.raises(RuntimeError, match="bad revision"):
            apply_alembic_migrations()


def test_apply_alembic_migrations_calls_upgrade_head() -> None:
    command = SimpleNamespace(upgrade=MagicMock())
    config_cls = MagicMock(return_value=MagicMock(name="alembic_cfg"))
    with patch("app.main._load_alembic_upgrade_api", return_value=(command, config_cls)):
        apply_alembic_migrations()
    config_cls.assert_called_once()
    command.upgrade.assert_called_once()
    assert command.upgrade.call_args.args[1] == "head"


def test_load_alembic_upgrade_api_resolves_installed_package() -> None:
    from app.main import _load_alembic_upgrade_api

    command, config_cls = _load_alembic_upgrade_api()
    assert callable(command.upgrade)
    assert config_cls.__name__ == "Config"
