"""Tests for the multi-site registry (config/sites.py)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from config.sites import get_site, list_site_ids, load_sites


def test_default_sites_present():
    ids = list_site_ids()
    assert "cbd" in ids
    assert "westlands" in ids
    assert "thika_road" in ids


def test_get_unknown_site_raises():
    with pytest.raises(ValueError):
        get_site("nonexistent-site")


def test_each_site_has_a_base_url():
    for site_id in list_site_ids():
        site = get_site(site_id)
        assert site.base_url.startswith("http")


def test_site_api_token_is_none_when_env_var_unset(monkeypatch):
    monkeypatch.delenv("SITE_CBD_TOKEN", raising=False)
    site = get_site("cbd")
    assert site.api_token is None


def test_site_api_token_reads_from_env(monkeypatch):
    monkeypatch.setenv("SITE_CBD_TOKEN", "secret123")
    site = get_site("cbd")
    assert site.api_token == "secret123"
