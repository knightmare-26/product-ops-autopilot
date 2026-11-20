"""Slack slash command for the Ask Product bot:  /ask How do sales returns work?

Setup (about 10 minutes, see README):
  1. Create a Slack app, add a slash command /ask whose Request URL is  https://<your-host>/slack/ask
  2. Set SLACK_SIGNING_SECRET (Slack app > Basic Information) and run:  python -m autopilot serve --port 3000
  3. For a local demo, expose the port with a tunnel such as ngrok or cloudflared.

Every request is checked against Slack's signature, so only your workspace can call it.
Slack expects a reply within 3 seconds: retrieval answers are instant and go back directly; Claude answers
are acknowledged straight away and posted to the channel when ready.
"""
import hashlib
import hmac
import json
import os
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import ask


def verify(secret, timestamp, body, signature, now=None):
    """Slack signs each request with HMAC-SHA256 of 'v0:<timestamp>:<body>'; reject anything older than 5 minutes."""
    if not (secret and timestamp and signature):
        return False
    try:
        if abs((now or time.time()) - int(timestamp)) > 300:
            return False
    except ValueError:
        return False
    expected = "v0=" + hmac.new(secret.encode(), f"v0:{timestamp}:{body}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def to_slack(result):
    lines = [result["answer"]]
    if result["cited"]:
        lines.append("\n*Sources*")
        lines += [f"{n}. <{h['url']}|{h['title']}>" if h["url"].startswith("http") else f"{n}. {h['title']}"
                  for n, h in enumerate(result["cited"], 1)]
    if not result["answered"]:
        lines.append("_Logged as a knowledge gap for this week's report._")
    return {"response_type": "in_channel", "text": f"*Q: {result['question']}*\n" + "\n".join(lines)}


def _post(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"content-type": "application/json"})
    urllib.request.urlopen(req, timeout=20).close()


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/slack/ask":
            return self._reply(404, {"text": "not found"})
        body = self.rfile.read(int(self.headers.get("content-length", 0))).decode()
        if not verify(os.environ.get("SLACK_SIGNING_SECRET"), self.headers.get("X-Slack-Request-Timestamp"),
                      body, self.headers.get("X-Slack-Signature")):
            return self._reply(401, {"text": "bad signature"})
        form = urllib.parse.parse_qs(body)
        question = (form.get("text") or [""])[0].strip()
        user = (form.get("user_name") or form.get("user_id") or [None])[0]
        if not question:
            return self._reply(200, {"response_type": "ephemeral", "text": "Usage: /ask How do sales returns work?"})
        if not ask.claude_available():
            return self._reply(200, to_slack(ask.ask(question, asker=user)))
        response_url = form["response_url"][0]
        threading.Thread(target=lambda: _post(response_url, to_slack(ask.ask(question, asker=user))),
                         daemon=True).start()
        self._reply(200, {"response_type": "ephemeral", "text": f"Looking up: {question}"})

    def _reply(self, code, payload):
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def run(port=3000):
    if not os.environ.get("SLACK_SIGNING_SECRET"):
        raise SystemExit("Set SLACK_SIGNING_SECRET first (Slack app > Basic Information > Signing Secret).")
    ask.index()  # build the search index once, before the first request
    print(f"Ask Product bot listening on http://0.0.0.0:{port}/slack/ask")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
