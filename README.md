# Handover Desk

**A pre-delivery acceptance desk that runs in your team chat.** Before a website goes to a client, two
Claude Code agents and two people (the developer and the client) check the live site together in one
Discord channel, fix what is wrong, recheck it, and sign it off, with a written record at the end.

Built for the **Flip the Switch** hackathon (WeMakeDevs × Switch), Track 01: Business workflow.

- Demo target (a fictional clinic site with planted problems): https://handover-desk-demo.vercel.app/,
  repo [`rasarafi/handover-desk-demo`](https://github.com/rasarafi/handover-desk-demo)
- Demo video: _link added on submission_

## The problem

Sites get handed to clients with embarrassing leftovers: a `test@test.com` account on the team page,
lorem ipsum in "Our story", links to a page that was never built, an API still pointing at `localhost`,
a dashboard that shows an empty table. Developers miss them because they know the site too well. The
client finds them, in front of their own customers.

The fix is a handover check with fresh eyes, but it only works if the developer *and* the client see the
same findings, can ask about them, and agree when it is done. That is a conversation, so it belongs in chat.

## The workflow

```
developer:  @auditor ready to ship https://site.example
auditor:    1. Test account visible to the public: test@test.com on / and /dashboard (high)
            2. Placeholder text: "Lorem ipsum…" in Our story (high)
            3. Dev URL shipped: http://localhost:3000/api in assets/app.js (high)
            ...                                   → room document "Handover audit — site.example"
client:     @auditor what does 3 mean for my customers?
auditor:    Bookings on the dashboard can't load for anyone but the developer's own laptop…
client:     @fixer fix 1
fixer:      I only take instructions from my owner…                 ← Switch "Who can talk: Only me"
developer:  @fixer fix 2, 3, 4
fixer:      PR #2 · Preview: https://…-git-fix-handover-2-3-4….vercel.app
            @auditor recheck <preview>                              ← agent hands off to agent
auditor:    2. fixed on preview · 3. fixed on preview · 4. fixed on preview · 1, 5… still open
developer:  @fixer merge
fixer:      Merged. Production is updated. @auditor recheck <production>
client:     @auditor approved
auditor:    Handed over. Record saved.                → room document "Handover record — site.example"
```

## How Switch is used (and why it would not work without it)

| Switch feature | What it does here |
|---|---|
| **Room bound to a Discord channel** | `#handover-desk` is one Switch room. Developer, client and both agents share it. No one installs anything but Discord. |
| **Two agents, each with its own working directory** | `auditor` runs in this repo (it needs `audit/audit.py`); `fixer` runs in the client site's repo (it needs git and `gh`). |
| **Who can talk** | `auditor` = **Anyone**: the client can question the audit. `fixer` = **Only me**: only the developer can order code changes. The client's `@fixer fix 1` is refused by Switch's access rule, not by a prompt. |
| **Agent-to-agent mentions** | `fixer` ends every PR with `@auditor recheck <preview>`; the recheck happens without a human relaying it. |
| **Room documents** | The audit and the final handover record are saved as room documents, so the sign-off is a durable record, not a scrolled-away message. |
| **Agent instructions** | The Switch field only points at `agents/auditor.md` / `agents/fixer.md`, so the behaviour is versioned in git and reproducible. |

Without Switch, this is a script the developer runs alone. The client never sees the findings until it is
too late, cannot ask about them, and there is no shared moment of "approved".

## Repository layout

```
audit/audit.py          deterministic URL-only checks (Python 3 standard library, no install)
agents/auditor.md       the auditor's procedure (audit, client questions, recheck, approved → record)
agents/fixer.md         the fixer's procedure (fix → branch → local check → PR → preview → recheck; merge)
tests/                  15 tests: a planted site must produce its known findings, a clean site none
tests/fixtures/planted-issues.md   the answer key for the demo site (kept out of the auditor's view)
```

## `audit.py` on its own

```bash
python3 audit/audit.py https://handover-desk-demo.vercel.app/          # Markdown report
python3 audit/audit.py https://handover-desk-demo.vercel.app/ --json   # for agents
python3 -m unittest discover -s tests                                  # 15 tests
```

Checks: site alive and HTTPS · test accounts and fake people · placeholder text · dev/staging URLs in
shipped HTML/JS/CSS · broken links (one finding per URL) · missing title, favicon, link-preview tags.
Same input, same findings; exit code 1 if anything is found. The `auditor` adds a browser walk
(Playwright) for what a script cannot see: console errors, empty states, dead buttons, phone layout.

## Set it up yourself

You need: [Switch Console](https://docs.switchagents.ai), a Discord server you own, Claude Code signed in,
Python 3, `git`, the GitHub CLI `gh`, and a site repo deployed on Vercel (or any host with PR previews).

1. **Discord.** Create a server and a bot application (Developer Portal). Turn on the *Server Members*
   and *Message Content* intents. Invite it with scopes `bot` and `applications.commands` and the
   permissions View Channels, Send Messages, Send Messages in Threads, Read Message History,
   Manage Webhooks, Manage Channels, Manage Roles, Attach Files, Add Reactions.
2. **Switch Console.** Start the local server, then *Messaging apps → Connect → Discord* with the bot
   token and the server id. *Link your Discord user account*: this is how Switch tells the developer
   (owner) from everyone else.
3. **Room.** Create a room bound to a channel (for example `#handover-desk`); the built-in Switch
   helper agent can do this from its welcome chat.
4. **Agents** (*Your Agents → +*, provider Claude Code, run on this computer):

   | | auditor | fixer |
   |---|---|---|
   | Directory | this repo | your site's repo (clone) |
   | Instructions | `You are the Handover Desk auditor. Read agents/auditor.md in your working directory at the start of every session and follow it exactly. Run audit/audit.py from that directory.` | `You are the Handover Desk fixer. At the start of every session read <path to this repo>/agents/fixer.md and follow it exactly. The Handover Desk repo (with audit/audit.py) is <path to this repo>.` |
   | Who can talk | **Anyone** | **Only me** |

   Then **add both agents to the room** (agent page → *Add to room*). A new agent is not in any room
   until you do; Discord will say "auditor isn't in this room".
5. **Try it.** In the channel, pick `@auditor` from the autocomplete (typed text does not trigger it)
   and send `ready to ship <your url>`.

## Keeping the fixer on a short leash

Instructions are not a security boundary, so the `fixer` also has hard limits on the machine it runs on:

- a **fine-grained GitHub token scoped to the one site repo** (contents + pull requests only), in its
  own `gh` config directory (`GH_CONFIG_DIR`), so it cannot reach any other repository;
- in the site repo's local `.claude/settings.local.json` (never committed): that `GH_CONFIG_DIR`,
  `GIT_SSH_COMMAND=false` (no SSH keys), and deny rules for reading `~/.ssh` and other credentials,
  `git config`, `git remote set-url/add`, `gh auth`, and any push to `main` or force push.

This stops mistakes and limits the token. It is not proof against a deliberately hostile agent running
as the same OS user; for that, run the fixer as a separate user.

## Limits

- `audit.py` reads public pages only: no logins, no forms, no destructive tests.
- Findings are numbered per thread; start a new thread for a new site.
- Built and tested on Switch Console 0.40.1 (Linux, early access) with Discord.
