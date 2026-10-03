"""PAM command-line interface.

CLI-first by design. Every command reads/writes records and/or runs read-only git; NONE shells out
to tmux. Spawn/attach/resume/onboarding *acts* stay harness-side — PAM emits the facts they consume.
"""
from __future__ import annotations

import argparse
import sys

from . import __version__, config, db, gitutil


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
    try:
        agent = db.add_agent(name=args.name, cwd=args.cwd,
                             last_session_id=args.session_id, identity_path=args.identity)
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
              "home_path", "created_at", "retired_at"):
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
    ao.set_defaults(func=cmd_agent_onboard)
    al = agent.add_parser("ls"); al.add_argument("--all", action="store_true")
    al.set_defaults(func=cmd_agent_ls)
    ash = agent.add_parser("show"); ash.add_argument("name"); ash.set_defaults(func=cmd_agent_show)
    arv = agent.add_parser("resolve"); arv.add_argument("name"); arv.set_defaults(func=cmd_agent_resolve)
    art = agent.add_parser("retire"); art.add_argument("name"); art.set_defaults(func=cmd_agent_retire)

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
