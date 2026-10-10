import pytest

from bibliothecary import search


@pytest.fixture(autouse=True)
def _links_are_readable(monkeypatch):
    """Tests never fetch pages to see whether a link is readable in full."""
    monkeypatch.setattr(search, "readable", lambda url: True)


@pytest.fixture(autouse=True)
def _no_local_env(monkeypatch):
    """Tests never read the developer's own .env (its voice, keys and settings would leak in)."""
    from margin import cli

    monkeypatch.setattr(cli, "load_env", lambda path=".env": None)

@pytest.fixture(autouse=True)
def _isolated_library(tmp_path, monkeypatch):
    monkeypatch.setenv('BIBLIOTHECARY_HOME', str(tmp_path / 'isolated-library'))
