"""Async read-only MCAS API client."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from aiohttp import ClientResponseError, ClientSession

from .const import (
    ACADEMIC_CALENDAR_PATH,
    API_BASE,
    TIMETABLE_PATH,
    TOKEN_PATH,
    USER_AGENT,
    USER_LIST_PATH,
)


class MCASApiError(Exception):
    """Base MCAS client error."""


class MCASAuthError(MCASApiError):
    """Raised when MCAS authentication fails."""


@dataclass(slots=True)
class MCASToken:
    access_token: str
    expires_in: int
    school_scope: Any | None = None


class MCASClient:
    """Minimal client for the read-only MCAS endpoints observed in browser traffic."""

    def __init__(
        self,
        session: ClientSession,
        *,
        school_id: str,
        contact_id: str,
        username: str,
        password: str,
        application_id: str,
        application_secret: str,
    ) -> None:
        self._session = session
        self.school_id = str(school_id)
        self.contact_id = str(contact_id)
        self.username = username
        self.password = password
        self.application_id = application_id
        self.application_secret = application_secret
        self._token: MCASToken | None = None

    async def authenticate(self) -> MCASToken:
        """Authenticate using the same form-style token exchange used by MCAS."""
        payload = {
            "schoolid": self.school_id,
            "username": self.username,
            "password": self.password,
            "grant_type": "password",
            "apiSource": "mcas",
            "userType": "parent",
            "application_id": self.application_id,
            "application_secret": self.application_secret,
            "ipAddress": "",
            "mcasParentLoginFromMIS": "false",
            "isPasswordHash": "false",
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
        return data if isinstance(data, list) else []

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
