"""Config flow for ARCADIA Integrate MCAS."""
from __future__ import annotations

from pathlib import Path
import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MCASApiError, MCASAuthError, MCASClient
from .const import CONF_CHILDREN, CONF_PASSWORD, CONF_SELECTED_CHILDREN, CONF_USERNAME, DOMAIN

_LOGGER = logging.getLogger(__name__)


def _child_key(child: dict[str, Any]) -> str:
    return f"{child['school_id']}:{child['contact_id']}:{child['student_id']}"


def _child_identity(child: dict[str, Any]) -> str:
    """Return a stable identity that ignores duplicate contact records."""
    return f"{child['school_id']}:{child['student_id']}"


def _extract_children(
    users: list[dict[str, Any]], school_id: str, contact_id: str
) -> list[dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    for user in users:
        students = user.get("Students") if isinstance(user, dict) else None
        if not isinstance(students, list):
            students = [user] if isinstance(user, dict) and user.get("StudentID") else []
        for student in students:
            if not isinstance(student, dict):
                continue
            sid = student.get("StudentID") or student.get("ID")
            if not sid:
                continue
            name = (
                student.get("PreferredFullName")
                or " ".join(
                    filter(None, [student.get("FirstName"), student.get("LastName")])
                )
                or f"Student {sid}"
            )
            child = {
                "student_id": str(sid),
                "school_id": str(student.get("SchoolID") or school_id),
                "contact_id": str(contact_id),
                "name": str(name),
                "school_name": str(student.get("SchoolName") or "MCAS School"),
            }
            found[_child_key(child)] = child
    return list(found.values())


def _dedupe_children(children: list[dict[str, str]]) -> list[dict[str, str]]:
    """Collapse duplicate MCAS contact records for the same child at a school."""
    unique: dict[str, dict[str, str]] = {}
    for child in children:
        unique.setdefault(_child_identity(child), child)
    return list(unique.values())


def _selected_for_discovered(
    stored_children: list[dict[str, Any]],
    stored_selected: list[str],
    discovered: list[dict[str, str]],
) -> list[str]:
    """Map old selections onto newly de-duplicated discovered children."""
    selected_identities = {
        _child_identity(child)
        for child in stored_children
        if _child_key(child) in set(stored_selected)
    }
    if not selected_identities:
        selected_identities = {_child_identity(child) for child in discovered}
    return [
        _child_key(child)
        for child in discovered
        if _child_identity(child) in selected_identities
    ]


def _selected_identities(
    children: list[dict[str, Any]], selected_keys: list[str] | set[str]
) -> set[str]:
    """Return stable child identities for a selection of child keys."""
    selected = set(selected_keys)
    return {
        _child_identity(child)
        for child in children
        if _child_key(child) in selected
    }


async def _async_remove_deselected_children(
    hass,
    entry,
    stored_children: list[dict[str, Any]],
    stored_selected: list[str],
    discovered_children: list[dict[str, Any]],
    new_selected: list[str],
) -> None:
    """Remove registry entries belonging to children explicitly deselected by the user."""
    previous_identities = _selected_identities(stored_children, stored_selected)
    new_identities = _selected_identities(discovered_children, new_selected)
    removed_identities = previous_identities - new_identities
    if not removed_identities:
        return

    removed_keys = {
        _child_key(child)
        for child in stored_children
        if _child_identity(child) in removed_identities
    }

    entity_registry = er.async_get(hass)
    for entity in list(entity_registry.entities.values()):
        if entity.config_entry_id != entry.entry_id:
            continue
        unique_id = str(entity.unique_id or "")
        if any(
            unique_id.startswith(f"{entry.entry_id}_{child_key}_")
            for child_key in removed_keys
        ):
            entity_registry.async_remove(entity.entity_id)

    device_registry = dr.async_get(hass)
    for child_key in removed_keys:
        device = device_registry.async_get_device(identifiers={(DOMAIN, child_key)})
        if device is not None:
            device_registry.async_remove_device(device.id)

    _LOGGER.info(
        "Removed Home Assistant registry entries for %d deselected MCAS child device(s)",
        len(removed_keys),
    )


async def _discover(hass, username: str, password: str) -> list[dict[str, str]]:
    session = async_get_clientsession(hass)
    contacts = await MCASClient.async_discover_school_contacts(session, username)
    if not contacts:
        raise MCASAuthError("No MCAS schools found for this account")
    children: list[dict[str, str]] = []
    for contact in contacts:
        client = MCASClient(
            session,
            school_id=contact.school_id,
            contact_id=contact.contact_id,
            username=username,
            password=password,
        )
        await client.authenticate()
        children.extend(
            _extract_children(
                await client.async_get_users(), contact.school_id, contact.contact_id
            )
        )
    children = _dedupe_children(children)
    if not children:
        raise MCASApiError("MCAS login succeeded but no linked children could be parsed")
    return children


class MCASConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2

    def __init__(self) -> None:
        self._credentials: dict[str, str] = {}
        self._children: list[dict[str, str]] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors = {}
        if user_input is not None:
            try:
                self._children = await _discover(
                    self.hass, user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
                )
            except MCASAuthError:
                errors["base"] = "invalid_auth"
            except MCASApiError as err:
                errors["base"] = "cannot_connect"
                _LOGGER.error("ARCADIA MCAS discovery failed: %s", err)
                Path("/config/mcas-debug.txt").write_text(
                    "MCASApiError: " + str(err) + "\n"
                )
            except Exception as err:
                _LOGGER.exception("ARCADIA MCAS setup failed unexpectedly")
                Path("/config/mcas-debug.txt").write_text(
                    type(err).__name__ + ": " + str(err) + "\n"
                )
                errors["base"] = "cannot_connect"
            else:
                self._credentials = dict(user_input)
                await self.async_set_unique_id(
                    user_input[CONF_USERNAME].strip().casefold()
                )
                self._abort_if_unique_id_configured()
                return await self.async_step_children()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): selector.TextSelector(
                        selector.TextSelectorConfig()
                    ),
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_children(self, user_input: dict[str, Any] | None = None):
        options = [
            selector.SelectOptionDict(
                value=_child_key(c), label=f"{c['name']} — {c['school_name']}"
            )
            for c in self._children
        ]
        if user_input is not None:
            selected = user_input[CONF_SELECTED_CHILDREN]
            if not selected:
                return self.async_show_form(
                    step_id="children",
                    data_schema=self._children_schema(options),
                    errors={"base": "select_child"},
                )
            return self.async_create_entry(
                title="ARCADIA Integrate MCAS",
                data={**self._credentials, CONF_CHILDREN: self._children},
                options={CONF_SELECTED_CHILDREN: selected},
            )
        return self.async_show_form(
            step_id="children", data_schema=self._children_schema(options)
        )

    def _children_schema(self, options):
        return vol.Schema(
            {
                vol.Required(
                    CONF_SELECTED_CHILDREN,
                    default=[o["value"] for o in options],
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=options, multiple=True)
                )
            }
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        # Home Assistant supplies the config entry through OptionsFlow.config_entry.
        return MCASOptionsFlow()

    async def async_step_reauth(self, entry_data):
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                children = await _discover(
                    self.hass,
                    self._reauth_entry.data[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
            except MCASAuthError:
                errors["base"] = "invalid_auth"
            except MCASApiError as err:
                errors["base"] = "cannot_connect"
                _LOGGER.error("ARCADIA MCAS discovery failed: %s", err)
                Path("/config/mcas-debug.txt").write_text(
                    "MCASApiError: " + str(err) + "\n"
                )
            except Exception as err:
                _LOGGER.exception("ARCADIA MCAS setup failed unexpectedly")
                Path("/config/mcas-debug.txt").write_text(
                    type(err).__name__ + ": " + str(err) + "\n"
                )
                errors["base"] = "cannot_connect"
            else:
                data = {
                    **self._reauth_entry.data,
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                    CONF_CHILDREN: children,
                }
                return self.async_update_reload_and_abort(
                    self._reauth_entry, data=data
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        )
                    )
                }
            ),
            errors=errors,
        )


def _health_summary(hass, entry) -> str:
    """Return a safe human-readable health summary for the options flow."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        return "Latest integration health: not available until the integration has loaded."
    diagnostics = (coordinator.data or {}).get("_diagnostics", {})
    warnings = diagnostics.get("warnings", []) if isinstance(diagnostics, dict) else []
    if not warnings:
        return "Latest integration health: OK — no unexpected responses were recorded on the last refresh."
    lines = ["Latest integration health: attention needed."]
    lines.extend(f"• {warning}" for warning in warnings[:6])
    if len(warnings) > 6:
        lines.append(f"• plus {len(warnings) - 6} more warning(s) in the Home Assistant log")
    return "\n".join(lines)


class MCASOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        try:
            children = await _discover(
                self.hass,
                self.config_entry.data[CONF_USERNAME],
                self.config_entry.data[CONF_PASSWORD],
            )
        except (MCASApiError, MCASAuthError):
            return self.async_abort(reason="cannot_connect")
        except Exception:
            _LOGGER.exception("ARCADIA MCAS options discovery failed unexpectedly")
            return self.async_abort(reason="cannot_connect")

        stored_children = self.config_entry.data.get(CONF_CHILDREN, [])
        stored_selected = list(
            self.config_entry.options.get(
                CONF_SELECTED_CHILDREN,
                [_child_key(c) for c in stored_children],
            )
        )
        selected = _selected_for_discovered(
            stored_children, stored_selected, children
        )

        choices = [
            selector.SelectOptionDict(
                value=_child_key(c), label=f"{c['name']} — {c['school_name']}"
            )
            for c in children
        ]
        if user_input is not None:
            new_selected = list(user_input.get(CONF_SELECTED_CHILDREN, []))
            if not new_selected:
                return self.async_show_form(
                    step_id="init",
                    description_placeholders={"health_summary": _health_summary(self.hass, self.config_entry)},
                    data_schema=vol.Schema(
                        {
                            vol.Required(
                                CONF_SELECTED_CHILDREN, default=selected
                            ): selector.SelectSelector(
                                selector.SelectSelectorConfig(
                                    options=choices, multiple=True
                                )
                            )
                        }
                    ),
                    errors={"base": "select_child"},
                )

            await _async_remove_deselected_children(
                self.hass,
                self.config_entry,
                stored_children,
                stored_selected,
                children,
                new_selected,
            )
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data, CONF_CHILDREN: children},
            )
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            description_placeholders={"health_summary": _health_summary(self.hass, self.config_entry)},
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SELECTED_CHILDREN, default=selected
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=choices, multiple=True
                        )
                    )
                }
            ),
        )
