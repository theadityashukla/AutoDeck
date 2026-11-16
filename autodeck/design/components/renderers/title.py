"""`title` — deck title, subtitle, presenter and date line.

The narrative job: set the context for everything that follows. A title slide answers three
questions: what is this deck about, who made it (or presents it), and when. Three pieces of
information, and the design job is proportional — make the title the headline, the subtitle
the supporting argument, and the presenter/date line small enough to read without competing.

The structure follows the headline-and-body pattern every other component uses: a title
stack (title and optional subtitle) placed in a body region, then an optional presenter/date
line at the foot.

Owning phase: 3a (task 3a.4), the first tranche.
"""

from __future__ import annotations

from dataclasses import dataclass

from pptx.slide import Slide

from autodeck.design.layout_kit import Canvas

#: Panel inset on all four sides for the main content block.
_PANEL_PADDING = 40.0


@dataclass
class TitleContent:
    """The slots this component fills."""

    title: str
    """The main deck title — the headline, set large."""
    subtitle: str = ""
    """A supporting subtitle under the title, optional."""
    presenter: str = ""
    """Who presents this deck — name and optionally role or organisation."""
    date: str = ""
    """When this deck was created or presented. May be left empty."""
    accent: str = "accent1"


def render(slide: Slide, canvas: Canvas, content: TitleContent) -> None:
    """Render `content` onto `slide`."""
    frame = canvas.on(slide)
    body, _caption = frame.body_and_caption()

    # Main title/subtitle stack
    main = frame.stack("title main", body.width - _PANEL_PADDING * 2)
    main.text(content.title, canvas.style("display", face="major", bold=True))
    if content.subtitle:
        main.text(
            content.subtitle,
            canvas.style("title", face="minor", color="dk2"),
            gap=canvas.baseline * 3,
        )
    region = main.place(body.pad(_PANEL_PADDING), valign="middle")

    # Presenter and date at the foot if provided.
    #
    # Presenter and date are two IR fields and stay two lines. They used to be joined into one
    # string with a hard-coded " · ": a component composing text the IR never held. A
    # separator is not a number, but "components copy content and never compose it" has no
    # exception for glyphs, and two lines need no invention at all.
    if content.presenter or content.date:
        footer = frame.stack("title footer", region.width)
        footer_style = canvas.style("body", color="dk2", valign="bottom")
        parts = [part for part in (content.presenter, content.date) if part]
        for index, part in enumerate(parts):
            footer.text(part, footer_style, gap=0.0 if index == 0 else canvas.baseline)
        footer.place(region, valign="bottom")
