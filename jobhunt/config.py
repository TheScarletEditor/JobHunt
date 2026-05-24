import os
from pathlib import Path

APP_NAME = "JobHunt"
APPDATA_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / APP_NAME
APPDATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = APPDATA_DIR / "jobhunt.db"
LOG_PATH = APPDATA_DIR / "jobhunt.log"

COLOR_BG = "#080808"
COLOR_BG_RAISED = "#141414"
COLOR_BG_HOVER = "#1d1d1d"
COLOR_BG_SIDEBAR = "#050505"
COLOR_BG_AI_PANEL = "#050505"
COLOR_INPUT_BG = "#1a1a1a"
COLOR_INPUT_BG_HOVER = "#222222"
COLOR_INPUT_BORDER = "#1a1a1a"
COLOR_INPUT_BORDER_HOVER = "#333333"
COLOR_ACCENT = "#C8102E"
COLOR_ACCENT_HOVER = "#E01735"
COLOR_ACCENT_DIM = "#8a0e22"
COLOR_ACCENT_SOFT = "#2a0c11"
COLOR_TEXT = "#ffffff"
COLOR_TEXT_DIM = "#a8a8a8"
COLOR_TEXT_FAINT = "#5a5a5a"
COLOR_BORDER = "#141414"
COLOR_BORDER_LIGHT = "#1d1d1d"
COLOR_SILVER = "#d0d0d0"
COLOR_FORM_LABEL = "#cfcfcf"

DEFAULT_STAGES = [
    ("Applied",    1, "#5b5b5b"),
    ("Screening",  2, "#c79100"),
    ("Interview",  3, "#3a78c7"),
    ("Offer",      4, "#5fa83a"),
    ("Rejected",   5, "#9b1a1a"),
    ("Withdrawn",  6, "#444444"),
]

DEFAULT_SOURCES = [
    "LinkedIn", "Indeed", "Glassdoor", "ZipRecruiter", "Greenhouse",
    "Lever", "Ashby", "Workable", "SmartRecruiters", "Jobvite",
    "RemoteOK", "We Work Remotely", "Wellfound", "BuiltIn",
    "YC Work at a Startup", "Hired", "Otta", "Company Website",
    "Referral", "Recruiter Outreach", "Other",
]

DEFAULT_TRUSTED_ATS = [
    ("Greenhouse",     0),
    ("Lever",          0),
    ("Ashby",          0),
    ("Workable",       0),
    ("SmartRecruiters",0),
    ("Jobvite",        0),
]

MICROSOFT_CLIENT_ID = "0f9a9990-a608-4bda-b26e-51c1c1d20b11"

# Google OAuth — used for Google Calendar push. Get a client_id by:
#   1. Going to https://console.cloud.google.com/
#   2. Creating a project + enabling the Google Calendar API
#   3. Creating an OAuth client of type "Desktop application"
#   4. Pasting the client_id here (the "client secret" for Desktop apps isn't
#      actually secret — bundled in the app per Google's guidance).
# When left empty, the Google Calendar push button shows a setup prompt.
GOOGLE_CLIENT_ID = "201246459031-0921ub18t9g7f03s09noh0j422pge51m.apps.googleusercontent.com"
GOOGLE_CLIENT_SECRET = ""  # Desktop-app pseudo-secret; safe to ship. Empty = PKCE-only.

DEFAULT_JOB_BOARDS = [
    ("LinkedIn Jobs",        "https://www.linkedin.com/jobs/"),
    ("Indeed",               "https://www.indeed.com/"),
    ("Glassdoor",            "https://www.glassdoor.com/Job/"),
    ("ZipRecruiter",         "https://www.ziprecruiter.com/jobs-search"),
    ("Wellfound",            "https://wellfound.com/jobs"),
    ("BuiltIn",              "https://builtin.com/jobs"),
    ("YC Work at a Startup", "https://www.workatastartup.com/companies"),
    ("Hired",                "https://hired.com/home"),
    ("RemoteOK",             "https://remoteok.com/"),
    ("We Work Remotely",     "https://weworkremotely.com/"),
    ("Otta / Welcome",       "https://app.welcometothejungle.com/"),
    ("Monster",              "https://www.monster.com/jobs/search"),
    ("Dice",                 "https://www.dice.com/jobs"),
]
