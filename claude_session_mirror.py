#!/usr/bin/env python3
"""claude-session-mirror: keep Claude Desktop (Code tab) sessions and scheduled tasks when you sign in with another
Claude account on the same Mac. Unofficial; relies on the app's on-disk layout observed on app 4.23118.0 (macOS).

The desktop app keeps one folder per signed-in profile (`<organizationUuid>/<accountUuid>`) under
~/Library/Application Support/Claude/claude-code-sessions/. Each session is a small `local_<id>.json` there that
points at the CLI transcript (`cliSessionId`) in ~/.claude/projects/<cwd slug>/<uuid>.jsonl, which every profile
shares. The folder also holds `scheduled-tasks.json`, the per-profile registry of scheduled tasks. The app reads the
folder when it starts, so every change here shows up after a restart (verified 2026-11-08 by importing a CLI
transcript of another account: it appeared in the sidebar and opened with its history).

Commands (dry run unless --execute):
  profiles                                   list the profile folders with session counts
  import <cliSessionId> --to <profile>       write a metadata file for a CLI transcript the app does not know
  mirror --from <profile> --to <profile>     copy every session metadata (same local_ id) and, with --tasks,
         [--tasks] [--archived] [--execute]   scheduled-tasks.json into another profile; never overwrites, never deletes
  switch [--yes] [--no-restart] [--dry-run]  one shot after signing in with another account: pull every session and
                                             scheduled task of the other profiles into the signed-in profile
                                             (detected from ~/.claude.json), then quit and relaunch the app

A profile is `<org>/<account>`; 8-character prefixes are enough. Nothing is printed from a transcript except its
title. Restart the desktop app after --execute.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone

STORE = os.path.expanduser('~/Library/Application Support/Claude/claude-code-sessions')
PROJECTS = os.path.expanduser('~/.claude/projects')


def profiles() -> list[tuple[str, str]]:
    found = []
    for org in sorted(os.listdir(STORE)) if os.path.isdir(STORE) else []:
        od = os.path.join(STORE, org)
        if not os.path.isdir(od):
            continue
        for acc in sorted(os.listdir(od)):
            if os.path.isdir(os.path.join(od, acc)):
                found.append((org, acc))
    return found


def resolve(spec: str) -> str:
    """`<org>/<account>` with prefixes to the full folder path."""
    try:
        org_p, acc_p = spec.split('/', 1)
    except ValueError:
        raise SystemExit(f'profile must be <org>/<account>: {spec!r}')
    hits = [(o, a) for o, a in profiles() if o.startswith(org_p) and a.startswith(acc_p)]
    if len(hits) != 1:
        raise SystemExit(f'{spec!r} matches {len(hits)} profiles; run `profiles`')
    return os.path.join(STORE, *hits[0])


def read_json(path: str):
    with open(path, encoding='utf-8') as handle:
        return json.load(handle)


def write_json(path: str, data) -> None:
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def session_files(folder: str) -> dict[str, dict]:
    out = {}
    for f in glob.glob(os.path.join(folder, 'local_*.json')):
        try:
            out[os.path.basename(f)] = read_json(f)
        except (OSError, ValueError):
            continue
    return out


def cmd_profiles(_: argparse.Namespace) -> None:
    for org, acc in profiles():
        folder = os.path.join(STORE, org, acc)
        sessions = session_files(folder)
        newest = max((d.get('lastActivityAt') or 0 for d in sessions.values()), default=0)
        archived = sum(1 for d in sessions.values() if d.get('isArchived'))
        tasks = os.path.join(folder, 'scheduled-tasks.json')
        count = len(read_json(tasks).get('scheduledTasks', [])) if os.path.exists(tasks) else 0
        when = time.strftime('%Y-%m-%d %H:%M', time.localtime(newest / 1000)) if newest else '-'
        print(f'{org[:8]}/{acc[:8]}  sessions={len(sessions)} (archived {archived})  newest={when}  scheduled-tasks={count}')


def transcript_path(cli_id: str) -> str:
    hits = glob.glob(os.path.join(PROJECTS, '*', f'{cli_id}.jsonl'))
    if len(hits) != 1:
        raise SystemExit(f'transcript {cli_id} not found once under {PROJECTS} ({len(hits)} hits)')
    return hits[0]


def transcript_facts(path: str) -> dict:
    facts = {'title': None, 'cwd': None, 'first': None, 'last': None, 'turns': 0, 'last_assistant': None, 'model': None}
    with open(path, encoding='utf-8', errors='ignore') as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            kind = row.get('type')
            facts['cwd'] = facts['cwd'] or row.get('cwd')
            if kind == 'ai-title':
                facts['title'] = row.get('title') or facts['title']
            stamp = row.get('timestamp')
            if stamp:
                facts['first'] = facts['first'] or stamp
                facts['last'] = stamp
            if kind == 'user' and not row.get('isMeta'):
                facts['turns'] += 1
            if kind == 'assistant':
                facts['last_assistant'] = row.get('uuid')
                model = (row.get('message') or {}).get('model')
                if model and not model.startswith('<'):
                    facts['model'] = model
    return facts


def ms(stamp: str | None) -> int:
    if not stamp:
        return int(time.time() * 1000)
    return int(datetime.fromisoformat(stamp.replace('Z', '+00:00')).astimezone(timezone.utc).timestamp() * 1000)


def known_everywhere(cli_id: str) -> list[str]:
    hits = []
    for org, acc in profiles():
        for name, data in session_files(os.path.join(STORE, org, acc)).items():
            if data.get('cliSessionId') == cli_id:
                hits.append(f'{org[:8]}/{acc[:8]}/{name}')
    return hits


def cmd_import(args: argparse.Namespace) -> None:
    target = resolve(args.to)
    path = transcript_path(args.cli_session_id)
    already = known_everywhere(args.cli_session_id)
    if already:
        print(f'transcript already has metadata: {already}; use `mirror` to copy it instead')
        return
    facts = transcript_facts(path)
    cwd = facts['cwd'] or os.path.expanduser('~')
    created, last = ms(facts['first']), ms(facts['last'])
    local_id = 'local_' + str(uuid.uuid4())
    meta = {
        'sessionId': local_id,
        'cliSessionId': args.cli_session_id,
        'cwd': cwd,
        'originCwd': cwd,
        'writtenRepositories': [],
        'gitAnchors': [{'gitRoot': cwd, 'commonDir': os.path.join(cwd, '.git'), 'trustedAt': created}]
        if os.path.isdir(os.path.join(cwd, '.git')) else [],
        'lastFocusedAt': last, 'createdAt': created, 'lastActivityAt': last, 'lastTurnEdgeAt': last,
        'model': facts['model'] or 'claude-fable-5-1',
        'effort': 'high',
        'isArchived': False,
        'title': (args.title or facts['title'] or f'CLI session {args.cli_session_id[:8]}')[:80],
        'titleSource': 'manual' if args.title else 'auto',
        'permissionMode': 'default',
        'completedTurns': facts['turns'],
        'lastAssistantUuid': facts['last_assistant'],
        'lastAssistantCliSessionId': args.cli_session_id,
    }
    out = os.path.join(target, f'{local_id}.json')
    print(f'{"write" if args.execute else "would write"} {out.replace(os.path.expanduser("~"), "~")}')
    print(f'  title={meta["title"]!r} turns={facts["turns"]} cwd={cwd}')
    if args.execute:
        write_json(out, meta)
        print('done: restart the desktop app, the session appears in the sidebar of that profile')


def cmd_mirror(args: argparse.Namespace) -> None:
    source, target = resolve(args.src), resolve(args.to)
    if source == target:
        raise SystemExit('source and target are the same profile')
    have = session_files(target)
    copied = skipped_present = skipped_archived = 0
    for name, data in sorted(session_files(source).items(), key=lambda kv: kv[1].get('lastActivityAt') or 0):
        if name in have:
            skipped_present += 1
            continue
        if data.get('isArchived') and not args.archived:
            skipped_archived += 1
            continue
        copied += 1
        if args.execute:
            write_json(os.path.join(target, name), data)
    verb = 'copied' if args.execute else 'would copy'
    print(f'sessions: {verb} {copied}, already present {skipped_present}, archived skipped {skipped_archived}')
    if args.tasks:
        src_tasks = os.path.join(source, 'scheduled-tasks.json')
        dst_tasks = os.path.join(target, 'scheduled-tasks.json')
        if not os.path.exists(src_tasks):
            print('scheduled-tasks.json: none in the source profile')
        elif os.path.exists(dst_tasks) and read_json(dst_tasks).get('scheduledTasks'):
            print('scheduled-tasks.json: target already has tasks, left untouched (merge by hand if needed)')
        else:
            print(f'scheduled-tasks.json: {verb} ({len(read_json(src_tasks).get("scheduledTasks", []))} tasks)')
            if args.execute:
                write_json(dst_tasks, read_json(src_tasks))
    if args.execute:
        print('done: restart the desktop app and sign in to the target profile')
    else:
        print('dry run: add --execute to write')


CLAUDE_JSON = os.path.expanduser('~/.claude.json')
APP_BUNDLE = 'com.anthropic.claudefordesktop'
APP_BINARY = '/Applications/Claude.app/Contents/MacOS/Claude'


def current_profile() -> tuple[str, str] | None:
    """Profile of the signed-in account: `<accountUuid>/<organizationUuid>` from ~/.claude.json (the app's embedded
    CLI keeps `oauthAccount` in step with the desktop login); None when unreadable."""
    try:
        account = read_json(CLAUDE_JSON).get('oauthAccount') or {}
    except (OSError, ValueError):
        return None
    acc, org = account.get('accountUuid'), account.get('organizationUuid')
    if not acc or not org:
        return None
    return acc, org


def newest_profile() -> tuple[str, str] | None:
    """Fallback: the profile folder touched most recently (a login touches it)."""
    best = None
    for org, acc in profiles():
        folder = os.path.join(STORE, org, acc)
        stamp = max([os.path.getmtime(folder)] + [os.path.getmtime(os.path.join(folder, f)) for f in os.listdir(folder)])
        if best is None or stamp > best[0]:
            best = (stamp, (org, acc))
    return best[1] if best else None


def merge_tasks(target: str, sources: list[str], execute: bool) -> None:
    """Add every scheduled task the target registry lacks (by id) from the richest source registry."""
    dst = os.path.join(target, 'scheduled-tasks.json')
    have = read_json(dst) if os.path.exists(dst) else {'scheduledTasks': []}
    have.setdefault('scheduledTasks', [])
    ids = {t.get('id') for t in have['scheduledTasks']}
    best = None
    for folder in sources:
        src = os.path.join(folder, 'scheduled-tasks.json')
        if os.path.exists(src):
            tasks = read_json(src).get('scheduledTasks', [])
            if best is None or len(tasks) > len(best):
                best = tasks
    missing = [t for t in (best or []) if t.get('id') not in ids]
    print(f'scheduled tasks: {"added" if execute else "would add"} {len(missing)}, already present {len(ids)}')
    if execute and missing:
        have['scheduledTasks'].extend(missing)
        write_json(dst, have)


def restart_app() -> None:
    import subprocess
    print('restarting the Claude desktop app ...')
    subprocess.run(['osascript', '-e', f'tell application id "{APP_BUNDLE}" to quit'], check=False)
    for _ in range(60):
        if subprocess.run(['pgrep', '-f', APP_BINARY + '$'], capture_output=True).returncode != 0:
            break
        time.sleep(1)
    else:
        print('the app did not quit within 60 s; open it yourself')
        return
    time.sleep(2)
    subprocess.run(['open', '-b', APP_BUNDLE], check=False)
    print('app relaunched: the sidebar should show the mirrored sessions')


AGENT_MODE = os.path.expanduser('~/Library/Application Support/Claude/local-agent-mode-sessions')


def account_last_seen() -> dict[str, float]:
    """Account id -> newest file time under local-agent-mode-sessions/<account>/, which the app writes when that
    account is in use; the lanes' session writes do not touch it, so it tells which account signed in last."""
    seen = {}
    if not os.path.isdir(AGENT_MODE):
        return seen
    for acc in os.listdir(AGENT_MODE):
        root = os.path.join(AGENT_MODE, acc)
        if not os.path.isdir(root):
            continue
        newest = os.path.getmtime(root)
        for dirpath, _, files in os.walk(root):
            for name in files:
                try:
                    newest = max(newest, os.path.getmtime(os.path.join(dirpath, name)))
                except OSError:
                    continue
        seen[acc] = newest
    return seen

def touched_at(folder: str) -> float:
    """Newest mtime of the profile folder or any file in it (the app rewrites files when it loads a profile)."""
    stamps = [os.path.getmtime(folder)]
    for name in os.listdir(folder):
        try:
            stamps.append(os.path.getmtime(os.path.join(folder, name)))
        except OSError:
            continue
    return max(stamps)


def log_line(text: str) -> None:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'switch.log')
    with open(path, 'a', encoding='utf-8') as handle:
        handle.write(time.strftime('%Y-%m-%d %H:%M:%S ') + text + '\n')


def cmd_switch(args: argparse.Namespace) -> None:
    """One shot after signing in with another account: pull every session and scheduled task of the other profiles
    into the signed-in profile, then restart the app.

    The signed-in profile is the folder the app touched most recently (it rewrites session files when it loads a
    profile); `~/.claude.json` (`oauthAccount`) is only a cross-check because the embedded CLI updates it only once
    a Code session starts under the new account. The user confirms the choice unless --yes."""
    rows = []
    oauth = current_profile()
    for org, acc in profiles():
        folder = os.path.join(STORE, org, acc)
        rows.append({'key': (org, acc), 'folder': folder, 'touched': touched_at(folder),
                     'sessions': len(session_files(folder)), 'oauth': oauth == (org, acc)})
    if not rows:
        raise SystemExit('no profile folder found; sign in and open the Code tab once')
    seen = account_last_seen()
    for r in rows:
        r['seen'] = seen.get(r['key'][0], 0.0)
    # signed-in account = the one the app used last (local-agent-mode-sessions), then its most recently touched org folder
    rows.sort(key=lambda r: (r['seen'], r['touched']), reverse=True)
    if args.to:
        target = resolve(args.to)
    else:
        target = rows[0]['folder']
    print('profiles (last signed-in first; * = ~/.claude.json, which lags until a Code session starts):')
    for i, r in enumerate(rows, 1):
        mark = '*' if r['oauth'] else ' '
        chosen = '<- target' if r['folder'] == target else ''
        seen_at = time.strftime('%m-%d %H:%M', time.localtime(r['seen'])) if r['seen'] else '-'
        print(f"  {i}. {mark} {r['key'][0][:8]}/{r['key'][1][:8]}  sessions={r['sessions']}  account seen={seen_at}  folder touched={time.strftime('%m-%d %H:%M', time.localtime(r['touched']))} {chosen}")
    if not args.yes and not args.dry_run:
        answer = input('Target = the signed-in profile? [Enter = yes, or type a number to pick another, n = cancel] ').strip().lower()
        if answer in ('n', 'no'):
            print('cancelled')
            log_line('switch cancelled at the profile prompt')
            return
        if answer.isdigit() and 1 <= int(answer) <= len(rows):
            target = rows[int(answer) - 1]['folder']
    sources = [r['folder'] for r in rows if r['folder'] != target]
    if args.src:
        sources = [resolve(args.src)]
    if not sources:
        raise SystemExit('no other profile to pull from')
    have = session_files(target) if os.path.isdir(target) else {}
    plan = {}
    for folder in sources:
        for name, data in session_files(folder).items():
            if name not in have and name not in plan:
                plan[name] = (folder, data)
    short = lambda f: '/'.join(x[:8] for x in f.replace(STORE + '/', '').split('/'))
    print(f'target {short(target)}: {len(have)} sessions already, {len(plan)} to copy from ' + ', '.join(short(f) for f in sources))
    if args.dry_run:
        merge_tasks(target, sources, execute=False)
        print('dry run, nothing written')
        log_line(f'dry run: target {short(target)} would copy {len(plan)}')
        return
    if not args.yes:
        answer = input(f'Copy {len(plan)} sessions + missing scheduled tasks into {short(target)} and restart the app? [Enter = yes, n = no] ').strip().lower()
        if answer in ('n', 'no'):
            print('cancelled')
            log_line(f'switch cancelled before copy (target {short(target)})')
            return
    os.makedirs(target, exist_ok=True)
    for name, (folder, data) in plan.items():
        write_json(os.path.join(target, name), data)
    print(f'sessions copied: {len(plan)}')
    merge_tasks(target, sources, execute=True)
    log_line(f'switch: target {short(target)} copied {len(plan)} sessions; sources {[short(f) for f in sources]}')
    print('after the relaunch open the Code tab (not the chat list): the sessions are there')
    if args.no_restart:
        print('done: restart the Claude desktop app to see them')
    else:
        restart_app()

def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('profiles').set_defaults(func=cmd_profiles)
    imp = sub.add_parser('import')
    imp.add_argument('cli_session_id')
    imp.add_argument('--to', required=True)
    imp.add_argument('--title')
    imp.add_argument('--execute', action='store_true')
    imp.set_defaults(func=cmd_import)
    mir = sub.add_parser('mirror')
    mir.add_argument('--from', dest='src', required=True)
    mir.add_argument('--to', required=True)
    mir.add_argument('--tasks', action='store_true', help='also copy scheduled-tasks.json when the target has none')
    mir.add_argument('--archived', action='store_true', help='include archived sessions')
    mir.add_argument('--execute', action='store_true')
    mir.set_defaults(func=cmd_mirror)
    sw = sub.add_parser('switch', help='after signing in with another account: pull everything into it and restart the app')
    sw.add_argument('--to', help='target profile (default: the signed-in one from ~/.claude.json)')
    sw.add_argument('--from', dest='src', help='only this source profile (default: every other profile)')
    sw.add_argument('--yes', action='store_true', help='no confirmation prompt')
    sw.add_argument('--no-restart', action='store_true')
    sw.add_argument('--dry-run', action='store_true')
    sw.set_defaults(func=cmd_switch)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == '__main__':
    main(sys.argv[1:])
