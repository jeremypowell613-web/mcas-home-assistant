"""ARCADIA Integrate MCAS for Home Assistant."""
from __future__ import annotations
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from .api import MCASClient
from .const import CONF_CHILDREN, CONF_PASSWORD, CONF_USERNAME, DOMAIN, PLATFORMS
from .coordinator import MCASDataUpdateCoordinator

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = async_get_clientsession(hass)
    clients: dict[tuple[str, str], MCASClient] = {}
    for child in entry.data.get(CONF_CHILDREN, []):
        pair = (str(child["school_id"]), str(child["contact_id"]))
        if pair not in clients:
            clients[pair] = MCASClient(session, school_id=pair[0], contact_id=pair[1], username=entry.data[CONF_USERNAME], password=entry.data[CONF_PASSWORD])
    coordinator = MCASDataUpdateCoordinator(hass, clients, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True

async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded
