"""HTML → Markdown. Fixtures only: no network and no provider involved."""

from __future__ import annotations

from relay.util.markdown import clean, html_to_markdown


def test_code_fence_keeps_its_language() -> None:
    html = '<pre><code class="language-python">def f():\n    return 1</code></pre>'

    assert html_to_markdown(html) == "```python\ndef f():\n    return 1\n```"


def test_table_survives_as_a_table() -> None:
    html = (
        "<table><thead><tr><th>A</th><th>B</th></tr></thead>"
        "<tbody><tr><td>1</td><td>2</td></tr></tbody></table>"
    )

    markdown = html_to_markdown(html)

    assert "| A | B |" in markdown
    assert "| 1 | 2 |" in markdown


def test_provider_buttons_are_removed() -> None:
    html = (
        "<div><p>Answer.</p>"
        '<button aria-label="Copy">Copy</button>'
        '<button aria-label="Regenerate">Regenerate</button>'
        '<svg><path d="M0 0"/></svg></div>'
    )

    markdown = html_to_markdown(html)

    assert "Answer." in markdown
    assert "Copy" not in markdown
    assert "Regenerate" not in markdown


def test_heading_style_is_atx() -> None:
    assert html_to_markdown("<h2>Title</h2>") == "## Title"


def test_inline_emphasis_and_lists() -> None:
    markdown = html_to_markdown("<p>Use <strong>relay</strong>.</p><ul><li>one</li></ul>")

    assert "**relay**" in markdown
    assert "- one" in markdown


def test_citation_anchors_are_unwrapped() -> None:
    markdown = html_to_markdown('<p>Claim<a href="#cite-1">1</a></p>')

    assert markdown == "Claim1"
    assert "](" not in markdown


def test_empty_input_is_empty_output() -> None:
    assert html_to_markdown("") == ""
    assert html_to_markdown("   ") == ""


def test_clean_collapses_blank_runs_and_trailing_space() -> None:
    assert clean("a   \n\n\n\nb\n") == "a\n\nb"


def test_clean_strips_zero_width_characters() -> None:
    assert clean("a\u200bb") == "ab"


def test_script_and_style_content_never_leaks() -> None:
    markdown = html_to_markdown("<style>.x{}</style><script>alert(1)</script><p>ok</p>")

    assert markdown == "ok"
