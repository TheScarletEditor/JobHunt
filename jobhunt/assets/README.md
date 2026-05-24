# JobHunt assets

Bundled binary assets, embedded as Python modules so the app ships
self-contained (no external files to ship alongside the `.exe`).

## `_logo_data.py`

Base64-encoded PNG of **The Scarlet Raven** logo — the sidebar mark.

- Decoded into `LOGO_PNG_BYTES` at import time
- Loaded by [`ui/sidebar.py`](../ui/sidebar.py) into a 72×72 `QPixmap`
- If the module is somehow missing, the sidebar falls back to a `LOGO`
  text placeholder so the app still runs

To **regenerate** (e.g. if the brand mark changes):

```python
import base64, textwrap
data = open("path/to/new_logo.png", "rb").read()
b64 = base64.b64encode(data).decode("ascii")
lines = textwrap.wrap(b64, 76)
# Write the same module shape as _logo_data.py:
#   _B64 = (\n  "...lines..."\n)\nLOGO_PNG_BYTES = base64.b64decode(_B64)
```

## Future

- `_icon_data.py` — multi-resolution `.ico` for the `.exe` / window taskbar
  (Phase 6 / installer chunk)
- Splash-screen image — also Phase 6
