# Cost is computed at ingest from effective-dated rate cards and stored

`cost_yuan` is a stored column, computed when an event is ingested using the rate card in effect at the request's instant (date range first, then time-of-day band). Rate cards live in a versioned, hand-edited file in the repo: today's hardcoded `PRICING` map, its "EDIT these rates" comment, and the glm-5.3-flash "limited-time discount" comment all become dated data. Export pushes the stored value as-is; no pricing happens at export.

Considered and rejected: deriving cost at read time, which would self-heal history whenever a card is added or corrected. The stored-at-ingest choice keeps a stable, auditable record that never moves after ingest, at the cost of leaving earlier events mispriced (or null) when a card arrives late — an explicit recompute pass is the only repair, and whether one is needed stays open on the map.
