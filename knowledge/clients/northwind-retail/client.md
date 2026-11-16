# Northwind Retail Group

> **Fictional.** Northwind is a long-standing placeholder company name in sample datasets;
> it is used here so the seed corpus can ship in a public repository. Nothing in this
> folder describes a real organisation, and none of the figures below are citable — see
> the note at the bottom.

## Who they are

A mid-market European retail group: roughly 400 stores, a growing e-commerce channel, and
an in-house engineering team of about 60. They sell general merchandise, so their product
catalogue is large, messy, and constantly changing — which is what pushed them toward
language models in the first place.

## What they have built

An LLM-backed customer-service assistant, live for eleven months, handling order status,
returns and product questions. It runs on a self-hosted open-weights model on rented GPUs
rather than a hosted API, a decision taken for data-residency reasons that have not
changed. A second workload — automated product-description generation for new catalogue
entries — runs as a nightly batch job on the same cluster.

## Why they are talking to us

The assistant works. The GPU bill does not. Serving cost per conversation has become the
constraint on rolling the assistant out to two further markets, and the engineering team's
own view is that they are "probably leaving a lot on the table" but cannot say how much
without a structured look at the options. They have asked specifically whether they should
buy more GPUs or serve the model better.

## What they care about, in their order

1. **Cost per conversation.** The number the CFO tracks. Everything else is instrumental.
2. **P95 latency on the interactive path.** They have an internal SLO and treat regressions
   as incidents. The batch job has no latency constraint at all — this asymmetry matters,
   because several techniques in the corpus trade latency for throughput or the reverse.
3. **Answer quality.** Measured by a human review sample and by escalation-to-agent rate.
   Their tolerance for a quality regression is low but not zero, and they have said they
   would accept a small one for a large cost move — with evidence.
4. **Data residency.** Non-negotiable and already settled. It is why they self-host, and it
   removes hosted-API options from the table rather than being a criterion to weigh.

## How to talk to them

The audience is the CTO and two engineering leads, not a board. They read the detail, they
will ask what hardware a number was measured on, and they respond badly to a benchmark
quoted without its configuration. Quantitative and hedged beats confident and round.

They have been pitched "10× cheaper inference" twice already and are sceptical of the
framing. Leading with a compound multiplier will cost credibility in the first two
minutes.

## Accuracy note

Everything above is engagement context — who they are and what they want. **None of it is
citable evidence.** It is fictional here, and even in a real engagement, a client-supplied
figure needs a source recorded like any other. Numbers on slides come from the project
corpus or from client data with a stated provenance, never from this file (A1, A5).
