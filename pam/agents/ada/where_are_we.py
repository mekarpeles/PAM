#!/usr/bin/env python3
"""Where are we in this piece of work? A read for a human, on demand.

Not a check, not a gate, not something the Oracle runs. Mek asked to be able
to ask an agent "where are we in the process" and get back: what is done,
what has gone stale, what is still owed. The data has always been in the
ledger; nothing rendered it.

THE PROPERTY THIS EXISTS TO PROTECT: POSITION IS NOT MONOTONIC.

Work does not accumulate. A rebase un-does `tested`. A moving base un-does
`green`. A review at a SHA that no longer exists is a review of something
else. So this never prints that a thing is *done* -- it prints that a thing
was done AS OF a commit, and says whether that commit is still what we have.

That distinction is the whole point and it is why the headline carries a SHA.
A status line that says "7 of 9 complete" is the kind of number that gets
repeated into a standup and is wrong by the time it is said.

WHAT IT REPORTS, and the four-way split is deliberate:

  DONE AS OF HEAD    terminal, has evidence, found against the current commit
  STALE              terminal, has evidence, found against a DIFFERENT commit.
                     Not wrong -- unverified. It may still hold exactly, but
                     acting on it without re-checking is acting on a memory.
  ASSERTED           terminal status with NO evidence. The ledger claims
                     something the world does not support. This is the
                     highest-cost row here and it is deliberately not grouped
                     with ordinary open work: unfinished work is visible and
                     gets finished, a confident wrong claim is invisible and
                     gets repeated.
  OPEN               ordinary unclosed work.

NO NETWORK. It reads a file or stdin and asks git for HEAD. A human-invoked
read is allowed to be slower than a hook, but there is no reason for it to
cost an API call, and the ledger text is already wherever the caller got it.

If HEAD cannot be determined it says so and refuses to classify staleness,
rather than treating "no head" as "nothing is stale" -- that would report the
reassuring answer on the strength of a failure to look, which is the failure
this fleet keeps producing.
"""
import argparse
import os
import subprocess
import sys

try:  # as a package module (pam.agents.ada.where_are_we)
    from . import ledger
except ImportError:  # as a standalone script (python3 where_are_we.py)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import ledger  # noqa: E402


def current_head(repo: str) -> tuple:
    """(sha, error). Never guesses, never substitutes a default."""
    try:
        r = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                           capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        return "", f"could not run git: {e}"
    if r.returncode != 0:
        return "", (r.stderr or "git rev-parse HEAD failed").strip().splitlines()[0]
    return r.stdout.strip(), ""


def classify(entries, head: str) -> dict:
    """Four buckets. An entry lands in exactly one."""
    out = {"done": [], "stale": [], "asserted": [], "open": []}
    for e in entries:
        if e.status == ledger.OPEN or e.unknown_status:
            out["open"].append(e)
        elif not e.evidence:
            # Terminal status, nothing behind it. `undischarged` in ledger.py
            # already treats this as owed; it is broken out here because its
            # COST is different, not just its state.
            out["asserted"].append(e)
        elif head and e.stale_against(head):
            out["stale"].append(e)
        else:
            out["done"].append(e)
    return out


def render(buckets: dict, head: str, head_err: str,
           has_marker: bool = True) -> str:
    L = []
    a = L.append
    total = sum(len(v) for v in buckets.values())

    if head_err:
        a(f"HEAD UNKNOWN: {head_err}")
        a("  Staleness could not be computed, so nothing below is marked stale.")
        a("  That is a gap in this report, NOT a finding that everything is current.")
        a("")
    else:
        a(f"as of HEAD {head[:12]}")
        a("")

    if not total:
        # NO MARKER and AN EMPTY BLOCK are different states and only one is
        # about the work. parse() returns [] for both, so reporting "the
        # ledger is empty" for text that contains no ledger at all is a
        # confident wrong answer about someone else's progress -- found by
        # this tool's own control, which fed it a bare entry list.
        if not has_marker:
            a(f"NO LEDGER FOUND: the text contains no {ledger.MARKER} block.")
            a("  This says nothing about the work. It says the input was not a")
            a("  ledger, or was the wrong part of one.")
        else:
            a("The ledger block is empty. That is not the same as the work being")
            a("done -- it means nothing has been written down, which is the one")
            a("state this report cannot distinguish from having nothing to do.")
        return "\n".join(L)

    done, stale = len(buckets["done"]), len(buckets["stale"])
    asserted, opn = len(buckets["asserted"]), len(buckets["open"])
    a(f"{done} of {total} discharged against this commit"
      + (f"; {stale} discharged against a different one" if stale else ""))
    a("")

    if buckets["asserted"]:
        a(f"ASSERTED WITHOUT EVIDENCE ({asserted}) -- the ledger claims these and "
          f"nothing backs them")
        a("  Highest cost here: unfinished work is visible and gets finished; a")
        a("  claim with nothing behind it is invisible and gets repeated.")
        for e in buckets["asserted"]:
            a(f"    [{e.status}] {e.description}")
        a("")

    if buckets["stale"]:
        a(f"STALE ({stale}) -- settled against a commit that is no longer HEAD")
        a("  Not wrong. Unverified. It may hold exactly; acting on it without")
        a("  re-checking is acting on a memory rather than on the world.")
        for e in buckets["stale"]:
            a(f"    [{e.status}@{e.sha[:8]}] {e.description}")
        a("")

    if buckets["open"]:
        a(f"OPEN ({opn})")
        for e in buckets["open"]:
            tag = f"[{e.status}]" if not e.unknown_status else f"[{e.status}?]"
            a(f"    {tag} {e.description}")
        a("")

    if buckets["done"]:
        a(f"DONE AS OF {head[:8] if head else 'an undetermined commit'} ({done})")
        for e in buckets["done"]:
            a(f"    [{e.status}] {e.description}")
        a("")

    problems = [e for e in buckets["open"] + buckets["asserted"]
                if e.escalation_problem]
    if problems:
        a("ESCALATIONS THAT ARE NOT YET VALID")
        for e in problems:
            a(f"    {e.description}")
            a(f"      {e.escalation_problem.splitlines()[0]}")
        a("")

    a("Position is not monotonic: a rebase un-does `tested` and a moving base")
    a("un-does `green`. Re-run this against the current HEAD rather than")
    a("quoting an earlier answer.")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ledger", default="-",
                    help="file holding the ledger text, or - for stdin")
    ap.add_argument("--repo", default=".", help="repo whose HEAD to compare against")
    ap.add_argument("--head", default="",
                    help="compare against this SHA instead of asking git")
    ap.add_argument("--only", choices=("asserted", "stale", "open"), default="",
                    help="report ONE bucket and exit 1 only if it is non-empty. "
                         "This is what makes the report reusable as an Oracle "
                         "check: the classifier is tested once and answers "
                         "several questions, rather than each check "
                         "re-deriving staleness and getting it subtly different.")
    args = ap.parse_args()

    if args.ledger == "-":
        text = sys.stdin.read()
    else:
        try:
            with open(args.ledger) as fh:
                text = fh.read()
        except OSError as e:
            print(f"CANNOT READ LEDGER: {e}", file=sys.stderr)
            print("This is not an empty ledger and must not be read as one.",
                  file=sys.stderr)
            return 2

    head, head_err = (args.head, "") if args.head else current_head(args.repo)
    buckets = classify(ledger.parse(text), head)

    if args.only:
        if head_err and args.only == "stale":
            # Staleness is uncomputable without a head. Saying "none" here
            # would let every stale row appear current -- the reassuring
            # answer produced by a failure to look.
            print(f"COULD NOT CHECK staleness: {head_err}", file=sys.stderr)
            return 2
        rows = buckets[args.only]
        if not rows:
            return 0
        print(render({k: (v if k == args.only else []) for k, v in buckets.items()},
                     head, head_err, ledger.MARKER in text))
        return 1

    print(render(buckets, head, head_err, ledger.MARKER in text))

    # Exit codes describe the READ, not the work. 2 means this report is
    # incomplete -- the one state that must never be mistaken for "clean".
    if head_err or ledger.MARKER not in text:
        return 2
    return 1 if (buckets["asserted"] or buckets["stale"] or buckets["open"]) else 0


if __name__ == "__main__":
    sys.exit(main())
