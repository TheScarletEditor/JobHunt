"""Render typography scheme previews using Pillow — NO app code changes.
Outputs PNGs showing page title, section title, stat value, form label,
sidebar nav, buttons, and body text in three candidate schemes.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "screenshots" / "typography"
OUT.mkdir(exist_ok=True, parents=True)

W, H = 1200, 820

BG = (8, 8, 8)
CARD = (20, 20, 20)
HOVER = (29, 29, 29)
TEXT = (255, 255, 255)
DIM = (168, 168, 168)
FAINT = (90, 90, 90)
ACCENT = (200, 16, 46)
SILVER = (208, 208, 208)
ACCENT_SOFT = (42, 12, 17)
BORDER_FAINT = (29, 29, 29)

FONT_FILES = {
    "regular":  "C:/Windows/Fonts/segoeui.ttf",
    "medium":   "C:/Windows/Fonts/seguisb.ttf",
    "semibold": "C:/Windows/Fonts/seguisb.ttf",
    "bold":     "C:/Windows/Fonts/segoeuib.ttf",
}


def f(weight: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_FILES[weight], size)


SCHEMES = [
    {
        "letter": "A",
        "name": "A — Current baseline",
        "subtitle": "Body 13 reg · Page title 24 semi · Section 11 semi · Stat value 30 semi · Form 12 reg",
        "body":         ("regular",  13),
        "page_title":   ("semibold", 24),
        "section":      ("semibold", 11),
        "form_label":   ("regular",  12),
        "stat_label":   ("regular",  11),
        "stat_value":   ("semibold", 30),
        "sidebar_nav":  ("regular",  13),
        "button":       ("regular",  13),
        "app_name":     ("semibold", 18),
    },
    {
        "letter": "B",
        "name": "B — Slightly larger & bolder",
        "subtitle": "Body 14 reg · Page title 28 bold · Section 12 bold · Stat value 34 bold · Form 13 semi",
        "body":         ("regular",  14),
        "page_title":   ("bold",     28),
        "section":      ("bold",     12),
        "form_label":   ("semibold", 13),
        "stat_label":   ("regular",  12),
        "stat_value":   ("bold",     34),
        "sidebar_nav":  ("semibold", 14),
        "button":       ("semibold", 14),
        "app_name":     ("bold",     20),
    },
    {
        "letter": "C",
        "name": "C — Larger, generous",
        "subtitle": "Body 15 reg · Page title 32 bold · Section 13 bold · Stat value 38 bold · Form 14 semi",
        "body":         ("regular",  15),
        "page_title":   ("bold",     32),
        "section":      ("bold",     13),
        "form_label":   ("semibold", 14),
        "stat_label":   ("regular",  12),
        "stat_value":   ("bold",     38),
        "sidebar_nav":  ("semibold", 14),
        "button":       ("semibold", 14),
        "app_name":     ("bold",     22),
    },
]


def render_scheme(scheme: dict) -> Path:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    draw.text((40, 22), scheme["name"], font=f("bold", 15), fill=TEXT)
    draw.text((40, 48), scheme["subtitle"], font=f("regular", 11), fill=DIM)
    draw.line([(40, 76), (W - 40, 76)], fill=BORDER_FAINT, width=1)

    sidebar_x = 40
    sidebar_y = 96
    sidebar_w = 220
    sidebar_h = H - sidebar_y - 40
    draw.rectangle([sidebar_x, sidebar_y, sidebar_x + sidebar_w, sidebar_y + sidebar_h], fill=(5, 5, 5))

    draw.rounded_rectangle(
        [sidebar_x + 16, sidebar_y + 18, sidebar_x + 16 + 64, sidebar_y + 18 + 64],
        radius=10, fill=CARD,
    )
    logo_w = draw.textlength("LOGO", font=f("regular", 10))
    draw.text(
        (sidebar_x + 48 - logo_w // 2, sidebar_y + 50 - 6),
        "LOGO", font=f("regular", 10), fill=FAINT,
    )
    draw.text(
        (sidebar_x + 16, sidebar_y + 102),
        "JobHunt", font=f(*scheme["app_name"]), fill=TEXT,
    )

    nav_y = sidebar_y + 160
    nav_items = [
        ("Dashboard", True),
        ("Pipeline", False),
        ("Resume", False),
        ("Cover Letter", False),
        ("Job Search", False),
        ("Settings", False),
    ]
    nav_height = 36
    for label, active in nav_items:
        if active:
            draw.rounded_rectangle(
                [sidebar_x + 12, nav_y, sidebar_x + sidebar_w - 12, nav_y + nav_height],
                radius=8, fill=ACCENT_SOFT,
            )
            color = ACCENT
        else:
            color = DIM
        draw.text((sidebar_x + 24, nav_y + 9), label, font=f(*scheme["sidebar_nav"]), fill=color)
        nav_y += 42

    main_x = sidebar_x + sidebar_w + 32
    main_y = 96

    draw.text((main_x, main_y), "Dashboard", font=f(*scheme["page_title"]), fill=TEXT)

    cards_y = main_y + max(48, scheme["page_title"][1] + 22)
    card_w, card_h = 220, 116
    card_gap = 16
    cards = [
        ("APPLICATIONS THIS WEEK", "12", False),
        ("RESPONSE RATE", "34%", True),
        ("ACTIVE IN PIPELINE", "8", False),
    ]
    for i, (label, value, accent) in enumerate(cards):
        cx = main_x + i * (card_w + card_gap)
        draw.rounded_rectangle([cx, cards_y, cx + card_w, cards_y + card_h], radius=12, fill=CARD)
        draw.text((cx + 22, cards_y + 20), label, font=f(*scheme["stat_label"]), fill=DIM)
        draw.text(
            (cx + 22, cards_y + card_h - scheme["stat_value"][1] - 18),
            value, font=f(*scheme["stat_value"]),
            fill=ACCENT if accent else TEXT,
        )

    section_y = cards_y + card_h + 36
    draw.text((main_x, section_y), "PIPELINE", font=f(*scheme["section"]), fill=SILVER)

    body_text = (
        "Your interview conversion rate is 34%. Three applications have been in "
        "the Screening stage for over two weeks — consider following up."
    )
    draw.text(
        (main_x, section_y + scheme["section"][1] + 14),
        body_text, font=f(*scheme["body"]), fill=TEXT,
    )

    form_y = section_y + scheme["section"][1] + 64
    draw.text((main_x, form_y + 6), "Legal name", font=f(*scheme["form_label"]), fill=DIM)
    draw.text((main_x + 130, form_y + 6), "Jane Sample", font=f(*scheme["body"]), fill=TEXT)
    draw.line(
        [(main_x + 130, form_y + scheme["body"][1] + 14),
         (main_x + 440, form_y + scheme["body"][1] + 14)],
        fill=BORDER_FAINT, width=1,
    )

    btn_y = form_y + 70
    btn_h = 40
    btn_specs = [
        ("Save version", ACCENT, TEXT),
        ("Tailor with AI", (38, 38, 38), TEXT),
        ("Import", (38, 38, 38), TEXT),
    ]
    btn_x = main_x
    for text, fill, fg in btn_specs:
        text_w = draw.textlength(text, font=f(*scheme["button"]))
        btn_w = int(text_w + 32)
        draw.rounded_rectangle([btn_x, btn_y, btn_x + btn_w, btn_y + btn_h], radius=8, fill=fill)
        draw.text(
            (btn_x + (btn_w - text_w) // 2, btn_y + (btn_h - scheme["button"][1]) // 2 - 2),
            text, font=f(*scheme["button"]), fill=fg,
        )
        btn_x += btn_w + 12

    out_path = OUT / f"scheme_{scheme['letter'].lower()}.png"
    img.save(out_path)
    return out_path


if __name__ == "__main__":
    for s in SCHEMES:
        path = render_scheme(s)
        print(f"saved {path.name}")
