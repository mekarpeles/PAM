#!/usr/bin/env python3
"""The gap ledger -- ada-oracle's loop engine.

Ada's AGENTS.md warns against exactly what a naive port would produce:

    "Don't convert a lesson into a checklist you can be compliant with
    instead of judgment you actually apply. A checklist is auditable;
    exercising judgment is exposure."

So this does not check whether the work is good. It checks that every
gap the agent itself named has been *closed with evidence* -- which is a
shell-checkable fact about reasoning rather than a judgment about code.

A criterion from the issue and a risk discovered mid-build are the same
object: something that must become true, or be consciously accepted. One
ledger holds both, which is why requirements and verification stop being
separate phases you can pass while still being lost.

Format, one entry per line, in a PR comment under `<!-- ada-ledger -->`:

    - [open] two workers can double-write the same activity row
    - [tested] empty feed renders | tests/test_feed.py::test_empty_feed
    - [fixed] feed ignored the follow table | a1b2c3d
    - [accepted] no pagination past 100 items | rare, follow-up #1234 | mek
    - [escalated] harden now or follow up? | now / follow-up, rec: now | mek

The bar that stops this becoming a compliance exercise: a terminal status
with no evidence does NOT close a gap. You cannot discharge an obligation
by typing the word "tested".
"""
import argparse
import os
import re
import sys

OPEN = "open"
TERMINAL = {"tested", "fixed", "accepted", "escalated"}
# Statuses that record a JUDGEMENT rather than a mechanical outcome. `tested`
# and `fixed` point at an artifact that can be re-run; these point at
# reasoning, which cannot. They are durable on purpose -- re-deriving a ruling
# loses the reasoning that produced it -- and that is exactly why the evidence
# beneath them needs a stamp of its own.
DECISIONS = {"accepted", "escalated"}

# An escalation must name two things, because the two most expensive failures
# of the fleet's first two days were escalations that named neither.
#
# WHAT WAS SEARCHED. impa escalated "is BookWorm a service or a CLI" to Mek;
# the answer sat in two GitHub issues, a draft PR, and knowledge-base docs it had
# written itself. ada escalated "may agents push branches" when AGENTS.md:224
# has always said everything up to merge is ours -- ada wrote that line. Cost:
# roughly a division-day idle, and a seam left broken because a branch went
# unpushed. A prose search-order rule exists now, and a prose rule is exactly
# the thing that does not fire at the moment it matters.
#
# WHICH KIND OF BLOCKED. `unfinished` is the most common and the least often
# said out loud, and naming it is usually enough to stop the escalation being
# sent at all.
BLOCKED_KINDS = {
    "decision",       # a judgement only a human can make
    "authorization",  # permitted, but not by me
    "access",         # someone else holds a credential or a door key
    "unfinished",     # I have not finished looking -- NOT an escalation
}
ESCALATION_HELP = (
    "an [escalated] entry must carry `kind:<" + "|".join(sorted(BLOCKED_KINDS)) +
    ">` and `searched:<what you actually checked, or none>` in its evidence field"
)
STATUSES = TERMINAL | {OPEN}

MARKER = "<!-- ada-ledger -->"
# `[open]` or `[open@1b213e1e]` -- the optional suffix is the commit the
# finding was made against.
ENTRY = re.compile(
    r"^\s*-\s*\[(?P<status>[a-z]+)(?:@(?P<sha>[0-9a-fA-F]{7,40}))?\]\s*(?P<rest>.+?)\s*$"
)


class Entry:
    def __init__(self, status, description, evidence, owner, line_no, sha=""):
        self.status = status
        self.description = description
        self.evidence = evidence
        self.owner = owner
        self.line_no = line_no
        # The commit this finding was made against. Optional, because a
        # requirement derived from the issue is not tied to a commit -- only a
        # finding about the code is.
        self.sha = (sha or "").lower()

    def stale_against(self, head: str) -> bool:
        """Was this found against code that is no longer what we have?

        Not the same as wrong. A finding made two commits ago may still hold
        exactly. But it was made about different source, so acting on it
        without re-checking is acting on a memory rather than on the world --
        and that has now cost this fleet four separate incidents in one day,
        the worst being a ruling made on a pre-split measurement that would
        have written a false claim into a security constant.
        """
        if not self.sha or not head:
            return False
        n = min(len(self.sha), len(head))
        return self.sha[:n] != head.lower()[:n]

    @property
    def unknown_status(self) -> bool:
        return self.status not in STATUSES

    @property
    def escalation_problem(self) -> str:
        """Why this escalation is not yet a valid one. Empty if it is fine."""
        if self.status != "escalated":
            return ""
        ev = f"{self.evidence} {self.owner}".lower()
        kind = re.search(r"kind:\s*([a-z-]+)", ev)
        searched = re.search(r"searched:\s*(\S+)", ev)
        if not kind or not searched:
            return ESCALATION_HELP
        if kind.group(1) not in BLOCKED_KINDS:
            return f"unknown kind {kind.group(1)!r} (use: {', '.join(sorted(BLOCKED_KINDS))})"
        if kind.group(1) == "unfinished":
            return ("kind:unfinished is not an escalation -- it is open work. Go and "
                    "look, then re-classify. This is the most common kind and the "
                    "least often said.")
        if searched.group(1).strip(",.") in ("none", "nothing", "n/a"):
            # The search ORDER is program-specific and belongs to the
            # implementation, not the framework. ADA states the obligation;
            # A project supplies where to look via ADA_SEARCH_ORDER.
            return ("searched:none -- look first. The two most expensive escalations "
                    "this fleet has sent were both answered in documents the sender "
                    "had written themselves. Order: "
                    + os.environ.get("ADA_SEARCH_ORDER",
                                     "your own docs -> issues INCLUDING CLOSED, read "
                                     "the bodies -> PRs INCLUDING DRAFTS -> your "
                                     "knowledge base"))
        return ""

    @property
    def undischarged(self) -> bool:
        """Still owed work: open, an unrecognised status, or a terminal
        status asserted without evidence. The third case is the one that
        matters -- it is how a checklist gets gamed."""
        if self.unknown_status or self.status == OPEN:
            return True
        if not self.evidence:
            return True
        # An escalation missing its provenance has not discharged anything --
        # it has moved the work to someone else without establishing that it
        # needed moving.
        return bool(self.escalation_problem)

    def why(self) -> str:
        if self.unknown_status:
            return f"unknown status '{self.status}' (use: {', '.join(sorted(STATUSES))})"
        if self.status == OPEN:
            return "still open"
        if not self.evidence:
            return f"marked '{self.status}' with no evidence"
        return self.escalation_problem or f"marked '{self.status}'"

    def __str__(self) -> str:
        return f"  - {self.description}  [{self.why()}]"


def parse(text: str) -> list[Entry]:
    """Entries from the LAST ledger block in `text`.

    Last, not first: a PR accumulates comments, and the newest ledger is
    the current one. Bounded to a single block so an entry can never pair
    with text from an unrelated comment -- an unbounded match is how a
    sibling check acquired a real bug, passing a blocking review as clean
    because the magic phrase appeared further down the page.
    """
    if MARKER not in text:
        return []
    block = text.rsplit(MARKER, 1)[1]
    entries = []
    for i, line in enumerate(block.splitlines(), start=1):
        if line.strip().startswith("<!--"):
            break  # next comment's marker: this ledger ends here
        m = ENTRY.match(line)
        if not m:
            continue
        parts = [p.strip() for p in m.group("rest").split("|")]
        entries.append(Entry(
            sha=m.group("sha") or "",
            status=m.group("status"),
            description=parts[0],
            evidence=parts[1] if len(parts) > 1 else "",
            owner=parts[2] if len(parts) > 2 else "",
            line_no=i,
        ))
    return entries


def undischarged(entries: list[Entry]) -> list[Entry]:
    return [e for e in entries if e.undischarged]


def main():
    ap = argparse.ArgumentParser(
        prog="ledger",
        description="Read an ada-oracle gap ledger on stdin and report what is still owed.",
    )
    ap.add_argument("--count", action="store_true",
                    help="print the number of undischarged gaps and exit 0")
    ap.add_argument("--require-any", action="store_true",
                    help="fail if the ledger is missing or empty (nothing has been reasoned about yet)")
    ap.add_argument("--head", default="",
                    help="current commit. Undischarged findings recorded against a "
                         "DIFFERENT commit are reported as stale: they were made about "
                         "source we no longer have, so acting on them without "
                         "re-checking is acting on a memory rather than on the world.")
    args = ap.parse_args()

    entries = parse(sys.stdin.read())

    if args.require_any:
        # Existence only. This deliberately does NOT also require the ledger
        # to be clear: "a ledger exists" and "nothing is owed" are two
        # different states, and conflating them means the graph can never
        # reach the loop -- it just re-reports "no ledger" forever.
        if not entries:
            print("no ledger found -- nothing has been recorded yet", file=sys.stderr)
            sys.exit(1)
        sys.exit(0)

    owed = undischarged(entries)

    if args.head:
        stale_open = [e for e in owed if e.stale_against(args.head)]
        # Decisions are DISCHARGED, so a staleness check that only looks at
        # open items skips them entirely -- and impa's two bad rulings were
        # both decisions resting on a measurement that had since moved. A
        # decision is durable precisely because it is not re-derived, which is
        # right for the judgement and wrong for the evidence under it. So the
        # rule is not "re-decide", it is: the ruling cites the stamp of the
        # evidence it rests on, and when that stamp moves, say so without
        # re-litigating the ruling itself.
        stale_decided = [e for e in entries
                         if not e.undischarged and e.status in DECISIONS
                         and e.stale_against(args.head)]

        if stale_open:
            print(f"{len(stale_open)} undischarged finding(s) were made against a "
                  f"different commit than {args.head[:9]} -- re-verify each against "
                  f"current source before acting on it:", file=sys.stderr)
            for e in stale_open:
                print(f"  - {e.description}  [found at {e.sha[:9]}]", file=sys.stderr)

        if stale_decided:
            print(f"{len(stale_decided)} DECISION(s) rest on evidence from a commit "
                  f"other than {args.head[:9]}. The ruling may still stand -- do not "
                  f"re-litigate it -- but the measurement under it has moved, so "
                  f"re-check the evidence before relying on it:", file=sys.stderr)
            for e in stale_decided:
                print(f"  - [{e.status}] {e.description}  [decided against {e.sha[:9]}]",
                      file=sys.stderr)

    if args.count:
        print(len(owed))
        sys.exit(0)

    if owed:
        print(f"{len(owed)} gap(s) still owed, of {len(entries)} recorded:", file=sys.stderr)
        for e in owed:
            print(str(e), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
