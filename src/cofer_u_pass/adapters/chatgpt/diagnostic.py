from __future__ import annotations

from playwright.async_api import Page, Locator

from cofer_u_pass.domain.errors import AdapterMismatch

from . import ChatGPTAdapter as _CurrentChatGPTAdapter
from . import _SIDEBAR_SURFACE_SELECTOR

_INTERACTIVE_DIAGNOSTIC_SELECTOR = (
    "button, [role='button'], [aria-haspopup], [aria-expanded], [aria-controls], "
    "[tabindex]:not([tabindex='-1']), select, summary, [data-testid]"
)
_MAX_DIAGNOSTIC_CONTROLS = 24
_MAX_DIAGNOSTIC_DISTANCE_PX = 1100.0
_MAX_DIAGNOSTIC_TEXT = 80


async def _nearby_interactive_controls(page: Page) -> list[dict[str, object]]:
    """Return bounded, sidebar-free metadata for visible controls near the composer."""
    controls = page.locator(_INTERACTIVE_DIAGNOSTIC_SELECTOR)
    try:
        return await controls.evaluate_all(
            r"""(elements, config) => {
                const composer =
                    document.querySelector("[data-testid='composer']") ||
                    document.querySelector("#prompt-textarea");
                if (!composer) return [];

                const composerRect = composer.getBoundingClientRect();
                const composerCx = composerRect.left + composerRect.width / 2;
                const composerCy = composerRect.top + composerRect.height / 2;

                const describe = element => {
                    const style = getComputedStyle(element);
                    const rect = element.getBoundingClientRect();
                    const visible = style.display !== 'none' && style.visibility !== 'hidden' &&
                        rect.width > 0 && rect.height > 0;
                    if (!visible) return null;
                    if (element.closest(config.sidebarSelector)) return null;

                    const cx = rect.left + rect.width / 2;
                    const cy = rect.top + rect.height / 2;
                    const distance = Math.hypot(cx - composerCx, cy - composerCy);
                    if (distance > config.maxDistance) return null;

                    const text = (element.innerText || element.textContent || '')
                        .replace(/\s+/g, ' ').trim().slice(0, config.maxText);

                    return {
                        tag: element.tagName ? element.tagName.toLowerCase() : null,
                        role: element.getAttribute('role'),
                        testid: element.getAttribute('data-testid'),
                        ariaLabel: element.getAttribute('aria-label'),
                        ariaHaspopup: element.getAttribute('aria-haspopup'),
                        ariaExpanded: element.getAttribute('aria-expanded'),
                        ariaControls: element.getAttribute('aria-controls'),
                        title: element.getAttribute('title'),
                        text,
                        bbox: {
                            x: Math.round(rect.left),
                            y: Math.round(rect.top),
                            width: Math.round(rect.width),
                            height: Math.round(rect.height),
                        },
                        distance: Math.round(distance),
                        insideComposer: Boolean(element.closest("[data-testid='composer']")),
                    };
                };

                const rows = [];
                const seen = new Set();
                for (const element of elements) {
                    const row = describe(element);
                    if (!row) continue;
                    const key = JSON.stringify([
                        row.tag,
                        row.role,
                        row.testid,
                        row.ariaLabel,
                        row.ariaHaspopup,
                        row.ariaControls,
                        row.title,
                        row.text,
                        row.bbox.x,
                        row.bbox.y,
                    ]);
                    if (seen.has(key)) continue;
                    seen.add(key);
                    rows.push(row);
                }

                rows.sort((a, b) => {
                    const aSignal = Number(Boolean(a.ariaHaspopup || a.ariaControls || a.testid || a.role === 'button'));
                    const bSignal = Number(Boolean(b.ariaHaspopup || b.ariaControls || b.testid || b.role === 'button'));
                    if (aSignal !== bSignal) return bSignal - aSignal;
                    return a.distance - b.distance;
                });
                return rows.slice(0, config.maxControls);
            }""",
            {
                "sidebarSelector": _SIDEBAR_SURFACE_SELECTOR,
                "maxDistance": _MAX_DIAGNOSTIC_DISTANCE_PX,
                "maxControls": _MAX_DIAGNOSTIC_CONTROLS,
                "maxText": _MAX_DIAGNOSTIC_TEXT,
            },
        )
    except Exception:
        return []


def _format_picker_diagnostics(rows: list[dict[str, object]]) -> str:
    if not rows:
        return "Nearby interactive controls: none captured safely."

    lines = ["Nearby interactive controls (sidebar/history excluded):"]
    for index, row in enumerate(rows):
        bbox = row.get("bbox") or {}
        if not isinstance(bbox, dict):
            bbox = {}
        lines.append(
            "[{index}] tag={tag!r} role={role!r} testid={testid!r} "
            "aria-label={aria_label!r} aria-haspopup={aria_haspopup!r} "
            "aria-expanded={aria_expanded!r} aria-controls={aria_controls!r} "
            "title={title!r} text={text!r} bbox=({x},{y},{width},{height}) "
            "distance={distance!r}px inside_composer={inside_composer!r}".format(
                index=index,
                tag=row.get("tag"),
                role=row.get("role"),
                testid=row.get("testid"),
                aria_label=row.get("ariaLabel"),
                aria_haspopup=row.get("ariaHaspopup"),
                aria_expanded=row.get("ariaExpanded"),
                aria_controls=row.get("ariaControls"),
                title=row.get("title"),
                text=row.get("text"),
                x=bbox.get("x"),
                y=bbox.get("y"),
                width=bbox.get("width"),
                height=bbox.get("height"),
                distance=row.get("distance"),
                inside_composer=row.get("insideComposer"),
            )
        )
    return "\n".join(lines)


class ChatGPTAdapter(_CurrentChatGPTAdapter):
    """ChatGPT adapter with safe failure diagnostics for picker discovery."""

    adapter_version = "1.2.6"

    async def _model_picker(self, page: Page) -> Locator:
        try:
            return await super()._model_picker(page)
        except AdapterMismatch as exc:
            rows = await _nearby_interactive_controls(page)
            raise AdapterMismatch(f"{exc}\n{_format_picker_diagnostics(rows)}") from exc


__all__ = ["ChatGPTAdapter"]
