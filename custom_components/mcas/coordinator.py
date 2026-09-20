# Copyright (C) 2026 Jeremy Powell
# ARCADIA Integrate MCAS
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE and NOTICE in this integration directory.

"""Data coordinator for MCAS."""
from __future__ import annotations

from datetime import date, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import MCASApiError, MCASAuthError, MCASClient
from .const import CONF_CHILDREN, CONF_SELECTED_CHILDREN, DEFAULT_UPDATE_INTERVAL, DOMAIN, INTEGRATION_VERSION

_LOGGER = logging.getLogger(__name__)


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _child_key(child: dict[str, Any]) -> str:
    return f"{child['school_id']}:{child['contact_id']}:{child['student_id']}"


def _merge_timetables(*payloads: Any) -> dict[str, Any]:
    lessons: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        table = payload.get("Table", [])
        if not isinstance(table, list):
            continue
        for lesson in table:
            if not isinstance(lesson, dict):
                continue
            marker = (
                lesson.get("CalendarID"),
                lesson.get("StartDate"),
                lesson.get("EndDate"),
                lesson.get("Subject"),
            )
            if marker in seen:
                continue
            seen.add(marker)
            lessons.append(lesson)
    lessons.sort(key=lambda item: str(item.get("StartDate") or ""))
    return {"Table": lessons}


def _current_year_id(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for table_name in ("Table1", "Table"):
        rows = payload.get(table_name, [])
        if isinstance(rows, list) and rows:
            value = rows[0].get("YearID") if isinstance(rows[0], dict) else None
            if value is not None:
                return str(value)
    return None


def _pick(item: dict[str, Any], *names: str) -> Any:
    """Case-insensitive field lookup across MCAS homework DTO variants."""
    folded = {str(key).casefold(): value for key, value in item.items()}
    for name in names:
        if name.casefold() in folded:
            return folded[name.casefold()]
    return None


def _homework_row(item: Any) -> bool:
    """Return True for mappings that look like any official MCAS homework DTO."""
    if not isinstance(item, dict):
        return False
    keys = {str(key).casefold() for key in item}
    identity = {
        "homeworkid",
        "assignmentid",
        "homeworktitle",
        "title",
    }
    # Office/Google assignment DTOs use generic ID/Name fields rather than
    # HomeworkID/HomeworkTitle. Require the companion assignment fields below
    # so unrelated nested objects are not mistaken for homework.
    assignment_identity = {"id", "name"}
    supporting = {
        "duedate",
        "assigneddate",
        "createddate",
        "subject",
        "subjectname",
        "homeworkdescription",
        "description",
        "ishomeworksubmitted",
        "iscompleted",
        "assignmenttype",
        "instructions",
        "status",
        "studentid",
        "schoolid",
    }
    return (
        bool(keys & identity) and bool(keys & supporting)
    ) or (
        assignment_identity.issubset(keys)
        and bool(keys & {"duedate", "createddate", "instructions", "status", "studentid"})
    )


def _canonical_homework(item: dict[str, Any]) -> dict[str, Any]:
    """Map Extended, Office/Assignments and Behaviour homework DTOs to one shape."""
    submitted = _pick(
        item,
        "IsHomeworkSubmitted",
        "IsAssignmentSubmitted",
        "IsSubmitted",
        "IsCompleted",
        "Completed",
    )
    if submitted is None:
        status = _pick(item, "Status")
        if isinstance(status, str):
            submitted = status.strip().casefold() in {
                "complete",
                "completed",
                "submitted",
                "turned in",
                "turned_in",
                "done",
            }
    title = _pick(item, "HomeworkTitle", "Title", "Name")
    description = _pick(item, "HomeworkDescription", "Description", "Instructions")
    subject = _pick(item, "Subject", "SubjectName", "SubjectDescription")
    assigned_by = _pick(item, "AssignedBy", "TeacherName", "Teacher", "ContactTeacher")
    homework_id = _pick(item, "HomeworkID", "HomeworkId", "AssignmentId", "AssignmentID", "Id")
    due = _pick(item, "DueDate", "DueDateAsDate", "Deadline", "EndDate")
    assigned = _pick(item, "AssignedDate", "CreatedDate", "StartDate")
    is_past = _pick(item, "IsPast")
    if is_past is None:
        is_past = False

    canonical = dict(item)
    canonical.update(
        {
            "HomeworkID": homework_id,
            "HomeworkTitle": title,
            "HomeworkDescription": description,
            "DueDate": due,
            "AssignedDate": assigned,
            "Subject": subject,
            "AssignedBy": assigned_by,
            "IsHomeworkSubmitted": bool(submitted),
            "IsPast": bool(is_past),
        }
    )
    return canonical


def _normalise_homework(payload: Any) -> dict[str, Any]:
    """Normalise differing MCAS homework response shapes into a Table list."""
    rows: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if _homework_row(value):
                canonical = _canonical_homework(value)
                marker = (
                    canonical.get("HomeworkID"),
                    canonical.get("HomeworkTitle"),
                    canonical.get("DueDate"),
                    canonical.get("Subject"),
                )
                if marker not in seen:
                    seen.add(marker)
                    rows.append(canonical)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)
    rows.sort(key=lambda item: str(item.get("DueDate") or ""))
    return {"Table": rows}


def _payment_student_matches(item: dict[str, Any], student_id: str) -> bool:
    """Return whether a payment record is for this child when it carries an ID."""
    value = _pick(item, "StudentID", "StudentId", "student_id")
    return value is None or str(value) == str(student_id)


def _normalise_payments(
    attempts: list[tuple[str, int, Any]], student_id: str
) -> dict[str, Any]:
    """Extract read-only outstanding payment data from official MCAS DTOs."""
    orders: list[dict[str, Any]] = []
    balances: list[dict[str, Any]] = []
    installments: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    def add(kind: str, item: dict[str, Any]) -> None:
        if not _payment_student_matches(item, student_id):
            return

        if kind == "order":
            canonical = {
                "order_id": _pick(item, "OrderID", "OrderId"),
                "order_number": _pick(item, "OrderNumber"),
                "status": _pick(item, "OrderStatusLocalized", "OrderStatus", "Status"),
                "amount": _pick(item, "OrderPrice", "OrderTotalAmount", "Amount"),
                "description": _pick(item, "OrderItemDescription", "ItemName", "Description"),
            }
            marker = (
                kind,
                canonical["order_id"],
                canonical["order_number"],
                canonical["amount"],
            )
            target = orders
        elif kind == "balance":
            canonical = {
                "club_id": _pick(item, "ClubId", "ClubID"),
                "name": _pick(item, "ItemName", "ClubName", "Name", "Description"),
                "total_cost": _pick(item, "TotalCost"),
                "payment_received": _pick(item, "PaymentReceived"),
                "outstanding": _pick(item, "TotalOutstanding", "OutstandingBalance", "Balance"),
                "number_of_sessions": _pick(item, "NumberOfSessions"),
            }
            marker = (
                kind,
                canonical["club_id"],
                canonical["name"],
                canonical["outstanding"],
            )
            target = balances
        else:
            canonical = {
                "payment_instalment_id": _pick(
                    item, "PaymentInstalmentID", "PaymentInstallmentID"
                ),
                "name": _pick(
                    item,
                    "InstalmentNameLocalized",
                    "InstallmentNameLocalized",
                    "ItemName",
                    "Name",
                    "Description",
                ),
                "due": _pick(item, "DueDate", "NextPaymentDue"),
                "amount": _pick(item, "Amount", "NextPaymentAmount", "TotalAmount"),
                "paid": _pick(item, "Paid", "IsPaid"),
            }
            marker = (
                kind,
                canonical["payment_instalment_id"],
                canonical["name"],
                canonical["due"],
                canonical["amount"],
            )
            target = installments

        if marker in seen:
            return
        seen.add(marker)
        if any(value not in (None, "") for value in canonical.values()):
            target.append(canonical)

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            keys = {str(key).casefold() for key in value}
            if (
                "ordernumber" in keys
                and keys
                & {
                    "orderprice",
                    "ordertotalamount",
                    "orderstatus",
                    "orderstatuslocalized",
                }
            ):
                add("order", value)
            if "totaloutstanding" in keys and keys & {"totalcost", "paymentreceived", "clubid"}:
                add("balance", value)
            if (
                "paymentinstalmentid" in keys
                or "paymentinstallmentid" in keys
                or ("nextpaymentdue" in keys and keys & {"amount", "totalamount", "nextpaymentamount"})
            ):
                add("installment", value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    for _label, status, payload in attempts:
        if status == 200 and _payload_has_content(payload):
            walk(payload)

    return {
        "orders": orders,
        "balances": balances,
        "installments": installments,
    }


def _payload_shape(payload: Any) -> str:
    """Describe response structure without logging student data or homework text."""
    if isinstance(payload, dict):
        parts: list[str] = []
        for key, value in payload.items():
            if isinstance(value, list):
                parts.append(f"{key}=list[{len(value)}]")
            elif isinstance(value, dict):
                parts.append(f"{key}=dict")
            else:
                parts.append(f"{key}={type(value).__name__}")
        return ", ".join(parts[:20]) or "empty-dict"
    if isinstance(payload, list):
        return f"list[{len(payload)}]"
    return type(payload).__name__


def _to_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalised = value.strip().casefold()
        if normalised in {"true", "1", "yes", "on"}:
            return True
        if normalised in {"false", "0", "no", "off"}:
            return False
    return None


def _config_bool(payload: Any, wanted_key: str) -> bool | None:
    """Find a boolean school config value across keyed and Key/Value responses."""
    wanted = wanted_key.casefold()
    if isinstance(payload, dict):
        # Direct keyed response.
        for key, value in payload.items():
            if str(key).casefold() == wanted:
                parsed = _to_bool(value)
                if parsed is not None:
                    return parsed

        # Common configuration DTO shape: {"Key": "...", "Value": "..."}.
        config_key = (
            payload.get("Key")
            or payload.get("key")
            or payload.get("ConfigurationKey")
            or payload.get("Name")
        )
        if config_key is not None and str(config_key).casefold() == wanted:
            config_value = (
                payload.get("Value")
                if "Value" in payload
                else payload.get("value")
                if "value" in payload
                else payload.get("ConfigurationValue")
            )
            parsed = _to_bool(config_value)
            if parsed is not None:
                return parsed

        for value in payload.values():
            found = _config_bool(value, wanted_key)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _config_bool(item, wanted_key)
            if found is not None:
                return found
    return None


def _payload_has_content(payload: Any) -> bool:
    if isinstance(payload, dict):
        return any(_payload_has_content(value) for value in payload.values())
    if isinstance(payload, list):
        return bool(payload)
    return payload not in (None, "", False)


def _payload_diagnostic(payload: Any) -> str:
    """Return a safe structural diagnostic with paths, counts and field names."""
    details: list[str] = []

    def walk(value: Any, path: str, depth: int) -> None:
        if depth > 4 or len(details) >= 24:
            return
        if isinstance(value, dict):
            keys = sorted(str(key) for key in value.keys())
            details.append(
                f"{path}=dict keys=[{','.join(keys[:16])}]"
            )
            for key, child in value.items():
                if isinstance(child, (dict, list)):
                    walk(child, f"{path}.{key}", depth + 1)
        elif isinstance(value, list):
            details.append(f"{path}=list[{len(value)}]")
            sample = next((item for item in value if isinstance(item, dict)), None)
            if sample is not None:
                fields = sorted(str(key) for key in sample.keys())
                details.append(
                    f"{path}[] fields=[{','.join(fields[:24])}]"
                )
                for key, child in sample.items():
                    if isinstance(child, (dict, list)):
                        walk(child, f"{path}[].{key}", depth + 1)

    walk(payload, "root", 0)
    return " | ".join(details) or _payload_shape(payload)


async def _optional(
    label: str, awaitable, warnings: list[str] | None = None
) -> dict[str, Any]:
    try:
        value = await awaitable
        return value if isinstance(value, dict) else {}
    except Exception as err:
        status = getattr(err, "status", "n/a")
        _LOGGER.warning(
            "MCAS optional %s unavailable (%s, status=%s)",
            label,
            type(err).__name__,
            status,
        )
        if warnings is not None:
            warnings.append(f"{label}: unavailable ({type(err).__name__}, status={status})")
        return {}


class MCASDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(
        self,
        hass: HomeAssistant,
        clients: dict[tuple[str, str], MCASClient],
        entry: ConfigEntry,
    ) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_UPDATE_INTERVAL,
            config_entry=entry,
        )
        self.clients = clients
        self.entry = entry
        # Cache schools/students that conclusively do not expose homework for
        # this coordinator lifetime so we do not keep polling unsupported
        # endpoints on every refresh.
        self._homework_supported: dict[str, bool] = {}

    async def _async_update_data(self) -> dict[str, Any]:
        all_children = self.entry.data.get(CONF_CHILDREN, [])
        selected = set(
            self.entry.options.get(
                CONF_SELECTED_CHILDREN,
                [_child_key(c) for c in all_children],
            )
        )
        warnings: list[str] = []
        result: dict[str, Any] = {"children": {}, "_diagnostics": {"warnings": warnings}}
        calendars: dict[tuple[str, str], dict[str, Any]] = {}
        today = date.today()
        this_week = _monday(today)
        next_week = this_week + timedelta(days=7)

        try:
            for child in all_children:
                key = _child_key(child)
                if key not in selected:
                    continue

                pair = (str(child["school_id"]), str(child["contact_id"]))
                client = self.clients[pair]
                if pair not in calendars:
                    calendars[pair] = await client.async_get_academic_calendar()

                student_id = str(child["student_id"])
                current_payload = await client.async_get_timetable(student_id, this_week)
                next_payload = await _optional(
                    "next-week timetable",
                    client.async_get_timetable(student_id, next_week),
                    warnings,
                )

                years = await _optional("school years", client.async_get_years(student_id), warnings)
                year_id = _current_year_id(years)

                attendance: dict[str, Any] = {}
                behaviour: dict[str, Any] = {}
                behaviour_chronological: dict[str, Any] = {}
                if year_id:
                    attendance = await _optional(
                        "attendance", client.async_get_attendance(student_id, year_id), warnings
                    )
                    behaviour = await _optional(
                        "behaviour", client.async_get_behaviour(student_id, year_id), warnings
                    )
                    behaviour_chronological = await _optional(
                        "behaviour chronology",
                        client.async_get_behaviour_chronological(student_id, year_id),
                        warnings,
                    )

                homework = {"Table": []}
                homework_supported = self._homework_supported.get(key)

                if homework_supported is not False:
                    # MCAS schools can expose homework through different official-client
                    # modules. Detect support once, then stop polling unsupported schools.
                    homework_attempts: list[str] = []
                    homework_payloads: list[tuple[str, Any]] = []

                    try:
                        extended_raw = await client.async_get_homework(student_id, today)
                        homework_payloads.append(("extended", extended_raw))
                        homework_attempts.append(
                            f"extended:200:{_payload_shape(extended_raw)}"
                        )
                    except Exception as err:
                        status = getattr(err, "status", "n/a")
                        homework_attempts.append(
                            f"extended:{status}:{type(err).__name__}"
                        )

                    school_config = await _optional(
                        "school homework config", client.async_get_school_config(), None
                    )
                    extended_mode = _config_bool(
                        school_config, "MCASHomeworkModuleHomeworkModeIsExtended"
                    )
                    assignments_enabled = _config_bool(
                        school_config, "MCASoffice365OrGoogleAssignmentsEnabled"
                    )

                    fallback_order = ["assignments", "behaviour"]
                    if extended_mode is False and assignments_enabled is not True:
                        fallback_order = ["behaviour", "assignments"]
                    elif assignments_enabled is True:
                        fallback_order = ["assignments", "behaviour"]

                    for mode, payload in homework_payloads:
                        candidate = _normalise_homework(payload)
                        if candidate["Table"]:
                            homework = candidate
                            result["_diagnostics"].setdefault("homework_backend", {})[key] = mode
                            break

                    if not homework["Table"]:
                        for mode in fallback_order:
                            if mode == "assignments":
                                attempts = await client.async_get_homework_assignments_candidates(
                                    student_id, today
                                )
                            else:
                                attempts = await client.async_get_homework_behaviour_candidates(
                                    student_id, today
                                )

                            for label, status, payload in attempts:
                                homework_attempts.append(
                                    f"{label}:{status}:{_payload_shape(payload)}"
                                )
                                if _payload_has_content(payload):
                                    homework_payloads.append((label, payload))
                                    candidate = _normalise_homework(payload)
                                    if candidate["Table"]:
                                        homework = candidate
                                        result["_diagnostics"].setdefault("homework_backend", {})[key] = label
                                        break
                            if homework["Table"]:
                                break

                    if homework["Table"]:
                        homework_supported = True
                        self._homework_supported[key] = True
                    else:
                        nonempty = [
                            f"{label}={_payload_diagnostic(payload)}"
                            for label, payload in homework_payloads
                            if _payload_has_content(payload)
                        ]
                        if nonempty:
                            # The school exposes a homework module, but this DTO
                            # is not recognised yet. Keep entities registered and
                            # provide a safe diagnostic for parser support.
                            homework_supported = True
                            self._homework_supported[key] = True
                            support = (
                                f"MCAS-DIAG HOMEWORK_UNRECOGNISED_SHAPE | "
                                f"version={INTEGRATION_VERSION} | "
                                f"date={today.isoformat()} | "
                                f"extended_mode={extended_mode} | "
                                f"assignments_enabled={assignments_enabled} | "
                                f"attempts=[{';'.join(homework_attempts)}] | "
                                f"structures=[{' || '.join(nonempty[:3])}]"
                            )
                            warnings.append(support)
                            _LOGGER.warning(
                                "Please send this to the developer: %s",
                                support,
                            )
                        else:
                            # All known homework backends are empty/not enabled.
                            # Treat homework as unsupported for this runtime and
                            # stop probing the endpoints on subsequent refreshes.
                            homework_supported = False
                            self._homework_supported[key] = False
                            _LOGGER.debug(
                                "MCAS homework is not exposed for child %s; "
                                "homework polling disabled until integration reload",
                                key,
                            )
                else:
                    homework_supported = False

                payment_attempts = await client.async_get_payment_candidates(student_id)
                payments = _normalise_payments(payment_attempts, student_id)
                payment_attempt_summary = [
                    f"{label}:{status}:{_payload_shape(payload)}"
                    for label, status, payload in payment_attempts
                ]
                payment_nonempty = [
                    f"{label}={_payload_diagnostic(payload)}"
                    for label, status, payload in payment_attempts
                    if status == 200 and _payload_has_content(payload)
                ]
                if payment_nonempty and not any(
                    payments[name] for name in ("orders", "balances", "installments")
                ):
                    support = (
                        f"MCAS-DIAG PAYMENTS_UNRECOGNISED_SHAPE | "
                        f"version={INTEGRATION_VERSION} | "
                        f"attempts=[{';'.join(payment_attempt_summary)}] | "
                        f"structures=[{' || '.join(payment_nonempty[:4])}]"
                    )
                    warnings.append(support)
                    _LOGGER.warning("Please send this to the developer: %s", support)

                result["children"][key] = {
                    "profile": child,
                    "timetable": _merge_timetables(current_payload, next_payload),
                    "academic_calendar": calendars[pair],
                    "year_id": year_id,
                    "attendance": attendance,
                    "homework": homework,
                    "features": {"homework": bool(homework_supported)},
                    "payments": payments,
                    "behaviour": behaviour,
                    "behaviour_chronological": behaviour_chronological,
                }
            return result
        except MCASAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except MCASApiError as err:
            raise UpdateFailed(str(err)) from err
