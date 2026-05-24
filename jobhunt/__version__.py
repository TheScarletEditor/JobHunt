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

__version__ = "0.6.1"
__app_name__ = "JobHunt"
__publisher__ = "The Scarlet Raven"
__app_id__ = "JobHunt.ScarletRaven"  # registry / GUID-ish id for Inno Setup
