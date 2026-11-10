import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from delivery import Store, DeliveryError
from make_test import make_manifest
from migrate_legacy import migrate


class OperationsTests(unittest.TestCase):
    def test_test_mail_is_single_self_recipient_and_separate_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            pdf = Path(folder) / 'test.pdf'
            pdf.write_bytes(b'%PDF-1.7\n'+b'x'*1200)
            m = make_manifest([pdf])
            self.assertEqual(m['recipients'], ['Stolas_In@cyberlink.com'])
            self.assertTrue(m['report_id'].startswith('delivery-test-'))
            m['recipients'] = ['other@example.com']
            with self.assertRaises(DeliveryError): Store(Path(folder)/'store').submit(m)

    def test_migration_is_idempotent_and_preserves_unknown(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            nightly = root/'nightly'; nightly.mkdir()
            wer = root/'wer'; (wer/'state').mkdir(parents=True)
            (nightly/'run-status.json').write_text(json.dumps({'date':'2026-11-09','email_sent':True}))
            (wer/'state/2026-11-10.json').write_text(json.dumps({'date':'2026-11-10','status':'sending'}))
            store = Store(root/'store')
            migrate(store, nightly, wer, 'Stolas_In@cyberlink.com')
            migrate(store, nightly, wer, 'Stolas_In@cyberlink.com')
            self.assertEqual(sorted(j['status'] for j in store.list()), ['send_unknown','sent'])
            self.assertEqual(store.claim('worker')['action'], 'empty')


if __name__ == '__main__': unittest.main()
