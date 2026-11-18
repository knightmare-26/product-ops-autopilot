"""Send messages to Slack via an incoming webhook, or print them when no webhook is set."""
import json
import os
import urllib.request


def send(text, webhook=None, dry_run=False):
    webhook = webhook or os.environ.get("SLACK_WEBHOOK_URL")
    if dry_run or not webhook:
        print("\n--- Slack message (dry run) ---\n" + text + "\n-------------------------------")
        return False
    req = urllib.request.Request(webhook, data=json.dumps({"text": text}).encode(),
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status == 200
