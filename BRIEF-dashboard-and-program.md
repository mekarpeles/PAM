# PAM brief — the Program config model and the PAM dashboard

From the Operator, 2026-10-02. This is product vision, captured faithfully. It extends the registry
design (PR #3) with requirements and adds the dashboard that sits on top of it. Ada routes; PAM owns.

## The core framing (the Operator's words, paraphrased only to connect them)

> We're creating an ecosystem called PAM. You configure PAM, define the Team, define the ADA agent and
> its Oracle; PAM saves all the state. Collectively that configuration is saved as a **Program** (ours
> is Open Library). PAM turns into a light self-serve management dashboard you can run locally, with
> flavors of https://github.com/internetarchive/openlibrary/agents.

**The dashboard is a VIEW over the registry you are already designing.** That makes it the registry's
acceptance test: if the registry + the issue tracker can answer the questions below, the schema is
right; if they can't, the schema is missing something. Build the registry so these questions are cheap.

## Part A — the Program (config) model: requirements on the PR #3 registry

Configuring PAM for a project produces a **Program**. The config captures:

1. **The forge**: issue tracker, git repo and where it's hosted, the gh account used (e.g.
   `openlibrary-bot`). (Already in PR #3 as projects/repos — confirm it covers the gh *account*.)
2. **Project-management queries** (new vs PR #3): current milestone, teammates, goals, yearly
   objectives — the things Adadash already surfaces. These are reads against the tracker/authored
   files, not cached state.
3. **Progress signal**: PAM may *set* progress via issue labels. So the Program defines a
   **label→state mapping** (e.g. the kanban states below).
4. **The Team**: Program Lead / Coordinator by default; Division/Project Leads promoted; the AGENTS
   file for a Division Lead. (Extends PR #3 teams.)
5. **ADA onboarding**: how an ADA agent is brought up — including **replacing the stop-hook with
   Oracle rules** as the onboarding step.
6. **The ADA agent definition**: its AGENTS.md, and its **Oracle config with defaults**. PAM saves
   this; each agent has a `cq`.

**All of it, saved together, is the Program.** Open Library is one Program; a third party's project is
another. Nothing here is OL-specific in the model — OL is an instance.

## Part B — the dashboard: two modes

### Mode 1 — Monitor (the live hierarchy; "what is actually happening")

The shape, exactly as the Operator drew it:

```
Program Lead
└─ Division Lead (n of them)
   └─ Epic / Plan  (m per lead — the epics under that lead)   [kanban: which are active]
      └─ ADA agent (per sub-issue)
         └─ progress  (what step it's on, what it's stuck on)
```

- **Who are my Division Leads**, and under each, their **Plans** = the epics they lead. Show which
  epics are currently **active** (kanban).
- For each epic, **who are the ADA agents**, and **the progress of each**.
- **Any agent without a Division Lead is the Program Lead's.**
- **Click any ADA agent → its progress**: what it's stuck on, what steps it has done.

**Data sources, so this isn't vague:**
- hierarchy (Lead→epic→agent, parentage) = the **registry** (PR #3: parentage, assignment).
- epic kanban state = **issue labels** (the label→state mapping from Part A.3).
- per-agent progress / "what is it stuck on" = the agent's **ledger** (`ada-ledger` marker) rendered
  by `where_are_we.py` (done-as-of-sha / stale / asserted / open), plus the **Oracle's last
  surfacing**, plus its **cq**. This view already exists conceptually — it's `where_are_we` in a UI.

### Mode 2 — Project Manage (planning and onboarding)

The Operator's list, verbatim in intent:

- **All Projects/Epics**, e.g. by/for year.
- **The current milestone** — the set of issues/projects that need to be done now.
- **Onboard a Division Lead** — do I need to spin up / onboard a new lead for a project?
- **A lead's set of epics/projects/initiatives as a kanban**: needs planning · has plan · in progress · done.
- **Add a Project/Epic to a Division Lead** — for OL that means creating a new epic issue; may differ
  per Program.
- **For any Epic, its state** — how many sub-issues, how many have ADA agents — again a kanban.

## Relationship to Adadash

**This generalizes Adadash; Adadash becomes the Open Library *flavor*.** The OL-specific pieces Adadash
already has (milestone, teammates, goals, yearly objectives) become Part A.2 reads for the OL Program.
Reuse that code where it fits; don't re-derive it. The problem the Operator named — "the dashboards we
have do too much and are not specific enough" — is solved by the two-mode split and the drill-down,
not by adding more to one page.

## Sequencing (Ada's note, not the Operator's mandate)

The dashboard depends on the registry. So: registry first (PR #3), with these questions as its
acceptance test; dashboard as the next unit. If a Monitor-mode question can't be answered cheaply from
the registry schema, that's a finding about the schema, surfaced before the dashboard is built — which
is the whole point of treating the dashboard as the acceptance test.
