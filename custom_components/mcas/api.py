"""Async read-only MCAS API client."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import date
from typing import Any

from aiohttp import ClientResponseError, ClientSession

from .const import (
    ACADEMIC_CALENDAR_PATH,
    API_BASE,
    APPLICATION_ID,
    APPLICATION_SECRET,
    DISCOVERY_BASE,
    SCHOOL_CONTACT_PATH,
    TIMETABLE_PATH,
    TOKEN_PATH,
    USER_AGENT,
    USER_LIST_PATH,
)


class MCASApiError(Exception):
    """Base MCAS client error."""


class MCASAuthError(MCASApiError):
    """Raised when MCAS authentication fails."""


@dataclass(slots=True, frozen=True)
class MCASSchoolContact:
    school_id: str
    contact_id: str


@dataclass(slots=True)
class MCASToken:
    access_token: str
    expires_in: int
    school_scope: Any | None = None


class MCASClient:
    """Client for the read-only MCAS endpoints observed in official client traffic."""

    def __init__(
        self,
        session: ClientSession,
        *,
        school_id: str,
        contact_id: str,
        username: str,
        password: str,
    ) -> None:
        self._session = session
        self.school_id = str(school_id)
        self.contact_id = str(contact_id)
        self.username = username
        self.password = password
        self._token: MCASToken | None = None

    @staticmethod
    async def async_discover_school_contacts(
        session: ClientSession, email: str
    ) -> list[MCASSchoolContact]:
        """Resolve MCAS school/contact pairs for a parent email address."""
        payload = {
            "ApplicationId": APPLICATION_ID,
            "ApplicationSecret": APPLICATION_SECRET,
            "ApiSource": "app",
            "Email": email,
        }
        try:
            async with session.post(
                f"{DISCOVERY_BASE}{SCHOOL_CONTACT_PATH}",
                json=payload,
                headers={"User-Agent": USER_AGENT},
            ) as response:
                response.raise_for_status()
                data = await response.json()
        except ClientResponseError as err:
            raise MCASApiError(
                f"MCAS school discovery failed: {err.status}"
            ) from err

        contacts: list[MCASSchoolContact] = []
        if isinstance(data, dict):
            data = data.get("Table") or data.get("Data") or data.get("data") or []
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                school_id = item.get("SchoolID") or item.get("schoolID") or item.get("schoolId")
                contact_id = item.get("ContactID") or item.get("contactID") or item.get("contactId")
                if school_id and contact_id:
                    contacts.append(MCASSchoolContact(str(school_id), str(contact_id)))
        return contacts

    async def authenticate(self) -> MCASToken:
        """Authenticate using the password transform used by the official MCAS client."""
        password_hash = base64.b64encode(
            hashlib.sha256(self.password.encode("utf-8")).digest()
        ).decode("ascii")
        payload = {
            "schoolid": self.school_id,
            "username": self.username,
            "password": password_hash,
            "grant_type": "password",
            "apiSource": "app",
            "userType": "mcas",
            "application_id": APPLICATION_ID,
            "application_secret": APPLICATION_SECRET,
            "ipAddress": "127.0.0.1",
            "mcasParentLoginFromMIS": "false",
            "isPasswordHash": "True",
        }
        try:
            async with self._session.post(
                f"{API_BASE}{TOKEN_PATH}",
                data=payload,
                headers={"User-Agent": USER_AGENT},
            ) as response:
                if response.status in (400, 401, 403):
                    raise MCASAuthError("MCAS rejected the supplied credentials")
                response.raise_for_status()
                data = await response.json()
        except ClientResponseError as err:
            raise MCASApiError(f"MCAS token request failed: {err.status}") from err

        token = data.get("access_token")
        if not token:
            raise MCASAuthError("MCAS token response did not contain an access token")

        self._token = MCASToken(
            access_token=token,
            expires_in=int(data.get("expires_in", 0)),
            school_scope=data.get("school_scope"),
        )
        return self._token

    async def _get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        if self._token is None:
            await self.authenticate()
        assert self._token is not None
        headers = {
            "Authorization": f"Bearer {self._token.access_token}",
            "SchoolID": self.school_id,
            "ContactID": self.contact_id,
            "ProxyType": "mcas",
            "User-Agent": USER_AGENT,
        }
        async with self._session.get(
            f"{API_BASE}{path}", headers=headers, params=params
        ) as response:
            if response.status == 401:
                await self.authenticate()
                assert self._token is not None
                headers["Authorization"] = f"Bearer {self._token.access_token}"
                async with self._session.get(
                    f"{API_BASE}{path}", headers=headers, params=params
                ) as retry:
                    retry.raise_for_status()
                    return await retry.json()
            response.raise_for_status()
            return await response.json()

    async def async_get_users(self, *, include_photos: bool = False) -> list[dict[str, Any]]:
        data = await self._get(
            USER_LIST_PATH,
            params={"includeStudentPhotosData": str(include_photos).lower()},
        )
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("Table", "Users", "Students", "Data", "data"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
        return []

    async def async_get_timetable(
        self, student_id: str, week_start: date
    ) -> dict[str, Any]:
        return await self._get(
            TIMETABLE_PATH,
            params={
                "studentid": str(student_id),
                "year": week_start.year,
                "month": week_start.month,
                "date": week_start.day,
            },
        )

    async def async_get_academic_calendar(self) -> dict[str, Any]:
        return await self._get(ACADEMIC_CALENDAR_PATH)
