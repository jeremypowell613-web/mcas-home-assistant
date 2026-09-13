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

class MCASDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, clients: dict[tuple[str, str], MCASClient], entry: ConfigEntry) -> None:
        super().__init__(hass, logger=_LOGGER, name=DOMAIN, update_interval=DEFAULT_UPDATE_INTERVAL, config_entry=entry)
        self.clients = clients
        self.entry = entry

    async def _async_update_data(self) -> dict[str, Any]:
        all_children = self.entry.data.get(CONF_CHILDREN, [])
        selected = set(self.entry.options.get(CONF_SELECTED_CHILDREN, [_child_key(c) for c in all_children]))
        result: dict[str, Any] = {"children": {}}
        calendars: dict[tuple[str, str], dict[str, Any]] = {}
        try:
            for child in all_children:
                key = _child_key(child)
                if key not in selected:
                    continue
                pair = (str(child["school_id"]), str(child["contact_id"]))
                client = self.clients[pair]
                if pair not in calendars:
                    calendars[pair] = await client.async_get_academic_calendar()
                result["children"][key] = {
                    "profile": child,
                    "timetable": await client.async_get_timetable(str(child["student_id"]), _monday(date.today())),
                    "academic_calendar": calendars[pair],
                }
            return result
        except MCASAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except MCASApiError as err:
            raise UpdateFailed(str(err)) from err
