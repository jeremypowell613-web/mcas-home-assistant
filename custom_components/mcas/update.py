# Copyright (C) 2026 Jeremy Powell
# ARCADIA Integrate MCAS
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE and NOTICE in this integration directory.

"""Update entity for the MCAS custom integration."""
from __future__ import annotations

from io import BytesIO
import logging
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile
from typing import Any

from aiohttp import ClientResponseError
from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.components import persistent_notification
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    GITHUB_RELEASES_API,
    GITHUB_RELEASE_URL,
    GITHUB_REPOSITORY,
    INTEGRATION_VERSION,
)

_LOGGER = logging.getLogger(__name__)


def _clean_version(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    return value[1:] if value.lower().startswith("v") else value


def _release_summary(body: str | None) -> str | None:
    if not body:
        return None
    compact = " ".join(body.strip().split())
    return compact[:252] + "..." if len(compact) > 255 else compact


def _stage_release_archive(archive: bytes, config_dir: str) -> tuple[str, str]:
    """Extract only custom_components/mcas from a GitHub release archive."""
    config_path = Path(config_dir)
    custom_components = config_path / "custom_components"
    target = custom_components / DOMAIN
    custom_components.mkdir(parents=True, exist_ok=True)

    workdir = Path(tempfile.mkdtemp(prefix="mcas-update-", dir=str(config_path)))
    staged = workdir / DOMAIN
    staged.mkdir(parents=True, exist_ok=True)

    found_files = 0
    try:
        with tarfile.open(fileobj=BytesIO(archive), mode="r:gz") as bundle:
            for member in bundle.getmembers():
                path = PurePosixPath(member.name)
                parts = path.parts
                try:
                    marker = parts.index("custom_components")
                except ValueError:
                    continue
                if len(parts) <= marker + 1 or parts[marker + 1] != DOMAIN:
                    continue

                relative_parts = parts[marker + 2 :]
                if not relative_parts:
                    continue
                if member.issym() or member.islnk():
                    raise ValueError("MCAS release archive contains links")
                if any(part in ("", ".", "..") for part in relative_parts):
                    raise ValueError("MCAS release archive contains an unsafe path")

                destination = staged.joinpath(*relative_parts)
                resolved = destination.resolve()
                if staged.resolve() not in resolved.parents and resolved != staged.resolve():
                    raise ValueError("MCAS release archive attempted path traversal")

                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    continue

                source = bundle.extractfile(member)
                if source is None:
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("wb") as output:
                    shutil.copyfileobj(source, output)
                found_files += 1

        if found_files == 0 or not (staged / "manifest.json").is_file():
            raise ValueError("MCAS release archive did not contain a valid integration")

        backup = workdir / "backup"
        if target.exists():
            shutil.copytree(target, backup)

        try:
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(staged, target)
        except Exception:
            if target.exists():
                shutil.rmtree(target)
            if backup.exists():
                shutil.copytree(backup, target)
            raise

        return str(target), str(workdir)
    except Exception:
        shutil.rmtree(workdir, ignore_errors=True)
        raise


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the MCAS update entity."""
    async_add_entities([MCASIntegrationUpdate(hass, entry)], update_before_add=True)


class MCASIntegrationUpdate(UpdateEntity):
    """Represent updates published as GitHub releases."""

    _attr_has_entity_name = True
    _attr_name = "Integration update"
    _attr_title = "ARCADIA Integrate MCAS"
    _attr_icon = "mdi:update"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_installed_version = INTEGRATION_VERSION
    _attr_supported_features = UpdateEntityFeature.INSTALL | UpdateEntityFeature.RELEASE_NOTES

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._attr_unique_id = f"{entry.entry_id}_integration_update"
        self._attr_latest_version = INTEGRATION_VERSION
        self._attr_release_url = GITHUB_RELEASE_URL
        self._release_notes: str | None = None
        self._archive_url: str | None = None
        self._tag_name: str | None = None
        self._attr_in_progress = False

    async def async_update(self) -> None:
        """Fetch the latest published GitHub release."""
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                GITHUB_RELEASES_API,
                headers={"Accept": "application/vnd.github+json"},
            ) as response:
                if response.status == 404:
                    self._attr_latest_version = INTEGRATION_VERSION
                    self._release_notes = None
                    self._archive_url = None
                    self._tag_name = None
                    return
                response.raise_for_status()
                payload: dict[str, Any] = await response.json()
        except (ClientResponseError, TimeoutError, ValueError) as err:
            _LOGGER.warning("Unable to check MCAS GitHub release: %s", err)
            return

        tag = str(payload.get("tag_name") or "").strip()
        version = _clean_version(tag)
        if not version:
            _LOGGER.warning("MCAS GitHub release did not contain a usable tag")
            return

        self._tag_name = tag
        self._attr_latest_version = version
        self._release_notes = str(payload.get("body") or "") or None
        self._attr_release_summary = _release_summary(self._release_notes)
        self._attr_release_url = str(payload.get("html_url") or GITHUB_RELEASE_URL)
        self._archive_url = str(payload.get("tarball_url") or "") or None

    async def async_release_notes(self) -> str | None:
        """Return cached release notes for the latest release."""
        return self._release_notes

    async def async_install(
        self,
        version: str | None,
        backup: bool,
        **kwargs: Any,
    ) -> None:
        """Install the latest release into /config/custom_components/mcas.

        The running Python module cannot be hot-reloaded safely after its own files
        are replaced, so Home Assistant must be restarted after installation.
        """
        if version and _clean_version(version) != self.latest_version:
            raise ValueError("Installing arbitrary MCAS versions is not supported")
        if not self._archive_url:
            raise ValueError("No downloadable MCAS release is currently available")

        self._attr_in_progress = True
        self.async_write_ha_state()
        session = async_get_clientsession(self.hass)
        workdir: str | None = None
        try:
            async with session.get(
                self._archive_url,
                headers={"Accept": "application/vnd.github+json"},
            ) as response:
                response.raise_for_status()
                archive = await response.read()

            _target, workdir = await self.hass.async_add_executor_job(
                _stage_release_archive,
                archive,
                self.hass.config.config_dir,
            )
            _LOGGER.warning(
                "MCAS %s files installed successfully. Restart Home Assistant to load the new version.",
                self.latest_version,
            )
            persistent_notification.async_create(
                self.hass,
                (
                    f"MCAS has been updated to {self.latest_version}. "
                    "Restart Home Assistant to finish loading the new version. "
                    "Go to Settings → System and restart Home Assistant."
                ),
                title="Restart Home Assistant to finish MCAS update",
                notification_id="mcas_update_restart_required",
            )
        finally:
            self._attr_in_progress = False
            self.async_write_ha_state()
            if workdir:
                await self.hass.async_add_executor_job(shutil.rmtree, workdir, True)
