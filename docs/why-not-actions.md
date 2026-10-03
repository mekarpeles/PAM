# Why not just use GitHub Actions?

This question will be asked by everyone who sees PAM, so the answer is written down rather than
re-derived. **It is not a preference. There are two structural blockers, and either alone is enough.**

## 1. An Action cannot keep an agent alive

A workflow run is **ephemeral by design**: it is given an environment, it runs, the environment is
destroyed. That is the correct behaviour for CI and it is fatal here.

An ADA agent is the opposite kind of object. It is **expensive to establish** (a worktree, a running
stack, a populated database, and context accumulated over hours) and it needs to **survive from the
moment a pull request opens until that pull request merges**, because the work arriving in between is
exactly what it exists to handle: a push to re-test, a review comment to answer, a rebase to run.

The most an Action can carry between runs is a **session identifier**. That is a pointer to an
environment the Action has no way to preserve. Resuming from it is not free either: in practice a
resume must happen from the same working directory the session started in, which an ephemeral runner
does not have.

**So the question is not "can an Action trigger an agent"; it can. It is "can an Action *be* the
agent", and it cannot.**

## 2. Some work cannot run in an Action at all

A scheduled check against infrastructure that **does not support Actions** (a private config
repository with no runners, a host reachable only from inside a network) has nowhere to live in that
model. The workflow file is not the problem; there is no runner that can see the target.

This is not hypothetical. A WAF rule-tuning division's daily check reads logs and configuration that
live outside any Actions-capable repository, and **can only run against an environment that holds
secrets.** Scheduling it is a real requirement and Actions cannot satisfy it.

## What follows

**The event source is remote; the execution must be local and durable.** PAM sits across that gap:

- It **observes** a source: polling or webhooks, GitHub first.
- It **decides what is actionable**: a push to a PR an agent owns, a review requested, a check
  failing.
- It **delivers to an agent that already exists**, rather than creating one.
- It **schedules** work that cannot be an Action.

**Where an Action does work, use an Action.** Labelling, linting, a check that genuinely wants a fresh
container: those belong in CI, and PAM should not grow a second-rate version of them.
