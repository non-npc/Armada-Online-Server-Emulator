# Changelog

## Versioning

Emulator releases use semantic versions: MAJOR.MINOR.PATCH, with an alpha suffix while development continues. Increase the major version for incompatible changes, the minor version for new functionality, and the patch version for fixes. Advance the alpha sequence for subsequent prereleases. Update `Server_Emulator/version.py`, the README pill in `docs/version.svg`, and this changelog together. Changes to the supplied patched client are recorded with the emulator release that requires them.

## 0.1.0-alpha.2 — October 12, 2026

First numbered release of the existing emulator.

- Local Windows server, authenticated game login and six character slots.
- Original starter-sector loading and gameplay command relay, including shop purchases and power removal.
- Browser administration for accounts and character metadata, with database backups.
- Automatic character snapshot storage and restoration, including a patched-client extension for resource balance, five powers and position.
- Reliable fragmented save transport and final saves on normal sector changes/logout.
- Windows launchers, tests under `Server_Emulator/tests/`, setup instructions and screenshots.

Save/reload hooks still require verification in the original game client. 
Authoritative multiplayer simulation and complete progression behavior remain unfinished. 
Existing accounts and characters are preserved during database migrations.
