"""Constants for the MCAS integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "mcas"
PLATFORMS = ["sensor", "calendar"]

API_BASE = "https://appsapi.bromcom.com/Nucleus/api"
TOKEN_PATH = "/token"
USER_LIST_PATH = "/api/v1/mcas/user/userList"
TIMETABLE_PATH = "/api/v1/timetable/mcas/studentTimetableByWeekStart"
ACADEMIC_CALENDAR_PATH = "/api/v1/calendars/mcas/academiccalendar"

CONF_SCHOOL_ID = "school_id"
CONF_CONTACT_ID = "contact_id"
CONF_STUDENT_ID = "student_id"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_APPLICATION_ID = "application_id"
CONF_APPLICATION_SECRET = "application_secret"

DEFAULT_UPDATE_INTERVAL = timedelta(minutes=30)
USER_AGENT = "HomeAssistant-MCAS/0.1"
