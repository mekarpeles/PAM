"""PAM command-line interface.

CLI-first by design. Every command reads/writes records and/or runs read-only git; NONE shells out
to tmux. Spawn/attach/resume/onboarding *acts* stay harness-side; PAM emits the facts they consume.
"""
from __future__ import annotations

import argparse
import os
import sys

from . import (__version__, activate, agent_def, bundle, config, db, gitutil, initializer, kb,
               project_config, spawn)


def _die(msg: str, code: int = 1):
    print(f"pam: {msg}", file=sys.stderr)
    raise SystemExit(code)


def _repo_short(url: str) -> str:
    return gitutil.normalize(url).rsplit("/", 1)[-1]


# ---- project ----------------------------------------------------------------

def cmd_init(args):
    db.init()
    try:
        r = initializer.init_project(args.path or os.getcwd(), name=args.name)
    except ValueError as e:
        _die(str(e))
    p = r["project"]
    if r["loaded"]:
        print(f"pam: loaded existing Project '{p['name']}' for this repo ({r['pam_dir']})")
    else:
        print(f"pam init: Project '{p['name']}' created in {r['pam_dir']} "
              f"(tracker {p['tracker']})")
    print(f"  commit {r['pam_dir']}/ with your code; it is the shared Project config.")
    print(f"  add team members: pam agent onboard <name> --project {p['name']} --role <role>")
    print("  built-in roles: project_lead, division_lead, ada_agent, agent")


def cmd_project_add(args):
    db.init()
    if db.get_project(args.name):
        _die(f"project already exists: {args.name}")
    origin = gitutil.origin(args.path)
    if origin is None:
        _die(f"no git 'origin' remote at {args.path} (is it a checkout?)")
    if not gitutil.same_repo(origin, args.repo) and not args.force:
        _die(f"origin mismatch: path origin '{origin}' != --repo '{args.repo}' "
             f"(use --force to override)")
    prog = db.add_project(name=args.name, framework=args.framework,
                          tracker=args.tracker, gh_account=args.gh_account,
                          config_path=args.config_path)
    repo = db.add_repo(prog["id"], name=args.repo_name or _repo_short(args.repo),
                       repo_url=args.repo, path=args.path, origin=origin,
                       default_branch=args.default_branch)
    print(f"project '{prog['name']}' [{prog['id']}] added")
    print(f"  + repo '{repo['name']}' -> {repo['path']} (origin verified, default {repo['default_branch']})")


def cmd_project_ls(args):
    db.init()
    progs = db.list_projects()
    if not progs:
        print("You have no Projects. Create one: pam project add <name> --repo <url> --path <dir>")
        return
    print("Projects:")
    for p in progs:
        repos = db.list_repos(p["id"])
        mems = db.list_memberships(p["id"])
        rl = ", ".join(r["name"] for r in repos) or "(no repos)"
        print(f"  {p['name']:20} [{p['id']}]  tracker={p['tracker']}  "
              f"gh={p['gh_account'] or '-'}  repos: {rl}  members: {len(mems)}")


def cmd_project_show(args):
    db.init()
    p = db.get_project(args.name)
    if not p:
        _die(f"no such project: {args.name}")
    print(f"Project: {p['name']} [{p['id']}]")
    print(f"  framework={p['framework'] or '-'}  tracker={p['tracker']}  gh_account={p['gh_account'] or '-'}")
    print(f"  config_path={p['config_path'] or '-'}")
    print("  repos:")
    for r in db.list_repos(p["id"]):
        print(f"    - {r['name']:18} {r['path']}  [{r['default_branch']}]  {r['repo_url']}")
    print("  members:")
    for m in db.list_memberships(p["id"]):
        print(f"    - {m['agent_name']:16} {m['role_key']}")
    print("  epics:")
    for pr in db.list_epics(project_id=p["id"]):
        print(f"    - {pr['title']}  ({pr['kind']} {pr['forge_ref'] or ''})")


def cmd_project_add_repo(args):
    db.init()
    p = db.get_project(args.name)
    if not p:
        _die(f"no such project: {args.name}")
    origin = gitutil.origin(args.path)
    if origin is None:
        _die(f"no git 'origin' remote at {args.path}")
    if not gitutil.same_repo(origin, args.repo) and not args.force:
        _die(f"origin mismatch: '{origin}' != --repo '{args.repo}' (use --force)")
    repo = db.add_repo(p["id"], name=args.repo_name or _repo_short(args.repo),
                       repo_url=args.repo, path=args.path, origin=origin,
                       default_branch=args.default_branch)
    print(f"repo '{repo['name']}' added to project '{p['name']}' ({repo['default_branch']})")


# ---- role -------------------------------------------------------------------

def cmd_role_ls(args):
    db.init()
    pid = None
    if args.project:
        p = db.get_project(args.project)
        if not p:
            _die(f"no such project: {args.project}")
        pid = p["id"]
    for r in db.list_roles(project_id=pid):
        scope = "builtin" if r["project_id"] == "" else "project"
        print(f"  {r['key']:16} [{scope}]  {r['title']}")


# ---- agent ------------------------------------------------------------------

def cmd_agent_onboard(args):
    db.init()
    p = db.get_project(args.project)
    if not p:
        _die(f"no such project: {args.project}")
    role = db.get_role(p["id"], args.role)
    if not role:
        _die(f"no such role: {args.role} (see: pam role ls --project {args.project})")
    reports_to_id = None
    if args.reports_to:
        rm = db.membership_of(args.reports_to, p["id"])
        if not rm:
            _die(f"--reports-to: '{args.reports_to}' is not a member of project '{p['name']}'")
        reports_to_id = rm["id"]
    # Full relaunch spec: `claude --resume` does NOT restore these unless re-passed.
    spec = {k: v for k, v in {
        "model": args.model,
        "mcp_config": args.mcp_config,
        "settings": args.settings,
        "add_dir": args.add_dir or None,
        "permission_mode": args.permission_mode,
        "agent": args.agent_type,
    }.items() if v}
    try:
        agent = db.add_agent(name=args.name, cwd=args.cwd,
                             last_session_id=args.session_id, identity_path=args.identity,
                             launch_spec=spec or None)
    except db.ActiveNameExists:
        _die(f"an active agent named '{args.name}' already exists; "
             f"retire it first (pam agent retire {args.name}) before reusing the name")
    mem = db.add_membership(agent_id=agent["id"], project_id=p["id"],
                            role_id=role["id"], reports_to_id=reports_to_id)
    # Write the committed, hand-editable definition into the repo's .pam/agents/<name>/.
    # The runtime home is provisioned later by cmux (issue #50); onboard does not touch ~/.pam.
    def_dir = None
    if p["config_path"]:
        pam_dir = os.path.dirname(p["config_path"])
        def_dir, _created = agent_def.scaffold(
            pam_dir, name=args.name, uuid=agent["id"], type_key=role["key"],
            reports_to=args.reports_to or "")
    print(f"onboarded '{agent['name']}' [{agent['id']}] as {role['key']} in '{p['name']}'")
    if reports_to_id:
        print(f"  reports to: {args.reports_to}")
    if def_dir:
        print(f"  definition: {def_dir} (commit it; the runtime home is provisioned at spawn)")
    else:
        print("  note: run `pam init` in the repo to get a .pam/ for the committed definition")
    if agent["last_session_id"]:
        print(f"  resume: claude --resume {agent['last_session_id']} (cwd {agent['cwd'] or '?'})")


def cmd_agent_ls(args):
    db.init()
    agents = db.list_agents(active_only=not args.all)
    if not agents:
        print("(no agents)")
        return
    for a in agents:
        print(f"  {a['name']:18} [{a['id']}]  {a['status']}  "
              f"session={a['last_session_id'] or '-'}")


def cmd_agent_show(args):
    db.init()
    a = db.get_agent(args.name)
    if not a:
        _die(f"no such agent: {args.name}")
    for k in ("id", "name", "status", "cwd", "last_session_id", "identity_path",
              "home_path", "launch_spec", "created_at", "retired_at"):
        print(f"  {k:16} {a[k]}")


def cmd_agent_resolve(args):
    db.init()
    a = db.resolve_agent(args.name)
    if not a:
        _die(f"no active agent named: {args.name}")
    print(f"{a['id']}\t{a['last_session_id'] or ''}\t{a['cwd'] or ''}")


def cmd_agent_retire(args):
    db.init()
    a = db.retire_agent(args.name)
    if not a:
        _die(f"no active agent named: {args.name}")
    print(f"retired '{a['name']}' [{a['id']}]; the name is now free to reuse")


def cmd_agent_state(args):
    db.init()
    from .forge import ForgeError, get_forge
    from .state import agent_state as st
    agent = db.get_agent(args.name)
    if not agent:
        _die(f"no such agent: {args.name}")
    work = db.agent_work(agent["id"])
    tracker = "github"
    if work:
        prog = db.get_project(work[0]["project_id"])
        tracker = prog["tracker"] if prog else "github"
    try:
        states = st.for_agent(get_forge(tracker), agent)
    except ForgeError as e:
        _die(f"forge error: {e}")
    print(f"{agent['name']} [{agent['status']}]")
    for s in states:
        loc = f"{s['repo'] or '-'}#{s['ref']}" if s["ref"] else "(no work)"
        print(f"  {s['status']:10} {s['category']:20} {loc:22} {s['reason']}")


def cmd_agent_ledger(args):
    db.init()
    from .agents.ada import ledger as L
    from .agents.ada import where_are_we as W
    from .forge import ForgeError, get_forge
    agent = db.get_agent(args.name)
    if not agent:
        _die(f"no such agent: {args.name}")
    refs = [w for w in db.agent_work(agent["id"]) if w["sub_ref"] and w["repo_url"]]
    if not refs:
        _die(f"{args.name} has no PR-bound work (assign one: pam epic assign ... --sub N)")
    prog = db.get_project(refs[0]["project_id"])
    forge = get_forge(prog["tracker"] if prog else "github")
    for w in refs:
        try:
            pr = forge.pr(w["repo_url"], w["sub_ref"])
            comments = forge.pr_comments(w["repo_url"], w["sub_ref"])
        except ForgeError as e:
            _die(f"forge error: {e}")
        head = pr.get("head_sha") or ""
        text = "\n".join((c.get("body") or "") for c in comments)
        entries = L.parse(text)
        print(f"{agent['name']}  {w['repo_name']}#{w['sub_ref']}  (head {head[:7] or '?'})")
        if not entries:
            print("  (no ledger found)")
            continue
        b = W.classify(entries, head)
        n = {k: len(v) for k, v in b.items()}
        owed = n["asserted"] + n["stale"] + n["open"]
        clean = " (clean as of HEAD)" if owed == 0 and n["done"] else ""
        print(f"  DONE {n['done']}  STALE {n['stale']}  ASSERTED {n['asserted']}  "
              f"OPEN {n['open']}{clean}")
        for name in ("stale", "asserted", "open"):
            for e in b[name]:
                sha = f"@{e.sha[:7]}" if e.sha else ""
                print(f"    [{name}] [{e.status}{sha}] {e.description}")


def cmd_epic_state(args):
    db.init()
    from .forge import ForgeError, get_forge
    from .state import agent_state as st
    proj = db.get_epic(args.epic)
    if not proj:
        _die(f"no such epic: {args.epic}")
    prog = db.get_project(proj["project_id"])
    tracker = prog["tracker"] if prog else "github"
    try:
        roll = st.for_epic(get_forge(tracker), proj)
    except ForgeError as e:
        _die(f"forge error: {e}")
    print(f"Epic: {roll['epic']}  epic {roll['forge_ref'] or '-'}  "
          f"kanban={roll['kanban'] or '-'}")
    for a in roll["agents"]:
        print(f"  {a['status']:10} {a['category']:20} {a['agent']:16} "
              f"#{a['ref'] or '-'}  {a['reason']}")


# ---- status -----------------------------------------------------------------

def cmd_status(args):
    db.init()
    progs = db.list_projects()
    if not progs:
        print("You have no Projects.")
        return
    print(f"PAM: {len(progs)} project(s)")
    act = activate.get_active()
    if act:
        print(f"  active: {act}")
    for p in progs:
        mems = db.list_memberships(p["id"])
        projs = db.list_epics(project_id=p["id"])
        print(f"\n  {p['name']} [{p['tracker']}]")
        leads = [m for m in mems if m["role_key"] in ("project_lead", "division_lead")]
        for m in leads:
            print(f"    {m['role_key']:14} {m['agent_name']}")
        print(f"    members: {len(mems)}   epics: {len(projs)}")


def cmd_activate(args):
    db.init()
    name = args.project
    if not name:
        repo = db.get_repo_by_path(os.path.abspath(os.getcwd()))
        if repo:
            name = db.get_project(repo["project_id"])["name"]
    if not name:
        _die("no project given and none bound to this directory; "
             "run from a Project repo or: pam activate <project>")
    p = db.get_project(name)
    if not p:
        _die(f"no such project: {name}")
    ident = {"gh_account": args.as_account, "git_name": args.git_name, "git_email": args.git_email}
    activate.save_settings(p["name"], ident)
    activate.gh_config_dir(p["name"]).mkdir(parents=True, exist_ok=True)
    activate.set_active(p["name"])
    if args.export:
        # stdout must carry ONLY the export lines so `eval "$(...)"` works.
        print(activate.export_lines(p["name"]))
        return
    print(f"activated Project '{p['name']}'")
    s = activate.load_settings(p["name"]).get("identity", {})
    if s.get("gh_account"):
        print(f"  gh account: {s['gh_account']}")
    print(f"  settings: {activate.settings_path(p['name'])}")
    if not activate.is_gh_authed(p["name"]):
        print("  gh is not authed for this Project yet; authenticate once with:")
        print(f"    GH_CONFIG_DIR={activate.gh_config_dir(p['name'])} gh auth login")
    print(f'  shell activation (optional): eval "$(pam activate {p["name"]} --export)"')


def cmd_deactivate(args):
    db.init()
    cur = activate.get_active()
    activate.clear_active()
    if not cur:
        print("no active Project")
        return
    print(f"deactivated Project '{cur}'")
    print("  if you eval-activated a shell, clear the env: unset PAM_ACTIVE_PROJECT GH_CONFIG_DIR "
          "GIT_AUTHOR_NAME GIT_AUTHOR_EMAIL GIT_COMMITTER_NAME GIT_COMMITTER_EMAIL")


def _resolve_pam_dir(args):
    """Resolve (project, pam_dir) from --project or the cwd's bound repo."""
    db.init()
    name = getattr(args, "project", None)
    if not name:
        repo = db.get_repo_by_path(os.path.abspath(os.getcwd()))
        if repo:
            name = db.get_project(repo["project_id"])["name"]
    if not name:
        _die("no project given and none bound to this directory; use --project or run in a repo")
    p = db.get_project(name)
    if not p:
        _die(f"no such project: {name}")
    if not p["config_path"]:
        _die(f"project '{name}' has no .pam/; run `pam init` in the repo first")
    return p, os.path.dirname(p["config_path"])


def cmd_spawn(args):
    db.init()
    project = args.project or activate.get_active()
    if not project:
        _die("no project: pass --project or `pam activate <project>` first")
    p = db.get_project(project)
    if not p:
        _die(f"no such project: {project}")
    if not db.resolve_agent(args.name):
        _die(f"no active agent named '{args.name}'; onboard it first (pam agent onboard ...)")
    mem = next((m for m in db.list_memberships(p["id"]) if m["agent_name"] == args.name), None)
    if not mem:
        _die(f"'{args.name}' is not a member of project '{p['name']}'")
    if not p["config_path"]:
        _die(f"project '{p['name']}' has no .pam/; run `pam init` first")
    pam_dir = os.path.dirname(p["config_path"])
    repos = db.list_repos(p["id"])
    if not repos:
        _die(f"project '{p['name']}' has no repo; add one first")
    repo_path = repos[0]["path"]
    defn_dir = os.path.join(pam_dir, "agents", args.name)

    home = spawn.seed_home(args.name, type_key=mem["role_key"], project=p["name"],
                           repo_path=repo_path, pam_dir=pam_dir, defn_dir=defn_dir,
                           issue=args.issue)
    pl = spawn.plan(args.name, p["name"])
    print(f"prepared homedir: {home}")
    if not args.go:
        print("DRY RUN (no agent launched). Would run, from the homedir:")
        print(f"  {pl['command']}")
        print(f"  env: {' '.join(f'{k}={v}' for k, v in pl['env'].items())}")
        print(f"  launch for real with: pam spawn {args.name} --project {p['name']} --go")
        return
    print(f"launching via cmux: {pl['command']}")
    res = spawn.launch(args.name, env=pl["env"])
    if getattr(res, "returncode", 0) not in (0, None):
        _die(f"cmux up failed (exit {res.returncode})")
    print(f"launched '{args.name}'; it boots in its homedir and will act for its role")


def cmd_kb_set(args):
    p, pam_dir = _resolve_pam_dir(args)
    path, scaffolded = kb.set_location(pam_dir, args.location)
    loc = kb.load(pam_dir).get("kb", {}).get("location")
    print(f"kb set for '{p['name']}': {loc}")
    print(f"  pointer: {path} (commit it)")
    if scaffolded:
        print("  scaffolded a local Obsidian-style KB; add notes as .md with [[wikilinks]]")


def cmd_kb_show(args):
    p, pam_dir = _resolve_pam_dir(args)
    cfg = kb.load(pam_dir).get("kb")
    if not cfg:
        _die(f"no KB set for '{p['name']}'; run: pam kb set [location]")
    for k, v in cfg.items():
        print(f"  {k:10} {v}")


def cmd_project_init(args):
    db.init()
    p = db.get_project(args.name)
    if not p:
        _die(f"no such project: {args.name}")
    cfg_path = p["config_path"]
    if not cfg_path:
        repos = db.list_repos(p["id"])
        if not repos:
            _die("project has no repo; add one first (pam project add-repo)")
        cfg_path = str(project_config.default_path(repos[0]["path"]))
    path, created = project_config.scaffold(cfg_path, name=p["name"], framework=p["framework"] or "")
    db.set_project_config_path(p["id"], str(path))
    if created:
        print(f"scaffolded Project config: {path}")
    else:
        print(f"config already exists (left untouched): {path}")
    print("  edit it in the repo and commit it; PAM reads it live, never caches it.")


def cmd_project_config(args):
    db.init()
    p = db.get_project(args.name)
    if not p:
        _die(f"no such project: {args.name}")
    if not p["config_path"]:
        _die(f"no config_path set; run: pam project init {args.name}")
    cfg = project_config.load(p["config_path"])
    if cfg is None:
        _die(f"config not found/readable at {p['config_path']}")
    print(f"# {p['config_path']} (read live)")
    import json as _json
    print(_json.dumps(cfg, indent=2))


def cmd_project_publish(args):
    db.init()
    try:
        out = bundle.publish(args.name, out_dir=args.out)
    except ValueError as e:
        _die(str(e))
    print(f"published Project '{args.name}' -> {out}")
    print(f"  manifest: {out / bundle.MANIFEST}  (authored config only; no recorded state)")
    print("  commit this as a pam-{project} repo; others install it with: pam project install <dir|git-url>")


def cmd_project_install(args):
    db.init()
    repo_paths = {}
    for item in (args.repo_path or []):
        if "=" not in item:
            _die(f"--repo-path expects name=path, got: {item}")
        k, v = item.split("=", 1)
        repo_paths[k] = v
    try:
        prog = bundle.install(args.bundle, name=args.name, repo_paths=repo_paths,
                              gh_account=args.gh_account, force=args.force)
    except (ValueError, RuntimeError) as e:
        _die(str(e))
    print(f"installed Project '{prog['name']}' [{prog['id']}]")
    print("  next: staff it with your own agents: pam agent onboard <name> --project "
          f"{prog['name']} --role project_lead")


# ---- membership & team ------------------------------------------------------

def cmd_membership_add(args):
    db.init()
    p = db.get_project(args.project)
    if not p:
        _die(f"no such project: {args.project}")
    agent = db.get_agent(args.agent, active_only=True)
    if not agent:
        _die(f"no active agent: {args.agent}")
    role = db.get_role(p["id"], args.role)
    if not role:
        _die(f"no such role: {args.role}")
    reports_to_id = None
    if args.reports_to:
        rm = db.membership_of(args.reports_to, p["id"])
        if not rm:
            _die(f"--reports-to: '{args.reports_to}' is not a member of '{p['name']}'")
        reports_to_id = rm["id"]
    team_id = None
    if args.team:
        t = db.get_team(p["id"], args.team)
        if not t:
            _die(f"no such team: {args.team} (pam team add {args.team} --project {p['name']})")
        team_id = t["id"]
    db.add_membership(agent["id"], p["id"], role["id"], team_id=team_id, reports_to_id=reports_to_id)
    print(f"'{agent['name']}' joined '{p['name']}' as {role['key']}")


def cmd_membership_ls(args):
    db.init()
    p = db.get_project(args.project)
    if not p:
        _die(f"no such project: {args.project}")
    for m in db.list_memberships(p["id"]):
        rt = ""
        if m["reports_to_id"]:
            rt = "  reports_to=" + m["reports_to_id"]
        print(f"  {m['agent_name']:18} {m['role_key']:14}{rt}")


def cmd_team_add(args):
    db.init()
    p = db.get_project(args.project)
    if not p:
        _die(f"no such project: {args.project}")
    t = db.add_team(p["id"], args.name)
    print(f"team '{t['name']}' added to '{p['name']}'")


def cmd_team_ls(args):
    db.init()
    p = db.get_project(args.project)
    if not p:
        _die(f"no such project: {args.project}")
    for t in db.list_teams(p["id"]):
        print(f"  {t['name']}")


# ---- epics ---------------------------------------------------------------

def cmd_epic_add(args):
    db.init()
    p = db.get_project(args.project)
    if not p:
        _die(f"no such project: {args.project}")
    owner_id = None
    if args.lead:
        lm = db.membership_of(args.lead, p["id"])
        if not lm:
            _die(f"--lead: '{args.lead}' is not a member of '{p['name']}'")
        owner_id = lm["id"]
    repo_id = None
    if args.repo:
        repos = {r["name"]: r for r in db.list_repos(p["id"])}
        if args.repo not in repos:
            _die(f"no such repo in project: {args.repo}")
        repo_id = repos[args.repo]["id"]
    proj = db.add_epic(p["id"], title=args.title, repo_id=repo_id, kind=args.kind,
                          forge_ref=args.epic, owner_id=owner_id, year=args.year)
    print(f"epic '{proj['title']}' [{proj['id']}] added to '{p['name']}'"
          + (f" (epic {args.epic})" if args.epic else ""))


def cmd_epic_ls(args):
    db.init()
    pid = None
    if args.project:
        p = db.get_project(args.project)
        if not p:
            _die(f"no such project: {args.project}")
        pid = p["id"]
    projs = db.list_epics(project_id=pid, year=args.year)
    if not projs:
        print("(no epics)")
        return
    for pr in projs:
        members = db.list_epic_members(pr["id"])
        print(f"  {pr['title']:32} {pr['kind']} {pr['forge_ref'] or '':>6}  "
              f"agents={len(members)}")


def cmd_epic_show(args):
    db.init()
    pr = db.get_epic(args.epic)
    if not pr:
        _die(f"no such epic: {args.epic}")
    print(f"Epic: {pr['title']} [{pr['id']}]  {pr['kind']} {pr['forge_ref'] or ''}")
    print("  agents:")
    for m in db.list_epic_members(pr["id"]):
        print(f"    - {m['agent_name']:16} {m['agent_status']:8} sub={m['sub_ref'] or '-'}")


def cmd_epic_assign(args):
    db.init()
    pr = db.get_epic(args.epic)
    if not pr:
        _die(f"no such epic: {args.epic}")
    agent = db.get_agent(args.agent, active_only=True)
    if not agent:
        _die(f"no active agent: {args.agent}")
    staffed_by = None
    if args.by:
        b = db.get_agent(args.by)
        staffed_by = b["id"] if b else None
    db.add_epic_member(pr["id"], agent["id"], sub_ref=args.sub, staffed_by=staffed_by)
    print(f"assigned '{agent['name']}' to '{pr['title']}'"
          + (f" (sub-issue {args.sub})" if args.sub else ""))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pam", description="PAM registry")
    p.add_argument("--version", action="version", version=f"pam {__version__}")
    sub = p.add_subparsers(dest="cmd")

    pin = sub.add_parser("init", help="initialize a Project in this repo (creates .pam/)")
    pin.add_argument("--path", default=None, help="repo path (default: current directory)")
    pin.add_argument("--name", default=None, help="Project name (default: inferred from origin)")
    pin.set_defaults(func=cmd_init)

    prog = sub.add_parser("project", help="manage Projects").add_subparsers(dest="sub")
    pa = prog.add_parser("add", help="register a Project + its first repo")
    pa.add_argument("name")
    pa.add_argument("--repo", required=True, help="canonical repo URL (owner/name or https/ssh)")
    pa.add_argument("--path", required=True, help="local checkout path (the bound path)")
    pa.add_argument("--repo-name", default=None)
    pa.add_argument("--tracker", default="github")
    pa.add_argument("--gh-account", default=None, dest="gh_account")
    pa.add_argument("--framework", default=None)
    pa.add_argument("--config-path", default=None, dest="config_path")
    pa.add_argument("--default-branch", default="main", dest="default_branch")
    pa.add_argument("--force", action="store_true", help="skip origin verification")
    pa.set_defaults(func=cmd_project_add)
    prog.add_parser("ls").set_defaults(func=cmd_project_ls)
    ps = prog.add_parser("show"); ps.add_argument("name"); ps.set_defaults(func=cmd_project_show)
    par = prog.add_parser("add-repo")
    par.add_argument("name"); par.add_argument("--repo", required=True)
    par.add_argument("--path", required=True); par.add_argument("--repo-name", default=None)
    par.add_argument("--default-branch", default="main", dest="default_branch")
    par.add_argument("--force", action="store_true")
    par.set_defaults(func=cmd_project_add_repo)
    pin = prog.add_parser("init", help="scaffold the authored config bundle into the repo")
    pin.add_argument("name"); pin.set_defaults(func=cmd_project_init)
    pcf = prog.add_parser("config", help="show the authored config (read live)")
    pcf.add_argument("name"); pcf.set_defaults(func=cmd_project_config)
    ppu = prog.add_parser("publish", help="serialize the authored config to a shareable bundle")
    ppu.add_argument("name"); ppu.add_argument("--out", default=None, help="output dir (default ./pam-<name>)")
    ppu.set_defaults(func=cmd_project_publish)
    ppi = prog.add_parser("install", help="install a Project from a bundle dir")
    ppi.add_argument("bundle", help="path to a bundle dir (containing pam.project.toml)")
    ppi.add_argument("--name", default=None, help="rename the installed Project")
    ppi.add_argument("--repo-path", action="append", default=None, dest="repo_path",
                     metavar="NAME=PATH", help="bind a repo's local checkout path (repeatable)")
    ppi.add_argument("--gh-account", default=None, dest="gh_account")
    ppi.add_argument("--force", action="store_true")
    ppi.set_defaults(func=cmd_project_install)

    role = sub.add_parser("role", help="list roles").add_subparsers(dest="sub")
    rl = role.add_parser("ls"); rl.add_argument("--project", default=None)
    rl.set_defaults(func=cmd_role_ls)

    agent = sub.add_parser("agent", help="manage agents").add_subparsers(dest="sub")
    ao = agent.add_parser("onboard", help="register an agent (incl. one PAM didn't start)")
    ao.add_argument("name")
    ao.add_argument("--project", required=True)
    ao.add_argument("--role", required=True)
    ao.add_argument("--session-id", default=None, dest="session_id")
    ao.add_argument("--cwd", default=None)
    ao.add_argument("--identity", default=None)
    ao.add_argument("--reports-to", default=None, dest="reports_to")
    # full relaunch spec (recorded so a resumed agent comes back identical)
    ao.add_argument("--model", default=None)
    ao.add_argument("--mcp-config", default=None, dest="mcp_config")
    ao.add_argument("--settings", default=None)
    ao.add_argument("--add-dir", action="append", default=None, dest="add_dir")
    ao.add_argument("--permission-mode", default=None, dest="permission_mode")
    ao.add_argument("--agent-type", default=None, dest="agent_type",
                    help="the --agent flag Claude was launched with")
    ao.set_defaults(func=cmd_agent_onboard)
    al = agent.add_parser("ls"); al.add_argument("--all", action="store_true")
    al.set_defaults(func=cmd_agent_ls)
    ash = agent.add_parser("show"); ash.add_argument("name"); ash.set_defaults(func=cmd_agent_show)
    arv = agent.add_parser("resolve"); arv.add_argument("name"); arv.set_defaults(func=cmd_agent_resolve)
    art = agent.add_parser("retire"); art.add_argument("name"); art.set_defaults(func=cmd_agent_retire)
    ast2 = agent.add_parser("state", help="computed work state (from forge signals)")
    ast2.add_argument("name"); ast2.set_defaults(func=cmd_agent_state)
    alg = agent.add_parser("ledger", help="per-requirement ledger (done/stale/asserted/open vs HEAD)")
    alg.add_argument("name"); alg.set_defaults(func=cmd_agent_ledger)

    mem = sub.add_parser("membership", help="agent<->project memberships").add_subparsers(dest="sub")
    ma = mem.add_parser("add")
    ma.add_argument("agent"); ma.add_argument("--project", required=True)
    ma.add_argument("--role", required=True); ma.add_argument("--reports-to", default=None, dest="reports_to")
    ma.add_argument("--team", default=None); ma.set_defaults(func=cmd_membership_add)
    ml = mem.add_parser("ls"); ml.add_argument("--project", required=True)
    ml.set_defaults(func=cmd_membership_ls)

    team = sub.add_parser("team", help="teams within a Project").add_subparsers(dest="sub")
    ta = team.add_parser("add"); ta.add_argument("name"); ta.add_argument("--project", required=True)
    ta.set_defaults(func=cmd_team_add)
    tl = team.add_parser("ls"); tl.add_argument("--project", required=True)
    tl.set_defaults(func=cmd_team_ls)

    proj = sub.add_parser("epic", help="Epics (= forge epics)").add_subparsers(dest="sub")
    pja = proj.add_parser("add")
    pja.add_argument("title"); pja.add_argument("--project", required=True)
    pja.add_argument("--lead", default=None, help="owning Division Lead (agent)")
    pja.add_argument("--epic", default=None, help="forge issue number of the epic")
    pja.add_argument("--repo", default=None); pja.add_argument("--kind", default="epic")
    pja.add_argument("--year", type=int, default=None); pja.set_defaults(func=cmd_epic_add)
    pjl = proj.add_parser("ls")
    pjl.add_argument("--project", default=None); pjl.add_argument("--year", type=int, default=None)
    pjl.set_defaults(func=cmd_epic_ls)
    pjs = proj.add_parser("show"); pjs.add_argument("epic"); pjs.set_defaults(func=cmd_epic_show)
    pjx = proj.add_parser("assign")
    pjx.add_argument("epic"); pjx.add_argument("--agent", required=True)
    pjx.add_argument("--sub", default=None); pjx.add_argument("--by", default=None)
    pjx.set_defaults(func=cmd_epic_assign)
    pjst = proj.add_parser("state", help="epic rollup: epic kanban + each agent's state")
    pjst.add_argument("epic"); pjst.set_defaults(func=cmd_epic_state)

    sub.add_parser("status", help="my Projects and their leads").set_defaults(func=cmd_status)

    act = sub.add_parser("activate", help="activate a Project (per-dev identity + env)")
    act.add_argument("project", nargs="?", default=None, help="Project name (default: from cwd)")
    act.add_argument("--as", dest="as_account", default=None, help="gh account to act as")
    act.add_argument("--git-name", dest="git_name", default=None)
    act.add_argument("--git-email", dest="git_email", default=None)
    act.add_argument("--export", action="store_true", help="print shell export lines for eval")
    act.set_defaults(func=cmd_activate)
    sub.add_parser("deactivate", help="deactivate the current Project").set_defaults(
        func=cmd_deactivate)

    kbp = sub.add_parser("kb", help="the Project's knowledge base pointer").add_subparsers(dest="sub")
    kbs = kbp.add_parser("set", help="set the KB location (default in-repo .pam/kb)")
    kbs.add_argument("location", nargs="?", default=None, help="in-repo path or external path/URL")
    kbs.add_argument("--project", default=None)
    kbs.set_defaults(func=cmd_kb_set)
    kbsh = kbp.add_parser("show", help="show the KB pointer")
    kbsh.add_argument("--project", default=None)
    kbsh.set_defaults(func=cmd_kb_show)

    sp = sub.add_parser("spawn", help="bring an onboarded agent up via cmux (dry-run unless --go)")
    sp.add_argument("name")
    sp.add_argument("--project", default=None, help="Project (default: the active one)")
    sp.add_argument("--issue", default=None, help="issue number to assign (for an ADA)")
    sp.add_argument("--go", action="store_true", help="actually launch (default is dry-run)")
    sp.set_defaults(func=cmd_spawn)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 0
    return func(args) or 0


if __name__ == "__main__":
    raise SystemExit(main())
