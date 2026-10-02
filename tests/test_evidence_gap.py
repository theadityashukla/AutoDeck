"""The evidence-gap check, and the ceiling that stops a model overclaiming.

The load-bearing tests are `test_a_model_cannot_claim_support_that_retrieval_did_not_find`
and `test_a_single_corpus_hit_is_capped_to_thin`. Both assert the same property from
different directions: **the classifier's answer is bounded by the evidence actually
retrieved.** A model asked "is this supported?" while holding topically-adjacent text is
agreeable, so agreement is not treated as evidence.

Every fake classifier here returns `supported`, deliberately. That is the failure being
guarded against — a model that always says yes — and the tests assert the module produces
the right answer anyway.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autodeck.agents.evidence_gap import (
    EvidenceClassification,
    EvidenceProbe,
    EvidenceSpan,
    gather_evidence,
)
from autodeck.ingest.document_store import Document, DocumentElement, DocumentStore
from autodeck.ir.models import KeyMessage
from autodeck.knowledge.loader import CachedClaim
from autodeck.retrieval.hybrid import build_index

MEMORY = (
    "LLM.int8() can cut the memory needed for inference by half while retaining full "
    "precision performance on models up to 175B parameters."
)
THROUGHPUT = (
    "vLLM improves the LLM serving throughput by 2-4x compared to the state-of-the-art "
    "systems, without affecting model accuracy."
)
LATENCY = "Speculative decoding gives a latency improvement of 2X-3X on T5-XXL."


class AlwaysSupported:
    """The failure mode, as a test double: a classifier that agrees with everything."""

    def __init__(self, quote: str = "") -> None:
        self.quote = quote
        self.calls = 0

    def complete_structured(self, prompt, response_model, *, system=None):  # type: ignore[no-untyped-def]
        self.calls += 1
        return EvidenceClassification(
            status="supported", reasoning="Looks right to me.", strongest_quote=self.quote
        )


class Honest:
    def __init__(self, status: str, quote: str = "") -> None:
        self.status = status
        self.quote = quote

    def complete_structured(self, prompt, response_model, *, system=None):  # type: ignore[no-untyped-def]
        return EvidenceClassification(
            status=self.status,  # type: ignore[arg-type]
            reasoning="Measures memory, not cost.",
            strongest_quote=self.quote,
        )


class Broken:
    def complete_structured(self, prompt, response_model, *, system=None):  # type: ignore[no-untyped-def]
        raise RuntimeError("provider exploded")


def element(
    element_id: str, text: str, *, page: int = 1, kind: str = "text"
) -> DocumentElement:
    return DocumentElement(
        element_id=element_id,
        doc_id="paper-1",
        kind=kind,  # type: ignore[arg-type]
        page=page,
        bbox=(72.0, 100.0, 523.0, 200.0),
        reading_order=0,
        text=text,
    )


def corpus(*elements: DocumentElement) -> Document:
    return Document(
        doc_id="paper-1", source_path="paper-1.pdf", page_count=6, elements=list(elements)
    )


def probe_for(tmp_path: Path, *elements: DocumentElement, **kwargs) -> EvidenceProbe:  # type: ignore[no-untyped-def]
    document = corpus(*elements)
    store = DocumentStore(tmp_path)
    store.add(document)
    return EvidenceProbe(
        index=build_index([document], project="llm-inference-efficiency"),
        store=store,
        **kwargs,
    )


def message(text: str = MEMORY, message_id: str = "km1") -> KeyMessage:
    return KeyMessage(id=message_id, text=text)


# ---------------------------------------------------------------------------
# The ceiling
# ---------------------------------------------------------------------------


def test_a_model_cannot_claim_support_that_retrieval_did_not_find(tmp_path: Path) -> None:
    """No citable span means no question to ask — the classifier is never even called."""
    classifier = AlwaysSupported()
    probe = probe_for(
        tmp_path, element("e1", "Photosynthesis in C4 plants."), classifier=classifier
    )

    result = probe.probe(message())

    assert result.status == "unsupported"
    assert classifier.calls == 0, "the model was consulted with nothing to judge"
    assert "nothing to judge" in result.reasoning


def test_a_single_corpus_hit_is_capped_to_thin(tmp_path: Path) -> None:
    """One source stated as settled is the definition of thin, so encode it rather than
    trusting the prompt to be obeyed."""
    probe = probe_for(tmp_path, element("e1", MEMORY), classifier=AlwaysSupported())

    result = probe.probe(message())

    assert result.status == "thin"
    assert result.capped is True


def test_capping_is_visible(tmp_path: Path) -> None:
    """A classifier that regularly needs capping is one to stop trusting — and that signal
    is invisible if the cap is silent."""
    probe = probe_for(
        tmp_path,
        element("e1", MEMORY),
        element("e2", THROUGHPUT, page=2),
        classifier=AlwaysSupported(),
    )
    assert probe.probe(message()).capped is False


def test_a_single_curated_claim_is_not_capped(tmp_path: Path) -> None:
    """A human already read it, checked the quote, and wrote down what it does not say."""
    probe = probe_for(
        tmp_path,
        element("e1", MEMORY),
        claims=[
            CachedClaim(
                claim="LLM.int8() halves inference memory.",
                doc_id="paper-1",
                page=1,
                quote="cut the memory needed for inference by half",
            )
        ],
        classifier=AlwaysSupported(),
    )

    result = probe.probe(message())

    assert result.status == "supported"
    assert result.capped is False
    assert result.evidence[0].source == "claims.md"


def test_a_fabricated_quote_is_dropped(tmp_path: Path) -> None:
    """A hallucinated quote in the brief looks identical to a real one, and would send the
    writer looking for a sentence that does not exist."""
    probe = probe_for(
        tmp_path,
        element("e1", MEMORY),
        element("e2", THROUGHPUT, page=2),
        classifier=AlwaysSupported(quote="cuts inference cost by 87% across all workloads"),
    )
    assert probe.probe(message()).strongest_quote == ""


def test_a_real_quote_survives(tmp_path: Path) -> None:
    probe = probe_for(
        tmp_path,
        element("e1", MEMORY),
        element("e2", THROUGHPUT, page=2),
        classifier=AlwaysSupported(quote="cut the memory needed for inference by half"),
    )
    assert "cut the memory" in probe.probe(message()).strongest_quote


# ---------------------------------------------------------------------------
# Honest failure
# ---------------------------------------------------------------------------


def test_a_classifier_failure_reports_unprobed_rather_than_guessing(tmp_path: Path) -> None:
    """Failing the whole session because one classification errored is worse than saying
    nobody looked — but claiming support would be worse than both."""
    probe = probe_for(tmp_path, element("e1", MEMORY), classifier=Broken())

    result = probe.probe(message())

    assert result.status == "unprobed"
    assert "Classification failed" in result.reasoning


def test_without_a_classifier_nothing_is_marked_supported(tmp_path: Path) -> None:
    probe = probe_for(tmp_path, element("e1", MEMORY), element("e2", THROUGHPUT, page=2))

    result = probe.probe(message())

    assert result.status == "unprobed"
    assert result.evidence, "gathering still ran"


def test_thin_and_unsupported_both_demand_a_risk(tmp_path: Path) -> None:
    for status in ("thin", "unsupported"):
        probe = probe_for(
            tmp_path,
            element("e1", MEMORY),
            element("e2", THROUGHPUT, page=2),
            classifier=Honest(status),
        )
        assert probe.probe(message()).needs_a_risk()


def test_supported_demands_no_risk(tmp_path: Path) -> None:
    probe = probe_for(
        tmp_path,
        element("e1", MEMORY),
        element("e2", THROUGHPUT, page=2),
        classifier=Honest("supported"),
    )
    assert not probe.probe(message()).needs_a_risk()


# ---------------------------------------------------------------------------
# Gathering
# ---------------------------------------------------------------------------


def test_gathering_returns_only_citable_spans(tmp_path: Path) -> None:
    """A figure description helps find the page and can never back a claim (§6.3).

    Including it would let the classifier treat generated text as evidence.
    """
    figure = element("fig1", "", kind="figure", page=3)
    figure.description = "[VLM figure description] Memory halving across model sizes."
    document = corpus(element("e1", MEMORY), figure)
    store = DocumentStore(tmp_path)
    store.add(document)

    spans = gather_evidence(
        "memory halving", index=build_index([document], project="p"), store=store
    )

    assert spans
    assert all(span.doc_id == "paper-1" for span in spans)
    assert not any("VLM figure description" in span.text for span in spans)


def test_curated_claims_lead_the_evidence(tmp_path: Path) -> None:
    """D8: claims.md is the main road, retrieval is the long tail."""
    document = corpus(element("e1", MEMORY), element("e2", THROUGHPUT, page=2))
    store = DocumentStore(tmp_path)
    store.add(document)

    spans = gather_evidence(
        "memory needed for inference by half",
        index=build_index([document], project="p"),
        store=store,
        claims=[
            CachedClaim(
                claim="LLM.int8() halves inference memory.",
                doc_id="paper-1",
                page=1,
                quote="cut the memory needed for inference by half",
            )
        ],
    )

    assert spans[0].source == "claims.md"


def test_a_stale_curated_claim_does_not_become_evidence(tmp_path: Path) -> None:
    """claims.md is hand-maintained and a re-ingest can move a span."""
    document = corpus(element("e1", MEMORY))
    store = DocumentStore(tmp_path)
    store.add(document)

    spans = gather_evidence(
        "memory inference half",
        index=build_index([document], project="p"),
        store=store,
        claims=[
            CachedClaim(
                claim="Memory inference halved.",
                doc_id="paper-1",
                page=1,
                quote="a sentence that is no longer in this document at all",
            )
        ],
    )

    assert all(span.source == "corpus" for span in spans)


def test_an_unrelated_message_gathers_nothing(tmp_path: Path) -> None:
    document = corpus(element("e1", MEMORY))
    store = DocumentStore(tmp_path)
    store.add(document)
    assert (
        gather_evidence(
            "chlorophyll absorption spectra",
            index=build_index([document], project="p"),
            store=store,
        )
        == []
    )


# ---------------------------------------------------------------------------
# Applying results to the brief
# ---------------------------------------------------------------------------


def test_a_result_updates_the_message_it_probed(tmp_path: Path) -> None:
    probe = probe_for(
        tmp_path,
        element("e1", MEMORY),
        element("e2", THROUGHPUT, page=2),
        classifier=Honest("thin"),
    )
    original = message()
    updated = probe.probe(original).apply(original)

    assert updated.evidence_status == "thin"
    assert updated.probe_notes == "Measures memory, not cost."
    assert updated.supporting_claims  # leads for the writer
    assert original.evidence_status == "unprobed", "the original must not be mutated"


def test_a_suggested_risk_carries_the_reasoning_and_a_name(tmp_path: Path) -> None:
    probe = probe_for(tmp_path, element("e1", MEMORY), classifier=Honest("thin"))
    subject = message()
    risk = probe.probe(subject).suggested_risk(subject, accepted_by="owner")

    assert risk.message_id == "km1"
    assert risk.accepted_by == "owner"
    assert "memory" in risk.description


def test_probing_a_brief_worth_of_messages(tmp_path: Path) -> None:
    probe = probe_for(
        tmp_path,
        element("e1", MEMORY),
        element("e2", THROUGHPUT, page=2),
        element("e3", LATENCY, page=4),
        classifier=Honest("supported"),
    )
    results = probe.probe_all([message(MEMORY, "km1"), message(LATENCY, "km2")])
    assert [r.message_id for r in results] == ["km1", "km2"]


def test_evidence_renders_with_its_source(tmp_path: Path) -> None:
    """The classifier is told whether it is looking at a curated claim or a raw hit."""
    rendered = EvidenceSpan(doc_id="paper-1", page=4, text="x", source="claims.md").render()
    assert "claims.md" in rendered
    assert "p.4" in rendered


def test_the_classifier_sees_the_message_and_the_evidence(tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    class Capturing:
        def complete_structured(self, prompt, response_model, *, system=None):  # type: ignore[no-untyped-def]
            captured["prompt"] = prompt
            captured["system"] = system or ""
            return EvidenceClassification(status="thin", reasoning="ok")

    probe = probe_for(tmp_path, element("e1", MEMORY), classifier=Capturing())
    probe.probe(message())

    assert MEMORY in captured["prompt"]
    assert "cut the memory" in captured["prompt"]
    assert "Topical relatedness is not support" in captured["system"]


def test_unprobed_is_not_an_answer_the_model_can_give() -> None:
    """The schema lets it through, so the prompt forbids it and the code never returns it
    from a successful classification — only from a failure or an absent classifier."""
    assert "Never unprobed" in (EvidenceClassification.model_fields["status"].description or "")


@pytest.mark.parametrize("status", ["supported", "thin", "unsupported"])
def test_every_classification_status_is_accepted(status: str) -> None:
    assert EvidenceClassification(status=status, reasoning="r").status == status  # type: ignore[arg-type]
