"""Regression tests for CLI entrypoint exception handling."""

import pytest

from ucagent import ApplicationWorkspaceArchiveError
from ucagent.application import entry


def test_main_handles_workspace_archive_error_without_name_error(monkeypatch, capsys):
    """The public exception alias used by the entrypoint is caught by main."""

    def fail_run():
        raise ApplicationWorkspaceArchiveError("invalid workspace archive")

    monkeypatch.setattr(entry, "run", fail_run)

    with pytest.raises(SystemExit) as exc_info:
        entry.main()

    assert exc_info.value.code == 1
    assert "Workspace archive error: invalid workspace archive" in capsys.readouterr().out
