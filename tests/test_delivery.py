import copy
import hashlib
import json
import multiprocessing
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from delivery import Store, DeliveryError, now


def claim_worker(root, queue):
    try:
        queue.put(Store(Path(root)).claim('parallel')['action'])
    except DeliveryError:
        queue.put('busy')


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.pdf = self.root / 'report.pdf'
        self.pdf.write_bytes(b'%PDF-1.7\n' + b'x' * 1200)
        raw = self.pdf.read_bytes()
        self.manifest = dict(schema_version=1, report_id='nightly-pr-report',
            report_date='2026-11-09', generation='g1', generated_at='2026-11-10T08:00:00+08:00',
            sender_account='Stolas_In@cyberlink.com', recipients=['rd@example.com'],
            subject='PR Daily Report — 2026-11-09', body='Original body',
            attachments=[dict(path=str(self.pdf), filename='report.pdf', mime_type='application/pdf',
                size=len(raw), sha256=hashlib.sha256(raw).hexdigest())])
        self.store = Store(self.root / 'store')

    def tearDown(self):
        self.tmp.cleanup()

    def submit(self):
        return self.store.submit(self.manifest)

    def evidence(self):
        return dict(kind='sent_items', sender_account=self.manifest['sender_account'],
            subject=self.manifest['subject'], recipients=self.manifest['recipients'],
            attachment_names=['report.pdf'], sent_at=now(),
            observation='Opened matching message in Sent Items')

    def test_snapshot_survives_source_replacement(self):
        job = self.submit()
        self.pdf.write_bytes(b'changed')
        self.assertTrue(Path(job['manifest']['attachments'][0]['path']).read_bytes().startswith(b'%PDF'))
        self.store.verify(job['id'])

    def test_same_date_generation_does_not_allow_resend(self):
        a = self.submit()
        self.manifest['generation'] = 'g2'
        self.assertEqual(self.submit()['id'], a['id'])
        self.manifest['subject'] = 'Changed subject'
        with self.assertRaises(DeliveryError):
            self.submit()

    def test_invalid_contract_rejected(self):
        for field, value in [('recipients', []), ('recipients', ['a@b.com;hidden@c.com']),
                ('report_date', 'invalid'), ('subject', 'x\nBcc: hidden'), ('sender_account', '')]:
            m = copy.deepcopy(self.manifest)
            m[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(DeliveryError):
                self.store.submit(m)
        self.manifest['attachments'][0]['sha256'] = '0' * 64
        with self.assertRaises(DeliveryError):
            self.submit()

    def test_mailbox_excludes_other_report_and_rejects_wrong_token(self):
        a = self.submit()
        self.manifest['report_id'] = 'wer-daily-report'
        self.submit()
        claimed = self.store.claim('chat-1')
        self.assertEqual(claimed['id'], a['id'])
        self.assertEqual(self.store.claim('chat-2')['action'], 'busy')
        with self.assertRaises(DeliveryError):
            self.store.transition(a['id'], 'wrong-token', 'attached', {'observation':'chip'})

    def test_send_intent_requires_attached_and_immutable_files(self):
        self.submit()
        c = self.store.claim('chat')
        with self.assertRaises(DeliveryError):
            self.store.transition(c['id'], c['token'], 'send_requested', {})
        self.store.transition(c['id'], c['token'], 'attached', {'observation':'verified attachment chip'})
        Path(c['manifest']['attachments'][0]['path']).write_bytes(b'corrupted')
        with self.assertRaises(DeliveryError):
            self.store.transition(c['id'], c['token'], 'send_requested', {'observation':'verified all fields'})

    def test_unknown_outcome_requires_reconciliation_not_retry(self):
        self.submit()
        c = self.store.claim('chat')
        self.store.transition(c['id'], c['token'], 'attached', {'observation':'chip'})
        self.store.transition(c['id'], c['token'], 'send_requested', {'observation':'ready'})
        self.store.recover(c['id'], owner_stopped=True, evidence='Original worker stopped', expected_token=c['token'])
        self.assertEqual(self.store.get(c['id'])['status'], 'send_unknown')
        self.assertEqual(self.store.claim('other')['action'], 'empty')
        self.assertEqual(self.submit()['status'], 'send_unknown')
        with self.assertRaises(DeliveryError):
            self.store.requeue(c['id'], 'not found yet')
        bad = self.evidence()
        bad['recipients'] = ['wrong@example.com']
        with self.assertRaises(DeliveryError):
            self.store.reconcile(c['id'], bad)
        reservation = self.store.reserve(c['id'], 'recovery-worker')
        self.assertEqual(self.store.reconcile(c['id'], self.evidence(), reservation['token'])['status'], 'sent')

    def test_pre_send_crash_requires_owner_stopped_and_draft_disposition(self):
        self.submit()
        c = self.store.claim('chat')
        with self.assertRaises(DeliveryError):
            self.store.recover(c['id'], owner_stopped=False, evidence='timeout')
        self.store.recover(c['id'], owner_stopped=True, evidence='Worker stopped; draft preserved', expected_token=c['token'])
        self.assertEqual(self.store.get(c['id'])['status'], 'failed_before_send')
        reservation = self.store.reserve(c['id'], 'recovery-worker')
        self.store.requeue(c['id'], 'Verified unsent; owned draft discarded', reservation['token'])
        self.assertEqual(self.store.claim('new')['action'], 'claimed')

    def test_sent_requires_sent_items_match_and_stays_sent(self):
        self.submit()
        c = self.store.claim('chat')
        self.store.transition(c['id'], c['token'], 'attached', {'observation':'chip'})
        self.store.transition(c['id'], c['token'], 'send_requested', {'observation':'ready'})
        with self.assertRaises(DeliveryError):
            self.store.transition(c['id'], c['token'], 'sent', {'observation':'compose closed'})
        result = self.store.transition(c['id'], c['token'], 'sent', self.evidence())
        self.assertTrue(result['email_sent'])
        self.assertEqual(self.submit()['status'], 'sent')
        self.assertEqual(self.store.claim('other')['action'], 'empty')

    def test_two_processes_only_one_can_claim(self):
        self.submit()
        context = multiprocessing.get_context('spawn')
        queue = context.Queue()
        workers = [context.Process(target=claim_worker, args=(str(self.store.root), queue)) for _ in range(2)]
        for worker in workers: worker.start()
        for worker in workers:
            worker.join(20)
            self.assertEqual(worker.exitcode, 0)
        self.assertEqual(sorted([queue.get(timeout=2), queue.get(timeout=2)]), ['busy', 'claimed'])
        queue.close()

    def test_legacy_import_blocks_even_changed_payload(self):
        self.store.import_legacy('nightly-pr-report', '2026-11-09', self.manifest['sender_account'],
            'sent', {'source':'legacy run-status'})
        self.assertEqual(self.submit()['status'], 'sent')

    def test_failure_diagnostics_and_single_escalation_are_persistent(self):
        self.submit()
        c = self.store.claim('chat')
        first = self.store.escalate(c['id'], 'chooser_timeout', 'Properly armed filechooser timed out')
        self.assertEqual(first['escalations'], 1)
        with self.assertRaises(DeliveryError):
            self.store.escalate(c['id'], 'chooser_timeout', 'again')
        self.store.transition(c['id'], c['token'], 'blocked', {'code':'upload_error', 'observation':'Sol unable to recover'})
        self.assertEqual(self.store.get(c['id'])['status'], 'blocked')

    def test_recovery_ui_excludes_composition_and_requires_token(self):
        self.submit()
        c = self.store.claim('old')
        self.store.recover(c['id'], True, 'Old worker confirmed stopped', expected_token=c['token'])
        reservation = self.store.reserve(c['id'], 'recovery')
        self.manifest['report_id'] = 'wer-daily-report'
        self.submit()
        self.assertEqual(self.store.claim('other')['action'], 'busy')
        with self.assertRaises(DeliveryError):
            self.store.requeue(c['id'], 'draft discarded', 'incorrect')
        self.store.requeue(c['id'], 'draft discarded', reservation['token'])
        self.assertEqual(self.store.claim('other')['action'], 'claimed')

    def test_old_and_future_sent_items_are_rejected_against_send_intent(self):
        import datetime as dt
        self.submit()
        c = self.store.claim('worker')
        c['created_at'] = (dt.datetime.fromisoformat(now())-dt.timedelta(days=1)).isoformat()
        c['send_requested_at'] = now()
        e = self.evidence()
        e['sent_at'] = (dt.datetime.fromisoformat(now())-dt.timedelta(hours=12)).isoformat()
        with self.assertRaises(DeliveryError): self.store._proof(c, e)
        e['sent_at'] = (dt.datetime.fromisoformat(now())+dt.timedelta(days=1)).isoformat()
        with self.assertRaises(DeliveryError): self.store._proof(c, e)

    def test_stale_recovery_cannot_release_new_live_recovery_owner(self):
        self.submit()
        old = self.store.claim('crashed-worker')
        self.store.recover(old['id'], True, 'Verified old worker stopped', expected_token=old['token'])
        active = self.store.reserve(old['id'], 'new-live-worker')
        with self.assertRaises(DeliveryError):
            self.store.recover(old['id'], True, 'Delayed observation of old worker', expected_token=old['token'])
        self.assertEqual(self.store.claim('competitor')['action'], 'busy')
        self.store.release(old['id'], active['token'], 'Investigation ended; state left unresolved')


if __name__ == '__main__':
    unittest.main()
