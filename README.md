# MCAS Home Assistant

Private, read-only Home Assistant custom integration for Bromcom MyChildAtSchool (MCAS).

## Initial scope

- Authenticate with parent credentials without storing session tokens in source control.
- Discover the linked student account from MCAS.
- Pull weekly timetable and academic-calendar data.
- Expose useful Home Assistant sensors and calendar entities.
- Keep all MCAS access read-only; no payments, bookings, messages, submissions, or other mutations.

This repository is being built from observed browser API behaviour. No captured passwords, bearer tokens, student IDs, school IDs, contact IDs, or HAR files are committed.
