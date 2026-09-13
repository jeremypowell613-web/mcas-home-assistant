"""Data coordinator for MCAS."""
from __future__ import annotations

from datetime import date, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import MCASApiError, MCASAuthError, MCASClient
from .const import CONF_CHILDREN, CONF_SELECTED_CHILDREN, DEFAULT_UPDATE_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _child_key(child: dict[str, Any]) -> str:
    return f"{child['school_id']}:{child['contact_id']}:{child['student_id']}"


def _merge_timetables(*payloads: Any) -> dict[str, Any]:
    """Merge MCAS timetable responses without exposing duplicate lessons."""
    lessons: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        table = payload.get("Table", [])
        if not isinstance(table, list):
            continue
        for lesson in table:
            if not isinstance(lesson, dict):
                continue
            marker = (
                lesson.get("CalendarID"),
                lesson.get("StartDate"),
                lesson.get("EndDate"),
                lesson.get("Subject"),
            )
            if marker in seen:
                continue
            seen.add(marker)
            lessons.append(lesson)
    lessons.sort(key=lambda item: str(item.get("StartDate") or ""))
    return {"Table": lessons}


class MCASDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(
        self,
        hass: HomeAssistant,
        clients: dict[tuple[str, str], MCASClient],
        entry: ConfigEntry,
    ) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_UPDATE_INTERVAL,
            config_entry=entry,
        )
        self.clients = clients
        self.entry = entry

    async def _async_update_data(self) -> dict[str, Any]:
        all_children = self.entry.data.get(CONF_CHILDREN, [])
        selected = set(
            self.entry.options.get(
                CONF_SELECTED_CHILDREN,
                [_child_key(c) for c in all_children],
            )
        )
        result: dict[str, Any] = {"children": {}}
        calendars: dict[tuple[str, str], dict[str, Any]] = {}
        today = date.today()
        this_week = _monday(today)
        next_week = this_week + timedelta(days=7)

        try:
            for child in all_children:
                key = _child_key(child)
                if key not in selected:
                    continue

                pair = (str(child["school_id"]), str(child["contact_id"]))
                client = self.clients[pair]
                if pair not in calendars:
                    calendars[pair] = await client.async_get_academic_calendar()

                student_id = str(child["student_id"])
                current_payload = await client.async_get_timetable(student_id, this_week)
                next_payload = await client.async_get_timetable(student_id, next_week)

                result["children"][key] = {
                    "profile": child,
                    "timetable": _merge_timetables(current_payload, next_payload),
                    "academic_calendar": calendars[pair],
                }
            return result
        except MCASAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except MCASApiError as err:
            raise UpdateFailed(str(err)) from err
