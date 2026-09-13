"""Sensors for ARCADIA Integrate MCAS."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import MCASDataUpdateCoordinator
from .helpers import (
    academic_day_for,
    academic_days,
    device_info,
    is_school_day,
    lessons,
    parse_day,
    parse_local_datetime,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: MCASDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []
    for child_key, child_data in coordinator.data.get("children", {}).items():
        profile = child_data["profile"]
        entities.extend(
            [
                MCASNextLessonSensor(coordinator, entry, child_key, profile),
                MCASFirstLessonSensor(coordinator, entry, child_key, profile),
                MCASSchoolStatusSensor(coordinator, entry, child_key, profile, 0),
                MCASSchoolStatusSensor(coordinator, entry, child_key, profile, 1),
                MCASSchoolFinishSensor(coordinator, entry, child_key, profile),
                MCASNextSchoolStartSensor(coordinator, entry, child_key, profile),
                MCASNextSchoolDaySensor(coordinator, entry, child_key, profile),
            ]
        )
    async_add_entities(entities)


class MCASSensorBase(CoordinatorEntity[MCASDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: MCASDataUpdateCoordinator,
        entry: ConfigEntry,
        child_key: str,
        profile: dict[str, Any],
        key: str,
    ) -> None:
        super().__init__(coordinator)
        self.child_key = child_key
        self._attr_unique_id = f"{entry.entry_id}_{child_key}_{key}"
        self._attr_device_info = device_info(profile, child_key)


class MCASNextLessonSensor(MCASSensorBase):
    _attr_name = "Next lesson"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator, entry, child_key, profile):
        super().__init__(coordinator, entry, child_key, profile, "next_lesson")

    def _next(self):
        now = dt_util.now()
        candidates = [
            (start, lesson)
            for lesson in lessons(self.coordinator.data, self.child_key)
            if (start := parse_local_datetime(lesson.get("StartDate"))) is not None
            and start >= now
        ]
        return min(candidates, key=lambda item: item[0]) if candidates else None

    @property
    def native_value(self):
        item = self._next()
        return None if item is None else item[1].get("Subject") or item[1].get("SystemPeriodName")

    @property
    def extra_state_attributes(self):
        item = self._next()
        if item is None:
            return {}
        start, lesson = item
        end = parse_local_datetime(lesson.get("EndDate"))
        return {
            "start": start.isoformat(),
            "end": end.isoformat() if end else None,
            "room": lesson.get("Room"),
            "teacher": lesson.get("TeacherName"),
            "class": lesson.get("Class"),
            "period": lesson.get("SystemPeriodName"),
        }


class MCASFirstLessonSensor(MCASSensorBase):
    _attr_name = "First lesson today"
    _attr_icon = "mdi:school"

    def __init__(self, coordinator, entry, child_key, profile):
        super().__init__(coordinator, entry, child_key, profile, "first_lesson_today")

    def _first(self):
        today = dt_util.now().date()
        matches = [
            (start, lesson)
            for lesson in lessons(self.coordinator.data, self.child_key)
            if (start := parse_local_datetime(lesson.get("StartDate"))) is not None
            and start.date() == today
        ]
        return min(matches, key=lambda item: item[0]) if matches else None

    @property
    def native_value(self):
        item = self._first()
        return None if item is None else item[1].get("Subject") or item[1].get("SystemPeriodName")

    @property
    def extra_state_attributes(self):
        item = self._first()
        if item is None:
            return {}
        start, lesson = item
        return {
            "start": start.isoformat(),
            "room": lesson.get("Room"),
            "teacher": lesson.get("TeacherName"),
            "class": lesson.get("Class"),
            "period": lesson.get("SystemPeriodName"),
        }


class MCASSchoolStatusSensor(MCASSensorBase):
    _attr_icon = "mdi:calendar-check"

    def __init__(self, coordinator, entry, child_key, profile, offset_days: int):
        self.offset_days = offset_days
        key = "school_status_today" if offset_days == 0 else "school_status_tomorrow"
        super().__init__(coordinator, entry, child_key, profile, key)
        self._attr_name = "School status today" if offset_days == 0 else "School status tomorrow"

    @property
    def native_value(self):
        target = dt_util.now().date() + timedelta(days=self.offset_days)
        item = academic_day_for(self.coordinator.data, self.child_key, target)
        return None if item is None else item.get("DayStatusDescription")

    @property
    def extra_state_attributes(self):
        target = dt_util.now().date() + timedelta(days=self.offset_days)
        item = academic_day_for(self.coordinator.data, self.child_key, target)
        if not item:
            return {"date": target.isoformat()}
        return {
            "date": target.isoformat(),
            "status_code": item.get("DayStatusCode"),
            "school_day": is_school_day(item),
            "has_diary_events": item.get("HasDiaryEvents"),
        }


class MCASSchoolFinishSensor(MCASSensorBase):
    _attr_name = "School finish today"
    _attr_icon = "mdi:school-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, entry, child_key, profile):
        super().__init__(coordinator, entry, child_key, profile, "school_finish_today")

    @property
    def native_value(self) -> datetime | None:
        today = dt_util.now().date()
        ends = [
            end
            for lesson in lessons(self.coordinator.data, self.child_key)
            if (end := parse_local_datetime(lesson.get("EndDate"))) is not None
            and end.date() == today
        ]
        return max(ends) if ends else None


class MCASNextSchoolStartSensor(MCASSensorBase):
    _attr_name = "Next school start"
    _attr_icon = "mdi:school"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, entry, child_key, profile):
        super().__init__(coordinator, entry, child_key, profile, "next_school_start")

    @property
    def native_value(self) -> datetime | None:
        now = dt_util.now()
        starts = [
            start
            for lesson in lessons(self.coordinator.data, self.child_key)
            if (start := parse_local_datetime(lesson.get("StartDate"))) is not None
            and start >= now
        ]
        return min(starts) if starts else None


class MCASNextSchoolDaySensor(MCASSensorBase):
    _attr_name = "Next school day"
    _attr_icon = "mdi:calendar-arrow-right"
    _attr_device_class = SensorDeviceClass.DATE

    def __init__(self, coordinator, entry, child_key, profile):
        super().__init__(coordinator, entry, child_key, profile, "next_school_day")

    @property
    def native_value(self) -> date | None:
        today = dt_util.now().date()
        candidates: list[date] = []
        for item in academic_days(self.coordinator.data, self.child_key):
            day = parse_day(item.get("Day"))
            if day is not None and day >= today and is_school_day(item):
                candidates.append(day)
        return min(candidates) if candidates else None
