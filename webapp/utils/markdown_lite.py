"""
A small Markdown-to-HTML converter, enough for VALIDATION.md: headings, paragraphs, bullet lists, tables, fenced code
blocks, links, **bold**, *italics* and `code`. Everything else is shown as plain text, and all text is escaped.
It has no dependencies, so the static site builder can load it without the Flask app.
"""

import html
import re

_LINK = re.compile(r"\[([^\]]+)\]\((https?://(?:[^()\s]|\([^()\s]*\))+|[A-Za-z0-9_./#-]+)\)")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC = re.compile(r"(?<![\w*])\*([^*\s][^*]*?)\*(?![\w*])")
_CODE = re.compile(r"`([^`]+)`")
_TABLE_SEPARATOR = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?$")


def inline(text):
    """Escape the text and turn the inline marks into HTML."""
    codes = []

    def keep(match):
        codes.append(f"<code>{html.escape(match.group(1), quote=False)}</code>")
        return f"\0{len(codes) - 1}\0"

    text = html.escape(_CODE.sub(keep, text), quote=False)
    text = _LINK.sub(lambda m: f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>', text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)
    return re.sub(r"\0(\d+)\0", lambda m: codes[int(m.group(1))], text)


def _cells(line):
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _table(lines):
    header, body = _cells(lines[0]), [_cells(line) for line in lines[2:]]
    rows = ["<thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in header) + "</tr></thead>", "<tbody>"]
    rows += ["<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>" for row in body]
    rows.append("</tbody>")
    return '<div class="table-responsive"><table class="table table-sm table-bordered align-middle">' + "".join(rows) + "</table></div>"


def render(markdown):
    """The HTML for a Markdown text (as a string of blocks, without <html> or <body>)."""
    lines = markdown.replace("\r\n", "\n").split("\n")
    blocks, i = [], 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
        elif line.startswith("```"):
            code = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            blocks.append("<pre><code>" + html.escape("\n".join(code), quote=False) + "</code></pre>")
        elif re.match(r"#{1,4} ", line):
            level = len(line) - len(line.lstrip("#"))
            blocks.append(f"<h{level}>{inline(line[level:].strip())}</h{level}>")
            i += 1
        elif line.startswith("|") and i + 1 < len(lines) and _TABLE_SEPARATOR.match(lines[i + 1].strip()):
            table = [line, lines[i + 1]]
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                table.append(lines[i])
                i += 1
            blocks.append(_table(table))
        elif re.match(r"[-*] ", line):
            items = []
            while i < len(lines) and (re.match(r"[-*] ", lines[i]) or (items and lines[i].startswith("  ") and lines[i].strip())):
                if re.match(r"[-*] ", lines[i]):
                    items.append(lines[i][2:].strip())
                else:
                    items[-1] += " " + lines[i].strip()
                i += 1
            blocks.append("<ul>" + "".join(f"<li>{inline(item)}</li>" for item in items) + "</ul>")
        else:
            paragraph = [line.strip()]                       # always takes this line, so the loop moves on
            i += 1
            while i < len(lines) and lines[i].strip() and not re.match(r"(#{1,4} |```|[-*] )", lines[i]) and not lines[i].startswith("|"):
                paragraph.append(lines[i].strip())
                i += 1
            blocks.append(f"<p>{inline(' '.join(paragraph))}</p>")
    return "\n".join(blocks)
