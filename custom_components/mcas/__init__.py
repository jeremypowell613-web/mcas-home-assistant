"""MyChildAtSchool integration for Home Assistant."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MCASClient
from .const import (
    CONF_APPLICATION_ID,
    CONF_APPLICATION_SECRET,
    CONF_CONTACT_ID,
    CONF_PASSWORD,
    CONF_SCHOOL_ID,
    CONF_USERNAME,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import MCASDataUpdateCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up MCAS from a config entry."""
    session = async_get_clientsession(hass)
    client = MCASClient(
        session,
        school_id=entry.data[CONF_SCHOOL_ID],
        contact_id=entry.data[CONF_CONTACT_ID],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        application_id=entry.data[CONF_APPLICATION_ID],
        application_secret=entry.data[CONF_APPLICATION_SECRET],
    )
    coordinator = MCASDataUpdateCoordinator(hass, client, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an MCAS config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded
