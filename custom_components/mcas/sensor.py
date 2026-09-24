# Copyright (C) 2026 Jeremy Powell
# ARCADIA Integrate MCAS
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE and NOTICE in this integration directory.

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
                MCASNextSchoolDayAfterTodaySensor(coordinator, entry, child_key, profile),
                MCASAttendanceSensor(coordinator, entry, child_key, profile),
                MCASOutstandingPaymentsSensor(coordinator, entry, child_key, profile),
                MCASOutstandingBalanceSensor(coordinator, entry, child_key, profile),
                MCASDinnerBalanceSensor(coordinator, entry, child_key, profile),
                MCASClubBalanceSensor(coordinator, entry, child_key, profile),
                MCASNextPaymentDueSensor(coordinator, entry, child_key, profile),
                MCASBehaviourPointsSensor(coordinator, entry, child_key, profile),
                MCASLatestBehaviourSensor(coordinator, entry, child_key, profile),
            ]
        )
        if child_data.get("features", {}).get("homework", True):
            entities.extend(
                [
                    MCASHomeworkOutstandingSensor(coordinator, entry, child_key, profile),
                    MCASNextHomeworkDueSensor(coordinator, entry, child_key, profile),
                    MCASNextHomeworkTitleSensor(coordinator, entry, child_key, profile),
                ]
            )
    async_add_entities(entities)


def _child_payload(data: dict[str, Any], child_key: str, key: str) -> dict[str, Any]:
    value = data.get("children", {}).get(child_key, {}).get(key, {})
    return value if isinstance(value, dict) else {}


def _homework_rows(data: dict[str, Any], child_key: str) -> list[dict[str, Any]]:
    rows = _child_payload(data, child_key, "homework").get("Table", [])
    return rows if isinstance(rows, list) else []


def _payment_data(data: dict[str, Any], child_key: str) -> dict[str, Any]:
    return _child_payload(data, child_key, "payments")


def _money(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = (
            value.replace("£", "")
            .replace(",", "")
            .replace("GBP", "")
            .strip()
        )
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _next_homework(data: dict[str, Any], child_key: str):
    candidates: list[tuple[datetime, dict[str, Any]]] = []
    for item in _homework_rows(data, child_key):
        if bool(item.get("IsHomeworkSubmitted")):
            continue
        due = parse_local_datetime(item.get("DueDate"))
        if due is not None and due >= dt_util.now():
            candidates.append((due, item))
    return min(candidates, key=lambda value: value[0]) if candidates else None


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
        if item is not None:
            return item.get("DayStatusDescription") or ("School day" if is_school_day(item) else "Not a school day")
        if target.weekday() >= 5:
            return "Not a school day"
        return "Unknown"

    @property
    def extra_state_attributes(self):
        target = dt_util.now().date() + timedelta(days=self.offset_days)
        item = academic_day_for(self.coordinator.data, self.child_key, target)
        if not item:
            return {
                "date": target.isoformat(),
                "school_day": False if target.weekday() >= 5 else None,
                "reason": "weekend" if target.weekday() >= 5 else "no_calendar_record",
            }
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
        now = dt_util.now()
        today = now.date()
        today_ends = [
            end
            for lesson in lessons(self.coordinator.data, self.child_key)
            if (end := parse_local_datetime(lesson.get("EndDate"))) is not None
            and end.date() == today
        ]
        today_finished = bool(today_ends) and max(today_ends) <= now

        candidates: list[date] = []
        for item in academic_days(self.coordinator.data, self.child_key):
            day = parse_day(item.get("Day"))
            if day is None or not is_school_day(item) or day < today:
                continue
            if day == today and today_finished:
                continue
            candidates.append(day)
        return min(candidates) if candidates else None


class MCASNextSchoolDayAfterTodaySensor(MCASSensorBase):
    _attr_name = "Next school day after today"
    _attr_icon = "mdi:calendar-arrow-right"
    _attr_device_class = SensorDeviceClass.DATE

    def __init__(self, coordinator, entry, child_key, profile):
        super().__init__(coordinator, entry, child_key, profile, "next_school_day_after_today")

    @property
    def native_value(self) -> date | None:
        today = dt_util.now().date()
        candidates: list[date] = []
        for item in academic_days(self.coordinator.data, self.child_key):
            day = parse_day(item.get("Day"))
            if day is None or day <= today or not is_school_day(item):
                continue
            candidates.append(day)
        return min(candidates) if candidates else None


class MCASAttendanceSensor(MCASSensorBase):
    _attr_name = "Attendance"
    _attr_icon = "mdi:account-check"
    _attr_native_unit_of_measurement = "%"

    def __init__(self, coordinator, entry, child_key, profile):
        super().__init__(coordinator, entry, child_key, profile, "attendance")

    def _summary(self) -> dict[str, Any] | None:
        rows = _child_payload(self.coordinator.data, self.child_key, "attendance").get("Table5", [])
        return rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else None

    @property
    def native_value(self):
        summary = self._summary()
        if not summary:
            return None
        total = int(summary.get("TotalMarks") or 0)
        present = int(summary.get("PresentMarks") or 0)
        return round((present / total) * 100, 1) if total else None

    @property
    def extra_state_attributes(self):
        summary = self._summary()
        if not summary:
            return {}
        return {
            "total_marks": summary.get("TotalMarks"),
            "present": summary.get("PresentMarks"),
            "authorised_absent": summary.get("AbsentMarks"),
            "unauthorised_absent": summary.get("UAbsentMarks"),
            "late": summary.get("LateMarks"),
            "not_taken": summary.get("NotTakenMarks"),
        }


class MCASHomeworkOutstandingSensor(MCASSensorBase):
    _attr_name = "Homework outstanding"
    _attr_icon = "mdi:book-open-page-variant"

    def __init__(self, coordinator, entry, child_key, profile):
        super().__init__(coordinator, entry, child_key, profile, "homework_outstanding")

    def _outstanding(self) -> list[dict[str, Any]]:
        return [
            item
            for item in _homework_rows(self.coordinator.data, self.child_key)
            if not bool(item.get("IsPast")) and not bool(item.get("IsHomeworkSubmitted"))
        ]

    @property
    def native_value(self):
        return len(self._outstanding())

    @property
    def extra_state_attributes(self):
        items = []
        for item in self._outstanding()[:10]:
            due = parse_local_datetime(item.get("DueDate"))
            detail = {
                "title": item.get("HomeworkTitle"),
                "due": due.isoformat() if due else item.get("DueDate"),
            }
            if item.get("Subject"):
                detail["subject"] = item.get("Subject")
            if item.get("AssignedBy"):
                detail["assigned_by"] = item.get("AssignedBy")
            items.append(detail)
        return {"items": items}


class MCASNextHomeworkDueSensor(MCASSensorBase):
    _attr_name = "Next homework due"
    _attr_icon = "mdi:book-clock"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, entry, child_key, profile):
        super().__init__(coordinator, entry, child_key, profile, "next_homework_due")

    @property
    def native_value(self) -> datetime | None:
        item = _next_homework(self.coordinator.data, self.child_key)
        return None if item is None else item[0]

    @property
    def extra_state_attributes(self):
        item = _next_homework(self.coordinator.data, self.child_key)
        if item is None:
            return {}
        due, homework = item
        attrs = {
            "title": homework.get("HomeworkTitle"),
            "due": due.isoformat(),
        }
        optional = {
            "subject": homework.get("Subject"),
            "class": homework.get("CollectionDescription"),
            "assigned_by": homework.get("AssignedBy"),
            "description": homework.get("HomeworkDescription"),
        }
        attrs.update({key: value for key, value in optional.items() if value not in (None, "")})
        return attrs


class MCASNextHomeworkTitleSensor(MCASSensorBase):
    _attr_name = "Next homework"
    _attr_icon = "mdi:book-open-variant"

    def __init__(self, coordinator, entry, child_key, profile):
        super().__init__(coordinator, entry, child_key, profile, "next_homework_title")

    @property
    def native_value(self):
        item = _next_homework(self.coordinator.data, self.child_key)
        return None if item is None else item[1].get("HomeworkTitle")

    @property
    def extra_state_attributes(self):
        item = _next_homework(self.coordinator.data, self.child_key)
        if item is None:
            return {}
        due, homework = item
        attrs = {"due": due.isoformat()}
        if homework.get("Subject"):
            attrs["subject"] = homework.get("Subject")
        if homework.get("AssignedBy"):
            attrs["assigned_by"] = homework.get("AssignedBy")
        return attrs


class MCASOutstandingPaymentsSensor(MCASSensorBase):
    _attr_name = "Outstanding payments"
    _attr_icon = "mdi:cash-clock"

    def __init__(self, coordinator, entry, child_key, profile):
        super().__init__(coordinator, entry, child_key, profile, "outstanding_payments")

    def _payments(self) -> dict[str, Any]:
        return _payment_data(self.coordinator.data, self.child_key)

    @property
    def native_value(self):
        payments = self._payments()
        return sum(
            len(payments.get(name, []))
            for name in ("orders", "balances", "installments")
            if isinstance(payments.get(name), list)
        )

    @property
    def extra_state_attributes(self):
        payments = self._payments()
        return {
            "orders": payments.get("orders", [])[:10],
            "balances": payments.get("balances", [])[:10],
            "installments": payments.get("installments", [])[:10],
        }


class MCASOutstandingBalanceSensor(MCASSensorBase):
    _attr_name = "Outstanding balance"
    _attr_icon = "mdi:cash-multiple"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "GBP"

    def __init__(self, coordinator, entry, child_key, profile):
        super().__init__(coordinator, entry, child_key, profile, "outstanding_balance")

    @property
    def native_value(self):
        payments = _payment_data(self.coordinator.data, self.child_key)
        values = [
            amount
            for item in payments.get("balances", [])
            if isinstance(item, dict)
            and (amount := _money(item.get("outstanding"))) is not None
        ]
        return round(sum(values), 2) if values else 0.0


class MCASDinnerBalanceSensor(MCASSensorBase):
    _attr_name = "Dinner balance"
    _attr_icon = "mdi:food"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "GBP"

    def __init__(self, coordinator, entry, child_key, profile):
        super().__init__(coordinator, entry, child_key, profile, "dinner_balance")

    @property
    def native_value(self):
        payments = _payment_data(self.coordinator.data, self.child_key)
        values = [
            amount
            for item in payments.get("student_balances", [])
            if isinstance(item, dict)
            and (amount := _money(item.get("dinner_balance"))) is not None
        ]
        return round(sum(values), 2) if values else None


class MCASClubBalanceSensor(MCASSensorBase):
    _attr_name = "Club balance"
    _attr_icon = "mdi:account-group"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "GBP"

    def __init__(self, coordinator, entry, child_key, profile):
        super().__init__(coordinator, entry, child_key, profile, "club_balance")

    @property
    def native_value(self):
        payments = _payment_data(self.coordinator.data, self.child_key)
        values = [
            amount
            for item in payments.get("student_balances", [])
            if isinstance(item, dict)
            and (amount := _money(item.get("club_balance"))) is not None
        ]
        return round(sum(values), 2) if values else None

    @property
    def extra_state_attributes(self):
        payments = _payment_data(self.coordinator.data, self.child_key)
        clubs = []
        for item in payments.get("student_balances", []):
            if not isinstance(item, dict):
                continue
            detail = {}
            if item.get("club_id") is not None:
                detail["club_id"] = item.get("club_id")
            if item.get("club_name"):
                detail["club_name"] = item.get("club_name")
            if item.get("club_balance") is not None:
                detail["balance"] = item.get("club_balance")
            if detail:
                clubs.append(detail)
        return {"clubs": clubs[:10]}


class MCASNextPaymentDueSensor(MCASSensorBase):
    _attr_name = "Next payment due"
    _attr_icon = "mdi:calendar-cash"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, entry, child_key, profile):
        super().__init__(coordinator, entry, child_key, profile, "next_payment_due")

    def _next(self):
        candidates: list[tuple[datetime, dict[str, Any]]] = []
        payments = _payment_data(self.coordinator.data, self.child_key)
        for item in payments.get("installments", []):
            if not isinstance(item, dict) or bool(item.get("paid")):
                continue
            due = parse_local_datetime(item.get("due"))
            if due is not None and due >= dt_util.now():
                candidates.append((due, item))
        return min(candidates, key=lambda value: value[0]) if candidates else None

    @property
    def native_value(self) -> datetime | None:
        item = self._next()
        return None if item is None else item[0]

    @property
    def extra_state_attributes(self):
        item = self._next()
        if item is None:
            return {}
        due, payment = item
        attrs = {"due": due.isoformat()}
        if payment.get("name"):
            attrs["name"] = payment.get("name")
        if payment.get("amount") is not None:
            attrs["amount"] = payment.get("amount")
        return attrs


class MCASBehaviourPointsSensor(MCASSensorBase):
    _attr_name = "Behaviour points"
    _attr_icon = "mdi:star-circle"

    def __init__(self, coordinator, entry, child_key, profile):
        super().__init__(coordinator, entry, child_key, profile, "behaviour_points")

    def _summary(self):
        rows = _child_payload(self.coordinator.data, self.child_key, "behaviour").get("Table4", [])
        return rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else None

    @property
    def native_value(self):
        summary = self._summary()
        if not summary:
            return None
        try:
            return int(summary.get("ShowTotalPointsAllTime"))
        except (TypeError, ValueError):
            return summary.get("ShowTotalPointsAllTime")

    @property
    def extra_state_attributes(self):
        summary = self._summary()
        if not summary:
            return {}
        return {
            "positive_points_all_time": summary.get("PositivePointsAllTime"),
            "negative_points_all_time": summary.get("NegativePointsAllTime"),
        }


class MCASLatestBehaviourSensor(MCASSensorBase):
    _attr_name = "Latest behaviour"
    _attr_icon = "mdi:account-star"

    def __init__(self, coordinator, entry, child_key, profile):
        super().__init__(coordinator, entry, child_key, profile, "latest_behaviour")

    def _latest(self):
        rows = _child_payload(
            self.coordinator.data, self.child_key, "behaviour_chronological"
        ).get("StudentEventsList", [])
        return rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else None

    @property
    def native_value(self):
        item = self._latest()
        return None if item is None else item.get("EventName") or item.get("EventType")

    @property
    def extra_state_attributes(self):
        item = self._latest()
        if not item:
            return {}
        return {
            "event_date": item.get("EventDate"),
            "event_type": item.get("EventType"),
            "points": item.get("Adjustment"),
            "subject": item.get("Subject"),
            "class": item.get("Class"),
            "owner": item.get("Owner"),
            "comments": item.get("Comments"),
        }
