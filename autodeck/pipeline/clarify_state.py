"""The clarify checkpoint as a file: what the draft assumes and what the person said (B47).

`runs/<run>/clarify.json` holds the clarify call's assumptions and questions and, once the
person has responded, their answers and any corrections to the assumptions. `autodeck
answer` and the review UI both record through `record_answers`, and `autodeck draft` reads
through `load_clarify`, so there is one reading of "the person has answered".

Answers are what the draft is allowed to start from: the draft is refused until every
question has an answer (accepting the suggestions counts, B48) — never defaulted silently,
because a question the person did not see is not a question they answered.

Nothing here approves anything; recording an answer is input to the draft, not an approval.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

CLARIFY_FILE = "clarify.json"


class ClarifyStateError(RuntimeError):
    """The clarify file is missing, unreadable, or the answers do not fit its questions."""


def clarify_path(run_root: Path) -> Path:
    return Path(run_root) / CLARIFY_FILE


def load_clarify(run_root: Path) -> dict[str, Any]:
    path = clarify_path(run_root)
    if not path.exists():
        raise ClarifyStateError(
            f"this run has no clarify step yet ({path} is missing). "
            "Run `autodeck clarify` first."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ClarifyStateError(f"{path} cannot be read: {exc}") from exc
    if not isinstance(data, dict):
        raise ClarifyStateError(f"{path} is not a clarify file.")
    return data


def save_clarify(run_root: Path, data: Mapping[str, Any]) -> Path:
    path = clarify_path(run_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(dict(data), indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def new_clarify(
    *,
    prompt: str,
    client: str,
    project: str,
    assumptions: Sequence[Mapping[str, Any]],
    questions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "prompt": prompt,
        "client": client,
        "project": project,
        "assumptions": [dict(a) for a in assumptions],
        "questions": [dict(q) for q in questions],
        "answers": None,
        "corrections": [],
    }


def missing_answers(data: Mapping[str, Any]) -> list[str]:
    """Ids of questions with no recorded answer; every one if nothing was recorded."""
    answers = data.get("answers") or {}
    return [
        q["id"] for q in data.get("questions", []) if not str(answers.get(q["id"], "")).strip()
    ]


def is_answered(data: Mapping[str, Any]) -> bool:
    """Whether the person has responded: an answer set exists and covers every question."""
    return data.get("answers") is not None and not missing_answers(data)


def record_answers(
    data: dict[str, Any],
    *,
    answers: Mapping[str, str] | None = None,
    corrections: Sequence[str] = (),
    accept_all: bool = False,
) -> dict[str, Any]:
    """Merge answers and corrections into `data` (in place) and return it.

    Raises:
        ClarifyStateError: an answer for a question that does not exist, or questions left
            unanswered without `accept_all` (they are named).
    """
    known = {q["id"]: q for q in data.get("questions", [])}
    given = {str(k): str(v).strip() for k, v in (answers or {}).items()}
    unknown = sorted(k for k in given if k not in known)
    if unknown:
        raise ClarifyStateError(
            f"no such question: {', '.join(unknown)}. Questions: {', '.join(known) or 'none'}."
        )
    merged = {**(data.get("answers") or {}), **{k: v for k, v in given.items() if v}}
    if accept_all:
        for qid, question in known.items():
            merged.setdefault(qid, str(question.get("suggested_answer", "")))
    left = [qid for qid in known if not str(merged.get(qid, "")).strip()]
    if left:
        raise ClarifyStateError(
            f"unanswered: {', '.join(left)}. Answer each, or accept the suggested answers."
        )
    data["answers"] = merged
    data["corrections"] = [
        *data.get("corrections", []),
        *(c.strip() for c in corrections if c.strip()),
    ]
    return data


def answer_pairs(data: Mapping[str, Any]) -> list[tuple[str, str] | str]:
    """What compose is told: `(question, answer)` pairs, then each correction as a string."""
    answers = data.get("answers") or {}
    out: list[tuple[str, str] | str] = [
        (q["question"], str(answers[q["id"]]))
        for q in data.get("questions", [])
        if q["id"] in answers
    ]
    out.extend(data.get("corrections", []))
    return out
