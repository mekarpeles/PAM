"""Compose the actual substantive text for a nudge -- not "checking in for an update."

This module has NO side effects and sends nothing (see README's Explicit safety boundary --
dispatch is unimplemented). It exists so a human reviewing dry-run output sees the real words
Ada would use, not just a category label, and can judge tone/substance before dispatch is ever
built.

Design constraint, direct from the Operator: "We absolutely do *not* want, 'it's me ada checking in to
get an update.' We want... 'we need to have a discussion about why this PR hasn't landed and
figure out what we can do to help move things forward. Is it testing? Code review? Are there
open architectural questions? Are we blocked on human review? Has the agent done all the work
they can?'" Every template below is written to that bar: it names the actual mechanical
evidence, states a concrete next step, and asks a real question only where genuine judgment is
needed of the human -- never "how's it going?"
"""

from __future__ import annotations


def compose(*, category: str, agent: str, effort: str, reason: str,
            case_study: str | None = None, pr_number: int | None = None) -> dict:
    """Returns {'to': 'operator' | agent_name, 'subject': str, 'body': str}.

    `to` distinguishes messages that belong in front of the Operator (a real decision) from ones that
    belong in front of the agent itself (needs_review/needs_testing are never generated here at
    all -- see taxonomy.NUDGE_WORTHY; those categories are the agent's own work, not a message).
    """
    case_tag = f" (case {case_study})" if case_study else ''
    builder = _BUILDERS.get(category)
    if builder is None:
        raise ValueError(f'no message template for category {category!r} -- if this is a real '
                          'nudge-worthy category, add one; if not, it should not reach here')
    return builder(agent=agent, effort=effort, reason=reason, case_tag=case_tag,
                   pr_number=pr_number)


def _blocked_on_human(*, agent, effort, reason, case_tag, pr_number):
    pr_ref = f"PR #{pr_number}" if pr_number else "the PR"
    return {
        'to': 'operator',
        'subject': f"{effort}{case_tag} — ready, waiting on you",
        'body': (
            f"{pr_ref} for {effort} has been sitting clean for a while: CI passing, no open "
            f"questions from `{agent}`, nothing left for the agent to do. Real signal: "
            f"{reason}. This isn't a status ping — it's genuinely just waiting on your merge/"
            f"landing decision. Worth 10 minutes now, or should this wait for a specific "
            f"session where you're reviewing a batch of these together?"
        ),
    }


def _open_architectural_question(*, agent, effort, reason, case_tag, pr_number):
    return {
        'to': 'operator',
        'subject': f"{effort}{case_tag} — real open question from the agent",
        'body': (
            f"`{agent}` has an actual open question blocking {effort}, not routine progress "
            f"chatter: {reason}. This is exactly the kind of thing that can sit for days "
            f"un-escalated if nobody surfaces it — flagging now rather than waiting for you to "
            f"notice it in cq yourself."
        ),
    }


def _no_agent_assigned(*, agent, effort, reason, case_tag, pr_number):
    return {
        'to': 'operator',
        'subject': f"{effort}{case_tag} — nobody is working this",
        'body': (
            f"{effort} has no cmux agent assigned at all right now: {reason}. This is not an "
            f"idle-agent problem, it's a coverage gap — if this is still a real priority, it "
            f"needs someone spun up; if it's been deprioritized, worth saying so explicitly "
            f"so it stops showing up here."
        ),
    }


def _exhausted_own_progress(*, agent, effort, reason, case_tag, pr_number):
    return {
        'to': 'operator',
        'subject': f"{effort}{case_tag} — stuck, not obviously why",
        'body': (
            f"`{agent}` on {effort} doesn't cleanly fit a known category: {reason}. Before "
            f"escalating this as a real blocker, the honest next step is for Ada to actually "
            f"go look at what `{agent}` has done and ask it directly what it's stuck on, "
            f"rather than guess from signals alone — flagging here so that's a visible next "
            f"action, not a silent one."
        ),
    }


def _needs_splitting(*, agent, effort, reason, case_tag, pr_number):
    pr_ref = f"PR #{pr_number}" if pr_number else "the PR"
    return {
        'to': 'operator',
        'subject': f"{effort}{case_tag} — likely too large for one review pass",
        'body': (
            f"{pr_ref} for {effort} has grown large while still in draft: {reason}. Worth "
            f"deciding now whether `{agent}` should split this into smaller, independently-"
            f"landable pieces before going further, rather than after the diff gets even "
            f"bigger — that's a call about direction, not something the agent should guess at "
            f"on its own."
        ),
    }


def _merged_needs_cleanup(*, agent, effort, reason, case_tag, pr_number):
    return {
        'to': agent,  # This one genuinely doesn't need the Operator -- it's mechanical teardown.
        'subject': f"{effort}{case_tag} — merged, time to wrap up",
        'body': (
            f"{reason}. Please confirm no uncommitted/unpushed work, then this session can be "
            f"torn down (cmux down + rm) per the usual post-merge cleanup — no need to wait "
            f"for a coordinator prompt for this one, it's mechanical."
        ),
    }


def _effort_closed(*, agent, effort, reason, case_tag, pr_number):
    return {
        # ada proposed 'operator' -- "shutting down a session is his". I have gone
        # with the lead and flagged the disagreement rather than quietly
        # choosing: the Operator confirmed Division Leads may spawn agents, and a lead
        # that can spawn can tear down. Routing every dead agent to him adds
        # to the queue that is already the bottleneck. The evidence here is
        # unambiguous -- the issue is CLOSED -- so the judgement is small.
        #
        # What is NOT small is the irreversibility, which is why the body
        # gates on unpushed work rather than just saying "tear it down".
        'to': 'ada',
        'subject': f"{effort}{case_tag} — effort closed; what to do with `{agent}`",
        'body': (
            f"{reason}\n\n"
            f"If this says the worktree holds unpushed commits, or that the check could "
            f"not run, then there is nothing to clean up yet — the work has to reach a "
            f"remote first. A survey of ~/Projects found 51 worktrees holding commits "
            f"that exist on no remote at all, one of them on this very list.\n\n"
            f"If it is genuinely clean, prefer moving the worktree aside over deleting "
            f"it: `git worktree move` costs disk and is reversible, and disk is the "
            f"cheaper of the two mistakes."
        ),
    }


def _no_resolvable_worktree(*, agent, effort, reason, case_tag, pr_number):
    return {
        # NOT to the agent. cmux records a working directory at first start and
        # reuses it forever, so an agent cannot change its own from inside --
        # unlike merged_needs_cleanup, which is mechanical and genuinely the
        # agent's to do. This needs whoever can relaunch it.
        'to': 'ada',
        'subject': f"{effort}{case_tag} — running outside its worktree, nothing derivable",
        'body': (
            f"{reason}\n\n"
            f"Until it is relaunched from its worktree, its git, docker and file operations "
            f"all default to the wrong repository, and no tool can derive anything about its "
            f"work — including the agent itself. It was almost certainly launched before "
            f"spawn.py's preflight existed to refuse this.\n\n"
            f"This is not the agent's to fix: it cannot change its own recorded cwd from "
            f"inside. Relaunch it from the worktree."
        ),
    }


def _unregistered_agent(*, agent, effort, reason, case_tag, pr_number):
    return {
        'to': 'operator',
        'subject': f"`{agent}` is running but untracked",
        'body': (
            f"`{agent}` is up in cmux right now but isn't in the heartbeat's known-efforts "
            f"registry: {reason}. Either it should be added (what is it working on?), or it's "
            f"a leftover that should be torn down — either way, an agent nobody is watching is "
            f"exactly the accountability gap this system exists to close."
        ),
    }


# Who a nudge can be addressed to. Was implicitly two -- the Operator, or the agent
# itself -- encoded as a literal in test_messages.py. A third became real when
# Division Leads appeared: some problems are neither a decision for the Operator nor
# something the agent can do, and `no_resolvable_worktree` is the first, since
# an agent cannot change its own recorded cwd from inside.
#
# Named here rather than in the test so that adding a recipient is a
# deliberate change to this module's contract, not a test being widened to
# accommodate whatever a new builder happened to return.
RECIPIENT_KINDS = ('operator', 'agent', 'lead')


_BUILDERS = {
    'blocked_on_human': _blocked_on_human,
    'open_architectural_question': _open_architectural_question,
    'no_agent_assigned': _no_agent_assigned,
    'exhausted_own_progress': _exhausted_own_progress,
    'needs_splitting': _needs_splitting,
    'merged_needs_cleanup': _merged_needs_cleanup,
    'unregistered_agent': _unregistered_agent,
    'no_resolvable_worktree': _no_resolvable_worktree,
    'effort_closed': _effort_closed,
}
