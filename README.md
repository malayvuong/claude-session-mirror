# claude-session-mirror

Keep your Claude Desktop **Code tab** sessions and scheduled tasks when you sign in with another Claude account on the same Mac.

The Claude desktop app keeps one folder per signed-in profile. Sign in with a second account and the Code tab starts empty: your sessions, and the scheduled tasks you registered, belong to the first profile. This tool copies the small session metadata files (and the scheduled-task registry) into the profile you just signed in with and restarts the app. The transcripts themselves are shared by every profile, so the mirrored sessions open with their full history.

Unofficial. It relies on the app's on-disk layout as observed on Claude Desktop 4.23118.0 (macOS) and may stop working when the app changes it. It never overwrites or deletes a file.

## Install

```bash
git clone https://github.com/malayvuong/claude-session-mirror.git
cd claude-session-mirror
```

Requires macOS and `python3` (bundled with the Xcode Command Line Tools). No dependencies.

## Switch account in one command

1. In the Claude desktop app: sign out, sign in with the other account, open the **Code** tab once (the app creates the profile folder).
2. In Terminal.app (not inside a Claude session, since the app will be restarted):

   ```bash
   ./switch-account.sh
   ```

   It prints the profiles it found, marks the one you just signed in with, and waits for Enter:

   ```
   profiles (last signed-in first; * = ~/.claude.json, which lags until a Code session starts):
     1.   a1b2c3d4/0f0f0f0f  sessions=9     account seen=11-08 18:00  folder touched=11-08 18:00 <- target
     2. * 11223344/0f0f0f0f  sessions=1197  account seen=11-08 17:59  folder touched=11-08 17:58
   target a1b2c3d4/0f0f0f0f: 9 sessions already, 1188 to copy from 11223344/0f0f0f0f
   Copy 1188 sessions + missing scheduled tasks into a1b2c3d4/0f0f0f0f and restart the app? [Enter = yes, n = no]
   ```

   Enter accepts, a number picks another target, `n` cancels.
3. The app quits and relaunches. Open the Code tab: every session is listed. Scheduled tasks are listed too and run under the new account.

Flags: `--dry-run` (print only), `--yes` (no prompt), `--no-restart`, `--to <profile>` / `--from <profile>` (8-character prefixes are enough). Every run is appended to `switch.log` next to the script.

## Other commands

```bash
python3 claude_session_mirror.py profiles                       # list profile folders
python3 claude_session_mirror.py import <cliSessionId> --to <profile> --execute
python3 claude_session_mirror.py mirror --from <profile> --to <profile> --tasks --execute
```

`import` adds a session the app does not know yet from its CLI transcript (`claude --resume` sessions). `mirror` copies one profile into another without restarting; `--archived` includes archived sessions.

## How it works

| What | Where |
|---|---|
| Profile folder (one per signed-in account) | `~/Library/Application Support/Claude/claude-code-sessions/<accountUuid>/<organizationUuid>/` |
| Session metadata (title, cwd, pointer to the transcript) | `local_<id>.json` inside the profile folder |
| Scheduled-task registry | `scheduled-tasks.json` inside the profile folder (prompts stay in `~/.claude/scheduled-tasks/<id>/SKILL.md`, shared) |
| Transcripts (shared by all profiles) | `~/.claude/projects/<cwd slug>/<uuid>.jsonl` |
| Which account was used last | newest file under `~/Library/Application Support/Claude/local-agent-mode-sessions/<accountUuid>/` |

The app reads the profile folder when it starts, so the tool quits and relaunches it (`osascript` + `open -b com.anthropic.claudefordesktop`). Session ids are kept, so links to a session keep working in the other account. `~/.claude.json` (`oauthAccount`) is shown as a cross-check only: the app's embedded CLI updates it once a Code session starts, so right after signing in it still names the previous account.

Verified on 2026-11-08: a profile with 1,185 sessions and 7 scheduled tasks mirrored into a second account; after the relaunch the Code tab listed them all, they opened with their history, and the scheduled tasks fired under the second account a minute later.

## Caveats

- Only one account is signed in at a time; the tool makes the profiles take turns, it does not run them together.
- Transcripts are not copied anywhere (they are already shared). Moving to another Mac means copying `~/.claude/projects/` too.
- Metadata written by this tool is adopted and rewritten by the app on first open; later changes made under one account (title, archive state) are not synced back to the other profile unless you run `switch` again.
- Nothing is uploaded; the tool touches only the folders above.

## License

MIT
