"""Config flow for MCAS."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MCASAuthError, MCASClient
from .const import CONF_APPLICATION_ID, CONF_APPLICATION_SECRET, CONF_CONTACT_ID, CONF_PASSWORD, CONF_SCHOOL_ID, CONF_USERNAME, DOMAIN


class MCASConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle an MCAS config flow."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            client = MCASClient(
                async_get_clientsession(self.hass),
                school_id=user_input[CONF_SCHOOL_ID],
                contact_id=user_input[CONF_CONTACT_ID],
                username=user_input[CONF_USERNAME],
                password=user_input[CONF_PASSWORD],
                application_id=user_input[CONF_APPLICATION_ID],
                application_secret=user_input[CONF_APPLICATION_SECRET],
            )
            try:
                await client.authenticate()
            except MCASAuthError:
                errors["base"] = "invalid_auth"
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(f"{user_input[CONF_SCHOOL_ID]}-{user_input[CONF_CONTACT_ID]}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=f"MCAS {user_input[CONF_USERNAME]}", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Required(CONF_SCHOOL_ID): str,
                vol.Required(CONF_CONTACT_ID): str,
                vol.Required(CONF_APPLICATION_ID): str,
                vol.Required(CONF_APPLICATION_SECRET): str,
            }),
            errors=errors,
        )
