# Copyright (C) 2026 Jeremy Powell
# ARCADIA Integrate MCAS
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE and NOTICE in this integration directory.

"""Constants for the MCAS integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "mcas"
PLATFORMS = ["sensor", "binary_sensor", "calendar", "update"]

INTEGRATION_VERSION = "2.3.0"
GITHUB_REPOSITORY = "jeremypowell613-web/mcas-home-assistant"
GITHUB_RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"
GITHUB_RELEASE_URL = f"https://github.com/{GITHUB_REPOSITORY}/releases"

API_BASE = "https://appsapi.bromcom.com/Nucleus/api"
DISCOVERY_BASE = "https://cloudmis.bromcom.com/Nucleus/api"
TOKEN_PATH = "/token"
SCHOOL_CONTACT_PATH = "/api/v1/mcas/user/schoolcontactinfoV2"
USER_LIST_PATH = "/api/v1/mcas/user/userList"
TIMETABLE_PATH = "/api/v1/timetable/mcas/studentTimetableByWeekStart"
TIMETABLE_YEARS_PATH = "/api/v1/timetable/mcas/years/{student_id}"
ACADEMIC_CALENDAR_PATH = "/api/v1/calendars/mcas/academiccalendar"
ATTENDANCE_PATH = "/api/v1/attendance/mcas/details/{student_id}/{year_id}/-1"
HOMEWORK_PATH = "/api/v1/mcas/homework/extendeddetails/{student_id}/{day}/{month}/{year}"
HOMEWORK_ASSIGNMENTS_PATH = "/api/v1/mcas/assignments"
HOMEWORK_BEHAVIOUR_PATH = "/api/v1/mcas/homework/behaviour"\nPAYMENTS_OUTSTANDING_PATH = "/api/v1/mcas/payments/FindOutstandingPayments"\nPAYMENTS_BALANCES_PATH = "/api/v1/mcas/payments/FindOutstandingBalances"\nPAYMENTS_INSTALLMENTS_PATH = "/api/v1/mcas/payments/findProductsAndPaymentInstalments"\nPAYMENTS_STUDENT_BALANCES_PATH = "/api/v1/mcas/payments/getBalancesForStudents"
SCHOOL_CONFIG_PATH = "/api/v1/school/config"
SCHOOL_CONFIG_KEYS = (
    "MCASHomeworkModuleHomeworkModeIsExtended",
    "MCASoffice365OrGoogleAssignmentsEnabled",
)
BEHAVIOUR_PATH = "/api/v1/eventRecords/mcas/eventdetails/{student_id}/{year_id}"
BEHAVIOUR_CHRONOLOGICAL_PATH = "/api/v1/eventRecords/mcas/chronologicalEventDetails/{student_id}/{year_id}/-1/0"

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
USER_AGENT = "HomeAssistant-Arcadia-MCAS/2.3.0"
