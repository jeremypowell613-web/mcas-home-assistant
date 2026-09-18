"""Calendar entities for ARCADIA Integrate MCAS."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import MCASDataUpdateCoordinator
from .helpers import academic_days, device_info, lessons, parse_day, parse_local_datetime


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: MCASDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[CalendarEntity] = []
    for child_key, child_data in coordinator.data.get("children", {}).items():
        profile = child_data["profile"]
        entities.extend(
            [
                MCASTimetableCalendar(coordinator, entry, child_key, profile),
                MCASAcademicCalendar(coordinator, entry, child_key, profile),
                MCASHomeworkCalendar(coordinator, entry, child_key, profile),
            ]
        )
    async_add_entities(entities)


def _homework_rows(data: dict[str, Any], child_key: str) -> list[dict[str, Any]]:
    rows = (
        data.get("children", {})
        .get(child_key, {})
        .get("homework", {})
        .get("Table", [])
    )
    return rows if isinstance(rows, list) else []


class MCASCalendarBase(CoordinatorEntity[MCASDataUpdateCoordinator], CalendarEntity):
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


class MCASTimetableCalendar(MCASCalendarBase):
    _attr_name = "Timetable"
    _attr_icon = "mdi:timetable"

    def __init__(self, coordinator, entry, child_key, profile):
        super().__init__(coordinator, entry, child_key, profile, "timetable_calendar")

    def _events(self) -> list[CalendarEvent]:
        events: list[CalendarEvent] = []
        for lesson in lessons(self.coordinator.data, self.child_key):
            start = parse_local_datetime(lesson.get("StartDate"))
            end = parse_local_datetime(lesson.get("EndDate"))
            if start is None or end is None:
                continue
            subject = str(lesson.get("Subject") or lesson.get("SystemPeriodName") or "Lesson")
            details = []
            if lesson.get("Class"):
                details.append(f"Class: {lesson['Class']}")
            if lesson.get("TeacherName"):
                details.append(f"Teacher: {lesson['TeacherName']}")
            if lesson.get("SystemPeriodName"):
                details.append(f"Period: {lesson['SystemPeriodName']}")
            events.append(
                CalendarEvent(
                    start=start,
                    end=end,
                    summary=subject,
                    description="\n".join(details) or None,
                    location=str(lesson.get("Room") or "") or None,
                )
            )
        events.sort(key=lambda event: event.start)
        return events

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.now()
        active_or_future = [event for event in self._events() if event.end > now]
        return min(active_or_future, key=lambda item: item.start) if active_or_future else None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        return [event for event in self._events() if event.end > start_date and event.start < end_date]


class MCASAcademicCalendar(MCASCalendarBase):
    _attr_name = "Academic calendar"
    _attr_icon = "mdi:calendar-school"

    def __init__(self, coordinator, entry, child_key, profile):
        super().__init__(coordinator, entry, child_key, profile, "academic_calendar")

    def _events(self) -> list[CalendarEvent]:
        events: list[CalendarEvent] = []
        for item in academic_days(self.coordinator.data, self.child_key):
            day = parse_day(item.get("Day"))
            if day is None:
                continue
            status = str(item.get("DayStatusDescription") or "")
            code = str(item.get("DayStatusCode") or "")
            if status == "Normal Day" and not item.get("HasDiaryEvents"):
                continue
            summary = status or "School calendar event"
            if item.get("HasDiaryEvents") and status == "Normal Day":
                summary = "School diary event"
            events.append(
                CalendarEvent(
                    start=day,
                    end=day + timedelta(days=1),
                    summary=summary,
                    description=f"MCAS status code: {code}" if code else None,
                )
            )
        events.sort(key=lambda event: event.start)
        return events

    @property
    def event(self) -> CalendarEvent | None:
        today = dt_util.now().date()
        upcoming = [event for event in self._events() if event.end > today]
        return min(upcoming, key=lambda item: item.start) if upcoming else None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        start_day = start_date.date()
        end_day = end_date.date()
        return [event for event in self._events() if event.end > start_day and event.start < end_day]


class MCASHomeworkCalendar(MCASCalendarBase):
    _attr_name = "Homework"
    _attr_icon = "mdi:book-education"

    def __init__(self, coordinator, entry, child_key, profile):
        super().__init__(coordinator, entry, child_key, profile, "homework_calendar")

    def _events(self) -> list[CalendarEvent]:
        events: list[CalendarEvent] = []
        for item in _homework_rows(self.coordinator.data, self.child_key):
            due = parse_local_datetime(item.get("DueDate"))
            if due is None:
                continue
            start = parse_local_datetime(item.get("AvailableFrom")) or due - timedelta(hours=1)
            title = str(item.get("HomeworkTitle") or "Homework")
            description_bits = []
            if item.get("Subject"):
                description_bits.append(f"Subject: {item['Subject']}")
            if item.get("CollectionDescription"):
                description_bits.append(f"Class: {item['CollectionDescription']}")
            if item.get("AssignedBy"):
                description_bits.append(f"Assigned by: {item['AssignedBy']}")
            if item.get("HomeworkDescription"):
                description_bits.append(str(item["HomeworkDescription"]))
            events.append(
                CalendarEvent(
                    start=start,
                    end=due,
                    summary=title,
                    description="\n".join(description_bits) or None,
                )
            )
        events.sort(key=lambda event: event.end)
        return events

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.now()
        upcoming = [event for event in self._events() if event.end >= now]
        return min(upcoming, key=lambda item: item.end) if upcoming else None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        return [event for event in self._events() if event.end > start_date and event.start < end_date]
