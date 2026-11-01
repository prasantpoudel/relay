"""HTML → Markdown, with structure intact.

Why not `innerText`: it flattens code fences and tables, which is most of what a coding
conversation actually contains. The assistant turn is scraped as HTML, cleaned of the buttons the
provider embeds in it, then converted.

Only this module knows how to convert. It has no provider knowledge: each driver hands it the HTML
of its last assistant turn and gets Markdown back.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag
from markdownify import markdownify

# Elements that are chrome, not content. Removing them here is cheaper and more predictable than
# post-processing the Markdown, where "Copy" is indistinguishable from prose.
_DROP_TAGS = (
    "button",
    "svg",
    "script",
    "style",
    "noscript",
    "textarea",
    "input",
    "select",
    "template",
)

# aria-label / data-testid substrings that identify provider chrome inside an assistant turn.
_DROP_LABEL_HINTS = (
    "copy",
    "regenerate",
    "retry",
    "share",
    "read aloud",
    "listen",
    "edit",
    "thumbs",
    "good response",
    "bad response",
    "more actions",
    "sources",
    "citation",
)

_BLANK_RUN = re.compile(r"\n{3,}")
_TRAILING_SPACE = re.compile(r"[ \t]+$", re.MULTILINE)
_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff"), None)


def _is_chrome(tag: Tag) -> bool:
    for attr in ("aria-label", "data-testid", "title"):
        value = tag.get(attr)
        if not isinstance(value, str):
            continue
        lowered = value.lower()
        if any(hint in lowered for hint in _DROP_LABEL_HINTS):
            return True
    return False


def _code_language(el: Tag) -> str:
    """Read the fence language off a <pre><code class="language-python"> element."""
    code = el.find("code") or el
    classes: list[str] | str = code.get("class") or []
    if isinstance(classes, str):
        classes = classes.split()
    for name in classes:
        for prefix in ("language-", "lang-", "highlight-source-"):
            if name.startswith(prefix):
                return name[len(prefix) :]
    return ""


def _prepare(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all(_DROP_TAGS):
        tag.decompose()

    # Two passes: the inner sweep can orphan an outer element, so re-read the tree each time.
    for tag in list(soup.find_all(_is_chrome)):
        tag.decompose()

    # Providers mark up inline citations as links to their own footnotes; they add noise and the
    # URLs are session-scoped. Unwrap the anchor, keep the text.
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href", ""))
        if href.startswith("#") or "/c/" in href or "citation" in href:
            anchor.unwrap()

    return soup


def html_to_markdown(html: str) -> str:
    """Convert one assistant turn from HTML to Markdown.

    Returns an empty string for empty or tag-only input rather than raising: a provider returning
    an empty turn is a content problem, not a parser crash.
    """
    if not html or not html.strip():
        return ""

    soup = _prepare(html)
    converted: str = markdownify(
        str(soup),
        heading_style="ATX",
        bullets="-",
        code_language_callback=_code_language,
        strip=["img"],
    )
    return clean(converted)


def clean(markdown: str) -> str:
    """Normalise whitespace without touching content.

    Collapses runs of blank lines, strips trailing spaces, and drops the zero-width characters
    providers inject around citation markers.
    """
    text = markdown.translate(_ZERO_WIDTH)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _TRAILING_SPACE.sub("", text)
    text = _BLANK_RUN.sub("\n\n", text)
    return text.strip()


__all__ = ["clean", "html_to_markdown"]
