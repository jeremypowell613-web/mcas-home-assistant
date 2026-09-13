"""Constants for the MCAS integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "mcas"
PLATFORMS = ["sensor"]

API_BASE = "https://appsapi.bromcom.com/Nucleus/api"
DISCOVERY_BASE = "https://cloudmis.bromcom.com/Nucleus/api"
TOKEN_PATH = "/token"
SCHOOL_CONTACT_PATH = "/api/v1/mcas/user/schoolcontactinfoV2"
USER_LIST_PATH = "/api/v1/mcas/user/userList"
TIMETABLE_PATH = "/api/v1/timetable/mcas/studentTimetableByWeekStart"
ACADEMIC_CALENDAR_PATH = "/api/v1/calendars/mcas/academiccalendar"

# Public client metadata shipped by the official MCAS mobile client. These values
# identify the MCAS application, not the parent account. Parent credentials and
# bearer tokens are never committed to the repository.
APPLICATION_ID = "52C10C82-077F-4E5A-B8CF-4B91D9A71617"
APPLICATION_SECRET = "IFCCLB7AYyI)^0OMDLG#"

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_CHILDREN = "children"
CONF_SELECTED_CHILDREN = "selected_children"
CONF_SCHOOL_ID = "school_id"
CONF_CONTACT_ID = "contact_id"
CONF_STUDENT_ID = "student_id"
CONF_NAME = "name"
CONF_SCHOOL_NAME = "school_name"

DEFAULT_UPDATE_INTERVAL = timedelta(minutes=30)
USER_AGENT = "HomeAssistant-Arcadia-MCAS/0.2"
