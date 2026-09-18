# ARCADIA Integrate MCAS for Home Assistant

Read-only Home Assistant custom integration for Bromcom MyChildAtSchool (MCAS).

## Version 2.0.0

Version 2 promotes the integration from the development branch to the stable install path. It includes:

- de-duplicated child discovery when MCAS returns the same student through multiple contact records;
- a repaired Home Assistant options/configure flow;
- proper registry cleanup when a child is deselected, so removed children do not leave unavailable entities/devices behind;
- timetable, academic calendar, attendance, behaviour and homework entities;
- broader homework response parsing and safe diagnostics for schools that return a different MCAS response shape;
- a native Home Assistant update entity backed by GitHub releases.

## Install

Copy `custom_components/mcas` into your Home Assistant `/config/custom_components/mcas` directory and restart Home Assistant. Then open **Settings → Devices & services → Add integration** and search for **MCAS**.

For command-line installs, download the stable `main` branch after v2 has been promoted. Existing installations can replace only the integration files; the Home Assistant config entry does not need to be deleted.

## Updating

Version 2 includes an **Integration update** entity. Once a newer GitHub release is published, Home Assistant can show the newer version and install its integration files. Restart Home Assistant after an in-app update so the new Python code is loaded.

## Notes

The integration is read-only. It does not make payments, bookings, send messages, submit homework, or perform other MCAS mutations.

MCAS behaviour can differ by school. Homework parsing is intentionally defensive; if a school returns an unsupported structure, safe structural diagnostics are logged without passwords, bearer tokens, student names or homework text.

No captured passwords, bearer tokens, student IDs, school IDs, contact IDs, or HAR files are committed to this repository.
