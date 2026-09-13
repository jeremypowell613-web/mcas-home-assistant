"""Sensors for ARCADIA Integrate MCAS."""
from __future__ import annotations
from datetime import datetime
from typing import Any
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN
from .coordinator import MCASDataUpdateCoordinator

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: MCASDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []
    for child_key, child_data in coordinator.data.get("children", {}).items():
        entities.extend([MCASNextLessonSensor(coordinator, entry, child_key, child_data["profile"]), MCASFirstLessonSensor(coordinator, entry, child_key, child_data["profile"])])
    async_add_entities(entities)

def _lessons(data: dict[str, Any], child_key: str) -> list[dict[str, Any]]:
    table = data.get("children", {}).get(child_key, {}).get("timetable", {}).get("Table", [])
    return table if isinstance(table, list) else []

def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

class MCASSensorBase(CoordinatorEntity[MCASDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True
    def __init__(self, coordinator, entry, child_key: str, profile: dict[str, Any], key: str) -> None:
        super().__init__(coordinator)
        self.child_key = child_key
        self._attr_unique_id = f"{entry.entry_id}_{child_key}_{key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, child_key)}, name=profile.get("name", "MCAS Student"), manufacturer="Bromcom", model="MyChildAtSchool", configuration_url="https://www.mychildatschool.com")

class MCASNextLessonSensor(MCASSensorBase):
    _attr_name = "Next lesson"
    _attr_icon = "mdi:calendar-clock"
    def __init__(self, coordinator, entry, child_key, profile):
        super().__init__(coordinator, entry, child_key, profile, "next_lesson")
    def _next(self):
        now = datetime.now().astimezone()
        candidates = [(start, lesson) for lesson in _lessons(self.coordinator.data, self.child_key) if (start := _parse(lesson.get("StartDate"))) is not None and start.astimezone() >= now]
        return min(candidates, key=lambda item: item[0]) if candidates else None
    @property
    def native_value(self):
        item = self._next()
        return None if item is None else item[1].get("Subject") or item[1].get("SystemPeriodName")
    @property
    def extra_state_attributes(self):
        item = self._next()
        if item is None: return {}
        start, lesson = item
        return {"start": start.isoformat(), "end": lesson.get("EndDate"), "room": lesson.get("Room"), "teacher": lesson.get("TeacherName"), "class": lesson.get("Class")}

class MCASFirstLessonSensor(MCASSensorBase):
    _attr_name = "First lesson today"
    _attr_icon = "mdi:school"
    def __init__(self, coordinator, entry, child_key, profile):
        super().__init__(coordinator, entry, child_key, profile, "first_lesson_today")
    @property
    def native_value(self):
        today = datetime.now().astimezone().date()
        matches = [(start, lesson) for lesson in _lessons(self.coordinator.data, self.child_key) if (start := _parse(lesson.get("StartDate"))) is not None and start.astimezone().date() == today]
        if not matches: return None
        _, lesson = min(matches, key=lambda item: item[0])
        return lesson.get("Subject") or lesson.get("SystemPeriodName")
