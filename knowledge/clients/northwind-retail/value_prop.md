# Value proposition — Northwind Retail Group

> **This file is framing, not fact (A5).** Everything here is positioning language: how we
> want the work understood. A sentence in this file can shape a deck's argument, and it can
> never back a number. If a claim in a deck traces to this file rather than to a citation,
> that is an A1 violation regardless of how reasonable the sentence sounds.

## The line

They are not short of GPUs. They are short of throughput per GPU. The published work on
inference efficiency is unusually mature and unusually quantitative, and most of it has
not been applied to their stack — so the first move is a measured audit of where their
serving cost actually goes, not a procurement decision.

## Why us

- We read the primary literature and cite it. Every number in what we deliver resolves to
  a page and a sentence in a paper they can open themselves. Given they have already been
  pitched round multipliers twice, verifiability *is* the differentiator here.
- We separate what is measured from what is inferred, and say which is which.
- We are explicit about what the evidence does not cover — technique interaction, their
  specific quality bar, currency cost — rather than extrapolating into it.

## Framing to use

- **"Serve better before you buy more."** The corpus supports this direction, and it is the
  question they actually asked.
- **Latency and throughput are separable for them.** They have one interactive workload
  with an SLO and one batch workload with none. That asymmetry is an advantage, and it is
  the kind of thing a generic vendor pitch misses.
- **Sequence the techniques.** They are independent bodies of work with different
  integration costs; a phased order is a genuinely more useful answer than a menu.

## Framing to avoid

- **Compound multipliers.** "4× cheaper" built by multiplying two papers' speedups is not
  supported by anything in the corpus, and this audience will spot it. A2 forbids it in any
  case: the derived number would have no source.
- **"Industry standard" / "everyone is doing this."** Unsourced, and they will ask who.
- **Hosted-API comparisons.** Data residency has closed that option. Raising it reads as
  not having listened.
- **Certainty about their quality impact.** Nothing in the corpus measures their task.
  Where the answer is "this needs an experiment on your data", say that (A8).
