# Work `hi` does without being asked

`hi` can prepare things for you in the background. It reads freely, writes reports, and **never changes anything
without your approval**. The design is in [adr/0002-automation.md](adr/0002-automation.md).

## What runs by itself

| What | When | Where you see it |
|---|---|---|
| **Scheduled tasks** | on a timetable you set ("every weekday at 8") | Inbox → Reports, a pop-up in the island |
| **Heartbeat** | every 30 minutes, 08:00 to 22:00 | one digest in the island, reports in the Inbox |
| **Drop folder** | within about two minutes of saving a file | a note in `hi/drop/notes/`, tasks added, a pop-up |
| **Screenshot watcher** (off by default) | new screenshots on the Desktop | a note, like the drop folder |

Everything it writes is a file in your vault: `hi/reports/`, `hi/schedules/`, `hi/proposals.jsonl`, `hi/heartbeat/`,
`hi/drop/`. Nothing is hidden in a database.

## Approving actions

A background run may read the vault, search the web, read repos and write reports. Anything else it wants to do
(send an email, write a file, push) is **not run**. It becomes a *proposal*:

- The island says what would run, for example `Approve send_email(to='bob@acme.com', subject='Follow-up')?`.
  Reply **yes** or **no** in the island.
- The **Inbox → Actions** tab shows the exact arguments, with Approve and Deny.
- An approved action runs once and is never retried. A proposal you ignore expires after 7 days.
- A question that was cut short for length cannot be approved from the island; open the Inbox.

## Scheduling by talking

Say it to `hi`: "every weekday at 8 brief me", "remind me Friday at 5 to send the invoice", "on Sunday evening
review my week". `hi` answers with the next three times it will run: check them. A schedule is a note in
`<vault>/hi/schedules/<id>.md`; edit it in Obsidian and it applies on the next tick. A note that does not parse is
listed with the reason in **Inbox → Schedules**, and the others keep running.

```markdown
---
when: "0 8 * * 1-5"      # five cron fields, local time; or: once 2026-11-20T15:00
kind: task               # task (the assistant works on it) | reminder (shown as written, no model)
tier: sonnet
deliver: notify          # notify | report (pop-up only for approvals) | silent
context: [vault, screen] # screen only for a local model
allow_web: true
catch_up: 2h             # run a missed slot if the Mac is back within this long
---
Brief me for today: ...
```

### Three to start with

**Morning brief** (weekdays 08:00)
```markdown
---
when: "0 8 * * 1-5"
kind: task
deliver: notify
context: [vault]
allow_web: false
---
Brief me for today. List what is overdue or due in the next two days, deadlines this week, the open loops from
yesterday's reflection, and anything I left half-done yesterday (from the journal). Draft my stand-up in three
bullet points. Start with a one-line headline.
```

**End-of-day journal summary** (weekdays 18:00)
```markdown
---
when: "0 18 * * 1-5"
kind: task
deliver: report
context: [vault]
---
Summarise what I did today from the journal: what moved forward, what is blocked, and what should come first
tomorrow. Keep it under 150 words and start with a one-line headline.
```

**Weekly review** (Sunday 18:00)
```markdown
---
when: "0 18 * * 0"
kind: task
deliver: notify
context: [vault]
allow_web: false
---
Review my week from the journal, the tasks and the reflections. What did I finish, what slipped, which decisions
did I make, and what are the three most important things for next week? Start with a one-line headline.
```

(The built-in weekly retro job still runs; this is an addition, not a replacement.)

## The heartbeat

Every 30 minutes `hi` collects facts by plain code: deadlines, a meeting within the hour, an error that has been on
your screen for 15+ minutes, actions waiting more than a day. If nothing changed since the last beat it stops there,
at no cost. Otherwise one cheap model call picks at most three things worth preparing, and each choice must quote a
real fact (checked in code). It prepares them (a summary of the failing CI log with a proposed fix, notes and the last
thread before a call, a draft email) and tells you once.

The screen is only used with a **local** model, and never when your screen context is paused or private. Turn the
heartbeat off, change the hours or the interval in Settings → automation.

## The drop folder

Save a file into `<vault>/hi/drop/` (Finder, or **Save to Files** on your iPhone, since the vault syncs through
iCloud). Documents, PDFs, images and voice memos are read; `hi` writes a note with a summary, the action items and
the text, adds the action items to your tasks, and moves the original to `drop/processed/`. A file that cannot be read
stays where it is and is reported once. In chat, the **file it** link on an attached file does the same.

## Limits and safety

- At most 6 background runs per hour and 50 on a hosted model per day (Settings → automation).
- Pop-ups share one budget (3 per hour). Approvals, reminders and failures always get through.
- Secrets are masked in reports, in prompts a background run sends to a hosted model, and in notes made from
  documents. A search query or fetch URL containing a secret is refused.
- `GET /health` shows every job's last run, the timezone schedules use, how many actions are waiting, and how fast
  each kind of turn has been.

## Always on

`hi --install-agent` starts the menu bar app at login and restarts it if it crashes (not when you choose Quit).
`hi --uninstall-agent` removes it. In Docker the backend restarts itself when it stops answering (`/livez`).
If your schedules fire at the wrong hour, check the timezone in `/health`: `hi` passes your Mac's zone to the
container when it starts the stack.
