from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit


def synthetic_ats_html(challenge: str, variant: str = "standard") -> bytes:
    challenge_markup = {
        "captcha": (
            '<div id="challenge" role="status" data-human-action="captcha">Complete CAPTCHA</div>'
        ),
        "otp": '<div id="challenge" role="status" data-human-action="otp">Enter OTP</div>',
        "none": '<div id="challenge" role="status" hidden>No challenge</div>',
    }[challenge]
    labels = (
        ("Given name", "Family name", "Email address")
        if variant == "changed-labels"
        else ("First name", "Last name", "Email")
    )
    optional_cover_letter = (
        '<label for="cover-letter">Cover letter (optional)</label>'
        '<input id="cover-letter" type="file" data-field-key="cover_letter">'
        if variant == "optional-cover-letter"
        else ""
    )
    novel_field = (
        '<label for="clearance">Unrecognized clearance declaration</label>'
        '<input id="clearance" data-field-key="clearance_declaration" required>'
        if variant == "novel-field"
        else ""
    )
    closed_marker = (
        '<div role="status" data-job-closed>This fictional opening is closed.</div>'
        if variant == "closed-job"
        else ""
    )
    first_step_end = (
        '<button type="button" data-next-step>Continue to documents</button></section>'
        '<section data-step="2" hidden>'
        if variant == "multi-step"
        else ""
    )
    first_step_start = '<section data-step="1">' if variant == "multi-step" else ""
    second_step_end = "</section>" if variant == "multi-step" else ""
    timeout_marker = "data-submit-timeout" if variant == "submit-timeout" else ""
    form = (
        f"""
  <form method="post">
    {first_step_start}
    <label for="first-name">{labels[0]}</label>
    <input id="first-name" data-field-key="first_name" required>
    <label for="last-name">{labels[1]}</label>
    <input id="last-name" data-field-key="last_name" required>
    <label for="email">{labels[2]}</label>
    <input id="email" type="email" data-field-key="email" required>
    {novel_field}
    {first_step_end}
    <label for="cv">CV</label>
    <input id="cv" type="file" data-field-key="cv" required>
    {optional_cover_letter}
    {challenge_markup}
    <button type="submit" data-final-submit {timeout_marker}>Submit application</button>
    {second_step_end}
  </form>
"""
        if variant != "closed-job"
        else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Synthetic ATS</title></head>
<body>
<main>
  <h1>Fictional application</h1>
  {closed_marker}
  {form}
</main>
<script>
if (localStorage.getItem('syntheticHumanActionCompleted') === 'true') {{
  const challenge = document.getElementById('challenge');
  if (challenge) challenge.hidden = true;
}}
const next = document.querySelector('[data-next-step]');
if (next) next.addEventListener('click', () => {{
  document.querySelector('[data-step="1"]').hidden = true;
  document.querySelector('[data-step="2"]').hidden = false;
}});
const form = document.querySelector('form');
if (form) form.addEventListener('change', () => {{
  fetch(window.location.href, {{method: 'POST', body: 'must-be-blocked'}}).catch(() => {{}});
  fetch('https://network-must-be-blocked.invalid/exfiltrate').catch(() => {{}});
}});
const timeoutSubmit = document.querySelector('[data-submit-timeout]');
if (timeoutSubmit) timeoutSubmit.addEventListener('click', (event) => {{
  event.preventDefault();
  document.body.dataset.timeoutAfterSubmit = 'simulated';
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
        variant = values.get("variant", ["standard"])
        if (
            parsed.path != "/application"
            or set(values) - {"challenge", "variant"}
            or len(challenge) != 1
            or len(variant) != 1
            or challenge[0] not in {"none", "captcha", "otp"}
            or variant[0]
            not in {
                "standard",
                "optional-cover-letter",
                "multi-step",
                "novel-field",
                "changed-labels",
                "closed-job",
                "submit-timeout",
                "duplicate-retry",
            }
        ):
            self.send_error(404)
            return
        content = synthetic_ats_html(challenge[0], variant[0])
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
