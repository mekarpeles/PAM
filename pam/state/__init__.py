"""Role-dependent state ("where are we").

Phase 3 lands here:
- ADA-agent state = reuse heartbeat/taxonomy.categorize() (coarse category from PR/CI/review/cq)
  + the current Oracle stage (first unsatisfied guard in oracle.yml `states:`)
  + ledger buckets from where_are_we.py (DONE/STALE/ASSERTED/OPEN vs a SHA).
- Division-Lead state = a review of a Epic/epic (sub-issues + their agents' states + labels).
We render what exists; we do NOT invent a phase:* label scheme or a monotonic "% done".
Kept empty in the foundation phase.
"""
