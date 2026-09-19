# ARCADIA Integrate MCAS for Home Assistant

![ARCADIA](assets/arcadia-logo.png)

[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz/) [![Home Assistant](https://img.shields.io/badge/Home%20Assistant-Custom%20Integration-blue.svg)](https://www.home-assistant.io/)

Read-only Home Assistant custom integration for Bromcom MyChildAtSchool (MCAS).

## Current release

Version 2.3 adds school-aware homework discovery. MCAS schools can expose homework through different official-client backends; the integration now checks the school's MCAS configuration, keeps the known extended-homework route, and safely falls back to the assignments and behaviour-homework backends when required.

It also includes:

- de-duplicated child discovery when MCAS returns the same student through multiple contact records;
- Home Assistant options/configure flow with child selection and registry cleanup;
- timetable, academic calendar, attendance, behaviour and homework entities;
- safe developer-ready diagnostics for unsupported or empty homework responses;
- a native Home Assistant update entity backed by GitHub releases.

## Install with HACS

The repository is HACS-compatible. Until it is accepted into the HACS default store, add it as a **Custom repository**:

1. Open HACS in Home Assistant.
2. Open the repository menu and choose **Custom repositories**.
3. Add `https://github.com/jeremypowell613-web/mcas-home-assistant`.
4. Choose the **Integration** category.
5. Install **ARCADIA Integrate MCAS** and restart Home Assistant.
6. Open **Settings → Devices & services → Add integration** and search for **MCAS**.

## Manual install

Copy `custom_components/mcas` into your Home Assistant `/config/custom_components/mcas` directory and restart Home Assistant. Then open **Settings → Devices & services → Add integration** and search for **MCAS**.

Existing installations can replace only the integration files; the Home Assistant config entry does not need to be deleted.

## Updating

The integration includes an **Integration update** entity. Once a newer GitHub release is published, Home Assistant can show the newer version and install its integration files. Restart Home Assistant after an in-app update so the new Python code is loaded.

HACS users can also update the integration directly from HACS.

## Privacy and safety

The integration is read-only. It does not make payments, bookings, send messages, submit homework, or perform other MCAS mutations.

MCAS behaviour can differ by school. Homework parsing is intentionally defensive; if a school returns an unsupported structure, safe structural diagnostics are logged without passwords, bearer tokens, student names, student IDs or homework text.

No captured passwords, bearer tokens, student IDs, school IDs, contact IDs, or HAR files are committed to this repository.

## Issues

If something does not work, open an issue at:
https://github.com/jeremypowell613-web/mcas-home-assistant/issues

## Licence and attribution

Copyright © 2026 Jeremy Powell. The integration code is licensed under **GPL-3.0-or-later**. See `LICENSE` and `NOTICE`.

Modified and redistributed versions must follow the GPL requirements, including preserving applicable copyright/licence notices and identifying modifications where required. The ARCADIA name and logo are project branding; the software licence does not grant rights to present an unofficial fork as the official ARCADIA project.


## Payments (read-only)

For schools that enable MCAS Online Payments, ARCADIA exposes read-only Home Assistant sensors for outstanding payment items, outstanding balance and the next instalment due. Payment checkout, card changes and other write actions are deliberately not implemented.
