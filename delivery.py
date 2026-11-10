"""Local delivery ledger. Browser actions are performed by the report-delivery skill.

This program NEVER sends mail or connects to a browser. State changes require
observations from the operator; a receipt is not independent transport telemetry.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import uuid

ROOT = Path(__file__).resolve().parent
TAIPEI = dt.timezone(dt.timedelta(hours=8))


class DeliveryError(ValueError):
    pass


def now():
    return dt.datetime.now(TAIPEI).isoformat(timespec='seconds')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def address(value):
    if not isinstance(value, str) or not re.fullmatch(r'[^\s@;,<>]+@[^\s@;,<>]+\.[^\s@;,<>]+', value):
        raise DeliveryError('Invalid email address')
    return value


def key(report_id, day, sender):
    if not isinstance(report_id, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', report_id):
        raise DeliveryError('Invalid report_id')
    try:
        if dt.date.fromisoformat(day).isoformat() != day:
            raise ValueError('Noncanonical date')
    except (TypeError, ValueError) as error:
        raise DeliveryError('Invalid report_date') from error
    address(sender)
    return hashlib.sha256(f'{report_id}|{day}|{sender.lower()}'.encode()).hexdigest()[:32]


def attachment(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    if path.suffix.lower() != '.pdf' or len(raw) < 1000 or not raw.startswith(b'%PDF-'):
        raise DeliveryError('Missing or invalid PDF')
    return dict(path=str(path), filename=path.name, mime_type='application/pdf',
                size=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def validate(manifest):
    m = json.loads(json.dumps(manifest))
    if m.get('schema_version') != 1:
        raise DeliveryError('Unsupported schema_version')
    key(m['report_id'], m['report_date'], m['sender_account'])
    if not m.get('generation') or not isinstance(m['generation'], str):
        raise DeliveryError('generation required')
    stamp = dt.datetime.fromisoformat(m['generated_at'])
    if stamp.tzinfo is None:
        raise DeliveryError('generated_at must include timezone')
    if not isinstance(m['recipients'], list) or not m['recipients']:
        raise DeliveryError('Nonempty recipients array required')
    m['recipients'] = list(dict((address(a).lower(), a) for a in m['recipients']).values())
    if m['report_id'].startswith('delivery-test-') and [a.lower() for a in m['recipients']] != ['stolas_in@cyberlink.com']:
        raise DeliveryError('Test mail is restricted to Stolas_In@cyberlink.com only')
    if not isinstance(m['subject'], str) or not m['subject'].strip() or any(c in m['subject'] for c in '\r\n'):
        raise DeliveryError('Invalid subject')
    if not isinstance(m['body'], str) or not m['body'].strip():
        raise DeliveryError('Nonempty body required')
    if not isinstance(m['attachments'], list):
        raise DeliveryError('attachments array required')
    if not m['attachments'] and m.get('no_attachment_reason') != 'no_pr_activity':
        raise DeliveryError('No attachment must explicitly declare no_pr_activity')
    names = set()
    for a in m['attachments']:
        if not Path(a['path']).is_absolute():
            raise DeliveryError('Absolute attachment path required')
        actual = attachment(a['path'])
        if a['filename'] != actual['filename'] or a['filename'].lower() in names:
            raise DeliveryError('Invalid or duplicate attachment filename')
        names.add(a['filename'].lower())
        if any(a[f] != actual[f] for f in ('sha256', 'size', 'mime_type')):
            raise DeliveryError('Attachment content does not match manifest')
    return m


def payload_hash(m):
    value = {k: m[k] for k in ('report_id', 'report_date', 'sender_account', 'recipients', 'subject', 'body', 'attachments')}
    value['attachments'] = [{k: a[k] for k in ('filename', 'mime_type', 'size', 'sha256')} for a in m['attachments']]
    value['sender_account'] = value['sender_account'].lower()
    value['recipients'] = sorted(a.lower() for a in value['recipients'])
    if 'project_metadata' in m:
        value['project_metadata'] = m['project_metadata']
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class Store:
    def __init__(self, root=ROOT / 'state'):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, job_id TEXT, at TEXT, kind TEXT, data TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS mailbox (slot INTEGER PRIMARY KEY CHECK(slot=1), job_id TEXT, token TEXT)')

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.root / 'delivery.sqlite3', timeout=15)
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _get(self, db, job_id):
        row = db.execute('SELECT data FROM jobs WHERE id=?', (job_id,)).fetchone()
        if not row:
            raise DeliveryError('Unknown job')
        return json.loads(row[0])

    def _save(self, db, job, kind, evidence):
        job['updated_at'] = now()
        db.execute('INSERT OR REPLACE INTO jobs VALUES (?,?)', (job['id'], json.dumps(job)))
        db.execute('INSERT INTO events(job_id,at,kind,data) VALUES (?,?,?,?)',
            (job['id'], now(), kind, json.dumps(evidence)))

    def get(self, job_id):
        with self.transaction() as db:
            return self._get(db, job_id)

    def list(self):
        with self.transaction() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT data FROM jobs ORDER BY rowid')]

    def submit(self, manifest):
        # Legacy sent records can skip missing historical files safely.
        job_id = key(manifest['report_id'], manifest['report_date'], manifest['sender_account'])
        with self.transaction() as db:
            row = db.execute('SELECT data FROM jobs WHERE id=?', (job_id,)).fetchone()
            old = json.loads(row[0]) if row else None
            if old and old.get('legacy'):
                return old
            m = validate(manifest)
            digest = payload_hash(m)
            if old:
                if old['payload_sha256'] != digest:
                    raise DeliveryError('Same report/date already submitted with different content; no automatic resend')
                return old
            folder = self.root / 'spool' / job_id
            folder.mkdir(parents=True, exist_ok=True)
            for a in m['attachments']:
                raw = Path(a['path']).read_bytes()
                if hashlib.sha256(raw).hexdigest() != a['sha256']:
                    raise DeliveryError('Attachment changed during submission')
                target = folder / a['filename']
                target.write_bytes(raw)
                a['path'] = str(target)
            write_json(folder / 'manifest.json', m)
            job = dict(id=job_id, status='queued', email_sent=False, manifest=m,
                payload_sha256=digest, created_at=now(), escalations=0)
            self._save(db, job, 'submitted', {'payload_sha256': digest})
            return job

    def verify(self, job_id):
        job = self.get(job_id)
        validate(job['manifest'])
        if payload_hash(job['manifest']) != job['payload_sha256']:
            raise DeliveryError('Spool manifest changed')
        return job

    def claim(self, owner):
        if not owner or not str(owner).strip():
            raise DeliveryError('Owner chat/worker identifier required')
        with self.transaction() as db:
            lease = db.execute('SELECT job_id FROM mailbox WHERE slot=1').fetchone()
            if lease:
                return dict(action='busy', active=self._get(db, lease[0]))
            jobs = [json.loads(r[0]) for r in db.execute('SELECT data FROM jobs ORDER BY rowid')]
            for job in jobs:
                if job['status'] == 'queued':
                    validate(job['manifest'])
                    token = uuid.uuid4().hex
                    job.update(status='composing', owner=owner, token=token, claimed_at=now())
                    db.execute('INSERT INTO mailbox VALUES (1,?,?)', (job['id'], token))
                    self._save(db, job, 'claimed', {'owner': owner})
                    return dict(action='claimed', **job)
            return dict(action='empty')

    def _proof(self, job, evidence):
        m = job['manifest']
        if not isinstance(evidence, dict) or evidence.get('kind') != 'sent_items' or not evidence.get('observation'):
            raise DeliveryError('Matching Sent Items evidence required')
        if evidence.get('sender_account', '').lower() != m['sender_account'].lower():
            raise DeliveryError('Sender evidence mismatch')
        if evidence.get('subject') != m['subject']:
            raise DeliveryError('Subject evidence mismatch')
        if sorted(a.lower() for a in evidence.get('recipients', [])) != sorted(a.lower() for a in m['recipients']):
            raise DeliveryError('Recipient evidence mismatch')
        if sorted(evidence.get('attachment_names', [])) != sorted(a['filename'] for a in m['attachments']):
            raise DeliveryError('Attachment evidence mismatch')
        stamp = dt.datetime.fromisoformat(evidence.get('sent_at', ''))
        # Outlook displays minute precision; tolerate rounding, not an old queue entry.
        requested = dt.datetime.fromisoformat(job['send_requested_at'])
        if stamp.tzinfo is None or stamp < requested - dt.timedelta(minutes=2) or stamp > dt.datetime.fromisoformat(now()) + dt.timedelta(minutes=2):
            raise DeliveryError('Sent time does not match this attempt')

    def _owned(self, db, job, token):
        lease = db.execute('SELECT job_id,token FROM mailbox WHERE slot=1').fetchone()
        if not token or lease != (job['id'], token) or job.get('token') != token:
            raise DeliveryError('Mailbox ownership token mismatch')

    def _release(self, db, job):
        db.execute('DELETE FROM mailbox WHERE job_id=?', (job['id'],))
        job.pop('token', None)
        job.pop('recovery', None)

    def reserve(self, job_id, owner):
        """Hold the same global mailbox lock during recovery-only UI operations."""
        if not owner or not str(owner).strip():
            raise DeliveryError('Recovery owner required')
        with self.transaction() as db:
            job = self._get(db, job_id)
            if db.execute('SELECT job_id FROM mailbox WHERE slot=1').fetchone():
                raise DeliveryError('Mailbox busy; do not inspect recovery UI concurrently')
            if job['status'] not in ('send_unknown', 'failed_before_send', 'blocked'):
                raise DeliveryError('Recovery reservation requires inactive unresolved job')
            token = uuid.uuid4().hex
            job.update(owner=owner, token=token, recovery=True)
            db.execute('INSERT INTO mailbox VALUES (1,?,?)', (job_id, token))
            self._save(db, job, 'recovery_reserved', {'owner':owner})
            return job

    def release(self, job_id, token, evidence):
        with self.transaction() as db:
            job = self._get(db, job_id)
            self._owned(db, job, token)
            if not job.get('recovery') or not evidence:
                raise DeliveryError('Release applies only to observed recovery sessions')
            self._release(db, job)
            self._save(db, job, 'recovery_released', {'observation':evidence})
            return job

    def transition(self, job_id, token, phase, evidence):
        allowed = {'composing': {'attached', 'failed_before_send', 'blocked'},
            'attached': {'send_requested', 'failed_before_send', 'blocked'},
            'send_requested': {'sent', 'send_unknown'}}
        with self.transaction() as db:
            job = self._get(db, job_id)
            self._owned(db, job, token)
            if job.get('recovery'):
                raise DeliveryError('Recovery reservation cannot send or compose')
            if phase not in allowed.get(job['status'], set()):
                raise DeliveryError('Invalid state transition')
            if not isinstance(evidence, dict) or not evidence.get('observation'):
                raise DeliveryError('Observed evidence required')
            if phase in ('attached', 'send_requested'):
                validate(job['manifest'])
            if phase == 'sent':
                self._proof(job, evidence)
            job.update(status=phase, email_sent=phase == 'sent', evidence=evidence)
            if phase == 'send_requested':
                job['send_requested_at'] = now()
            if phase == 'sent':
                job['sent_at'] = evidence['sent_at']
            if phase in ('sent', 'send_unknown', 'failed_before_send', 'blocked'):
                self._release(db, job)
            self._save(db, job, phase, evidence)
            return job

    def recover(self, job_id, owner_stopped, evidence, expected_token=None):
        if not owner_stopped or not evidence:
            raise DeliveryError('Verify original worker stopped before recovery')
        with self.transaction() as db:
            job = self._get(db, job_id)
            if not expected_token or job.get('token') != expected_token:
                raise DeliveryError('Owner changed since inspection; stale recovery rejected')
            self._owned(db, job, expected_token)
            if job['status'] not in ('composing', 'attached', 'send_requested') and not job.get('recovery'):
                raise DeliveryError('Only interrupted active jobs need recovery')
            if not job.get('recovery'):
                job['status'] = 'send_unknown' if job['status'] == 'send_requested' else 'failed_before_send'
            self._release(db, job)
            self._save(db, job, 'recovered', {'owner_stopped': True, 'observation': evidence})
            return job

    def requeue(self, job_id, evidence, token=None):
        with self.transaction() as db:
            job = self._get(db, job_id)
            self._owned(db, job, token)
            if not job.get('recovery'):
                raise DeliveryError('Recovery reservation required for draft cleanup')
            if job['status'] not in ('failed_before_send', 'blocked') or not evidence or job.get('legacy'):
                raise DeliveryError('Only a verified unsent job may be requeued')
            validate(job['manifest'])
            job['status'] = 'queued'
            self._release(db, job)
            self._save(db, job, 'requeued', {'observation': evidence})
            return job

    def reconcile(self, job_id, evidence, token=None):
        with self.transaction() as db:
            job = self._get(db, job_id)
            self._owned(db, job, token)
            if not job.get('recovery'):
                raise DeliveryError('Recovery reservation required for Sent Items lookup')
            if job['status'] != 'send_unknown' or job.get('legacy'):
                raise DeliveryError('Reconcile only unknown current-format jobs')
            self._proof(job, evidence)
            job.update(status='sent', email_sent=True, evidence=evidence, sent_at=evidence['sent_at'])
            self._release(db, job)
            self._save(db, job, 'reconciled_sent', evidence)
            return job

    def escalate(self, job_id, code, observation):
        delivery_codes = {'browser_connection_failed', 'capability_unavailable', 'compose_error',
            'chooser_timeout', 'upload_error', 'detached_node', 'verification_error',
            'login_required', 'tool_approval_required', 'policy_denied'}
        with self.transaction() as db:
            job = self._get(db, job_id)
            if code not in delivery_codes or not observation or job.get('escalations', 0) >= 1 or job['status'] == 'sent':
                raise DeliveryError('Only one delivery-only Sol escalation per job')
            job['escalations'] = 1
            job['diagnosis'] = dict(code=code, observation=observation, model='gpt-6.1-sol')
            self._save(db, job, 'escalated', job['diagnosis'])
            return job

    def import_legacy(self, report_id, day, sender, status, evidence):
        job_id = key(report_id, day, sender)
        if status not in ('sent', 'sending', 'send_unknown', 'preparing'):
            raise DeliveryError('Unsupported legacy status')
        with self.transaction() as db:
            row = db.execute('SELECT data FROM jobs WHERE id=?', (job_id,)).fetchone()
            if row:
                return json.loads(row[0])
            job = dict(id=job_id, status='sent' if status == 'sent' else 'send_unknown',
                email_sent=status == 'sent', legacy=True, report_id=report_id, report_date=day,
                sender_account=sender, evidence=evidence, created_at=now(), escalations=0)
            self._save(db, job, 'legacy_import', evidence)
            return job


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT / 'state')
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('submit'); p.add_argument('manifest', type=Path)
    sub.add_parser('list')
    p = sub.add_parser('claim'); p.add_argument('--owner', required=True)
    for name in ('get', 'verify', 'transition', 'recover', 'reserve', 'release', 'requeue', 'reconcile', 'escalate'):
        p = sub.add_parser(name); p.add_argument('id')
        if name == 'transition':
            p.add_argument('--phase', required=True)
        if name in ('transition', 'release', 'requeue', 'reconcile'): p.add_argument('--token', required=True)
        if name == 'reserve': p.add_argument('--owner', required=True)
        if name in ('transition', 'reconcile'):
            p.add_argument('--evidence-file', type=Path, required=True)
        if name in ('recover', 'release', 'requeue', 'escalate'):
            p.add_argument('--evidence', required=True)
        if name == 'recover':
            p.add_argument('--owner-stopped', action='store_true')
            p.add_argument('--expected-token', required=True)
        if name == 'escalate': p.add_argument('--code', required=True)
    p = sub.add_parser('import-legacy')
    p.add_argument('--report-id', required=True); p.add_argument('--date', required=True)
    p.add_argument('--sender', required=True); p.add_argument('--status', required=True)
    p.add_argument('--source', required=True)
    args = parser.parse_args()
    store = Store(args.root)
    if args.action == 'submit': result = store.submit(read_json(args.manifest))
    elif args.action == 'list': result = store.list()
    elif args.action == 'claim': result = store.claim(args.owner)
    elif args.action in ('get', 'verify'): result = getattr(store, args.action)(args.id)
    elif args.action == 'transition': result = store.transition(args.id, args.token, args.phase, read_json(args.evidence_file))
    elif args.action == 'recover': result = store.recover(args.id, args.owner_stopped, args.evidence, args.expected_token)
    elif args.action == 'reserve': result = store.reserve(args.id, args.owner)
    elif args.action == 'release': result = store.release(args.id, args.token, args.evidence)
    elif args.action == 'requeue': result = store.requeue(args.id, args.evidence, args.token)
    elif args.action == 'reconcile': result = store.reconcile(args.id, read_json(args.evidence_file), args.token)
    elif args.action == 'escalate': result = store.escalate(args.id, args.code, args.evidence)
    else: result = store.import_legacy(args.report_id, args.date, args.sender, args.status, {'source':args.source})
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError, sqlite3.Error) as error:
        print(json.dumps({'error': str(error), 'type': type(error).__name__}), file=sys.stderr)
        sys.exit(1)
