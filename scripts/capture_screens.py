"""Capture an offscreen render of each page so layout issues can be audited."""
import os
import sys
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from jobhunt import theme
from jobhunt.db import DB
from jobhunt.ui.main_window import MainWindow
from jobhunt.ui.pages.settings import SettingsPage
from jobhunt.ui.dialogs.add_application import AddApplicationDialog
from jobhunt.documents.model import ResumeContent, ResumeSection, ResumeItem
from jobhunt.ui.dialogs.tailor_resume import TailorResumeDialog


OUT = ROOT / "scripts" / "screenshots"
OUT.mkdir(exist_ok=True)


def _process(app, ms: int = 200):
    end = time.time() + (ms / 1000)
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.stylesheet())
    DB.connect()

    window = MainWindow()
    window.resize(1480, 860)
    window.show()
    _process(app, 400)

    for key in ("dashboard", "pipeline", "resume", "cover_letter",
                "browser", "autonomous", "interviews", "reports", "settings"):
        window._on_nav(key)
        _process(app, 250)
        pix = window.grab()
        pix.save(str(OUT / f"page_{key}.png"))
        print(f"saved page_{key}.png")

    settings_page = window.pages["settings"]
    tabs = settings_page.findChild(type(settings_page).__bases__[0])
    from PySide6.QtWidgets import QTabWidget
    tab_widget = settings_page.findChild(QTabWidget)
    if tab_widget is not None:
        for i in range(tab_widget.count()):
            tab_widget.setCurrentIndex(i)
            _process(app, 200)
            window._on_nav("settings")
            _process(app, 150)
            pix = window.grab()
            label = tab_widget.tabText(i).replace(" ", "_").lower()
            pix.save(str(OUT / f"settings_{i:02d}_{label}.png"))
            print(f"saved settings_{i:02d}_{label}.png")

    add_dlg = AddApplicationDialog(window)
    add_dlg.show()
    _process(app, 200)
    add_dlg.grab().save(str(OUT / "dialog_add_application.png"))
    print("saved dialog_add_application.png")
    add_dlg.close()

    sample = ResumeContent(
        name="Jane Sample",
        contact=["jane@example.com", "(555) 555-1212", "linkedin.com/in/janesample"],
        summary="Senior software engineer with 8 years of experience building distributed backend systems.",
        sections=[
            ResumeSection(title="Experience", items=[
                ResumeItem(
                    header="Senior Engineer · Acme · 2022-Present",
                    subheader="Remote",
                    bullets=[
                        "Led migration of monolithic Rails app to Go microservices.",
                        "Cut p99 latency from 800ms to 120ms across the checkout path.",
                        "Mentored 4 junior engineers; ran weekly architecture reviews.",
                    ],
                ),
                ResumeItem(
                    header="Software Engineer · Beta Corp · 2019-2022",
                    subheader="San Francisco, CA",
                    bullets=[
                        "Designed the events pipeline ingesting 2B records/day.",
                        "Owned the on-call rotation for 18 months.",
                    ],
                ),
            ]),
            ResumeSection(title="Skills", items=[
                ResumeItem(bullets=["Go, Python, TypeScript", "Kubernetes, Postgres, Kafka"]),
            ]),
        ],
    )
    tailor_dlg = TailorResumeDialog(sample, 1, window)
    tailor_dlg.show()
    _process(app, 200)
    tailor_dlg.grab().save(str(OUT / "dialog_tailor_resume.png"))
    print("saved dialog_tailor_resume.png")
    tailor_dlg.close()

    print(f"\nAll screenshots written to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
