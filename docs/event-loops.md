> **Ported from a working implementation.** This was written against one program's setup; names have
> been replaced with roles. The loops and their intervals are real — they ran daily for months.

# pam.py Integration — ADA Loops

Two new loops to add to `~/Projects/pm/pam.py`. These are the heartbeat and cleanup mechanism for ADA sessions.

---

## Loop 1: `python3 pam.py an ADA agent` — spawn loop

**Poll interval**: 5 minutes

**What it does**: finds issues newly assigned to the project bot that don't already have a running ADA session, then spawns one.

```python
def poll_ada_assignments():
    """Find issues assigned to the project bot with no active ADA session."""
    # Get issues assigned to the project bot
    result = subprocess.run([
        'gh', 'issue', 'list',
        '--repo', REPO,
        '--assignee', 'the project bot',
        '--state', 'open',
        '--json', 'number,title',
        '--limit', '50',
    ], capture_output=True, text=True)
    issues = json.loads(result.stdout or '[]')

    # Get running ADA sessions
    ls_result = subprocess.run(['cmux', 'ls', '--json'], capture_output=True, text=True)
    running = {s['name'] for s in json.loads(ls_result.stdout or '[]')}

    for issue in issues:
        number = issue['number']
        # Check if a session already exists for this issue
        if any(s.startswith(f'pr-{number}-') for s in running):
            continue  # already running
        # Derive slug from title
        slug = slugify(issue['title'])[:30]  # short, lowercase, hyphens only
        spawn_ada(number, slug)

def spawn_ada(issue_number: int, slug: str) -> None:
    agent_name = f'pr-{issue_number}-{slug}'
    subprocess.run([
        'cmux', '-s', 'the atomic-agent workspace', 'start', agent_name,
        '-i', str(Path.home() / 'Projects/an ADA agent/AGENTS.md'),
        '-d', '--',
        f'You are ADA. You have been assigned issue #{issue_number} on internetarchive/the application repo. '
        f'Issue URL: https://github.com/internetarchive/the application repo/issues/{issue_number}. '
        f'Start at Phase 1: Discovery.',
    ])
    log(f'ADA spawned: {agent_name} for issue #{issue_number}')
```

---

## Loop 2: `python3 pam.py ada_heartbeat` — heartbeat + cleanup loop

**Poll interval**: 5 minutes

**What it does**:
1. Finds all running `pr-{N}-*` sessions in `the atomic-agent workspace`
2. For each session, checks the PR state for that issue
3. **If PR is MERGED or CLOSED**: sends ADA the cleanup signal, then (after 2 min) archives the session
4. **If PR is still open**: checks how long the session has been idle (no new commits, no cmux activity), and sends a nudge if it's been waiting too long

```python
WAITING_PHASES = {
    'Needs: Approval': (
        'Phase 4 reminder: still waiting for staff approval on your plan. '
        'Check for any new comments on the issue. If the plan was approved, proceed to Phase 5.'
    ),
    'CI_PENDING': (
        'CI check: run `gh pr checks {PR} --repo internetarchive/the application repo` to see current status. '
        'If all checks pass, proceed to the next step. If any fail, diagnose and fix.'
    ),
}

def heartbeat_ada_sessions():
    ls_result = subprocess.run(['cmux', 'ls', '--json'], capture_output=True, text=True)
    sessions = [s for s in json.loads(ls_result.stdout or '[]')
                if re.match(r'^pr-\d+-', s.get('name', ''))]

    for session in sessions:
        name = session['name']
        issue_number = int(name.split('-')[1])

        # Find associated PR
        pr_result = subprocess.run([
            'gh', 'pr', 'list', '--repo', REPO,
            '--head', f'{issue_number}/*',
            '--json', 'number,state',
        ], capture_output=True, text=True)
        prs = json.loads(pr_result.stdout or '[]')

        if not prs:
            # No PR yet — ADA is still in early phases
            # Nudge if idle > 30 minutes
            nudge_if_idle(name, issue_number, threshold_minutes=30)
            continue

        pr = prs[0]
        pr_number = pr['number']
        pr_state = pr['state']  # OPEN, MERGED, CLOSED

        if pr_state in ('MERGED', 'CLOSED'):
            # Signal cleanup
            subprocess.run(['cmux', 'send', name,
                f'This is pam.py heartbeat: PR #{pr_number} is {pr_state}. '
                f'Read skills/cleanup.md and run the cleanup steps now.'])
        else:
            # PR is open — check CI and nudge if stuck
            nudge_if_idle(name, issue_number, threshold_minutes=15,
                          pr_number=pr_number)

def nudge_if_idle(session_name, issue_number, threshold_minutes, pr_number=None):
    """Send a status-check nudge if the session hasn't shown recent activity."""
    # Check last git commit time in any matching worktree
    worktrees = list(Path.home().glob(f'Projects/the application repo-{issue_number}-*'))
    if not worktrees:
        return
    worktree = worktrees[0]
    last_commit = subprocess.run(
        ['git', '-C', str(worktree), 'log', '-1', '--format=%ct'],
        capture_output=True, text=True
    ).stdout.strip()
    if last_commit:
        age_minutes = (time.time() - int(last_commit)) / 60
        if age_minutes < threshold_minutes:
            return  # recently active — no nudge needed

    msg = (
        f'This is pam.py heartbeat. No recent commits detected for issue #{issue_number}. '
    )
    if pr_number:
        msg += (
            f'Check CI status: `gh pr checks {pr_number} --repo {REPO}`. '
            f'If CI is green and all Copilot and CodeQL threads are resolved, mark the PR ready for review. '
            f'If stuck, report to Lupin with the specific blocker.'
        )
    else:
        msg += (
            f'Where are you in the ADA workflow? '
            f'If waiting for approval on issue #{issue_number}, '
            f'check for new staff comments and proceed to Phase 5 if approved.'
        )
    subprocess.run(['cmux', 'send', session_name, msg])
```

---

## State Tracking

Heartbeat state lives in `~/Projects/pm/state/an ADA agent-sessions.jsonl`. Each entry:

```jsonl
{"ts": "2026-07-15T10:00:00Z", "session": "pr-13158-genre-explorer", "issue": 13158, "pr": null, "phase": "gate", "last_nudge": null}
{"ts": "2026-07-15T10:30:00Z", "session": "pr-13158-genre-explorer", "issue": 13158, "pr": 13200, "phase": "ci", "last_nudge": "2026-07-15T10:30:00Z"}
```

---

## Loop 3: `python3 pam.py ada_maintenance` — daily bot-PR cleanup scan

**Poll interval**: once per day (86400s)

**What it does**: fires a maintenance prompt at a running ADA session (or starts a short-lived one) to scan all open the project bot PRs for cleanup needs and delegate to Pierre.

```python
MAINTENANCE_PROMPT = (
    'This is pam.py: daily maintenance pass. '
    'Scan all open the project bot PRs for bot commits, merge conflicts, and lint CI failures. '
    'For each PR that needs work, delegate to Pierre following skills/pierre.md. '
    'Report the summary to Lupin when done.'
)

def run_ada_maintenance():
    ls_result = subprocess.run(['cmux', 'ls', '--json'], capture_output=True, text=True)
    sessions = json.loads(ls_result.stdout or '[]')
    ada_sessions = [s for s in sessions if re.match(r'^pr-\d+-', s.get('name', ''))]

    if ada_sessions:
        # Reuse the first active ADA session
        target = ada_sessions[0]['name']
        subprocess.run(['cmux', 'send', target, MAINTENANCE_PROMPT])
    else:
        # Start a short-lived maintenance session
        subprocess.run([
            'cmux', '-s', 'the atomic-agent workspace', 'start', 'an ADA agent-maintenance',
            '-i', str(Path.home() / 'Projects/an ADA agent/AGENTS.md'),
            '-d', '--', MAINTENANCE_PROMPT,
        ])
```

---

## Running the Loops

```bash
# Add to pam.py dispatch:
python3 ~/Projects/pm/pam.py an ADA agent             # spawn loop (every 5 min)
python3 ~/Projects/pm/pam.py ada_heartbeat   # heartbeat + cleanup loop (every 5 min)
python3 ~/Projects/pm/pam.py ada_maintenance # daily bot-PR cleanup scan (once/day)

# Or via cmux:
cmux send the atomic-agent workspace "cd ~/Projects/pm && python3 pam.py an ADA agent | tee -a /tmp/ol-pam-an ADA agent.log"
cmux send the atomic-agent workspace "cd ~/Projects/pm && python3 pam.py ada_heartbeat | tee -a /tmp/ol-pam-an ADA agent-hb.log"
cmux send the atomic-agent workspace "cd ~/Projects/pm && python3 pam.py ada_maintenance | tee -a /tmp/ol-pam-an ADA agent-maint.log"
```

---

**Note (2026-07-17, corrected by ADA Lovelace / coordinator):** the installed `cmux` CLI has no `--link` flag. The
correct flag is `-i <path>` (long form `--identity`), which copies the given file to the new agent's
`identity.md` on first start only (never overwrites on resume). All `--link` examples above have been
corrected to `-i`. See `skills/spawn-agent.md` for the manual/ad-hoc spawn pattern used when a human
coordinator (not `pam.py`) is spinning up a one-off ADA for a specific existing PR or issue.
