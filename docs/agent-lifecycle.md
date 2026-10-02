> **Ported from a working implementation**, including its progress log, because the log is where the
> anti-goals were discovered. Names replaced with roles.

# ADA Heartbeat — atomic-agent lifecycle tracking

Started 2026-08-09 while the Operator was away for 2-3h, per his explicit brief. This file is both the
design doc and the running progress log — update the **Progress** section at the bottom every
session rather than letting it go stale.

## The problem, in the Operator's own words

> We have a critical mass of atrophying prototypes... a Pareto effect where the last 20% of
> these projects requires 80% of the work... What we don't have is a safe, effective system
> that proactively (and safely and efficiently) engages our workers and finds ways to move each
> initiative forward. I don't want agents plowing forward in an unpredictable direction but I
> don't want 10 agents sitting around doing nothing... The biggest thing is the framework which
> is preventing ~5 efforts from moving forward in parallel. We have a bunch of agents sleeping
> on the job and no accountability.

And the explicit anti-goal: **not** "hi it's an ADA agent checking in for an update." Not pinging every
5 minutes. Real intuition about idle time. Once an agent answers, either continue the
conversation toward a safe next step, or record the state and stop asking — never loop.

## Scope: what counts as an "atomic agent"

Per the Operator directly: an atomic agent is one responsible for **issue → PR → review → merge →
cleanup**. Not a standing specialist (`saul`, `adadash`, `lupin`, `adapro`), not a personal
agent (`mek*` prefix), not a pure-investigation task with no PR at the end. This scope
deliberately excludes AdaDash's own broader "initiative" tracking, which is about epics and
roadmap visibility — this is one level down, about individual PR-shaped units of work and
whether a human's attention is the actual bottleneck.

## Architecture: three tiers, not one script

the Operator asked directly whether "a centralized script" is the right mechanism. Answer: yes for
signal-gathering, no for judgment — split by cost:

1. **Signal collection (deterministic, ~free).** Reuses `adadash/collect.py` almost entirely —
   it already does exactly this kind of mechanical gathering (`cq` SQLite read-only, `gh --json`,
   `cmux ls`), proven correct over two weeks of real use. This tier decides nothing; it just
   produces facts: PR state/CI/review-decision, per-agent idle hours (self vs. any-writer,
   already distinguished in `collect.py`), and the agent's own last `cq` comment verbatim.
2. **Blocker categorization (cheap, mechanical-first).** New in this directory
   (`taxonomy.py`). Takes tier-1 signals and assigns exactly one category from the Operator's own
   taxonomy (see below). Mostly rule-based against real signals (CI conclusion, review
   decision, diff size, idle hours) — cheap enough to run on every collection pass with no
   token cost at all for the clear-cut cases. A model pass is only warranted for the fuzzy
   cases (does this `cq` comment contain a real open question, or is it a routine log
   entry?) — `taxonomy.py` ships a heuristic first pass for this and flags genuinely
   ambiguous cases rather than guessing.
3. **The nudge itself (expensive, rare, only when it's real).** Not built by an autonomous
   loop in this session — see **Explicit safety boundary** below. This tier is where a
   substantive, category-specific question gets composed and where a decision actually
   worth the Operator's time gets surfaced. Firing this tier is gated by tier-4 (below), not by a
   timer.
4. **Idle-intuition + "don't re-ask" state machine (`state.py`).** The mechanism `claudio`'s
   own `nudges` feature just shipped, one level up: track *when* an agent's real signals
   (tier 1) last materially changed, not a poll clock. A nudge fires only once per genuinely
   new idle-and-stuck period; once fired, the agent moves to "awaiting reply" and is not
   re-nudged until either a real reply lands (new `cq` activity from that agent) or the Operator
   explicitly closes the loop. This is the direct mechanism for "record the state and then
   don't ask again."

## The taxonomy (the Operator's own categories, made concrete)

| Category | Mechanical signal | Example from the live fleet (2026-08-09) |
|---|---|---|
| `no_agent_assigned` | A known-needed effort (see `known_efforts.json`) with no running `cmux` agent referencing it at all | Amazon affiliate → Creators API migration (#13277) — zero agents, zero PRs, 3 days after the post-mortem |
| `needs_testing` | PR failing CI checks that are **not** in the known fork-infra-breakage allowlist (`KNOWN_INFRA_CHECKS` in `collect.py`), or draft with `ntests == 0` on a non-trivial diff | — |
| `needs_review` | PR open, CI green, `reviewDecision` unset, agent's own last comment says it considers the work done | (candidates checked live below) |
| `open_architectural_question` | Agent's last `cq` comment is question-shaped (ends in `?`, or matches a small set of decision-request phrasings) **and** no reply from `an ADA agent`/the Operator postdates it | Solr Availability (#12689) — reindex-vs-active-loans race still open |
| `blocked_on_human` | PR open, CI green, no open questions in `cq`, nothing left for the agent to do | Feed Registry (#13241), AI Workflows (#13242) |
| `exhausted_own_progress` | Idle past threshold, PR neither mergeable-and-clean nor clearly waiting on a specific question — genuinely stuck without one obvious next step | — |
| `needs_splitting` | Draft, alive a long time, diff size large relative to test coverage (reuses `review_confidence`'s "sprawl" signal) | — |
| `merged_needs_cleanup` | PR `state == MERGED` (or `CLOSED`) but the `cmux` agent is still registered/up | — |

This table is deliberately grounded in the real fleet, not hypothetical — `taxonomy.py`'s
tests assert against live (read-only) data where possible, synthetic fixtures where the real
fleet doesn't currently have an example of a category.

## Explicit safety boundary (per the Operator: "do not test against prod agents in a way that may screw
things up")

This build session produces:
- The full read-only signal → category pipeline, tested against real (but never mutated) fleet
  state.
- The state machine, tested against synthetic fixtures (no real agent's nudge-cooldown state is
  touched by a test).
- A **dry-run report** — exactly what the system would say, to whom, and why — generated from
  real data, printed/logged, never sent.

It deliberately does **not**, in this session:
- Send any real `cmux send` to a production agent.
- Write to any real agent's `cq` database.
- Touch `cwd`/`last-session-id` files (that's the separate, already-solved session-integrity
  work from earlier).
- Auto-dispatch anything. Dispatch is a explicit, separate `--dispatch` flag, left unimplemented
  (raises `NotImplementedError`) until the Operator reviews the dry-run output and says go.

## Open decisions for the Operator (not mine to make unilaterally)

1. Where should `known_efforts.json` actually live and who maintains it — is this the same
   thing as the fleet registry (`~/.cmux/.fleet/.cq`) AdaDash already reads from `load_registry()`,
   just needing a "no agent assigned yet" reading added, rather than a new parallel file?
   *(Leaning toward: reuse the existing registry, not a new file — see Progress log.)*
2. Nudge cooldown length — how long is "genuinely idle" before a `blocked_on_human` /
   `exhausted_own_progress` nudge is worth firing? Claudio's own nudges default to 900s (15min)
   for a single agent's own idle loop; this is a much slower-moving system (PRs sit for hours/
   days, not seconds), so the right default is probably hours, not minutes — proposing 4h to
   match `collect.py`'s existing `ACTIVE_H` threshold, but this is a real judgment call.
3. Once dry-run output looks trustworthy, does dispatch mean a real `cmux send`, or should it
   post to a durable, reviewable place first (a `cq` comment on a dedicated heartbeat-tracking
   issue, or a page on the PAM dashboard) with `cmux send` reserved for the rarer
   `no_agent_assigned` / genuinely-new-blocker cases? Leaning toward the latter — matches "not
   pinging every 5 minutes."

---

## Progress log

_(most recent first)_

### TL;DR of the 2026-08-09 build session

Working v1, dry-run only, **57 tests, all real, all passing**. Ran against the live fleet and:

- Correctly reproduced every part of the manual diagnostic table from the framework
  conversation (Solr/Feed-Registry/Core-Vitals `blocked_on_human`, Amazon outage
  `no_agent_assigned`).
- Found 4 real things nobody had flagged: `slackbot` idle 11 days with no PR ever opened;
  `br-1580-audioreader` and `lenny-194-opds-perf` running completely untracked (now
  registered); a genuinely multi-repo Lenny effort this schema can only half-track.
- Found and fixed **4 real bugs**, all caught by tests or real data, none by inspection alone:
  a fork-infra-only CI failure miscategorizing a clean PR; a category transition misreading
  `new` as `changed`; a registry data error (issue number used where a PR number belonged);
  and an unhandled `REVIEW_REQUIRED` review-decision state.
- Proved the core "don't re-ask" promise against real persisted state, not just synthetic
  tests: running twice back-to-back produces zero duplicate surfacings.
- Built the actual message text per category (`messages.py`), tested against the Operator's own literal
  anti-pattern so it can't regress into "just checking in."

**Nothing was sent to anyone.** No `cmux send`, no `cq` writes to any real agent, `--dispatch`
still raises `NotImplementedError` on purpose. Three real open decisions left for the Operator (below),
plus two known, documented-not-fixed limitations (multi-ref-per-effort; the question-detector
only sees a truncated first line of an agent's last comment).

Run `python3 heartbeat.py` from this directory any time for the current report, or
`python3 -m pytest tests/ -v` to re-verify everything including against live data.

Full session narrative, in order, follows below.

### 2026-08-09, build session (the Operator away ~2-3h)

**Status: working v1 of the full dry-run pipeline, validated against live fleet data, 50 tests
passing, nothing dispatched to anyone.**

Built, in order:
1. `known_efforts.json` — standalone registry for this session (5 named case studies + 3 more
   found live: Activity Feed, Preserve Intent, Slackbot). See Open Decision #1 for why this
   should probably move into the real fleet registry later.
2. `taxonomy.py` — the categorizer. 18 tests. **Found and fixed one real logic bug while
   testing**: a PR whose only failing check was a known fork-infra one (see
   `KNOWN_INFRA_CHECKS`) was falling through to the generic `exhausted_own_progress` fallback
   instead of correctly reaching `blocked_on_human` — the `if pr['failing']:` gate was too
   coarse, treating "has any failing check" the same as "has a check failing that's actually
   the PR's fault." Fixed by computing `non_infra_failing` up front and gating on that instead.
   Caught by `test_only_known_infra_check_failing_is_not_needs_testing`, not by inspection.
3. `state.py` — the idle-intuition / don't-re-ask state machine. 15 tests. **Found and fixed a
   second real bug**: transitioning from a never-surfaced category (e.g. `active`) straight
   into a nudge-worthy one (e.g. `blocked_on_human`) was read as `changed` instead of `new`,
   because the code only checked "did prior state exist" rather than "was prior state ever
   actually surfaced." Fixed by tracking `last_surfaced is not None` as the real marker.
   Also caught one test of my own that asserted the WRONG thing (`needs_testing` changing
   failure details should stay quiet, not surface — that's the agent's own work, not the Operator's).
4. `heartbeat.py` — orchestrator wiring collect.py → taxonomy → state, dry-run render, and a
   `--dispatch` flag that deliberately raises `NotImplementedError`.
5. **First real run against the live fleet correctly reproduced the manual diagnostic table**
   from the framework conversation with the Operator, plus found things the manual pass missed:
   - Confirmed `blocked_on_human` for cases b/c/d (Solr, Feed Registry, Core Vitals) exactly as
     discussed live.
   - Confirmed `no_agent_assigned` for case (a), the Amazon/Creators-API outage — still true.
   - **New finding, not previously flagged**: `slackbot` has been idle **262 hours (~11 days)**
     with no PR ever opened. This is exactly the "agent sleeping on the job, no accountability"
     pattern the Operator described, caught mechanically on the very first real run.
   - **A real bug in my own registry data**, caught by the run itself: `known_efforts.json` had
     used the *tracking issue* number for Activity Feed (#10242) and Preserve Intent (#13261)
     as the `ref` field, but `fetch_pr()` needs the actual *PR* number (#13246, #13264) — the
     issue number isn't a PR, so `gh pr view` silently returned nothing and both were
     miscategorized as "no PR opened yet." Fixed the data; this is now a documented **known
     limitation** (see below) rather than a one-off fix, since it will recur for any future
     effort that starts as an issue and later gets a PR under a different number.
   - **Confirmed the "don't re-ask" promise against real, persisted state**, not just synthetic
     tests: ran the pipeline twice back-to-back against the live fleet; the second run
     correctly surfaced zero new items — everything went to `repeat`. Locked in as
     `test_second_run_against_same_state_is_quiet`.
6. `messages.py` — composes the actual substantive text per category (not category labels).
   Every template is written against the Operator's literal bar ("not a status ping... is it testing?
   code review? architectural questions?") and there's a standing test
   (`test_no_message_template_says_checking_in`) that fails the build if any future template
   regresses toward "just checking in."
7. Wired `messages.compose()` into `heartbeat.py`'s render so dry-run output shows the real
   words ADA would use, not just a category — see the sample output further down.

**Known limitation found while building, not yet fixed**: `known_efforts.json` has one `ref`
field per effort, but a real effort's primary tracking artifact changes over its life (issue
→ PR, sometimes multiple PRs). This caused the Activity Feed / Preserve Intent bug above. A
more robust schema would track a *list* of refs, or resolve dynamically (search GitHub for
open PRs referencing the tracking issue) rather than requiring hand-maintenance. Flagged, not
fixed, in this session — didn't want to over-build the registry format before the Operator weighs in on
Open Decision #1 (does this even stay a separate file, or move into the fleet registry).

**Test count: 50, all passing.** `test_taxonomy.py` (18), `test_state.py` (15),
`test_messages.py` (12), `test_heartbeat_integration.py` (5). The integration tests run the
real pipeline against live `cmux ls`/`gh --json`/`cq` data — safe because every read is
read-only by construction (inherited from `adadash/collect.py`'s own guarantee) — but never
touch the real `heartbeat/state.json` (tests redirect to a tmp path via `monkeypatch`).

**Update, same session — built auto-discovery after all.** Added `find_unregistered_agents()`:
flags any agent `up` in real `cmux ls` that's in no `known_efforts.json` entry and isn't a
recognized standing specialist (`an ADA agent`, `adadash`, `saul`, `lupin`, `adapro`, `cmuxtour`) or
personal (`mek*`) agent. New category `unregistered_agent`, own message template, own tests.
**Immediately found 3 real, genuine gaps on the very first run**: `br-1580-audioreader` (the
audiobook demo — I knew about it but never added it to the registry), `lenny-194-opds-perf`
(adapro's pyopds2 fix agent, same story), and `cmux` itself (a real agent doing cmux's own
bug/feature backlog on the tool itself — legitimately the same issue→PR shape, just a
different repo, so correctly flagged rather than silently excluded). None of these are bugs in
the detector; they're exactly the accountability gap it's supposed to catch. 56 tests now,
verified against a real double-run that the steady state (10 genuine findings, then silence on
an identical second run) holds.

**Explicitly not done in this session** (see Open Decisions): no dispatch, no fleet-registry
integration (the registry is still a hand-maintained JSON file, and now needs at minimum
`br-1580-audioreader` and `lenny-194-opds-perf` added the honest way rather than relying on
auto-discovery to keep catching them by surprise), no distinction yet between "blocked on
merge" vs. "blocked on a real design decision" within `blocked_on_human` (Activity Feed is
technically the latter — waiting on which of 10 design variants to build — but currently reads
with the same generic wording as a plain ready-to-merge PR), and the known `ref`-field schema
limitation (issue vs. PR number) is documented but not fixed.

**Update, same session — registered the 2 real efforts found above, and found a third real
bug doing it.** Added `br-1580-audioreader` (bookreader#1581, coordinated by `adapro` not
`an ADA agent` — included anyway since the heartbeat's scope is fleet-wide, not just an ADA agent-coordinated)
and `lenny-194-opds-perf` (ArchiveLabs/lenny#195 — flagged as a genuine multi-repo case, see
the file comment, since a second real PR exists at `ArchiveLabs/pyopds2_lenny#31` that this
single-ref schema can't also track). Categorizing `br-1580-audioreader` against its real PR
surfaced **another real gap**: `pr.get('review')` can be `'REVIEW_REQUIRED'` (GitHub's
reviewDecision for "requested, not yet decided"), which `categorize()` didn't handle at all —
it fell through the `('', None)` check straight to the generic ambiguous fallback. Fixed by
grouping `REVIEW_REQUIRED` with the unset case (both mean "nothing more for the agent, waiting
on a human"). Caught by real data, not by inspection or by the 56 tests that existed before
this — worth remembering that synthetic fixtures only cover what you thought to write.

**A related, NOT-yet-fixed limitation, also found while reading this real example.**
`br-1580-audioreader`'s actual last comment has real substance under an "Open for a human"
heading — a genuine voice-licensing decision needed, and a PR-fork-ownership question — but
`looks_like_open_question()` never saw it, because `adadash/collect.py`'s `agent_cq_detail()`
truncates `last_msg` to just the **first non-empty line** of the comment (by design, for its
own dashboard use — not a bug in collect.py, just a mismatch with what this module needs).
Real open questions buried deeper in a longer comment are currently invisible to this
detector. Not fixed here — fixing it means either asking AdaDash to expose the full last-
comment body (a cross-agent coordination ask, not something to do unilaterally to a file
another agent owns) or having `taxonomy.py` re-read the cq database directly itself, which
would duplicate collect.py's own logic. Flagging for the Operator rather than picking one silently.

**57 tests now**, all passing, including the `REVIEW_REQUIRED` regression test.

**For whoever picks this up next (including a future me):** run `python3 heartbeat.py` from
this directory for the current dry-run report, or `python3 -m pytest tests/ -v` to re-verify
everything including against live data. Nothing here has ever sent a real message or touched a
real agent's state — see "Explicit safety boundary" above, still fully intact.
