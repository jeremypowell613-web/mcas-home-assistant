"""Data coordinator for MCAS."""

from __future__ import annotations

from datetime import date, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import MCASApiError, MCASClient
from .const import CONF_STUDENT_ID, DEFAULT_UPDATE_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


class MCASDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch and cache MCAS data for one Home Assistant config entry."""

    def __init__(
        self, hass: HomeAssistant, client: MCASClient, entry: ConfigEntry
    ) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_UPDATE_INTERVAL,
            config_entry=entry,
        )
        self.client = client
        self.entry = entry

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            users = await self.client.async_get_users()
            student_id = self.entry.data.get(CONF_STUDENT_ID) or _first_student_id(users)
            if not student_id:
                raise UpdateFailed("MCAS returned no linked student")

            today = date.today()
            timetable = await self.client.async_get_timetable(
                str(student_id), _monday(today)
            )
            academic_calendar = await self.client.async_get_academic_calendar()
            return {
                "student_id": str(student_id),
                "users": users,
                "timetable": timetable,
                "academic_calendar": academic_calendar,
            }
        except MCASApiError as err:
            raise UpdateFailed(str(err)) from err


def _first_student_id(users: list[dict[str, Any]]) -> str | None:
    """Extract the first linked student id without depending on one MCAS payload shape."""
    for user in users:
        direct = user.get("StudentID")
        if direct:
            return str(direct)
        students = user.get("Students") or []
        if isinstance(students, list):
            for student in students:
                if not isinstance(student, dict):
                    continue
                value = student.get("StudentID") or student.get("ID")
                if value:
                    return str(value)
    return None
