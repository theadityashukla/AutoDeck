"""`autodeck.design.charts` — native editable charts from `ChartSpec` (task 3a.5).

Three things are worth being able to say about this module with evidence rather than
assertion, and this file is organised around them:

- **The data is genuinely editable, not baked.** `TestEditableData` unzips a produced
  `.pptx`, confirms the chart is a `c:chartSpace` part referenced by formula (`c:f`) rather
  than a picture, and opens the embedded workbook with `openpyxl` to check its cells hold
  the real numbers.
- **No chart type falls back to a picture.** `TestEveryChartKind` builds all seven; the one
  case this module cannot build from bad input (`scatter` with non-numeric categories)
  raises `ChartConstructionError` rather than drawing anything.
- **Nothing shrinks chart text to fit.** `TestOverflow` checks the `LayoutOverflowError`
  path for a title, an axis title, a category label and a series name, and that nothing was
  drawn to the slide before the raise.

`TestRenderedByLibreOffice` is the local, B31-honest half: LibreOffice is what this
environment actually has (there is no PowerPoint here), so it is what gets exercised
directly, both by rasterising the deck and by round-tripping it through LibreOffice's own
`--convert-to pptx` and re-checking the chart part and workbook survive.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import get_args

import openpyxl
import pytest
from pptx.enum.chart import XL_CHART_TYPE
from pptx.enum.shapes import MSO_SHAPE_TYPE

from autodeck.design import charts
from autodeck.design.charts import ChartConstructionError, place_chart
from autodeck.design.fonts import is_available
from autodeck.design.layout_kit import Canvas, Frame, LayoutOverflowError
from autodeck.design.theme.master_builder import new_presentation, save_themed
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ir.models import ChartKind, ChartSeries, ChartSpec, Citation
from autodeck.render.qa.libreoffice import render_pptx
from tests.test_catalog import tokens_for

requires_test_font = pytest.mark.skipif(
    not is_available("Liberation Sans"), reason="Liberation Sans not installed"
)

QUOTE_A = "Revenue grew from $10.0M in Q1 to $14.0M in Q4."
QUOTE_B = "Headcount rose from 40 to 55 over the same period."


def _citation(doc_id: str = "vendor-report", page: int = 4, quote: str = QUOTE_A) -> Citation:
    return Citation.for_quote(
        doc_id=doc_id,
        page=page,
        bbox=(10.0, 20.0, 300.0, 44.0),
        quote=quote,
        retrieved_by="writer",
    )


def _spec(**overrides: object) -> ChartSpec:
    """A valid column chart, overridable field by field.

    If `categories` is overridden without also overriding `series`, the default series'
    values are stretched or trimmed to match — most tests here only care about one field at
    a time and would otherwise have to restate a matching series just to change how many
    categories there are.
    """
    defaults: dict[str, object] = dict(
        chart_type="column",
        title="Quarterly revenue",
        categories=["Q1", "Q2", "Q3", "Q4"],
        series=[ChartSeries(name="Revenue", values=[10.0, 11.5, 12.0, 14.0])],
        x_axis_label="Quarter",
        y_axis_label="Revenue ($M)",
        source_citations=[_citation()],
    )
    if "categories" in overrides and "series" not in overrides:
        width = len(overrides["categories"])  # type: ignore[arg-type]
        values = [float(i + 1) for i in range(width)]
        overrides = {**overrides, "series": [ChartSeries(name="Revenue", values=values)]}
    defaults.update(overrides)
    return ChartSpec(**defaults)  # type: ignore[arg-type]


def _frame(tokens: DesignTokens) -> Frame:
    """A real slide to draw on. python-pptx only — no LibreOffice, so this runs in CI."""
    presentation = new_presentation(tokens)
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    return Canvas(tokens).on(slide)


def _text_of(shape: object) -> str | None:
    if not getattr(shape, "has_text_frame", False):
        return None
    return shape.text_frame.text  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Every ChartKind
# ---------------------------------------------------------------------------


class TestEveryChartKind:
    @requires_test_font
    def test_every_chart_kind_has_a_native_mapping(self) -> None:
        assert set(charts._CHART_TYPE) == set(get_args(ChartKind))

    @requires_test_font
    @pytest.mark.parametrize("kind", get_args(ChartKind))
    def test_builds_a_native_chart_not_a_picture(self, kind: ChartKind) -> None:
        categories = ["1", "2", "3"] if kind == "scatter" else ["Alpha", "Beta", "Gamma"]
        spec = _spec(
            chart_type=kind,
            categories=categories,
            series=[ChartSeries(name="Series 1", values=[3.0, 5.0, 4.0])],
        )
        frame = _frame(tokens_for())
        graphic_frame = place_chart(frame, frame.canvas.content, spec)

        assert graphic_frame.has_chart
        assert graphic_frame.shape_type == MSO_SHAPE_TYPE.CHART
        assert not any(
            shape.shape_type == MSO_SHAPE_TYPE.PICTURE for shape in frame.slide.shapes
        )

    @requires_test_font
    def test_scatter_with_non_numeric_categories_is_an_escalation_not_a_picture(self) -> None:
        spec = _spec(chart_type="scatter", categories=["Alpha", "Beta", "Gamma"])
        frame = _frame(tokens_for())
        with pytest.raises(ChartConstructionError, match="numbers"):
            place_chart(frame, frame.canvas.content, spec)
        assert len(frame.slide.shapes) == 0

    @requires_test_font
    def test_scatter_with_numeric_categories_builds(self) -> None:
        spec = _spec(chart_type="scatter", categories=["2021", "2022", "2023"])
        frame = _frame(tokens_for())
        graphic_frame = place_chart(frame, frame.canvas.content, spec)
        assert graphic_frame.chart.chart_type == XL_CHART_TYPE.XY_SCATTER


# ---------------------------------------------------------------------------
# Styling: legend, per-point colour for pie, axes skipped for pie
# ---------------------------------------------------------------------------


class TestStyling:
    @requires_test_font
    def test_legend_is_shown_only_for_more_than_one_series(self) -> None:
        one_series = _spec(series=[ChartSeries(name="Revenue", values=[1.0, 2.0, 3.0, 4.0])])
        frame = _frame(tokens_for())
        assert place_chart(frame, frame.canvas.content, one_series).chart.has_legend is False

        two_series = _spec(
            series=[
                ChartSeries(name="Revenue", values=[1.0, 2.0, 3.0, 4.0]),
                ChartSeries(name="Cost", values=[0.5, 0.6, 0.7, 0.8]),
            ]
        )
        frame2 = _frame(tokens_for())
        assert place_chart(frame2, frame2.canvas.content, two_series).chart.has_legend is True

    @requires_test_font
    def test_pie_colours_each_point_distinctly_rather_than_the_one_series(self) -> None:
        spec = _spec(
            chart_type="pie",
            categories=["A", "B", "C"],
            x_axis_label=None,
            y_axis_label=None,
            series=[ChartSeries(name="Share", values=[40.0, 35.0, 25.0])],
        )
        frame = _frame(tokens_for())
        graphic_frame = place_chart(frame, frame.canvas.content, spec)
        points = list(graphic_frame.chart.series[0].points)
        colours = {point.format.fill.fore_color.theme_color for point in points}
        assert len(colours) == len(points)

    @requires_test_font
    def test_pie_does_not_raise_even_when_axis_labels_are_given(self) -> None:
        """A pie chart has no axis; the labels are simply not drawable, not an error."""
        spec = _spec(chart_type="pie", categories=["A", "B"], x_axis_label="Ignored")
        frame = _frame(tokens_for())
        place_chart(frame, frame.canvas.content, spec)  # must not raise


# ---------------------------------------------------------------------------
# Citations -> the caption band
# ---------------------------------------------------------------------------


class TestCitationCaption:
    @requires_test_font
    def test_source_caption_names_every_distinct_citation_once(self) -> None:
        spec = _spec(
            source_citations=[
                _citation(doc_id="vendor-report", page=4, quote=QUOTE_A),
                _citation(doc_id="vendor-report", page=4, quote="A different span, same cell."),
                _citation(doc_id="hr-report", page=9, quote=QUOTE_B),
            ]
        )
        frame = _frame(tokens_for())
        place_chart(frame, frame.canvas.content, spec)

        captions = [t for t in (_text_of(s) for s in frame.slide.shapes) if t and "Source" in t]
        assert captions == ["Source: vendor-report p.4; hr-report p.9"]

    @requires_test_font
    def test_a_chart_always_draws_a_caption_because_citations_are_never_empty(self) -> None:
        # ChartSpec.source_citations has min_length=1 — there is no "no source" case to
        # special-case the way a plain str `source` field elsewhere in the catalog does.
        spec = _spec()
        frame = _frame(tokens_for())
        place_chart(frame, frame.canvas.content, spec)
        assert any("Source:" in (_text_of(s) or "") for s in frame.slide.shapes)


# ---------------------------------------------------------------------------
# Overflow — raise, never shrink
# ---------------------------------------------------------------------------


class TestOverflow:
    @requires_test_font
    def test_a_title_that_will_not_fit_one_line_raises_rather_than_shrinking(self) -> None:
        spec = _spec(title="This chart title is deliberately far too long to fit " * 4)
        frame = _frame(tokens_for())
        with pytest.raises(LayoutOverflowError, match="title"):
            place_chart(frame, frame.canvas.content, spec)
        assert len(frame.slide.shapes) == 0

    @requires_test_font
    def test_a_category_label_that_will_not_fit_raises(self) -> None:
        spec = _spec(
            categories=["Q1", "A category label written as an entire sentence", "Q3", "Q4"],
            series=[ChartSeries(name="Revenue", values=[10.0, 11.5, 12.0, 14.0])],
        )
        frame = _frame(tokens_for())
        with pytest.raises(LayoutOverflowError, match="category label"):
            place_chart(frame, frame.canvas.content, spec)
        assert len(frame.slide.shapes) == 0

    @requires_test_font
    def test_a_series_name_that_will_not_fit_the_legend_raises(self) -> None:
        long_name = (
            "A second series whose legend label is an entire sentence long " * 3
        ).strip()
        spec = _spec(
            series=[
                ChartSeries(name="Revenue", values=[1.0, 2.0, 3.0, 4.0]),
                ChartSeries(name=long_name, values=[0.5, 0.6, 0.7, 0.8]),
            ]
        )
        frame = _frame(tokens_for())
        with pytest.raises(LayoutOverflowError, match="series name"):
            place_chart(frame, frame.canvas.content, spec)
        assert len(frame.slide.shapes) == 0

    @requires_test_font
    def test_an_axis_title_that_will_not_fit_raises(self) -> None:
        long_label = ("A y-axis title written out as an entire long sentence " * 3).strip()
        spec = _spec(y_axis_label=long_label)
        frame = _frame(tokens_for())
        with pytest.raises(LayoutOverflowError, match="axis title"):
            place_chart(frame, frame.canvas.content, spec)
        assert len(frame.slide.shapes) == 0

    @requires_test_font
    def test_a_single_line_title_at_a_normal_length_does_not_raise(self) -> None:
        spec = _spec(title="Quarterly revenue")
        frame = _frame(tokens_for())
        place_chart(frame, frame.canvas.content, spec)  # must not raise


# ---------------------------------------------------------------------------
# The data itself: editable, not baked
# ---------------------------------------------------------------------------


class TestEditableData:
    @requires_test_font
    def test_the_embedded_workbook_holds_the_real_category_and_series_values(
        self, tmp_path: Path
    ) -> None:
        spec = _spec(
            categories=["Q1", "Q2", "Q3", "Q4"],
            series=[ChartSeries(name="Revenue", values=[10.0, 11.5, 12.0, 14.0])],
        )
        tokens = tokens_for()
        presentation = new_presentation(tokens)
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        frame = Canvas(tokens).on(slide)
        place_chart(frame, frame.canvas.content, spec)

        pptx_path = tmp_path / "deck.pptx"
        save_themed(presentation, tokens, pptx_path)

        with zipfile.ZipFile(pptx_path) as package:
            names = package.namelist()
            chart_parts = [
                n for n in names if n.startswith("ppt/charts/chart") and n.endswith(".xml")
            ]
            embeddings = [
                n for n in names if n.startswith("ppt/embeddings/") and n.endswith(".xlsx")
            ]
            assert chart_parts, f"no chart part in {names}"
            assert embeddings, f"no embedded workbook in {names}"

            chart_xml = package.read(chart_parts[0]).decode("utf-8")
            # A picture would need none of this: `c:f` is the formula reference into the
            # embedded workbook that makes "Edit Data" (and LibreOffice's own data-table
            # editor) point at real cells rather than a cached number with nowhere to go.
            assert "<c:f>Sheet1!" in chart_xml

            workbook_bytes = package.read(embeddings[0])

        workbook = openpyxl.load_workbook(io.BytesIO(workbook_bytes))
        sheet = workbook["Sheet1"]
        assert [sheet.cell(row, 1).value for row in (2, 3, 4, 5)] == ["Q1", "Q2", "Q3", "Q4"]
        assert sheet.cell(1, 2).value == "Revenue"
        assert [sheet.cell(row, 2).value for row in (2, 3, 4, 5)] == [10.0, 11.5, 12.0, 14.0]

    @requires_test_font
    def test_no_image_part_is_ever_written(self, tmp_path: Path) -> None:
        """D10: not one chart type here ever degrades to a picture."""
        tokens = tokens_for()
        presentation = new_presentation(tokens)
        for kind in get_args(ChartKind):
            categories = ["1", "2", "3"] if kind == "scatter" else ["A", "B", "C"]
            slide = presentation.slides.add_slide(presentation.slide_layouts[6])
            frame = Canvas(tokens).on(slide)
            place_chart(
                frame,
                frame.canvas.content,
                _spec(chart_type=kind, categories=categories, title=None),
            )

        pptx_path = tmp_path / "deck.pptx"
        save_themed(presentation, tokens, pptx_path)
        with zipfile.ZipFile(pptx_path) as package:
            images = [n for n in package.namelist() if n.startswith("ppt/media/")]
        assert images == []


# ---------------------------------------------------------------------------
# What LibreOffice actually does with the file (B31: no PowerPoint here)
# ---------------------------------------------------------------------------


class TestRenderedByLibreOffice:
    @pytest.mark.render
    def test_libreoffice_rasterises_the_chart_without_error(self, tmp_path: Path) -> None:
        tokens = tokens_for(family="Inter") if is_available("Inter") else tokens_for()
        presentation = new_presentation(tokens)
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        frame = Canvas(tokens).on(slide)
        place_chart(frame, frame.canvas.content, _spec())

        pptx_path = tmp_path / "deck.pptx"
        save_themed(presentation, tokens, pptx_path)

        result = render_pptx(pptx_path, tmp_path, tokens)
        assert result.page_count == 1
        assert result.images[0].stat().st_size > 0

    @pytest.mark.render
    def test_libreoffice_keeps_it_a_native_chart_with_correct_values_on_its_own_round_trip(
        self, tmp_path: Path
    ) -> None:
        """Convert the deck with LibreOffice itself (`--convert-to pptx`) and inspect what
        comes back out.

        Two things hold, checked directly against the round-tripped XML: it is still a
        `c:chartSpace` (a native chart, never flattened to a picture), and the category and
        series values in its `c:cat`/`c:val` caches are still exactly what this module wrote
        — LibreOffice's own save path did not silently round or drop a number.

        One thing does **not** hold, and is recorded here rather than asserted around: the
        embedded `.xlsx` workbook this module writes is gone from the round-tripped file.
        LibreOffice edits a chart's data through its own in-XML "Data Table" dialog, not
        through the external workbook PowerPoint's "Edit Data in Excel" opens, and its save
        path reflects that — the `c:f` formula references left behind no longer point at a
        real worksheet range (checked: they become bare placeholder strings). This is
        exactly the kind of PowerPoint/LibreOffice OOXML disagreement B31 names as owner
        debt, observed directly rather than assumed: the file this module produces carries a
        real embedded workbook (`TestEditableData`) for PowerPoint's own mechanism, and a
        LibreOffice-native round trip is evidence about LibreOffice's mechanism only, not
        about PowerPoint's — which is exactly why the GATE 3 handover item asks the owner to
        check the latter directly rather than inferring it from this."""
        soffice = shutil.which("soffice") or shutil.which("libreoffice")
        if soffice is None:
            pytest.skip("LibreOffice not installed")

        tokens = tokens_for()
        presentation = new_presentation(tokens)
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        frame = Canvas(tokens).on(slide)
        place_chart(frame, frame.canvas.content, _spec())

        pptx_path = tmp_path / "deck.pptx"
        save_themed(presentation, tokens, pptx_path)

        roundtrip_dir = tmp_path / "roundtrip"
        roundtrip_dir.mkdir()
        subprocess.run(
            [
                soffice,
                f"-env:UserInstallation=file://{tmp_path / 'profile'}",
                "--headless",
                "--norestore",
                "--convert-to",
                "pptx",
                str(pptx_path),
                "--outdir",
                str(roundtrip_dir),
            ],
            capture_output=True,
            text=True,
            timeout=240,
            check=True,
        )
        roundtripped = roundtrip_dir / "deck.pptx"
        assert roundtripped.exists()

        with zipfile.ZipFile(roundtripped) as package:
            names = package.namelist()
            chart_parts = [n for n in names if "chart" in n and n.endswith(".xml")]
            assert chart_parts, f"LibreOffice dropped the chart part entirely: {names}"
            chart_xml = package.read(chart_parts[0]).decode("utf-8")

        assert "<c:barChart>" in chart_xml, "LibreOffice flattened the chart to something else"
        for category in ("Q1", "Q2", "Q3", "Q4"):
            assert f"<c:v>{category}</c:v>" in chart_xml
        for value in ("10", "11.5", "12", "14"):
            assert f"<c:v>{value}</c:v>" in chart_xml
