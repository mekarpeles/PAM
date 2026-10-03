"""PAM command-line interface.

CLI-first by design. Every command reads/writes records and/or runs read-only git; NONE shells out
to tmux. Spawn/attach/resume/onboarding *acts* stay harness-side — PAM emits the facts they consume.
"""
from __future__ import annotations

import argparse
import sys

from . import __version__, bundle, config, db, gitutil, program_config


def _die(msg: str, code: int = 1):
    print(f"pam: {msg}", file=sys.stderr)
    raise SystemExit(code)


def _repo_short(url: str) -> str:
    return gitutil.normalize(url).rsplit("/", 1)[-1]


# ---- program ----------------------------------------------------------------

def cmd_program_add(args):
    db.init()
    if db.get_program(args.name):
        _die(f"program already exists: {args.name}")
    origin = gitutil.origin(args.path)
    if origin is None:
        _die(f"no git 'origin' remote at {args.path} (is it a checkout?)")
    if not gitutil.same_repo(origin, args.repo) and not args.force:
        _die(f"origin mismatch: path origin '{origin}' != --repo '{args.repo}' "
             f"(use --force to override)")
    prog = db.add_program(name=args.name, framework=args.framework,
                          tracker=args.tracker, gh_account=args.gh_account,
                          config_path=args.config_path)
    repo = db.add_repo(prog["id"], name=args.repo_name or _repo_short(args.repo),
                       repo_url=args.repo, path=args.path, origin=origin,
                       default_branch=args.default_branch)
    print(f"program '{prog['name']}' [{prog['id']}] added")
    print(f"  + repo '{repo['name']}' -> {repo['path']} (origin verified, default {repo['default_branch']})")


def cmd_program_ls(args):
    db.init()
    progs = db.list_programs()
    if not progs:
        print("You have no Programs. Create one: pam program add <name> --repo <url> --path <dir>")
        return
    print("Programs:")
    for p in progs:
        repos = db.list_repos(p["id"])
        mems = db.list_memberships(p["id"])
        rl = ", ".join(r["name"] for r in repos) or "(no repos)"
        print(f"  {p['name']:20} [{p['id']}]  tracker={p['tracker']}  "
              f"gh={p['gh_account'] or '-'}  repos: {rl}  members: {len(mems)}")


def cmd_program_show(args):
    db.init()
    p = db.get_program(args.name)
    if not p:
        _die(f"no such program: {args.name}")
    print(f"Program: {p['name']} [{p['id']}]")
    print(f"  framework={p['framework'] or '-'}  tracker={p['tracker']}  gh_account={p['gh_account'] or '-'}")
    print(f"  config_path={p['config_path'] or '-'}")
    print("  repos:")
    for r in db.list_repos(p["id"]):
        print(f"    - {r['name']:18} {r['path']}  [{r['default_branch']}]  {r['repo_url']}")
    print("  members:")
    for m in db.list_memberships(p["id"]):
        print(f"    - {m['agent_name']:16} {m['role_key']}")
    print("  projects:")
    for pr in db.list_projects(program_id=p["id"]):
        print(f"    - {pr['title']}  ({pr['kind']} {pr['forge_ref'] or ''})")


def cmd_program_add_repo(args):
    db.init()
    p = db.get_program(args.name)
    if not p:
        _die(f"no such program: {args.name}")
    origin = gitutil.origin(args.path)
    if origin is None:
        _die(f"no git 'origin' remote at {args.path}")
    if not gitutil.same_repo(origin, args.repo) and not args.force:
        _die(f"origin mismatch: '{origin}' != --repo '{args.repo}' (use --force)")
    repo = db.add_repo(p["id"], name=args.repo_name or _repo_short(args.repo),
                       repo_url=args.repo, path=args.path, origin=origin,
                       default_branch=args.default_branch)
    print(f"repo '{repo['name']}' added to program '{p['name']}' ({repo['default_branch']})")


# ---- role -------------------------------------------------------------------

def cmd_role_ls(args):
    db.init()
    pid = None
    if args.program:
        p = db.get_program(args.program)
        if not p:
            _die(f"no such program: {args.program}")
        pid = p["id"]
    for r in db.list_roles(program_id=pid):
        scope = "builtin" if r["program_id"] == "" else "program"
        print(f"  {r['key']:16} [{scope}]  {r['title']}")


# ---- agent ------------------------------------------------------------------

def cmd_agent_onboard(args):
    db.init()
    p = db.get_program(args.program)
    if not p:
        _die(f"no such program: {args.program}")
    role = db.get_role(p["id"], args.role)
    if not role:
        _die(f"no such role: {args.role} (see: pam role ls --program {args.program})")
    reports_to_id = None
    if args.reports_to:
        rm = db.membership_of(args.reports_to, p["id"])
        if not rm:
            _die(f"--reports-to: '{args.reports_to}' is not a member of program '{p['name']}'")
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
    mem = db.add_membership(agent_id=agent["id"], program_id=p["id"],
                            role_id=role["id"], reports_to_id=reports_to_id)
    # create the durable PAM-land home dir
    try:
        config.agents_dir().mkdir(parents=True, exist_ok=True)
        (config.agents_dir() / agent["id"]).mkdir(exist_ok=True)
    except OSError:
        pass
    print(f"onboarded '{agent['name']}' [{agent['id']}] as {role['key']} in '{p['name']}'")
    if reports_to_id:
        print(f"  reports to: {args.reports_to}")
    print(f"  home: {agent['home_path']}")
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
    print(f"retired '{a['name']}' [{a['id']}] — the name is now free to reuse")


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
        prog = db.get_program(work[0]["program_id"])
        tracker = prog["tracker"] if prog else "github"
    try:
        states = st.for_agent(get_forge(tracker), agent)
    except ForgeError as e:
        _die(f"forge error: {e}")
    print(f"{agent['name']} [{agent['status']}]")
    for s in states:
        loc = f"{s['repo'] or '-'}#{s['ref']}" if s["ref"] else "(no work)"
        print(f"  {s['status']:10} {s['category']:20} {loc:22} {s['reason']}")


def cmd_project_state(args):
    db.init()
    from .forge import ForgeError, get_forge
    from .state import agent_state as st
    proj = db.get_project(args.project)
    if not proj:
        _die(f"no such project: {args.project}")
    prog = db.get_program(proj["program_id"])
    tracker = prog["tracker"] if prog else "github"
    try:
        roll = st.for_project(get_forge(tracker), proj)
    except ForgeError as e:
        _die(f"forge error: {e}")
    print(f"Project: {roll['project']}  epic {roll['forge_ref'] or '-'}  "
          f"kanban={roll['kanban'] or '-'}")
    for a in roll["agents"]:
        print(f"  {a['status']:10} {a['category']:20} {a['agent']:16} "
              f"#{a['ref'] or '-'}  {a['reason']}")


# ---- status -----------------------------------------------------------------

def cmd_status(args):
    db.init()
    progs = db.list_programs()
    if not progs:
        print("You have no Programs.")
        return
    print(f"PAM — {len(progs)} program(s)")
    for p in progs:
        mems = db.list_memberships(p["id"])
        projs = db.list_projects(program_id=p["id"])
        print(f"\n  {p['name']} [{p['tracker']}]")
        leads = [m for m in mems if m["role_key"] in ("program_lead", "division_lead")]
        for m in leads:
            print(f"    {m['role_key']:14} {m['agent_name']}")
        print(f"    members: {len(mems)}   projects: {len(projs)}")


def cmd_program_init(args):
    db.init()
    p = db.get_program(args.name)
    if not p:
        _die(f"no such program: {args.name}")
    cfg_path = p["config_path"]
    if not cfg_path:
        repos = db.list_repos(p["id"])
        if not repos:
            _die("program has no repo; add one first (pam program add-repo)")
        cfg_path = str(program_config.default_path(repos[0]["path"]))
    path, created = program_config.scaffold(cfg_path, name=p["name"], framework=p["framework"] or "")
    db.set_program_config_path(p["id"], str(path))
    if created:
        print(f"scaffolded Program config: {path}")
    else:
        print(f"config already exists (left untouched): {path}")
    print("  edit it in the repo and commit it; PAM reads it live, never caches it.")


def cmd_program_config(args):
    db.init()
    p = db.get_program(args.name)
    if not p:
        _die(f"no such program: {args.name}")
    if not p["config_path"]:
        _die(f"no config_path set; run: pam program init {args.name}")
    cfg = program_config.load(p["config_path"])
    if cfg is None:
        _die(f"config not found/readable at {p['config_path']}")
    print(f"# {p['config_path']} (read live)")
    import json as _json
    print(_json.dumps(cfg, indent=2))


def cmd_program_publish(args):
    db.init()
    try:
        out = bundle.publish(args.name, out_dir=args.out)
    except ValueError as e:
        _die(str(e))
    print(f"published Program '{args.name}' -> {out}")
    print(f"  manifest: {out / bundle.MANIFEST}  (authored config only; no recorded state)")
    print("  commit this as a pam-{program} repo; others install it with: pam program install <dir|git-url>")


def cmd_program_install(args):
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
    print(f"installed Program '{prog['name']}' [{prog['id']}]")
    print("  next: staff it with your own agents — pam agent onboard <name> --program "
          f"{prog['name']} --role program_lead")


# ---- membership & team ------------------------------------------------------

def cmd_membership_add(args):
    db.init()
    p = db.get_program(args.program)
    if not p:
        _die(f"no such program: {args.program}")
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
            _die(f"no such team: {args.team} (pam team add {args.team} --program {p['name']})")
        team_id = t["id"]
    db.add_membership(agent["id"], p["id"], role["id"], team_id=team_id, reports_to_id=reports_to_id)
    print(f"'{agent['name']}' joined '{p['name']}' as {role['key']}")


def cmd_membership_ls(args):
    db.init()
    p = db.get_program(args.program)
    if not p:
        _die(f"no such program: {args.program}")
    for m in db.list_memberships(p["id"]):
        rt = ""
        if m["reports_to_id"]:
            rt = "  reports_to=" + m["reports_to_id"]
        print(f"  {m['agent_name']:18} {m['role_key']:14}{rt}")


def cmd_team_add(args):
    db.init()
    p = db.get_program(args.program)
    if not p:
        _die(f"no such program: {args.program}")
    t = db.add_team(p["id"], args.name)
    print(f"team '{t['name']}' added to '{p['name']}'")


def cmd_team_ls(args):
    db.init()
    p = db.get_program(args.program)
    if not p:
        _die(f"no such program: {args.program}")
    for t in db.list_teams(p["id"]):
        print(f"  {t['name']}")


# ---- projects ---------------------------------------------------------------

def cmd_project_add(args):
    db.init()
    p = db.get_program(args.program)
    if not p:
        _die(f"no such program: {args.program}")
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
            _die(f"no such repo in program: {args.repo}")
        repo_id = repos[args.repo]["id"]
    proj = db.add_project(p["id"], title=args.title, repo_id=repo_id, kind=args.kind,
                          forge_ref=args.epic, owner_id=owner_id, year=args.year)
    print(f"project '{proj['title']}' [{proj['id']}] added to '{p['name']}'"
          + (f" (epic {args.epic})" if args.epic else ""))


def cmd_project_ls(args):
    db.init()
    pid = None
    if args.program:
        p = db.get_program(args.program)
        if not p:
            _die(f"no such program: {args.program}")
        pid = p["id"]
    projs = db.list_projects(program_id=pid, year=args.year)
    if not projs:
        print("(no projects)")
        return
    for pr in projs:
        members = db.list_project_members(pr["id"])
        print(f"  {pr['title']:32} {pr['kind']} {pr['forge_ref'] or '':>6}  "
              f"agents={len(members)}")


def cmd_project_show(args):
    db.init()
    pr = db.get_project(args.project)
    if not pr:
        _die(f"no such project: {args.project}")
    print(f"Project: {pr['title']} [{pr['id']}]  {pr['kind']} {pr['forge_ref'] or ''}")
    print("  agents:")
    for m in db.list_project_members(pr["id"]):
        print(f"    - {m['agent_name']:16} {m['agent_status']:8} sub={m['sub_ref'] or '-'}")


def cmd_project_assign(args):
    db.init()
    pr = db.get_project(args.project)
    if not pr:
        _die(f"no such project: {args.project}")
    agent = db.get_agent(args.agent, active_only=True)
    if not agent:
        _die(f"no active agent: {args.agent}")
    staffed_by = None
    if args.by:
        b = db.get_agent(args.by)
        staffed_by = b["id"] if b else None
    db.add_project_member(pr["id"], agent["id"], sub_ref=args.sub, staffed_by=staffed_by)
    print(f"assigned '{agent['name']}' to '{pr['title']}'"
          + (f" (sub-issue {args.sub})" if args.sub else ""))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pam", description="PAM registry")
    p.add_argument("--version", action="version", version=f"pam {__version__}")
    sub = p.add_subparsers(dest="cmd")

    prog = sub.add_parser("program", help="manage Programs").add_subparsers(dest="sub")
    pa = prog.add_parser("add", help="register a Program + its first repo")
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
    pa.set_defaults(func=cmd_program_add)
    prog.add_parser("ls").set_defaults(func=cmd_program_ls)
    ps = prog.add_parser("show"); ps.add_argument("name"); ps.set_defaults(func=cmd_program_show)
    par = prog.add_parser("add-repo")
    par.add_argument("name"); par.add_argument("--repo", required=True)
    par.add_argument("--path", required=True); par.add_argument("--repo-name", default=None)
    par.add_argument("--default-branch", default="main", dest="default_branch")
    par.add_argument("--force", action="store_true")
    par.set_defaults(func=cmd_program_add_repo)
    pin = prog.add_parser("init", help="scaffold the authored config bundle into the repo")
    pin.add_argument("name"); pin.set_defaults(func=cmd_program_init)
    pcf = prog.add_parser("config", help="show the authored config (read live)")
    pcf.add_argument("name"); pcf.set_defaults(func=cmd_program_config)
    ppu = prog.add_parser("publish", help="serialize the authored config to a shareable bundle")
    ppu.add_argument("name"); ppu.add_argument("--out", default=None, help="output dir (default ./pam-<name>)")
    ppu.set_defaults(func=cmd_program_publish)
    ppi = prog.add_parser("install", help="install a Program from a bundle dir")
    ppi.add_argument("bundle", help="path to a bundle dir (containing pam.program.toml)")
    ppi.add_argument("--name", default=None, help="rename the installed Program")
    ppi.add_argument("--repo-path", action="append", default=None, dest="repo_path",
                     metavar="NAME=PATH", help="bind a repo's local checkout path (repeatable)")
    ppi.add_argument("--gh-account", default=None, dest="gh_account")
    ppi.add_argument("--force", action="store_true")
    ppi.set_defaults(func=cmd_program_install)

    role = sub.add_parser("role", help="list roles").add_subparsers(dest="sub")
    rl = role.add_parser("ls"); rl.add_argument("--program", default=None)
    rl.set_defaults(func=cmd_role_ls)

    agent = sub.add_parser("agent", help="manage agents").add_subparsers(dest="sub")
    ao = agent.add_parser("onboard", help="register an agent (incl. one PAM didn't start)")
    ao.add_argument("name")
    ao.add_argument("--program", required=True)
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

    mem = sub.add_parser("membership", help="agent<->program memberships").add_subparsers(dest="sub")
    ma = mem.add_parser("add")
    ma.add_argument("agent"); ma.add_argument("--program", required=True)
    ma.add_argument("--role", required=True); ma.add_argument("--reports-to", default=None, dest="reports_to")
    ma.add_argument("--team", default=None); ma.set_defaults(func=cmd_membership_add)
    ml = mem.add_parser("ls"); ml.add_argument("--program", required=True)
    ml.set_defaults(func=cmd_membership_ls)

    team = sub.add_parser("team", help="teams within a Program").add_subparsers(dest="sub")
    ta = team.add_parser("add"); ta.add_argument("name"); ta.add_argument("--program", required=True)
    ta.set_defaults(func=cmd_team_add)
    tl = team.add_parser("ls"); tl.add_argument("--program", required=True)
    tl.set_defaults(func=cmd_team_ls)

    proj = sub.add_parser("project", help="Projects (= forge epics)").add_subparsers(dest="sub")
    pja = proj.add_parser("add")
    pja.add_argument("title"); pja.add_argument("--program", required=True)
    pja.add_argument("--lead", default=None, help="owning Division Lead (agent)")
    pja.add_argument("--epic", default=None, help="forge issue number of the epic")
    pja.add_argument("--repo", default=None); pja.add_argument("--kind", default="epic")
    pja.add_argument("--year", type=int, default=None); pja.set_defaults(func=cmd_project_add)
    pjl = proj.add_parser("ls")
    pjl.add_argument("--program", default=None); pjl.add_argument("--year", type=int, default=None)
    pjl.set_defaults(func=cmd_project_ls)
    pjs = proj.add_parser("show"); pjs.add_argument("project"); pjs.set_defaults(func=cmd_project_show)
    pjx = proj.add_parser("assign")
    pjx.add_argument("project"); pjx.add_argument("--agent", required=True)
    pjx.add_argument("--sub", default=None); pjx.add_argument("--by", default=None)
    pjx.set_defaults(func=cmd_project_assign)
    pjst = proj.add_parser("state", help="project rollup: epic kanban + each agent's state")
    pjst.add_argument("project"); pjst.set_defaults(func=cmd_project_state)

    sub.add_parser("status", help="my Programs and their leads").set_defaults(func=cmd_status)
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
