from __future__ import annotations

from cofer_u_pass.domain.models import Block


def _join_nonempty(parts: list[str], separator: str) -> str:
    return separator.join(part for part in parts if part)


def block_to_text(block: Block) -> str:
    """Derive plain text from the canonical block tree without duplicating content.

    Container nodes produced by the DOM canonicalizer may carry ``text`` as a
    convenience/fallback while also containing child nodes that represent the
    same rendered content. When children exist they are authoritative; the
    container's own ``text`` is used only when there are no usable children.
    """
    if block.type in {"text", "heading", "code", "link", "image"}:
        return block.text or ""

    child_text = [block_to_text(child) for child in block.children]

    if block.type == "document":
        return _join_nonempty(child_text, "\n\n")

    if block.type == "paragraph":
        # Paragraph children represent inline DOM order, including direct text
        # nodes, so concatenating them is faithful and avoids duplicating the
        # paragraph's fallback ``text`` value.
        rendered = _join_nonempty(child_text, "")
        return rendered or (block.text or "")

    if block.type == "list":
        return _join_nonempty(child_text, "\n")

    if block.type == "list_item":
        rendered = _join_nonempty([part.strip() for part in child_text], " ")
        return rendered or (block.text or "")

    if block.type == "blockquote":
        return _join_nonempty(child_text, "\n") or (block.text or "")

    if block.type == "thematic_break":
        return ""

    # Unknown/structural nodes should preserve their descendants. Their own
    # ``text`` is a fallback only, because the canonicalizer also emits direct
    # text nodes as children.
    rendered = _join_nonempty(child_text, "\n")
    return rendered or (block.text or "")


def block_to_markdown(block: Block) -> str:
    if block.type == "document":
        return "\n\n".join(filter(None, (block_to_markdown(c) for c in block.children)))
    if block.type == "heading":
        return f"{'#' * (block.level or 1)} {block.text or ''}".rstrip()
    if block.type == "paragraph":
        if block.children:
            return "".join(block_to_markdown(c) for c in block.children)
        return block.text or ""
    if block.type == "text":
        return block.text or ""
    if block.type == "code":
        lang = block.language or ""
        return f"```{lang}\n{block.text or ''}\n```"
    if block.type == "blockquote":
        content = "\n".join(block_to_markdown(c) for c in block.children) or (block.text or "")
        return "\n".join(f"> {line}" for line in content.splitlines())
    if block.type == "list":
        ordered = bool(block.attrs.get("ordered"))
        lines: list[str] = []
        for i, child in enumerate(block.children, start=1):
            content = block_to_markdown(child).strip()
            prefix = f"{i}. " if ordered else "- "
            lines.append(prefix + content.replace("\n", "\n  "))
        return "\n".join(lines)
    if block.type == "list_item":
        return " ".join(filter(None, (block_to_markdown(c).strip() for c in block.children))) or (block.text or "")
    if block.type == "link":
        return f"[{block.text or block.href or ''}]({block.href or ''})"
    if block.type == "image":
        return f"![{block.text or ''}]({block.href or ''})"
    if block.type == "thematic_break":
        return "---"
    if block.children:
        return "\n".join(block_to_markdown(c) for c in block.children)
    return block.text or ""
