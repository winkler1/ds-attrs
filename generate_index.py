"""Generate a searchable HTML table of Datastar data attributes from JSON."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape as html_escape
import json
import re
from pathlib import Path
import sys
from typing import Any, Iterable, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DATA_BODY_RE = re.compile(r"^data\-(?P<name>[A-Za-z*][A-Za-z0-9\-*]*)(?P<rest>.*)$")
PLACEHOLDER_RE = re.compile(r"\$\{\d+:(.+?)\}")
PRO_FEATURES: tuple[str, ...] = (
    "data-custom-validity",
    "data-on-raf",
    "data-on-resize",
    "data-persist",
    "data-query-string",
    "data-replace-url",
    "data-scroll-into-view",
    "data-view-transition",
)


SOURCE_URL: str = (
    "https://raw.githubusercontent.com/starfederation/datastar/refs/heads/develop/tools/"
    "vscode-extension/src/data-attributes.json"
)
OUTPUT_FILENAME: str = "index.html"
USER_AGENT: str = "ds-attrs-html-generator/1.0 (+https://example.local)"
TIMEOUT_SECONDS: float = 15.0


@dataclass(frozen=True)
class Row:
    body: str
    description: str
    href: Optional[str]


def warn(msg: str) -> None:
    print(f"[warn] {msg}", file=sys.stderr)


def fetch_json(url: str, timeout: float = TIMEOUT_SECONDS) -> dict[str, Any]:
    """Fetch and parse JSON; raise RuntimeError/ValueError on failure."""
    req = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            payload = resp.read().decode(charset, errors="replace")
    except HTTPError as e:
        raise RuntimeError(f"HTTP error {e.code} while fetching JSON: {e.reason}") from e
    except URLError as e:
        raise RuntimeError(f"Network error while fetching JSON: {e.reason}") from e

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        raise ValueError(f"Malformed JSON: {e.msg}") from e

    if not isinstance(data, dict):
        raise ValueError("Unexpected JSON structure: expected an object at top-level")
    return data


def _first_ref_url(references: Any) -> Optional[str]:
    """Return first http(s) URL in references, if any."""
    if not isinstance(references, list):
        return None
    for ref in references:
        if isinstance(ref, dict):
            url = ref.get("url")
            if isinstance(url, str):
                url = url.strip()
                if url.lower().startswith(("http://", "https://")) and url:
                    return url
    return None


def _sort_key_body(text: str) -> str:
    m = DATA_BODY_RE.match(text)
    base = (m.group("name") + m.group("rest")) if m else text
    base = PLACEHOLDER_RE.sub(lambda m: m.group(1), base)
    return base.strip().lower()


def to_rows(data: dict[str, Any]) -> list[Row]:
    """Normalize entries to Row, skipping invalid ones, then sort by body."""
    rows: list[Row] = []
    for key, value in data.items():
        if not isinstance(value, dict):
            warn(f"Skipping '{key}': expected object, got {type(value).__name__}")
            continue
        body = value.get("body")
        desc = value.get("description")
        refs = value.get("references")
        if not isinstance(body, str) or not body.strip():
            warn(f"Skipping '{key}': missing or invalid 'body'")
            continue
        if not isinstance(desc, str) or not desc.strip():
            warn(f"Skipping '{key}': missing or invalid 'description'")
            continue
        b = body.strip()
        if b.startswith(PRO_FEATURES):
            continue
        href = _first_ref_url(refs)
        rows.append(Row(body=b, description=desc.strip(), href=href))
    rows.sort(key=lambda r: _sort_key_body(r.body))
    return rows


def anchor_wrap(inner_html: str, href: Optional[str]) -> str:
    if href:
        safe_href = html_escape(href, quote=True)
        return (
            f'<a class="link no-underline opacity-80 hover:opacity-100 hover:underline" '
            f'target="_blank" rel="noopener noreferrer" href="{safe_href}">{inner_html}</a>'
        )
    return inner_html


def _escape_and_style(seg: str) -> str:
    out: list[str] = []
    for ch in seg:
        if ch == "=":
            out.append('<span class="text-gray-600">=</span>')
        else:
            out.append(html_escape(ch))
    return "".join(out)


def _render_placeholders(s: str) -> str:
    out: list[str] = []
    last = 0
    for m in PLACEHOLDER_RE.finditer(s):
        out.append(_escape_and_style(s[last:m.start()]))
        var = html_escape(m.group(1))
        out.append(f'<span class="italic">{var}</span>')
        last = m.end()
    out.append(_escape_and_style(s[last:]))
    return "".join(out)


def format_body_html(body: str) -> str:
    m = DATA_BODY_RE.match(body)
    if not m:
        return _render_placeholders(body)
    name_html = f'<span class="font-medium">{html_escape(m.group("name"))}</span>'
    rest_html = _render_placeholders(m.group("rest"))
    return name_html + rest_html


def render_html(rows: Iterable[Row], generated_at: datetime) -> str:
    """Return full HTML document."""
    gen_str = generated_at.strftime("%Y-%m-%d %H:%M UTC")
    css_href = "https://cdn.jsdelivr.net/npm/daisyui@4.12.10/dist/full.min.css"

    body_rows = []
    for r in rows:
        body_inner = format_body_html(r.body)
        body_td = anchor_wrap(body_inner, r.href)
        desc_td = anchor_wrap(html_escape(r.description), r.href)
        body_rows.append(
            """
            <tr class="group transition-colors">
              <td class="align-top whitespace-pre-wrap py-1 px-2 group-hover:bg-gray-50">{body_td}</td>
              <td class="align-top py-1 px-2 group-hover:bg-gray-50">{desc_td}</td>
            </tr>
            """.format(
                body_td=body_td,
                desc_td=desc_td,
            )
        )

    rows_html = "\n".join(body_rows)

    return f"""
<!DOCTYPE html>
<html lang="en" data-theme="light">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Datastar RC6 Data Attributes</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="{css_href}" rel="stylesheet" />
    <style>
      tbody tr:hover td {{ background-color: rgba(0,0,0,0.04); transition: background-color .15s ease; }}
    </style>
  </head>
  <body>
    <div class="container mx-auto px-4 py-6">
 
      <div class="overflow-x-auto">
        <table class="table table-zebra text-lg">
          <tbody>
{rows_html}
          </tbody>
        </table>
      </div>

      <footer class="mt-8 text-sm text-gray-200">Generated on {html_escape(gen_str)}</footer>
    </div>
  </body>
</html>
"""


def write_file(path: Path, content: str) -> None:
    """Write UTF-8 file."""
    try:
        path.write_text(content, encoding="utf-8")
    except OSError as e:
        raise RuntimeError(f"Failed to write output file '{path}': {e.strerror}") from e


def main() -> int:
    """Program entry point."""
    try:
        data = fetch_json(SOURCE_URL, timeout=TIMEOUT_SECONDS)
        rows = to_rows(data)
        now = datetime.now(timezone.utc)
        html = render_html(rows, generated_at=now)
        out_path = Path.cwd() / OUTPUT_FILENAME
        write_file(out_path, html)
        print(f"Wrote {len(rows)} rows to {out_path}")
        return 0
    except (RuntimeError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
