from __future__ import annotations

from playwright.async_api import Locator, Page

from cofer_u_pass.domain.errors import AdapterMismatch

from . import ChatGPTAdapter as _CurrentChatGPTAdapter
from . import _SIDEBAR_SURFACE_SELECTOR
from .adapter import _close_popup

_INTERACTIVE_DIAGNOSTIC_SELECTOR = (
    "button, [role='button'], [aria-haspopup], [aria-expanded], [aria-controls], "
    "[tabindex]:not([tabindex='-1']), select, summary, [data-testid]"
)
_MAX_DIAGNOSTIC_CONTROLS = 24
_MAX_DIAGNOSTIC_DISTANCE_PX = 1100.0
_MAX_DIAGNOSTIC_TEXT = 80
_MAX_EFFORT_MENU_ITEMS = 24
_MAX_MODEL_METADATA_ITEMS = 16


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
                    const aSignal = Number(Boolean(
                        a.ariaHaspopup || a.ariaControls || a.testid || a.role === 'button'
                    ));
                    const bSignal = Number(Boolean(
                        b.ariaHaspopup || b.ariaControls || b.testid || b.role === 'button'
                    ));
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


async def _describe_control(control: Locator) -> dict[str, object] | None:
    try:
        return await control.evaluate(
            r"""element => {
                const rect = element.getBoundingClientRect();
                return {
                    tag: element.tagName ? element.tagName.toLowerCase() : null,
                    role: element.getAttribute('role'),
                    testid: element.getAttribute('data-testid'),
                    ariaLabel: element.getAttribute('aria-label'),
                    ariaHaspopup: element.getAttribute('aria-haspopup'),
                    ariaExpanded: element.getAttribute('aria-expanded'),
                    ariaControls: element.getAttribute('aria-controls'),
                    ariaChecked: element.getAttribute('aria-checked'),
                    ariaSelected: element.getAttribute('aria-selected'),
                    dataState: element.getAttribute('data-state'),
                    dataValue: element.getAttribute('data-value'),
                    title: element.getAttribute('title'),
                    text: (element.innerText || element.textContent || '')
                        .replace(/\s+/g, ' ').trim().slice(0, 80),
                    bbox: {
                        x: Math.round(rect.left),
                        y: Math.round(rect.top),
                        width: Math.round(rect.width),
                        height: Math.round(rect.height),
                    },
                };
            }"""
        )
    except Exception:
        return None


async def _visible_effort_menu_items(
    page: Page,
    picker: Locator,
) -> list[dict[str, object]]:
    """Capture visible option-like nodes near the open effort picker without clicking them."""
    try:
        picker_box = await picker.bounding_box()
        if not picker_box:
            return []
        elements = page.locator(
            "[role='menuitemradio'], [role='menuitem'], [role='option'], [role='radio'], "
            "[role='menu'] button, [role='listbox'] button, "
            "[data-radix-menu-content] button, [data-value]"
        )
        return await elements.evaluate_all(
            r"""(nodes, config) => {
                const pcx = config.picker.x + config.picker.width / 2;
                const pcy = config.picker.y + config.picker.height / 2;
                const rows = [];
                const seen = new Set();

                for (const element of nodes) {
                    const style = getComputedStyle(element);
                    const rect = element.getBoundingClientRect();
                    const visible = style.display !== 'none' && style.visibility !== 'hidden' &&
                        rect.width > 0 && rect.height > 0;
                    if (!visible || element.closest(config.sidebarSelector)) continue;

                    const cx = rect.left + rect.width / 2;
                    const cy = rect.top + rect.height / 2;
                    const distance = Math.hypot(cx - pcx, cy - pcy);
                    if (distance > 720) continue;

                    const row = {
                        tag: element.tagName ? element.tagName.toLowerCase() : null,
                        role: element.getAttribute('role'),
                        testid: element.getAttribute('data-testid'),
                        ariaLabel: element.getAttribute('aria-label'),
                        ariaChecked: element.getAttribute('aria-checked'),
                        ariaSelected: element.getAttribute('aria-selected'),
                        dataState: element.getAttribute('data-state'),
                        dataValue: element.getAttribute('data-value'),
                        title: element.getAttribute('title'),
                        text: (element.innerText || element.textContent || '')
                            .replace(/\s+/g, ' ').trim().slice(0, 80),
                        bbox: {
                            x: Math.round(rect.left),
                            y: Math.round(rect.top),
                            width: Math.round(rect.width),
                            height: Math.round(rect.height),
                        },
                        distance: Math.round(distance),
                    };
                    const key = JSON.stringify([
                        row.tag, row.role, row.testid, row.ariaLabel, row.dataValue,
                        row.text, row.bbox.x, row.bbox.y,
                    ]);
                    if (seen.has(key)) continue;
                    seen.add(key);
                    rows.push(row);
                }

                rows.sort((a, b) => a.distance - b.distance);
                return rows.slice(0, config.maxItems);
            }""",
            {
                "picker": picker_box,
                "sidebarSelector": _SIDEBAR_SURFACE_SELECTOR,
                "maxItems": _MAX_EFFORT_MENU_ITEMS,
            },
        )
    except Exception:
        return []


async def _visible_model_mode_metadata(page: Page) -> list[dict[str, object]]:
    """Capture bounded visible provider metadata whose attributes suggest model/mode state."""
    candidates = page.locator(
        "[data-testid], [aria-label], [title], [data-value], [data-mode], [data-model]"
    )
    try:
        return await candidates.evaluate_all(
            r"""(elements, config) => {
                const tokens = /(?:model|mode|gpt|reasoning|effort|thinking|intelligence)/i;
                const rows = [];
                const seen = new Set();
                for (const element of elements) {
                    const style = getComputedStyle(element);
                    const rect = element.getBoundingClientRect();
                    const visible = style.display !== 'none' && style.visibility !== 'hidden' &&
                        rect.width > 0 && rect.height > 0;
                    if (!visible || element.closest(config.sidebarSelector)) continue;

                    const attrs = {
                        testid: element.getAttribute('data-testid'),
                        ariaLabel: element.getAttribute('aria-label'),
                        title: element.getAttribute('title'),
                        dataValue: element.getAttribute('data-value'),
                        dataMode: element.getAttribute('data-mode'),
                        dataModel: element.getAttribute('data-model'),
                    };
                    const haystack = Object.values(attrs).filter(Boolean).join(' ');
                    if (!tokens.test(haystack)) continue;

                    const row = {
                        tag: element.tagName ? element.tagName.toLowerCase() : null,
                        role: element.getAttribute('role'),
                        ...attrs,
                        text: (element.innerText || element.textContent || '')
                            .replace(/\s+/g, ' ').trim().slice(0, 80),
                        bbox: {
                            x: Math.round(rect.left),
                            y: Math.round(rect.top),
                            width: Math.round(rect.width),
                            height: Math.round(rect.height),
                        },
                    };
                    const key = JSON.stringify([
                        row.tag, row.role, row.testid, row.ariaLabel, row.title,
                        row.dataValue, row.dataMode, row.dataModel, row.bbox.x, row.bbox.y,
                    ]);
                    if (seen.has(key)) continue;
                    seen.add(key);
                    rows.push(row);
                }
                return rows.slice(0, config.maxItems);
            }""",
            {
                "sidebarSelector": _SIDEBAR_SURFACE_SELECTOR,
                "maxItems": _MAX_MODEL_METADATA_ITEMS,
            },
        )
    except Exception:
        return []


def _format_row(row: dict[str, object], *, include_picker_fields: bool = False) -> str:
    bbox = row.get("bbox") or {}
    if not isinstance(bbox, dict):
        bbox = {}
    fields = [
        f"tag={row.get('tag')!r}",
        f"role={row.get('role')!r}",
        f"testid={row.get('testid')!r}",
        f"aria-label={row.get('ariaLabel')!r}",
    ]
    if include_picker_fields:
        fields.extend([
            f"aria-haspopup={row.get('ariaHaspopup')!r}",
            f"aria-expanded={row.get('ariaExpanded')!r}",
            f"aria-controls={row.get('ariaControls')!r}",
        ])
    fields.extend([
        f"aria-checked={row.get('ariaChecked')!r}",
        f"aria-selected={row.get('ariaSelected')!r}",
        f"data-state={row.get('dataState')!r}",
        f"data-value={row.get('dataValue')!r}",
        f"title={row.get('title')!r}",
        f"text={row.get('text')!r}",
        "bbox=({x},{y},{width},{height})".format(
            x=bbox.get("x"),
            y=bbox.get("y"),
            width=bbox.get("width"),
            height=bbox.get("height"),
        ),
    ])
    if row.get("distance") is not None:
        fields.append(f"distance={row.get('distance')!r}px")
    return " ".join(fields)


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


async def _effort_menu_diagnostics(adapter: "ChatGPTAdapter", page: Page) -> str:
    picker = await adapter._effort_picker(page)
    if picker is None:
        return "Effort picker diagnostic: no safely recognized effort picker."

    picker_row = await _describe_control(picker)
    recognized: list[str] = []
    failure: str | None = None
    raw_items: list[dict[str, object]] = []
    try:
        try:
            choices = await adapter._effort_options(page)
            recognized = [
                f"{choice.id} (label={choice.label!r}, native_id={choice.native_id!r}, "
                f"selected={choice.selected!r})"
                for choice in choices
            ]
        except Exception as exc:
            failure = f"{type(exc).__name__}: {exc}"
        raw_items = await _visible_effort_menu_items(page, picker)
    finally:
        await _close_popup(page)

    lines = ["Effort picker/menu diagnostic (no option selected):"]
    lines.append(
        "picker: " + (
            _format_row(picker_row, include_picker_fields=True)
            if picker_row is not None
            else "metadata unavailable"
        )
    )
    lines.append(
        "recognized_efforts: " + (", ".join(recognized) if recognized else "none")
    )
    if failure:
        lines.append(f"effort_option_discovery_error: {failure}")
    lines.append("raw_visible_menu_items:")
    if raw_items:
        lines.extend(
            f"[{index}] {_format_row(row)}"
            for index, row in enumerate(raw_items)
        )
    else:
        lines.append("none captured safely")
    return "\n".join(lines)


def _format_model_mode_metadata(rows: list[dict[str, object]]) -> str:
    lines = ["Visible model/mode-related metadata (sidebar/history excluded):"]
    if not rows:
        lines.append("none captured safely")
        return "\n".join(lines)
    for index, row in enumerate(rows):
        bbox = row.get("bbox") or {}
        if not isinstance(bbox, dict):
            bbox = {}
        lines.append(
            "[{index}] tag={tag!r} role={role!r} testid={testid!r} "
            "aria-label={aria_label!r} title={title!r} data-value={data_value!r} "
            "data-mode={data_mode!r} data-model={data_model!r} text={text!r} "
            "bbox=({x},{y},{width},{height})".format(
                index=index,
                tag=row.get("tag"),
                role=row.get("role"),
                testid=row.get("testid"),
                aria_label=row.get("ariaLabel"),
                title=row.get("title"),
                data_value=row.get("dataValue"),
                data_mode=row.get("dataMode"),
                data_model=row.get("dataModel"),
                text=row.get("text"),
                x=bbox.get("x"),
                y=bbox.get("y"),
                width=bbox.get("width"),
                height=bbox.get("height"),
            )
        )
    return "\n".join(lines)


class ChatGPTAdapter(_CurrentChatGPTAdapter):
    """ChatGPT adapter with safe failure diagnostics for picker discovery."""

    adapter_version = "1.2.7"

    async def _model_picker(self, page: Page) -> Locator:
        try:
            return await super()._model_picker(page)
        except AdapterMismatch as exc:
            controls = await _nearby_interactive_controls(page)
            effort = await _effort_menu_diagnostics(self, page)
            model_metadata = await _visible_model_mode_metadata(page)
            raise AdapterMismatch(
                f"{exc}\n{_format_picker_diagnostics(controls)}\n"
                f"{effort}\n{_format_model_mode_metadata(model_metadata)}"
            ) from exc


__all__ = ["ChatGPTAdapter"]