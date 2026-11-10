# Report Delivery

Shared local delivery ledger and Chrome Outlook skill. Python 3.11+ standard library, no network credentials or mail API. Producers retain email content and recipient configuration.

Clone beside Nightly-PR-Report and WER-Daily-Report. Copy config.example.json to config.local.json and set sender_account to the signed-in Outlook account. The test-recipient restriction remains Stolas_In@cyberlink.com. Configuration, runtime state and observed email evidence are local; restore them separately when moving this installation. The installed skill contains this machine's absolute paths; adjust those deliberately when installing elsewhere.

- CLI: `python delivery.py --help`
- Workflow: [skill/report-delivery/SKILL.md](skill/report-delivery/SKILL.md)
- Settings: `config.local.json` (verified Outlook account; tests restricted to Stolas only)
- Persistent authority: `state/delivery.sqlite3` with full-synchronous transactions, mailbox ownership and an event table.
- Immutable input snapshots: `state/spool/ID/manifest.json` and dated PDF files. Verify before Send; never modify the spool.
- `list`, `submit MANIFEST`, `claim --owner CHAT_ID`, `verify ID`, `transition`, `recover`, `reserve`, `release`, `requeue`, `reconcile`, `escalate`, `import-legacy` print JSON. CLI never sends mail.

Run `python -m unittest discover -s tests -v`. SQLite files/spools/evidence/config/backups are local and excluded from git. Keep them for recovery. Never delete a lock/state merely to unblock a run. Recovery requires verifying the previous worker stopped and, for any retry before Send, the disposition of its own draft. Unknown sends can only be reconciled against Sent Items; missing evidence remains unknown.

WER: daily 08:00 Asia/Taipei. PR: Tuesday–Saturday 09:00 Asia/Taipei. These are trigger times; generation and sending take time. Both existing schedules orchestrate their own producer and this shared workflow. Luna escalates delivery diagnosis to gpt-6.1-sol once; report-content failures stop.

Installation: global `C:/Users/stolas_in/.codex/skills/report-delivery` is a directory junction to this repo's `skill/report-delivery`, so only one maintained skill exists. New chats discover it; existing schedules also read its explicit path.

Migration: import confirmed legacy dates as sent with weaker legacy evidence; do not resend them. Import sending/preparing/send_unknown as unknown. Unrecorded historical dates are not automatically backfilled. Backups of touched live files and schedules are under backups/2026-11-10. To roll back, restore producers/docs from backup and use the automation tool to restore previous prompts/times; preserve the shared ledger to retain duplicate protection.

Receipts rely on observed Outlook evidence supplied by the agent. The state machine checks identity, time, recipients and filenames, but cannot independently prove a screenshot's truth or guarantee exactly-once delivery across an external mail system. Ambiguity intentionally blocks re-send.
