"""Sensors for MCAS."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MCASDataUpdateCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: MCASDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([MCASNextLessonSensor(coordinator, entry), MCASFirstLessonSensor(coordinator, entry)])


def _lessons(data: dict[str, Any]) -> list[dict[str, Any]]:
    table = data.get("timetable", {}).get("Table", [])
    return table if isinstance(table, list) else []


def _parse_mcas_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class MCASSensorBase(CoordinatorEntity[MCASDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: MCASDataUpdateCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"


class MCASNextLessonSensor(MCASSensorBase):
    _attr_name = "Next lesson"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: MCASDataUpdateCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "next_lesson")

    def _next(self) -> tuple[datetime, dict[str, Any]] | None:
        now = datetime.now().astimezone()
        candidates = []
        for lesson in _lessons(self.coordinator.data):
            start = _parse_mcas_datetime(lesson.get("StartDate"))
            if start is not None and start.astimezone() >= now:
                candidates.append((start, lesson))
        return min(candidates, key=lambda item: item[0]) if candidates else None

    @property
    def native_value(self) -> str | None:
        item = self._next()
        if item is None:
            return None
        return item[1].get("Subject") or item[1].get("SystemPeriodName")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        item = self._next()
        if item is None:
            return {}
        start, lesson = item
        return {"start": start.isoformat(), "room": lesson.get("Room"), "teacher": lesson.get("TeacherName"), "class": lesson.get("Class")}


class MCASFirstLessonSensor(MCASSensorBase):
    _attr_name = "First lesson today"
    _attr_icon = "mdi:school"

    def __init__(self, coordinator: MCASDataUpdateCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "first_lesson_today")

    @property
    def native_value(self) -> str | None:
        today = datetime.now().astimezone().date()
        matches = []
        for lesson in _lessons(self.coordinator.data):
            start = _parse_mcas_datetime(lesson.get("StartDate"))
            if start is not None and start.astimezone().date() == today:
                matches.append((start, lesson))
        if not matches:
            return None
        _, lesson = min(matches, key=lambda item: item[0])
        return lesson.get("Subject") or lesson.get("SystemPeriodName")
