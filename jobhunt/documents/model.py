from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict


# ----- Section-kind classification (shared by editor, export, preview) -----

SECTION_KIND_DETAIL = "detail"   # Experience / Projects / Education — header + sub + bullets
SECTION_KIND_LIST   = "list"     # Skills / Tools — category + comma-list of short items
SECTION_KIND_LINE   = "line"     # Certifications / Awards — one short line per entry


def detect_section_kind(title: str) -> str:
    t = (title or "").lower()
    if any(k in t for k in ("skill", "tool", "technolog", "stack", "competenc", "proficienc")):
        return SECTION_KIND_LIST
    if any(k in t for k in ("certif", "course", "award", "honor", "publication", "language")):
        return SECTION_KIND_LINE
    return SECTION_KIND_DETAIL


@dataclass
class ResumeItem:
    header: str = ""
    subheader: str = ""
    bullets: list[str] = field(default_factory=list)


@dataclass
class ResumeSection:
    title: str = ""
    items: list[ResumeItem] = field(default_factory=list)


@dataclass
class ResumeContent:
    name: str = ""
    contact: list[str] = field(default_factory=list)
    summary: str = ""
    sections: list[ResumeSection] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict) -> "ResumeContent":
        return cls(
            name=d.get("name", "") or "",
            contact=list(d.get("contact", []) or []),
            summary=d.get("summary", "") or "",
            sections=[
                ResumeSection(
                    title=s.get("title", "") or "",
                    items=[
                        ResumeItem(
                            header=i.get("header", "") or "",
                            subheader=i.get("subheader", "") or "",
                            bullets=list(i.get("bullets", []) or []),
                        )
                        for i in (s.get("items") or [])
                    ],
                )
                for s in (d.get("sections") or [])
            ],
        )

    @classmethod
    def from_json(cls, s: str) -> "ResumeContent":
        return cls.from_dict(json.loads(s))

    def to_plain_text(self) -> str:
        lines: list[str] = []
        if self.name:
            lines.append(self.name)
        if self.contact:
            lines.append(" · ".join(self.contact))
        if self.summary:
            lines.append("")
            lines.append(self.summary)
        for section in self.sections:
            lines.append("")
            lines.append(section.title.upper())
            for item in section.items:
                lines.append("")
                if item.header:
                    lines.append(item.header)
                if item.subheader:
                    lines.append(item.subheader)
                for b in item.bullets:
                    lines.append(f"  • {b}")
        return "\n".join(lines).strip()

    def all_keywords(self) -> set[str]:
        words: set[str] = set()
        for chunk in [self.summary, *(b for s in self.sections for i in s.items for b in i.bullets)]:
            for tok in chunk.replace("/", " ").replace(",", " ").split():
                t = tok.strip(".()[]{}:;").lower()
                if len(t) > 2:
                    words.add(t)
        return words
