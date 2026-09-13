"""ARCADIA Integrate MCAS for Home Assistant."""
from __future__ import annotations

from pathlib import Path
import traceback

_DEBUG = Path("/config/mcas-startup-debug.txt")


def _debug(message: str) -> None:
    try:
        with _DEBUG.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")
    except OSError:
        pass


_debug("0 module import started")

try:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from .api import MCASClient
    from .const import CONF_CHILDREN, CONF_PASSWORD, CONF_USERNAME, DOMAIN, PLATFORMS
    from .coordinator import MCASDataUpdateCoordinator
    _debug("0a imports passed")
except Exception as err:
    _debug(f"IMPORT ERROR {type(err).__name__}: {err}")
    _debug(traceback.format_exc())
    raise


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    try:
        _debug("1 setup_entry started")
        session = async_get_clientsession(hass)
        clients: dict[tuple[str, str], MCASClient] = {}
        for child in entry.data.get(CONF_CHILDREN, []):
            pair = (str(child["school_id"]), str(child["contact_id"]))
            if pair not in clients:
                clients[pair] = MCASClient(
                    session,
                    school_id=pair[0],
                    contact_id=pair[1],
                    username=entry.data[CONF_USERNAME],
                    password=entry.data[CONF_PASSWORD],
                )
        _debug(f"2 clients={len(clients)}")

        coordinator = MCASDataUpdateCoordinator(hass, clients, entry)
        _debug("3 coordinator created")
        await coordinator.async_config_entry_first_refresh()
        _debug("4 first refresh passed")

        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
        _debug(f"5 forwarding platforms={PLATFORMS}")
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        _debug("6 platforms loaded")

        entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
        return True
    except Exception as err:
        _debug(f"ERROR {type(err).__name__}: {err}")
        _debug(traceback.format_exc())
        raise


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded
