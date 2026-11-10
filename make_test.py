"""Create an isolated self-only mail manifest. Does not submit or send it."""
import argparse
import datetime as dt
import json
from pathlib import Path
import uuid
from delivery import ROOT, TAIPEI, attachment, now, validate, write_json


def make_manifest(pdfs):
    identifier = uuid.uuid4().hex
    day = dt.datetime.now(TAIPEI).date().isoformat()
    return validate(dict(schema_version=1, report_id='delivery-test-'+identifier[:12],
        report_date=day, generation=identifier, generated_at=now(),
        sender_account='Stolas_In@cyberlink.com', recipients=['Stolas_In@cyberlink.com'],
        subject=f'[TEST] Report Delivery — {day} ({identifier[:8]})',
        body='共用報告寄送模組測試，僅寄給 Stolas In。\n\n附件為現有 PR／WER 報告，用來驗證 PDF 附加與寄件備份確認。\n本信不會寄給正式報告收件者。',
        attachments=[attachment(p) for p in pdfs]))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf', action='append', type=Path, required=True)
    parser.add_argument('--out', type=Path, default=ROOT/'test-output/test-manifest.json')
    args = parser.parse_args()
    manifest = make_manifest(args.pdf)
    write_json(args.out, manifest)
    print(json.dumps({'manifest': str(args.out.resolve()), 'recipients':manifest['recipients'], 'subject':manifest['subject']}))
