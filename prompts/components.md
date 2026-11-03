# Components

The catalog in the request lists every component, what each is for, and its slots with their
budgets. Choose for what the slide has to *do*: the claim's shape decides the component. The
`slide-bodies` skill has the table for matching a claim to a component and a body recipe for
every component. Fill only the slots the chosen component has.

## Filling the slots

- Use only the slot names printed for the chosen component.
- A slot marked **LIST** takes one block per item, all with that slot name, in display order.
- A slot marked `(optional)` may be left empty, and should be when nothing honest fills it.
  **A content slide's body is not optional.** At least one cited block goes under every
  content headline.
- `source` and `section_number` are filled by code. Never write them.
- Each slot shows a **target** ("aim ≤ N characters") and a **ceiling** ("at most L lines,
  roughly M characters"). Write to the target. A block over the ceiling is rejected, measured
  in the real font. It is never shrunk to fit.
- Some components give the headline only one line of about 43 characters, and
  `callout_takeaway` has no headline slot at all. Read the budget before writing the header.
