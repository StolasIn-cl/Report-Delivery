# Local validation — 2026-11-10

Installed module: C:/Users/stolas_in/Desktop/Report-Delivery. Global skill is a junction to skill/report-delivery; no duplicate maintained Outlook procedure remains in the two producers.

## Automated checks

- Shared ledger/operations: 16 tests passed, including real two-process claim exclusion, immutable snapshots, duplicate dates, interrupted sends, recovery ownership races, evidence time matching, legacy migration and self-only test manifests.
- Nightly PR: 60 tests passed, including producer freshness, original subject/body/recipients, no-PR mail and receipt synchronization after a later fetch.
- WER: 23 tests passed, including ready manifest generation without declaring success, original mail content and receipt rejection before sent.
- Installed skill quick_validate passed. Current PR and WER HTML rendered to valid local PDFs. Git diff whitespace checks passed.

Independent code review identified recovery UI serialization, evidence time matching and delayed receipt synchronization issues. These were fixed with regression tests; the follow-up review found no remaining important issue in the focused changes.

## Live Chrome tests

All test messages use independent delivery-test identities and only Stolas_In@cyberlink.com. Neither production recipient file was changed. Each test attaches both the dated PR and WER PDFs from immutable spool paths.

- Initial test job 75f2b7f0b94cbbe6ad9066930d6f947f: sent and verified in Sent Items, sender/self-only recipient and both attachment names checked. Evidence: evidence/self-test-before-send.json and evidence/self-test-sent-items.json.
- Luna 6 xhigh test job 307219c9a936e398ec2e5283522f5f87: sent once at 14:13 +08 and verified in Sent Items. Contact card confirmed the full self-only company email; both attachment names matched, 555 KB total. Receipt: evidence/307219c9a936e398ec2e5283522f5f87-sent-items.json. No Sol escalation was needed.

The real test exposed a Chrome tab already claimed by the parent chat. The skill now explicitly creates its own Outlook tab on the same extension backend when this occurs. It also arms the documented file chooser listener before Browse this computer.

## Installed schedules and migration

Updated the existing automations through the Codex app tool, then verified their stored configuration:

- nightly-pr-report-2: ACTIVE, Tuesday–Saturday 09:00 Asia/Taipei; original cron/project/local target and gpt-6-luna/xhigh retained.
- wer-crash: ACTIVE, daily 08:00 Asia/Taipei; original heartbeat chat retained.

Both prompts use producer preparation → shared delivery → producer receipt sync. Delivery problems get one gpt-6.1-sol diagnostic round after bounded local recovery. Report/data/date/PDF failures stop instead. Original subjects, bodies and production recipients remain producer-owned.

Legacy PR 2026-11-09 and WER 2026-11-10 sent records were imported to prevent resending. Backups of the touched installed files and original automation configurations are under backups/2026-11-10. Nightly changes are on codex/shared-report-delivery; WER is an installed directory without a Git repository.

## Limits

Chrome/extension availability and Outlook sign-in remain runtime dependencies. Actual tool approval or policy gates cannot be removed by a skill. Sent Items evidence establishes Outlook acceptance, not final recipient delivery. Unknown outcomes stay unknown until reconciled; they are never blindly resent. The Sol escalation state is tested locally; no live failure was deliberately induced to test the full diagnostic delegation route.
