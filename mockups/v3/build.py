#!/usr/bin/env python3
"""Build mockups/v3/index.html (a page fragment, see SPEC.md section 2).

Usage: python3 mockups/v3/build.py [--stub]
Uses src/slides.js, or src/slides.stub.js with --stub (also the fallback,
with a warning, when src/slides.js does not exist yet).
"""
import html
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "src"


def read(p):
    return p.read_text(encoding="utf-8")


def font_links(js):
    m = re.search(r"/\*\s*FONT_LINKS\b(.*?)\*/", js[:4000], re.S)
    if not m:
        return []
    return [ln.strip() for ln in m.group(1).splitlines() if ln.strip().startswith("http")]


def safe_script(js):
    return re.sub(r"</(script)", r"<\\/\1", js, flags=re.I)


def safe_style(css):
    return re.sub(r"</(style)", r"<\\/\1", css, flags=re.I)


def main():
    use_stub = "--stub" in sys.argv[1:]
    slides = SRC / "slides.js"
    if use_stub:
        slides = SRC / "slides.stub.js"
    elif not slides.exists():
        print("warning: src/slides.js not found, using src/slides.stub.js", file=sys.stderr)
        slides = SRC / "slides.stub.js"
    slides_js = read(slides)
    parts = [
        "<title>AutoDeck v3 Mock-up</title>",
        '<meta name="claude:viewport-fit-sides" content="cover">',
    ]
    for url in font_links(slides_js):
        parts.append('<link rel="stylesheet" href="%s">' % html.escape(url, quote=True))
    parts.append("<style>\n%s\n</style>" % safe_style(read(SRC / "app.css")))
    parts.append(read(SRC / "body.html"))
    parts.append("<script>\n%s\n</script>" % safe_script(slides_js))
    parts.append("<script>\n%s\n</script>" % safe_script(read(SRC / "app.js")))
    out = HERE / "index.html"
    out.write_text("\n".join(parts) + "\n", encoding="utf-8")
    print("wrote %s (%d bytes) using %s" % (out, out.stat().st_size, slides.name))


if __name__ == "__main__":
    main()
