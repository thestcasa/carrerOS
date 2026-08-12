from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.domain.enums import DocumentKind
from app.materials.contracts import GeneratedDocument

_SPECIAL_CHARACTERS = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "$": r"\$",
    "&": r"\&",
    "#": r"\#",
    "_": r"\_",
    "%": r"\%",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def escape_latex(value: str) -> str:
    """Escape all LaTeX control characters; input can never become executable TeX."""

    return "".join(_SPECIAL_CHARACTERS.get(character, character) for character in value)


def _comment_value(value: str) -> str:
    """Keep untrusted template labels on one inert TeX comment line."""

    return value.replace("\r", " ").replace("\n", " ")


@dataclass(frozen=True, slots=True)
class LatexSource:
    content: bytes
    sha256: str
    template_id: str
    template_version: str


class DeterministicLatexSourceBuilder:
    """Build a fixed, network-free LaTeX document from reviewed semantic text."""

    compiler_version = "restricted_latex_v1"

    def build(
        self,
        document: GeneratedDocument,
        *,
        template_id: str,
        template_version: str,
    ) -> LatexSource:
        title = "Curriculum Vitae" if document.kind is DocumentKind.CV else "Cover Letter"
        rendered_lines: list[str] = []
        for line in document.content.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            if not line:
                rendered_lines.append(r"\vspace{0.55em}")
            elif line.startswith("- "):
                rendered_lines.append(
                    r"\noindent\hangindent=1.2em\hangafter=1\textbullet\ "
                    + escape_latex(line[2:])
                    + r"\par"
                )
            else:
                rendered_lines.append(r"\noindent " + escape_latex(line) + r"\par")
        source = (
            "\\documentclass[10pt,a4paper]{article}\n"
            "\\usepackage[T1]{fontenc}\n"
            "\\usepackage[utf8]{inputenc}\n"
            "\\usepackage[margin=1.7cm]{geometry}\n"
            "\\usepackage{lmodern}\n"
            "\\pagestyle{empty}\n"
            "\\setlength{\\parindent}{0pt}\n"
            "\\setlength{\\parskip}{0pt}\n"
            f"% CareerOS {escape_latex(title)} template "
            f"{escape_latex(_comment_value(template_id))}"
            f"@{escape_latex(_comment_value(template_version))}\n"
            "\\begin{document}\n"
            "\\small\n" + "\n".join(rendered_lines) + "\n\\end{document}\n"
        ).encode("utf-8")
        return LatexSource(
            content=source,
            sha256=hashlib.sha256(source).hexdigest(),
            template_id=template_id,
            template_version=template_version,
        )
