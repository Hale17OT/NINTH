"""Mandatory chronological development and holdout windows for NINTH sports.

These constants are intentionally code-level invariants.  A caller cannot
silently slide the Football or NFL evaluation window based on today's date.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SeasonWindow:
    sport: str
    development: tuple[int, ...]
    holdout: tuple[int, ...]
    label_style: str

    def label(self, season: int) -> str:
        return f"{season}/{str(season + 1)[-2:]}" if self.label_style == "split" else str(season)


WINDOWS = {
    "football": SeasonWindow(
        sport="football",
        development=(2018, 2019, 2020, 2021, 2022, 2023),
        holdout=(2024, 2025),
        label_style="split",
    ),
    "american-football": SeasonWindow(
        sport="american-football",
        development=(2018, 2019, 2020, 2021, 2022, 2023),
        holdout=(2024, 2025),
        label_style="year",
    ),
}


def row_season(row: dict, sport: str) -> int:
    explicit = row.get("season")
    if explicit not in (None, ""):
        return int(explicit)
    event_id = str(row.get("event_id") or "")
    if sport == "american-football" and len(event_id) >= 4 and event_id[:4].isdigit():
        return int(event_id[:4])
    at = datetime.fromisoformat(str(row["event_time"]).replace("Z", "+00:00"))
    if sport == "football":
        return at.year if at.month >= 7 else at.year - 1
    return at.year


def partition_fixed_window(rows: list[dict], sport: str) -> dict:
    window = WINDOWS.get(sport)
    if window is None:
        raise ValueError(f"No fixed season window is registered for {sport}")
    grouped = {season: [] for season in (*window.development, *window.holdout)}
    ignored = []
    for row in rows:
        season = row_season(row, sport)
        row["_season"] = season
        if season in grouped:
            grouped[season].append(row)
        else:
            ignored.append(row)
    missing_development = [season for season in window.development if not grouped[season]]
    missing_holdout = [season for season in window.holdout if not grouped[season]]
    if missing_development or missing_holdout:
        raise ValueError(
            f"{sport} fixed-window dataset is incomplete; missing development "
            f"{missing_development or 'none'}, holdout {missing_holdout or 'none'}"
        )
    return {
        "window": window,
        "development": [row for season in window.development for row in grouped[season]],
        "holdout": [row for season in window.holdout for row in grouped[season]],
        "by_season": grouped,
        "ignored": ignored,
    }


def window_metadata(partition: dict) -> dict:
    window: SeasonWindow = partition["window"]
    development = partition["development"]
    holdout = partition["holdout"]
    return {
        "development_dataset_start": development[0]["event_time"],
        "development_dataset_end": development[-1]["event_time"],
        "development_seasons": [window.label(value) for value in window.development],
        "holdout_dataset_start": holdout[0]["event_time"],
        "holdout_dataset_end": holdout[-1]["event_time"],
        "holdout_seasons": [window.label(value) for value in window.holdout],
        "holdout_consumed": True,
        "holdout_use": "evaluation only; excluded from fitting, calibration, feature selection and threshold selection",
    }
