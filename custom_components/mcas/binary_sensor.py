"""Binary sensors for ARCADIA Integrate MCAS."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import MCASDataUpdateCoordinator
from .helpers import academic_day_for, device_info, is_school_day


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: MCASDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[BinarySensorEntity] = []
    for child_key, child_data in coordinator.data.get("children", {}).items():
        profile = child_data["profile"]
        entities.extend(
            [
                MCASSchoolDayBinarySensor(coordinator, entry, child_key, profile, 0),
                MCASSchoolDayBinarySensor(coordinator, entry, child_key, profile, 1),
            ]
        )
    async_add_entities(entities)


class MCASSchoolDayBinarySensor(
    CoordinatorEntity[MCASDataUpdateCoordinator], BinarySensorEntity
):
    _attr_has_entity_name = True
    _attr_icon = "mdi:school"

    def __init__(
        self,
        coordinator: MCASDataUpdateCoordinator,
        entry: ConfigEntry,
        child_key: str,
        profile: dict[str, Any],
        offset_days: int,
    ) -> None:
        super().__init__(coordinator)
        self.child_key = child_key
        self.offset_days = offset_days
        suffix = "today" if offset_days == 0 else "tomorrow"
        self._attr_name = f"School day {suffix}"
        self._attr_unique_id = f"{entry.entry_id}_{child_key}_school_day_{suffix}"
        self._attr_device_info = device_info(profile, child_key)

    @property
    def is_on(self) -> bool:
        target = dt_util.now().date() + timedelta(days=self.offset_days)
        item = academic_day_for(self.coordinator.data, self.child_key, target)
        return is_school_day(item)

    @property
    def extra_state_attributes(self):
        target = dt_util.now().date() + timedelta(days=self.offset_days)
        item = academic_day_for(self.coordinator.data, self.child_key, target)
        if not item:
            return {"date": target.isoformat(), "status": None}
        return {
            "date": target.isoformat(),
            "status": item.get("DayStatusDescription"),
            "status_code": item.get("DayStatusCode"),
        }
