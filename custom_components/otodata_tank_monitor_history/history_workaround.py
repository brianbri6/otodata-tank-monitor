"""Use the Nee-Vo history API to replace stale summary tank percentages."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import math
import re
from typing import Any
from urllib.parse import quote

_LOGGER = logging.getLogger(__name__)
_HISTORY_URL = "https://ws.otodatanetwork.com/neevoapp/v1/DataService.svc/GetPropaneLevels/"
_WCF_DATE = re.compile(r"^/Date\((-?\d{10,13})(?:[+-]\d{4})?\)/$")


def _level(raw: Any) -> float | None:
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        value = float(raw)
    except (ValueError, TypeError, OverflowError):
        return None
    return value if math.isfinite(value) and 0 <= value <= 100 else None


def _date(raw: Any) -> datetime | None:
    try:
        if isinstance(raw, str):
            match = _WCF_DATE.fullmatch(raw.strip())
            if match:
                raw = int(match.group(1)) / (1000 if len(match.group(1).lstrip("-")) == 13 else 1)
            else:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            epoch = float(raw)
            return datetime.fromtimestamp(epoch / 1000 if abs(epoch) >= 1e11 else epoch, tz=timezone.utc)
    except (ValueError, TypeError, OverflowError, OSError):
        pass
    return None


def _latest_graph_point(payload: dict[str, Any]) -> tuple[float, Any, datetime] | None:
    points = payload.get("GraphLevelsData")
    if not isinstance(points, list):
        return None
    dated = []
    for point in points:
        if isinstance(point, dict):
            value = _level(point.get("Level"))
            date = _date(point.get("Date"))
            if value is not None and date is not None:
                dated.append((value, point.get("Date"), date))
    return max(dated, key=lambda x: x[2]) if dated else None


def _choose_history(payload: Any, preference: str) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    graph = _latest_graph_point(payload)
    current = _level(payload.get("CurrentLevel"))
    order = ("current", "graph") if preference == "current" else ("graph", "current")
    for source in order:
        if source == "graph" and graph:
            return dict(level=graph[0], source="history_graph", date=graph[1],
                        parsed_date=graph[2], current=current,
                        graph_level=graph[0], graph_date=graph[1])
        if source == "current" and current is not None:
            matching = graph if graph and abs(graph[0] - current) <= 0.05 else None
            return dict(level=current, source="history_current",
                        date=matching[1] if matching else None,
                        parsed_date=matching[2] if matching else None,
                        current=current, graph_level=graph[0] if graph else None,
                        graph_date=graph[1] if graph else None)
    return None


async def async_apply_history_levels(
    session: Any, auth: Any, tanks: Any, timeout: int,
    preference: str, cache: dict[str, dict[str, Any]]
) -> Any:
    """Use graph readings, retaining the last valid history reading on errors.

    When no history has been received, publish unavailable rather than the
    potentially stale summary level. Keep summary metadata and percentage.
    """
    if preference == "summary":
        return tanks
    if not isinstance(tanks, list):
        raise ValueError("Expected a list of tanks from device summary API")
    semaphore = asyncio.Semaphore(3)

    async def one_tank(raw: Any) -> Any:
        if not isinstance(raw, dict):
            return raw
        tank = dict(raw)
        tank_id = str(tank.get("Id") or "")
        tank["_SummaryLevel"] = tank.get("Level")
        tank["_LevelSource"] = "history_unavailable"
        tank["_HistoryStatus"] = "unavailable"
        chosen = None
        if tank_id:
            try:
                async with semaphore:
                    async with asyncio.timeout(timeout):
                        async with session.get(
                            _HISTORY_URL + quote(tank_id, safe=""), auth=auth
                        ) as response:
                            response.raise_for_status()
                            payload = await response.json(content_type=None)
                chosen = _choose_history(payload, preference)
                if chosen is None:
                    _LOGGER.warning("Otodata history has no usable level")
            except Exception as err:
                _LOGGER.warning("Otodata history request unavailable (%s)", type(err).__name__)

        previous = cache.get(tank_id) if tank_id else None
        if chosen is not None and previous is not None:
            old_dt = previous.get("parsed_date")
            new_dt = chosen.get("parsed_date")
            if old_dt is not None and new_dt is not None and new_dt < old_dt:
                chosen = None
        if chosen is not None:
            cache[tank_id] = chosen
            tank["_HistoryStatus"] = "live"
        elif previous is not None:
            chosen = previous
            tank["_HistoryStatus"] = "cached"
        if chosen is not None:
            tank["Level"] = chosen["level"]
            tank["_LevelSource"] = chosen["source"]
            tank["_HistoryCurrentLevel"] = chosen.get("current")
            tank["_HistoryGraphLevel"] = chosen.get("graph_level")
            tank["_HistoryGraphDate"] = chosen.get("graph_date")
            if chosen.get("parsed_date") is not None:
                epoch_ms = int(chosen["parsed_date"].timestamp() * 1000)
                tank["LastReadingDate"] = f"/Date({epoch_ms})/"
        else:
            tank["Level"] = None
        return tank

    return list(await asyncio.gather(*(one_tank(tank) for tank in tanks)))
