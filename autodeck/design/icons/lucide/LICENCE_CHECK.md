# Licence check — vendored Lucide icons (task 3a.7)

The brief puts this in bold: *"Verify library licences at implementation time."* This is
that check, done before any icon code in this task, against the actual file committed at
`autodeck/design/icons/lucide/LICENSE` — not against Lucide's reputation as "a permissively
licensed family".

## What is vendored

Ten SVGs, one design (24x24 viewBox, `stroke-width="2"`, round caps/joins, `fill="none"`):
`circle-alert`, `clock`, `git-branch`, `layers`, `shield-check`, `target`, `trending-down`,
`trending-up`, `users`, `zap`.

## The licence file, verbatim

The committed `LICENSE` carries two licences, not one:

> ISC License
>
> Copyright (c) 2026 Lucide Icons and Contributors
>
> Permission to use, copy, modify, and/or distribute this software for any
> purpose with or without fee is hereby granted, provided that the above
> copyright notice and this permission notice appear in all copies.
>
> THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
> WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
> MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
> ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
> WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
> ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
> OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

followed by a second block covering the subset of icons Lucide inherited from the Feather
project:

> The following Lucide icons are derived from the Feather project:
>
> airplay, alert-circle, alert-octagon, alert-triangle, aperture, arrow-down-circle, ...
> (150+ names; abridged here — the full comma-separated list is in the committed `LICENSE`
> file verbatim, not reproduced in full in this record)
>
> The MIT License (MIT) (for the icons listed above)
>
> Copyright (c) 2013-present Cole Bemis
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

Cross-checked against the upstream `lucide-icons/lucide` repository's `LICENSE` on GitHub:
the wording matches (ISC primary licence, MIT carve-out for the named Feather-derived
subset, same two copyright holders). This is the genuine upstream text, not a locally
edited or truncated copy.

## Which licence covers which vendored icon

The Feather-derived list names icons by their **historical Lucide filename**, and Lucide
has since renamed several of them. Checking name-for-name against the list above:

| Vendored icon | In the Feather/MIT list? | Licence that applies |
|---|---|---|
| `clock` | yes (`clock`) | ISC **and** MIT (both notices required) |
| `target` | yes (`target`) | ISC **and** MIT (both notices required) |
| `circle-alert` | not under this name — but this is Lucide's renamed `alert-circle`, which *is* listed | ISC, and MIT by descent (see note) |
| `git-branch` | no | ISC only |
| `layers` | no | ISC only |
| `shield-check` | no | ISC only |
| `trending-down` | no | ISC only |
| `trending-up` | no | ISC only |
| `users` | no | ISC only |
| `zap` | no | ISC only |

**Note on `circle-alert`:** Lucide renamed `alert-circle` to `circle-alert` in a later
release; the Feather-attribution list was written against the old filename and was not
updated on rename. This is a documentation lag in the upstream project, not a licensing
gap — the geometry is the same icon under a new name, so the MIT notice that named
`alert-circle` still covers it. Recorded here so a future contributor does not read the
list literally and miss it.

## Verdict

**Suitable — both licences are short-form permissive.** ISC and MIT each ask only for two
things: keep the copyright notice and permission text with the software, and don't hold the
author liable. Neither is copyleft, neither restricts commercial use, and neither requires
attribution to appear in *output* the software produces (a rendered deck) — only in copies
of the software itself. That condition is satisfied by this repository: the `LICENSE` file
sits in the same directory as the SVGs it covers and is committed alongside them, so every
copy of this codebase carries the required notice with the icons it distributes. No decks
built with this library need to carry an attribution line for this reason alone (a client
contract could still require one, which is a separate, non-licensing question).

The two licences are also mutually compatible — permissive-on-permissive, no term of
either conflicts with the other — so vendoring both under one `LICENSE` file for a mixed
icon set is standard practice, not a shortcut.

**No escalation required.** This does not block building the icon system on top of this
vendored set.

Checked: 2026-09-20, against `autodeck/design/icons/lucide/LICENSE` as committed on this
branch, and cross-referenced with the upstream `lucide-icons/lucide` `LICENSE` file.
