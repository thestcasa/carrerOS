from __future__ import annotations

from app.browser.contracts import FieldKind, FormField, SyntheticForm


def standard_application_form(*, challenge: FieldKind | None = None) -> SyntheticForm:
    """Return a deterministic, network-free ATS fixture for tests and local dry runs."""
    fields = [
        FormField(field_id="first_name", label="First name", kind=FieldKind.TEXT, required=True),
        FormField(field_id="email", label="Email", kind=FieldKind.EMAIL, required=True),
        FormField(field_id="resume", label="Resume", kind=FieldKind.FILE, required=True),
    ]
    if challenge is not None:
        fields.append(FormField(field_id="challenge", label=challenge.value, kind=challenge))
    fields.append(
        FormField(field_id="final-submit", label="Submit application", kind=FieldKind.SUBMIT)
    )
    return SyntheticForm(
        form_id="standard-application",
        source_url="https://synthetic.invalid/apply/standard",
        fields=tuple(fields),
    )
