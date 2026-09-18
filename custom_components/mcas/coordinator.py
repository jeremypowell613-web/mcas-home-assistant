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


def _current_year_id(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for table_name in ("Table1", "Table"):
        rows = payload.get(table_name, [])
        if isinstance(rows, list) and rows:
            value = rows[0].get("YearID") if isinstance(rows[0], dict) else None
            if value is not None:
                return str(value)
    return None


def _homework_row(item: Any) -> bool:
    """Return True for mappings that look like MCAS homework records."""
    if not isinstance(item, dict):
        return False
    keys = set(item)
    return bool(
        keys
        & {
            "HomeworkID",
            "HomeworkTitle",
            "HomeworkDescription",
            "DueDate",
            "IsHomeworkSubmitted",
            "AssignedBy",
        }
    )


def _normalise_homework(payload: Any) -> dict[str, Any]:
    """Normalise differing MCAS homework response shapes into a Table list."""
    rows: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if _homework_row(value):
                marker = (
                    value.get("HomeworkID"),
                    value.get("HomeworkTitle"),
                    value.get("DueDate"),
                    value.get("Subject"),
                )
                if marker not in seen:
                    seen.add(marker)
                    rows.append(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)
    rows.sort(key=lambda item: str(item.get("DueDate") or ""))
    return {"Table": rows}


def _payload_shape(payload: Any) -> str:
    """Describe response structure without logging student data or homework text."""
    if isinstance(payload, dict):
        parts: list[str] = []
        for key, value in payload.items():
            if isinstance(value, list):
                parts.append(f"{key}=list[{len(value)}]")
            elif isinstance(value, dict):
                parts.append(f"{key}=dict")
            else:
                parts.append(f"{key}={type(value).__name__}")
        return ", ".join(parts[:20]) or "empty-dict"
    if isinstance(payload, list):
        return f"list[{len(payload)}]"
    return type(payload).__name__


async def _optional(
    label: str, awaitable, warnings: list[str] | None = None
) -> dict[str, Any]:
    try:
        value = await awaitable
        return value if isinstance(value, dict) else {}
    except Exception as err:
        status = getattr(err, "status", "n/a")
        _LOGGER.warning(
            "MCAS optional %s unavailable (%s, status=%s)",
            label,
            type(err).__name__,
            status,
        )
        if warnings is not None:
            warnings.append(f"{label}: unavailable ({type(err).__name__}, status={status})")
        return {}


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
        warnings: list[str] = []
        result: dict[str, Any] = {"children": {}, "_diagnostics": {"warnings": warnings}}
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
                next_payload = await _optional(
                    "next-week timetable",
                    client.async_get_timetable(student_id, next_week),
                    warnings,
                )

                years = await _optional("school years", client.async_get_years(student_id), warnings)
                year_id = _current_year_id(years)

                attendance: dict[str, Any] = {}
                behaviour: dict[str, Any] = {}
                behaviour_chronological: dict[str, Any] = {}
                if year_id:
                    attendance = await _optional(
                        "attendance", client.async_get_attendance(student_id, year_id), warnings
                    )
                    behaviour = await _optional(
                        "behaviour", client.async_get_behaviour(student_id, year_id), warnings
                    )
                    behaviour_chronological = await _optional(
                        "behaviour chronology",
                        client.async_get_behaviour_chronological(student_id, year_id),
                        warnings,
                    )

                homework_raw = await _optional(
                    "homework", client.async_get_homework(student_id, today), warnings
                )
                homework = _normalise_homework(homework_raw)
                if not homework["Table"] and homework_raw:
                    shape = _payload_shape(homework_raw)
                    warnings.append(f"homework: unrecognised response shape ({shape})")
                    _LOGGER.warning(
                        "MCAS homework returned no recognisable rows; response shape: %s",
                        shape,
                    )

                result["children"][key] = {
                    "profile": child,
                    "timetable": _merge_timetables(current_payload, next_payload),
                    "academic_calendar": calendars[pair],
                    "year_id": year_id,
                    "attendance": attendance,
                    "homework": homework,
                    "behaviour": behaviour,
                    "behaviour_chronological": behaviour_chronological,
                }
            return result
        except MCASAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except MCASApiError as err:
            raise UpdateFailed(str(err)) from err
