# Contoso Health

> **Fictional.** Contoso is a long-standing placeholder company name in sample datasets.
> Nothing here describes a real organisation.

## Why this folder exists

To make A4 falsifiable against real folders rather than only against a test fixture.

Client isolation is the invariant whose failure is a confidentiality breach rather than a
bad slide, and an invariant that only one client's data can ever exercise is not really
being tested. With `contoso-health` present, a `northwind-retail` build that reaches into
this directory — through a path, a reference deck, a theme asset, or a cached retrieval
index — raises `ClientIsolationError` in the seed corpus, not just in `tests/`.

It is deliberately thin. Two required files and nothing else: the point is that it exists
and is reachable in principle, not that it is a worked example.

## Who they are

A regional healthcare provider evaluating a clinical-documentation assistant. They share
the project corpus — inference efficiency is inference efficiency — and nothing else with
Northwind. Different regulatory position, different latency profile, different audience.

That shared-project / separate-client split is the two-tier structure (D8) doing its job:
the evidence is reusable, the context is not.

## Accuracy note

Engagement context, not evidence. Nothing here is citable.
