from __future__ import annotations

import re
from pathlib import Path

_LOCAL_EXAMPLE = "examples/"


def readme_path() -> Path:
    root = Path(__file__).resolve().parents[1]
    return root / "README.md"


def man_page(markdown: str | None = None) -> str:
    text = readme_path().read_text() if markdown is None else markdown
    text = re.sub(
        r"<!--\s*github-only\s*-->.*?<!--\s*/github-only\s*-->\s*",
        "",
        text,
        flags=re.S,
    )
    lines = [
        '.TH MAKE-LABELS 1 "2026-09-30" "label-maker 0.1.0" "User Commands"',
        ".SH NAME",
        r"make-labels \- print text and pictures on a sheet of stickers",
        ".SH DESCRIPTION",
    ]
    for kind, value in _blocks(text):
        if kind == "title":
            continue
        if kind == "section":
            lines.append(f".SH {value.upper()}")
            continue
        if kind == "switch":
            lines.append(".TP")
            lines.append(_flags(value))
            continue
        if kind == "table":
            examples: list[tuple[str, str]] = []
            for row in value:
                if _rule(row) or not any(cell.startswith("-") or "`-" in cell for cell in row):
                    continue
                lines.append(".TP")
                lines.append(_flags(row[0].replace("`", "")))
                lines.extend(_broken(_switch_text(row)))
                if len(row) > 3 and row[3].strip():
                    examples.append((row[0], row[3]))
            lines.append("")
            if examples:
                lines.append(".SH EXAMPLES")
                for flags, example in examples:
                    lines.append(".TP")
                    lines.append(_flags(flags.replace("`", "")))
                    lines.extend(_example_block(example))
                lines.append("")
            continue
        if kind == "code":
            lines.append(".nf")
            lines.extend(_code_line(line) for line in value)
            lines.append(".fi")
            lines.append("")
            continue
        lines.extend(_broken_lines(value))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _blocks(markdown: str):
    paragraph: list[str] = []
    code: list[str] | None = None
    rows = markdown.splitlines()
    index = 0

    def flush():
        if paragraph:
            yield "paragraph", list(paragraph)
            paragraph.clear()

    while index < len(rows):
        line = rows[index].rstrip()
        index += 1
        if code is not None:
            if line.startswith("```"):
                yield "code", code
                code = None
            else:
                code.append(line)
            continue
        if line.startswith("```"):
            yield from flush()
            code = []
            continue
        if line.lstrip().startswith("|"):
            yield from flush()
            table = [_cells(line)]
            while index < len(rows) and rows[index].lstrip().startswith("|"):
                table.append(_cells(rows[index].rstrip()))
                index += 1
            yield "table", table
            continue
        if not line.strip():
            yield from flush()
            continue
        if line.startswith("# "):
            yield from flush()
            yield "title", line[2:].strip()
            continue
        if line.startswith("### "):
            yield from flush()
            yield "switch", line[4:].strip()
            continue
        if line.startswith("## "):
            yield from flush()
            yield "section", line[3:].strip()
            continue
        paragraph.append(line.strip())
    if code is not None:
        yield "code", code
    yield from flush()


def _cells(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for char in body:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "|":
            cells.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    cells.append("".join(current).strip())
    return cells


def _rule(row: list[str]) -> bool:
    return bool(row) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in row)


def _broken_lines(sentences: list[str]) -> list[str]:
    sentences = [s for s in sentences if _LOCAL_EXAMPLE not in s]
    out: list[str] = []
    for index, sentence in enumerate(sentences):
        out.extend(_broken(sentence))
        if index + 1 < len(sentences):
            out.append(".br")
    return out


def _broken(text: str) -> list[str]:
    parts = re.split(r"\s*<br>\s*", text)
    out: list[str] = []
    for index, part in enumerate(parts):
        if not part.strip():
            continue
        out.extend(_wrap(_inline(part)))
        if index + 1 < len(parts):
            out.append(".br")
    return out


def _example_block(text: str) -> list[str]:
    parts = []
    for part in re.split(r"\s*<br>\s*", text):
        part = part.strip()
        if not part or _LOCAL_EXAMPLE in part:
            continue
        parts.append(_code_line(part.strip("`")))
    return [".nf", *parts, ".fi"]


def _switch_text(row: list[str]) -> str:
    if len(row) > 2:
        default, detail = row[1], row[2]
    else:
        default, detail = "", row[1] if len(row) > 1 else ""
    if default and default != "—":
        return f"Default: {default}.<br>{detail}"
    return detail


def _flags(heading: str) -> str:
    pieces = []
    for part in heading.split(", "):
        rendered = []
        for bit in part.split(" "):
            if bit.startswith("-"):
                rendered.append(r"\fB" + bit.replace("-", r"\-") + r"\fR")
            else:
                rendered.append(r"\fI" + bit + r"\fR")
        pieces.append(" ".join(rendered))
    return ", ".join(pieces)


def _inline(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)

    def code(match: re.Match[str]) -> str:
        return r"\fB" + _escape(match.group(1)) + r"\fR"

    text = re.sub(r"`([^`]+)`", code, text)
    if text.startswith("."):
        text = r"\&" + text
    return text


def _code_line(line: str) -> str:
    escaped = _escape(line)
    if escaped.startswith("."):
        return r"\&" + escaped
    return escaped


def _escape(text: str) -> str:
    return text.replace("\\", r"\e").replace("-", r"\-")


def _wrap(text: str, width: int = 64) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split(" "):
        trial = word if not current else f"{current} {word}"
        if current and len(trial.encode()) > width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines
