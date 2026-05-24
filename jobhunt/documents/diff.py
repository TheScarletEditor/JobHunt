from __future__ import annotations

import difflib


def line_diff(text_a: str, text_b: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Compute an aligned line-level diff.

    Returns (left_rows, right_rows). Each row is (text, status) where status is one of:
    'same', 'removed', 'added', 'pad'. Padding rows let the two columns stay aligned.
    """
    a = text_a.splitlines()
    b = text_b.splitlines()
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    left: list[tuple[str, str]] = []
    right: list[tuple[str, str]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for line in a[i1:i2]:
                left.append((line, "same"))
                right.append((line, "same"))
        elif tag == "delete":
            for line in a[i1:i2]:
                left.append((line, "removed"))
                right.append(("", "pad"))
        elif tag == "insert":
            for line in b[j1:j2]:
                left.append(("", "pad"))
                right.append((line, "added"))
        elif tag == "replace":
            a_lines = a[i1:i2]
            b_lines = b[j1:j2]
            n = max(len(a_lines), len(b_lines))
            for k in range(n):
                av = a_lines[k] if k < len(a_lines) else ""
                bv = b_lines[k] if k < len(b_lines) else ""
                left.append((av, "removed" if av else "pad"))
                right.append((bv, "added" if bv else "pad"))
    return left, right
