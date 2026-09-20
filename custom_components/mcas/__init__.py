# Copyright (C) 2026 Jeremy Powell
# ARCADIA Integrate MCAS
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE and NOTICE in this integration directory.

"""ARCADIA Integrate MCAS for Home Assistant."""
from __future__ import annotations

from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MCASClient
from .const import CONF_CHILDREN, CONF_PASSWORD, CONF_USERNAME, DOMAIN, PLATFORMS
from .coordinator import MCASDataUpdateCoordinator


_LICENSE_MARKERS = (
    "GNU GENERAL PUBLIC LICENSE",
    "Version 3",
)
_NOTICE_MARKERS = (
    "Copyright (C) 2026 Jeremy Powell",
    "ARCADIA Integrate MCAS",
    "GPL-3.0-or-later",
)


def _verify_distribution_files() -> None:
    """Refuse startup when required licence/attribution files are missing."""
    integration_dir = Path(__file__).resolve().parent
    required = {
        "LICENSE": _LICENSE_MARKERS,
        "NOTICE": _NOTICE_MARKERS,
    }
    problems: list[str] = []
    for filename, markers in required.items():
        path = integration_dir / filename
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            problems.append(f"{filename} is missing or unreadable")
            continue
        if any(marker not in content for marker in markers):
            problems.append(f"{filename} does not contain the required attribution markers")

    if problems:
        raise ConfigEntryError(
            "ARCADIA Integrate MCAS installation is incomplete: "
            + "; ".join(problems)
            + ". Reinstall the official integration package."
        )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # File I/O must not run in Home Assistant's event loop.
    await hass.async_add_executor_job(_verify_distribution_files)
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
