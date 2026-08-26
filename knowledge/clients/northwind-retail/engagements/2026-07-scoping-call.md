# Scoping call — 2026-07-14

> Fictional, like the rest of this folder. Present so the loader's `engagements/` path is
> exercised by real content and so `ContextAssembler.assemble()` has something to load
> beyond the two required files.

Attendees: their CTO, two engineering leads; us.

## What they said

- Serving cost per conversation has roughly tripled since launch, driven by volume rather
  than by any change to the model or the prompt.
- They run a single open-weights model, self-hosted, on rented GPUs. Data residency
  settled that; they do not want it reopened.
- Two workloads on one cluster: the interactive assistant, which has a P95 latency SLO,
  and a nightly batch job generating product descriptions, which has no latency constraint
  whatsoever. They had not previously thought of these as different problems.
- Their instinct is that batch size is the lever. They have not measured where memory goes.
- Explicit ask: *"Should we buy more GPUs or serve the model better?"*
- Explicit warning: they have sat through two vendor pitches promising an order of
  magnitude and found neither survived a question about the measurement setup.

## What we agreed to produce

A findings deck: where their serving cost goes, which published techniques apply to their
stack, and a sequenced recommendation. Every number cited to a page.

## Open questions carried into the work

- What is their actual quality bar, expressed as something measurable? "Escalation rate
  must not rise" was offered but not quantified.
- Batch job SLA — is overnight a hard window or a habit? Changes whether throughput-first
  techniques apply cleanly to it.
- No GPU utilisation telemetry was shared on the call. Without it, any claim about *their*
  bottleneck is an inference from the literature, not a measurement of their system, and
  the deck must say so (A8).
