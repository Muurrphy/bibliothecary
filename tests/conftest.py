import pytest

from bibliothecary import search


@pytest.fixture(autouse=True)
def _links_are_readable(monkeypatch):
    """Tests never fetch pages to see whether a link is readable in full."""
    monkeypatch.setattr(search, "readable", lambda url: True)
