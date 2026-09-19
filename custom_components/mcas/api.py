"""Async read-only MCAS API client."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from aiohttp import ClientResponseError, ClientSession

from .const import (
    ACADEMIC_CALENDAR_PATH,
    API_BASE,
    APPLICATION_ID,
    APPLICATION_SECRET,
    ATTENDANCE_PATH,
    BEHAVIOUR_CHRONOLOGICAL_PATH,
    BEHAVIOUR_PATH,
    DISCOVERY_BASE,
    HOMEWORK_ASSIGNMENTS_PATH,
    HOMEWORK_BEHAVIOUR_PATH,
    HOMEWORK_PATH,
    SCHOOL_CONFIG_KEYS,
    SCHOOL_CONFIG_PATH,
    SCHOOL_CONTACT_PATH,
    TIMETABLE_PATH,
    TIMETABLE_YEARS_PATH,
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


def _walk_dicts(value: Any):
    """Yield every mapping contained in an arbitrary JSON-compatible value."""
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


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
            raise MCASApiError(f"MCAS school discovery failed: {err.status}") from err

        contacts: dict[tuple[str, str], MCASSchoolContact] = {}
        for item in _walk_dicts(data):
            school_id = item.get("SchoolID") or item.get("schoolID") or item.get("schoolId")
            contact_id = item.get("ContactID") or item.get("contactID") or item.get("contactId")
            if school_id and contact_id:
                pair = (str(school_id), str(contact_id))
                contacts[pair] = MCASSchoolContact(*pair)
        return list(contacts.values())

    async def async_get_hashed_password(self) -> str:
        payload = {
            "ApplicationId": APPLICATION_ID,
            "ApplicationSecret": APPLICATION_SECRET,
            "ApiSource": "app",
            "Password": self.password,
        }
        try:
            async with self._session.post(
                f"{DISCOVERY_BASE}/api/v1/mcas/user/hashpasswordV2",
                json=payload,
                headers={"User-Agent": USER_AGENT},
            ) as response:
                if response.status in (400, 401, 403):
                    raise MCASAuthError("MCAS rejected the supplied credentials")
                response.raise_for_status()
                try:
                    data = await response.json()
                except (ValueError, TypeError):
                    data = (await response.text()).strip().strip('"')
        except ClientResponseError as err:
            raise MCASApiError(f"MCAS password hashing failed: {err.status}") from err

        if isinstance(data, str):
            hashed_password = data.strip().strip('"')
        else:
            hashed_password = str(data or "").strip().strip('"')
        if not hashed_password:
            raise MCASApiError("MCAS password hashing returned an empty value")
        return hashed_password

    async def authenticate(self) -> MCASToken:
        password_hash = await self.async_get_hashed_password()
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
                f"{API_BASE}{TOKEN_PATH}", data=payload, headers={"User-Agent": USER_AGENT}
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
        async with self._session.get(f"{API_BASE}{path}", headers=headers, params=params) as response:
            if response.status == 401:
                await self.authenticate()
                assert self._token is not None
                headers["Authorization"] = f"Bearer {self._token.access_token}"
                async with self._session.get(f"{API_BASE}{path}", headers=headers, params=params) as retry:
                    retry.raise_for_status()
                    return await retry.json()
            response.raise_for_status()
            return await response.json()

    async def async_get_users(self, *, include_photos: bool = False) -> list[dict[str, Any]]:
        data = await self._get(
            USER_LIST_PATH,
            params={"includeStudentPhotosData": str(include_photos).lower()},
        )
        records: list[dict[str, Any]] = []
        seen: set[int] = set()
        for item in _walk_dicts(data):
            if item.get("StudentID") or item.get("studentID") or item.get("studentId"):
                marker = id(item)
                if marker not in seen:
                    seen.add(marker)
                    records.append(item)
            students = item.get("Students") or item.get("students")
            if isinstance(students, list):
                marker = id(item)
                if marker not in seen:
                    seen.add(marker)
                    records.append(item)
        return records

    async def async_get_timetable(self, student_id: str, week_start: date) -> dict[str, Any]:
        return await self._get(
            TIMETABLE_PATH,
            params={
                "studentid": str(student_id),
                "year": week_start.year,
                "month": week_start.month,
                "date": week_start.day,
            },
        )

    async def async_get_years(self, student_id: str) -> dict[str, Any]:
        return await self._get(TIMETABLE_YEARS_PATH.format(student_id=student_id))

    async def async_get_academic_calendar(self) -> dict[str, Any]:
        return await self._get(ACADEMIC_CALENDAR_PATH)

    async def async_get_attendance(self, student_id: str, year_id: str) -> dict[str, Any]:
        return await self._get(ATTENDANCE_PATH.format(student_id=student_id, year_id=year_id))

    async def async_get_homework(self, student_id: str, day: date) -> dict[str, Any]:
        """Return the extended-homework payload used by schools in extended mode."""
        return await self._get(
            HOMEWORK_PATH.format(
                student_id=student_id,
                day=day.day,
                month=day.month,
                year=day.year,
            )
        )

    async def async_get_school_config(self) -> dict[str, Any]:
        """Return the homework-related school configuration flags."""
        return await self._get(
            SCHOOL_CONFIG_PATH,
            params={"keys": ",".join(SCHOOL_CONFIG_KEYS)},
        )

    async def _probe_get(
        self, path: str, *, params: dict[str, Any] | None = None
    ) -> tuple[int, Any]:
        """GET an observed candidate endpoint without making a missing variant fatal."""
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

        async def request() -> tuple[int, Any]:
            async with self._session.get(
                f"{API_BASE}{path}", headers=headers, params=params
            ) as response:
                status = response.status
                if status == 401:
                    return status, None
                if status >= 400:
                    return status, {}
                try:
                    return status, await response.json()
                except (ValueError, TypeError):
                    return status, {}

        status, data = await request()
        if status == 401:
            await self.authenticate()
            assert self._token is not None
            headers["Authorization"] = f"Bearer {self._token.access_token}"
            status, data = await request()
        return status, data

    async def async_get_homework_assignments_candidates(
        self, student_id: str, day: date
    ) -> list[tuple[str, int, Any]]:
        """Probe official-client assignment endpoint forms observed across MCAS versions."""
        query = {
            "studentid": str(student_id),
            "year": day.year,
            "month": day.month,
            "date": day.day,
        }
        path_style = (
            f"{HOMEWORK_ASSIGNMENTS_PATH}/{student_id}/{day.day}/{day.month}/{day.year}"
        )
        attempts: list[tuple[str, int, Any]] = []
        status, payload = await self._probe_get(path_style)
        attempts.append(("assignments-path", status, payload))
        if status >= 400 or not payload:
            status, payload = await self._probe_get(
                f"{HOMEWORK_ASSIGNMENTS_PATH}/", params=query
            )
            attempts.append(("assignments-query", status, payload))
        return attempts

    async def async_get_homework_behaviour_candidates(
        self, student_id: str, day: date
    ) -> list[tuple[str, int, Any]]:
        """Probe official-client behaviour-homework endpoint forms."""
        query = {
            "studentid": str(student_id),
            "year": day.year,
            "month": day.month,
            "date": day.day,
        }
        path_style = (
            f"{HOMEWORK_BEHAVIOUR_PATH}/{student_id}/{day.day}/{day.month}/{day.year}"
        )
        attempts: list[tuple[str, int, Any]] = []
        status, payload = await self._probe_get(path_style)
        attempts.append(("behaviour-path", status, payload))
        if status >= 400 or not payload:
            status, payload = await self._probe_get(
                f"{HOMEWORK_BEHAVIOUR_PATH}/", params=query
            )
            attempts.append(("behaviour-query", status, payload))
        return attempts

    async def async_get_behaviour(self, student_id: str, year_id: str) -> dict[str, Any]:
        return await self._get(BEHAVIOUR_PATH.format(student_id=student_id, year_id=year_id))

    async def async_get_behaviour_chronological(self, student_id: str, year_id: str) -> dict[str, Any]:
        return await self._get(
            BEHAVIOUR_CHRONOLOGICAL_PATH.format(student_id=student_id, year_id=year_id)
        )
