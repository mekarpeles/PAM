#!/usr/bin/env python3
"""Ada Heartbeat -- dry-run orchestrator.

Wires together adadash/collect.py (signals), taxonomy.py (categorization) and state.py
(idle-intuition / don't-re-ask) into one pass over the known atomic agents.

STRICTLY DRY-RUN in this build. It prints/returns exactly what it would tell the Operator and why, and
persists heartbeat state (its own file, see state.py), but never calls `cmux send`, never
writes to any agent's cq, and never touches session-integrity files. See README.md's "Explicit
safety boundary" for why, and `--dispatch` below for the deliberately-unimplemented next step.

Usage:
  python3 heartbeat.py              # dry-run report, markdown, to stdout
  python3 heartbeat.py --json       # raw structured result
  python3 heartbeat.py --dispatch   # raises NotImplementedError on purpose
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ADADASH_COLLECT = os.path.join(os.path.dirname(HERE), 'adadash', 'collect.py')
KNOWN_EFFORTS_PATH = os.path.join(HERE, 'known_efforts.json')

sys.path.insert(0, HERE)
import taxonomy  # noqa: E402
import state as state_mod  # noqa: E402
import messages  # noqa: E402


def _load_collect_module():
    """Import adadash/collect.py by path -- it's a standalone script, not a package, and it
    lives in a sibling directory owned by a different (concurrently-running) agent, so we
    import rather than vendor/copy to never drift from the real, live-tested version."""
    spec = importlib.util.spec_from_file_location('adadash_collect', ADADASH_COLLECT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_known_efforts(path: str = KNOWN_EFFORTS_PATH) -> list[dict]:
    with open(path) as f:
        return json.load(f)['efforts']


def run(cooldown_h: float = state_mod.DEFAULT_COOLDOWN_H, use_github: bool = True) -> dict:
    collect = _load_collect_module()
    efforts = load_known_efforts()
    status = collect.cmux_status()  # real `cmux ls` -- read-only, safe
    hs = state_mod.HeartbeatState()

    # Which object stores are claimed by more than one agent. Computed once
    # over the whole fleet, because it is not answerable from inside a single
    # agent's directory: ~/Projects/ada looks like an ordinary private clone
    # until you notice adadash is sitting in it too.
    shared_stores = taxonomy.stores_with_multiple_agents(
        [a for e in efforts for a in e['agents']])

    results = []
    for effort in efforts:
        for agent in effort['agents']:
            up = status.get(agent) == 'up'
            cq = collect.agent_cq_state(agent)
            detail = collect.agent_cq_detail(agent)
            pr = collect.fetch_pr(effort['repo'], effort['ref']) if use_github else None
            # cmux records each agent's working directory once, at first
            # start, and reuses it forever -- so an agent launched from the
            # wrong place has one, and nothing about its work is derivable.
            cwd_path = os.path.join(os.path.expanduser('~/.cmux'), agent, 'cwd')
            agent_cwd = None
            if os.path.exists(cwd_path):
                with open(cwd_path) as f:
                    agent_cwd = f.read().strip()
            verdict = taxonomy.categorize(
                agent=agent, up=up, cq=cq, detail=detail, pr=pr,
                worktree_ok=taxonomy.worktree_resolves(agent_cwd),
                effort_closed=taxonomy.effort_is_closed(agent, effort.get('repo'),
                                                        effort.get('ref')),
                # Precondition is "is this a git repo whose store no other
                # agent claims", NOT worktree_resolves -- that asks whether
                # origin is on github.com, which is the wrong question here
                # and fails in the dangerous direction. The 10 agents sitting
                # in ~/Projects/{ada,mek,pm} have no remote at all, so their
                # commits exist nowhere else; worktree_resolves calls them
                # False and this check would have gone quiet on exactly the
                # repositories where teardown is unrecoverable.
                #
                # None still means unknown, and the effort_closed branch
                # refuses on unknown -- you cannot safely tear down what you
                # could not measure.
                unpushed=(taxonomy.unpushed_commits(
                    agent_cwd, shared=store in shared_stores)
                    if (store := taxonomy.store_of(agent_cwd)) else None),
                unpushed_unknown_why=taxonomy.why_unmeasurable(
                    agent_cwd, store, shared_stores),
                working_tree=taxonomy.uncommitted(agent_cwd))
            transition = hs.evaluate(agent, verdict.category, verdict.reason,
                                      cooldown_h=cooldown_h)
            results.append({
                'effort': effort['name'], 'case_study': effort.get('case_study'),
                'agent': agent, 'up': up, 'category': verdict.category,
                'reason': verdict.reason, 'confidence': verdict.confidence,
                'transition': transition, 'pr_number': pr['number'] if pr else None,
            })

    running = {a for a, s in status.items() if s == 'up'}

    unassigned = taxonomy.find_unassigned_efforts(efforts, running)
    for effort in unassigned:
        transition = hs.evaluate(f'__effort__:{effort["ref"]}', 'no_agent_assigned',
                                  f"{effort['name']} (#{effort['ref']}) has no agent",
                                  cooldown_h=cooldown_h)
        results.append({
            'effort': effort['name'], 'case_study': effort.get('case_study'),
            'agent': None, 'up': False, 'category': 'no_agent_assigned',
            'reason': f"no cmux agent is working {effort['repo']}#{effort['ref']}",
            'confidence': 'high', 'transition': transition, 'pr_number': None,
        })

    for agent in taxonomy.find_unregistered_agents(efforts, running):
        reason = f"`{agent}` is up but appears in no known_efforts.json entry"
        transition = hs.evaluate(f'__unregistered__:{agent}', 'unregistered_agent', reason,
                                  cooldown_h=cooldown_h)
        results.append({
            'effort': f'(untracked agent: {agent})', 'case_study': None,
            'agent': agent, 'up': True, 'category': 'unregistered_agent',
            'reason': reason, 'confidence': 'high', 'transition': transition, 'pr_number': None,
        })

    hs.save()
    return {'results': results, 'generated': collect.NOW.isoformat()}


SURFACE_TRANSITIONS = {'new', 'changed', 'cooldown'}


def render(d: dict) -> str:
    lines = [f"# Ada Heartbeat — dry run, {d['generated'][:19]}Z", '',
             '_Dry run only. Nothing below was sent to any agent or human — see README.md_', '']

    surfaced = [r for r in d['results'] if r['transition'] in SURFACE_TRANSITIONS]
    quiet = [r for r in d['results'] if r['transition'] not in SURFACE_TRANSITIONS]

    lines.append(f"## Would surface now ({len(surfaced)})\n")
    if not surfaced:
        lines.append('_Nothing new — every known blocker has already been surfaced and is '
                      'within its cooldown, or nothing is blocked._\n')
    for r in surfaced:
        who = r['agent'] or '(no agent)'
        badge = {'new': 'NEW', 'changed': 'CHANGED', 'cooldown': 'REMINDER'}[r['transition']]
        conf = '' if r['confidence'] == 'high' else '  _(ambiguous — verify before acting)_'
        case_note = f" (case {r['case_study']})" if r['case_study'] else ''
        lines.append(f"- **[{badge}]** `{who}` — {r['effort']}{case_note}: "
                      f"**{r['category']}** — {r['reason']}{conf}")
        try:
            msg = messages.compose(category=r['category'], agent=who, effort=r['effort'],
                                    reason=r['reason'], case_study=r['case_study'],
                                    pr_number=r.get('pr_number'))
            lines.append(f"  > **To {msg['to']}:** _{msg['subject']}_")
            lines.append(f"  > {msg['body']}")
        except ValueError:
            pass  # no template for this category yet -- category label above still shown
    lines.append('')

    lines.append(f"## Quiet — already known, within cooldown, or not nudge-worthy "
                 f"({len(quiet)})\n")
    for r in quiet:
        who = r['agent'] or '(no agent)'
        lines.append(f"- `{who}` — {r['category']} ({r['transition']})")

    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser(description='Ada Heartbeat dry-run orchestrator')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--no-github', action='store_true')
    ap.add_argument('--cooldown-h', type=float, default=state_mod.DEFAULT_COOLDOWN_H)
    ap.add_argument('--dispatch', action='store_true',
                     help='NOT IMPLEMENTED on purpose -- see README safety boundary')
    args = ap.parse_args()
    if args.dispatch:
        raise NotImplementedError(
            'Dispatch is deliberately unimplemented until the Operator reviews dry-run output. '
            'See README.md "Explicit safety boundary".'
        )
    d = run(cooldown_h=args.cooldown_h, use_github=not args.no_github)
    print(json.dumps(d, indent=2) if args.json else render(d))


if __name__ == '__main__':
    main()
