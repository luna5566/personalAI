import re
from io import StringIO

_WHITESPACE_RE = re.compile(r"[ \t\f\v]+")
_LINE_BREAK_RE = re.compile(r"\r\n?|\n")


def clean_text(text: str) -> str:
    output = StringIO()
    start = 0
    wrote_content = False
    pending_blank_line = False

    for match in _LINE_BREAK_RE.finditer(text):
        line = _WHITESPACE_RE.sub(" ", text[start : match.start()]).strip()
        wrote_content, pending_blank_line = _write_clean_line(
            output,
            line,
            wrote_content=wrote_content,
            pending_blank_line=pending_blank_line,
        )
        start = match.end()

    line = _WHITESPACE_RE.sub(" ", text[start:]).strip()
    _write_clean_line(
        output,
        line,
        wrote_content=wrote_content,
        pending_blank_line=pending_blank_line,
    )
    return output.getvalue()


def _write_clean_line(
    output: StringIO,
    line: str,
    *,
    wrote_content: bool,
    pending_blank_line: bool,
) -> tuple[bool, bool]:
    if not line:
        return wrote_content, wrote_content
    if wrote_content:
        output.write("\n\n" if pending_blank_line else "\n")
    output.write(line)
    return True, False
