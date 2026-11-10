"""Import existing sent/uncertain dates without generating or sending reports."""
import argparse
import json
from pathlib import Path
from delivery import ROOT, Store, read_json


def migrate(store, nightly, wer, sender):
    results = []
    path = Path(nightly)/'run-status.json'
    if path.exists():
        old = read_json(path)
        if old.get('email_sent') is True:
            results.append(store.import_legacy('nightly-pr-report', old['date'], sender,
                'sent', {'source':str(path), 'original':old}))
    for path in sorted((Path(wer)/'state').glob('????-??-??.json')):
        old = read_json(path)
        if old.get('status') in ('sent','sending','send_unknown','preparing'):
            results.append(store.import_legacy('wer-daily-report', old['date'], sender,
                old['status'], {'source':str(path), 'original':old}))
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nightly', type=Path, default=ROOT.parent/'Nightly-PR-Report')
    parser.add_argument('--wer', type=Path, default=ROOT.parent/'WER-Daily-Report')
    args = parser.parse_args()
    sender = read_json(ROOT/'config.local.json')['sender_account']
    print(json.dumps(migrate(Store(), args.nightly, args.wer, sender), ensure_ascii=True))
