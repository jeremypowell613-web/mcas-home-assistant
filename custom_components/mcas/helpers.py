"""Shared helpers for ARCADIA Integrate MCAS entities."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.util import dt as dt_util

from .const import DOMAIN

SCHOOL_DAY_CODES = {"-", "SCHL"}


def device_info(profile: dict[str, Any], child_key: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, child_key)},
        name=profile.get("name", "MCAS Student"),
        manufacturer="Bromcom",
        model="MyChildAtSchool",
        configuration_url="https://www.mychildatschool.com",
    )


def lessons(data: dict[str, Any], child_key: str) -> list[dict[str, Any]]:
    table = (
        data.get("children", {})
        .get(child_key, {})
        .get("timetable", {})
        .get("Table", [])
    )
    return table if isinstance(table, list) else []


def academic_days(data: dict[str, Any], child_key: str) -> list[dict[str, Any]]:
    table = (
        data.get("children", {})
        .get(child_key, {})
        .get("academic_calendar", {})
        .get("Table", [])
    )
    return table if isinstance(table, list) else []


def parse_local_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
    return parsed


def parse_day(value: Any) -> date | None:
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def academic_day_for(
    data: dict[str, Any], child_key: str, target: date
) -> dict[str, Any] | None:
    for item in academic_days(data, child_key):
        if parse_day(item.get("Day")) == target:
            return item
    return None


def is_school_day(item: dict[str, Any] | None) -> bool:
    if not item:
        return False
    return str(item.get("DayStatusCode") or "") in SCHOOL_DAY_CODES
