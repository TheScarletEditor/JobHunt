"""Single source of truth for the app version.

Read by:
  - jobhunt/ui/sidebar.py (version label at the bottom of the sidebar)
  - jobhunt/updater.py     (compares against latest GitHub release)
  - jobhunt.spec / installer/JobHunt.iss  (PyInstaller + Inno Setup at build time)
  - build.py               (composes the output installer filename)

Bump this before tagging a release. Follow semver:
  MAJOR.MINOR.PATCH  — bump PATCH for bugfixes, MINOR for features,
  MAJOR when the on-disk SQLite schema requires manual migration.
"""

__version__ = "0.6.3"
__app_name__ = "JobHunt"
__publisher__ = "The Scarlet Coder"
# Internal identifier — DELIBERATELY KEEPS "ScarletRaven" so the Windows
# AppUserModelID stays stable across the v0.6.3 brand rename. Changing it
# would orphan taskbar pins / "recent" entries on every existing install.
# The visible publisher string is __publisher__ above; internal ids stay.
__app_id__ = "JobHunt.ScarletRaven"
