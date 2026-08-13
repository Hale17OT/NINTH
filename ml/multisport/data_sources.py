"""Open and optional free-account source contracts for new sport collectors.

This module does not scrape website HTML. Every provider here exposes an API
or a licensed/open data release and must be archived before feature building.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class SourceUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class JsonApi:
    base_url: str
    token_env: str | None = None
    token_header: str = "Authorization"
    token_prefix: str = "Bearer "
    minimum_interval: float = 0.0

    def get(self, path: str, params: dict | None = None) -> dict | list:
        token = os.getenv(self.token_env, "") if self.token_env else ""
        if self.token_env and not token:
            raise SourceUnavailable(f"{self.token_env} is not configured")
        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        if params:
            url += "?" + urlencode(params)
        headers = {"Accept": "application/json", "User-Agent": "NINTH-Research/1.0"}
        if token:
            headers[self.token_header] = f"{self.token_prefix}{token}"
        if self.minimum_interval:
            time.sleep(self.minimum_interval)
        with urlopen(Request(url, headers=headers), timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))


FOOTBALL_DATA = JsonApi(
    "https://api.football-data.org/v4", "NINTH_FOOTBALL_DATA_TOKEN",
    token_header="X-Auth-Token", token_prefix="", minimum_interval=6.1,
)
RIOT = JsonApi("https://americas.api.riotgames.com", "RIOT_API_KEY", token_header="X-Riot-Token", token_prefix="")


def source_status() -> dict:
    return {
        "football_open_csv": {"configured": True, "scope": "keyless top-five fixtures/results/prices"},
        "statsbomb_open": {"configured": True, "scope": "keyless selected events/lineups/360"},
        "football_data": {"configured": bool(os.getenv("NINTH_FOOTBALL_DATA_TOKEN")), "optional": True, "scope": "free-account competition supplement"},
        "grid": {"configured": bool(os.getenv("GRID_API_KEY")), "scope": "official CS2 / Valorant professional data"},
        "liquipedia_api": {"configured": True, "scope": "keyless Valorant, CS2 and League of Legends schedules/results/directories"},
        "csapi": {"configured": True, "scope": "keyless CS2 results/rankings/player statistics supplement"},
        "riot": {"configured": bool(os.getenv("RIOT_API_KEY")), "scope": "official opt-in Valorant matches"},
        "nba_stats": {"configured": True, "scope": "official NBA statistics; collector validation required"},
        "nflverse": {"configured": True, "scope": "open historical NFL play-by-play releases"},
        "vlr_scraper": {"configured": False, "prohibited": True, "reason": "VLR terms prohibit automated scraping/data-mining"},
    }
