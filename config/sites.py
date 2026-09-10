"""
Site registry — the foundation of remote troubleshooting.

The original design assumed one router at localhost. Real ISP support
covers multiple physical sites (branches, client premises), each with
its own router reachable over its own network path and secured with its
own credentials. This module makes "which router" a first-class,
explicit parameter instead of a hardcoded URL, so a technician can ask
the copilot about *any* site they're responsible for in the same
conversation.

Sites are defined in code (DEFAULT_SITES) for the mock/demo setup, and
can be extended or overridden by pointing SITES_CONFIG at a JSON file —
so a real deployment's site list doesn't need a code change, just config.

    export SITES_CONFIG=/path/to/sites.json

sites.json format:
    [
      {"id": "branch-a", "name": "Branch A (Nairobi CBD)",
       "base_url": "https://branch-a.example.com:8443",
       "api_token_env": "BRANCH_A_TOKEN"},
      ...
    ]

Each site's bearer token is read from an environment variable (named by
api_token_env), never stored in the site config itself — this keeps
credentials out of any file that might end up committed to a repo.
"""

import json
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Site:
    id: str
    name: str
    base_url: str
    api_token_env: str = ""  # env var name holding this site's bearer token, if any

    @property
    def api_token(self) -> str | None:
        if not self.api_token_env:
            return None
        return os.getenv(self.api_token_env) or None


DEFAULT_SITES = {
    "cbd": Site(
        id="cbd",
        name="Nairobi CBD",
        base_url=os.getenv("SITE_CBD_URL", "http://localhost:8088"),
        api_token_env="SITE_CBD_TOKEN",
    ),
    "westlands": Site(
        id="westlands",
        name="Westlands",
        base_url=os.getenv("SITE_WESTLANDS_URL", "http://localhost:8089"),
        api_token_env="SITE_WESTLANDS_TOKEN",
    ),
    "thika_road": Site(
        id="thika_road",
        name="Thika Road",
        base_url=os.getenv("SITE_THIKA_ROAD_URL", "http://localhost:8090"),
        api_token_env="SITE_THIKA_ROAD_TOKEN",
    ),
}


def load_sites() -> dict[str, Site]:
    """
    Returns the full site registry: DEFAULT_SITES plus anything defined
    in the file pointed to by SITES_CONFIG, if set. Entries in the config
    file override a default site of the same id.
    """
    sites = dict(DEFAULT_SITES)
    config_path = os.getenv("SITES_CONFIG")
    if config_path and os.path.exists(config_path):
        with open(config_path, encoding="utf-8") as f:
            entries = json.load(f)
        for entry in entries:
            sites[entry["id"]] = Site(
                id=entry["id"],
                name=entry.get("name", entry["id"]),
                base_url=entry["base_url"],
                api_token_env=entry.get("api_token_env", ""),
            )
    return sites


def get_site(site_id: str) -> Site:
    sites = load_sites()
    if site_id not in sites:
        raise ValueError(f"Unknown site '{site_id}'. Known sites: {sorted(sites)}")
    return sites[site_id]


def list_site_ids() -> list[str]:
    return sorted(load_sites())
