from __future__ import annotations

import asyncio

from playwright.async_api import Locator, Page

from cofer_u_pass.domain.errors import AdapterMismatch

from .adapter import (
    ChatGPTAdapter as _BaseChatGPTAdapter,
    _Choice,
    _EFFORT_OPTION_SELECTOR,
    _MODEL_OPTION_SELECTOR,
    _MODEL_PICKER_SELECTORS,
    _MODEL_TESTID_EXCLUSIONS,
    _close_popup,
    _headline,
    _is_selected,
    _locator_label,
    _model_choice,
    _normalize_effort,
)

_MODEL_PICKER_FALLBACK_SELECTORS = (
    "[data-testid*='model-switcher' i]",
    "button[aria-label*='model' i]",
    "[role='button'][aria-label*='model' i]",
    "button",
    "[role='button']",
)

_POPUP_SCOPE_SELECTOR = "[role='menu'], [role='listbox'], [role='dialog']"
_PREEXISTING_OPTION_MARKER = "data-cofer-u-pass-preexisting-option"
_PREEXISTING_POPUP_MARKER = "data-cofer-u-pass-preexisting-popup"


async def _is_model_picker_candidate(candidate: Locator) -> bool:
    """Accept only controls with positive evidence that they select a model."""
    try:
        role = (await candidate.get_attribute("role") or "").strip().lower()
        if role in {"menuitem", "menuitemradio", "option"}:
            return False

        native_id = (await candidate.get_attribute("data-testid") or "").strip()
        aria_label = (await candidate.get_attribute("aria-label") or "").strip()
        label = await _locator_label(candidate)
    except Exception:
        return False

    # Structural provider metadata is stronger than the current visible label.
    # ChatGPT may display a mode such as "Instant" on the trigger and expose the
    # actual model only after the picker opens.
    if "model-switcher" in native_id.lower():
        return True
    if "model" in aria_label.lower():
        return True

    parsed = _model_choice(label, native_id)
    if parsed is None:
        return False

    # Last-resort semantic fallback for current ChatGPT variants that render the
    # picker as an ordinary button/role=button with no popup or test-id metadata.
    # Require the whole visible label to be the recognized model name so nearby
    # UI such as "Upgrade to GPT-5.6 Pro" cannot be mistaken for the picker.
    return _headline(label).casefold() == _headline(parsed[1]).casefold()


def _css_attr_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


async def _mark_currently_visible(page: Page, selector: str, marker: str) -> None:
    await page.locator(selector).evaluate_all(
        """(elements, marker) => {
            for (const element of elements) {
                const style = getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                const visible = style.display !== 'none' && style.visibility !== 'hidden' &&
                    rect.width > 0 && rect.height > 0;
                if (visible) element.setAttribute(marker, '1');
            }
        }""",
        marker,
    )


async def _clear_marker(page: Page, marker: str) -> None:
    await page.locator(f"[{marker}]").evaluate_all(
        "(elements, marker) => elements.forEach(element => element.removeAttribute(marker))",
        marker,
    )


async def _matches_model_option(item: Locator) -> bool:
    try:
        native_id = await item.get_attribute("data-testid")
        if native_id and any(part in native_id.lower() for part in _MODEL_TESTID_EXCLUSIONS):
            return False
        return _model_choice(await _locator_label(item), native_id) is not None
    except Exception:
        return False


async def _matches_effort_option(item: Locator) -> bool:
    try:
        label = await _locator_label(item)
        native_id = await item.get_attribute("data-testid")
        return _normalize_effort(label) is not None or _normalize_effort(native_id) is not None
    except Exception:
        return False


async def _matching_items(scope: Locator, selector: str, *, kind: str) -> list[Locator]:
    items = scope.locator(selector)
    matches: list[Locator] = []
    for index in range(await items.count()):
        item = items.nth(index)
        try:
            if not await item.is_visible():
                continue
        except Exception:
            continue
        matched = await (_matches_model_option(item) if kind == "model" else _matches_effort_option(item))
        if matched:
            matches.append(item)
    return matches


async def _controlled_popup_scopes(page: Page, picker: Locator, selector: str, *, kind: str) -> list[Locator]:
    scopes: list[Locator] = []
    seen_ids: set[str] = set()
    for attr in ("aria-controls", "aria-owns"):
        raw = (await picker.get_attribute(attr) or "").strip()
        for target_id in raw.split():
            if not target_id or target_id in seen_ids:
                continue
            seen_ids.add(target_id)
            target = page.locator(f'[id="{_css_attr_value(target_id)}"]')
            if await target.count() != 1:
                continue
            target = target.first
            try:
                if not await target.is_visible():
                    continue
            except Exception:
                continue
            if await _matching_items(target, selector, kind=kind):
                scopes.append(target)
    return scopes


async def _new_popup_scopes(page: Page, selector: str, *, kind: str) -> list[Locator]:
    scopes = page.locator(_POPUP_SCOPE_SELECTOR)
    matches: list[Locator] = []
    for index in range(await scopes.count()):
        scope = scopes.nth(index)
        try:
            if not await scope.is_visible():
                continue
            if await scope.get_attribute(_PREEXISTING_POPUP_MARKER) == "1":
                continue
        except Exception:
            continue
        if await _matching_items(scope, selector, kind=kind):
            matches.append(scope)
    return matches


async def _opened_option_items(
    page: Page,
    picker: Locator,
    selector: str,
    *,
    kind: str,
) -> list[Locator]:
    """Open one picker and return only options causally scoped to that popup."""
    await _close_popup(page)
    await _mark_currently_visible(page, selector, _PREEXISTING_OPTION_MARKER)
    await _mark_currently_visible(page, _POPUP_SCOPE_SELECTOR, _PREEXISTING_POPUP_MARKER)

    try:
        await picker.click()
        await asyncio.sleep(0.1)

        controlled = await _controlled_popup_scopes(page, picker, selector, kind=kind)
        if len(controlled) > 1:
            raise AdapterMismatch(f"ChatGPT {kind} picker controls multiple matching popups")
        if controlled:
            return await _matching_items(controlled[0], selector, kind=kind)

        opened_scopes = await _new_popup_scopes(page, selector, kind=kind)
        if len(opened_scopes) > 1:
            raise AdapterMismatch(f"ChatGPT {kind} picker opened multiple matching popups")
        if opened_scopes:
            return await _matching_items(opened_scopes[0], selector, kind=kind)

        # Some current ChatGPT variants expose no accessible popup container.
        # In that case accept only option nodes that became visible because this
        # picker was clicked. Anything already visible elsewhere in the app (for
        # example chat-history/sidebar menuitems) is explicitly excluded.
        items = page.locator(selector)
        revealed: list[Locator] = []
        for index in range(await items.count()):
            item = items.nth(index)
            try:
                if not await item.is_visible():
                    continue
                if await item.get_attribute(_PREEXISTING_OPTION_MARKER) == "1":
                    continue
            except Exception:
                continue
            matched = await (_matches_model_option(item) if kind == "model" else _matches_effort_option(item))
            if matched:
                revealed.append(item)
        return revealed
    finally:
        await _clear_marker(page, _PREEXISTING_OPTION_MARKER)
        await _clear_marker(page, _PREEXISTING_POPUP_MARKER)


class ChatGPTAdapter(_BaseChatGPTAdapter):
    """Current ChatGPT adapter with resilient, evidence-based picker discovery."""

    adapter_version = "1.2.2"

    async def _model_picker(self, page: Page) -> Locator:
        picker = await self._first_visible(page, _MODEL_PICKER_SELECTORS)
        if picker is not None and await _is_model_picker_candidate(picker):
            return picker

        for selector in _MODEL_PICKER_FALLBACK_SELECTORS:
            candidates = page.locator(selector)
            try:
                count = await candidates.count()
            except Exception:
                continue
            for index in range(count):
                candidate = candidates.nth(index)
                try:
                    if not await candidate.is_visible():
                        continue
                except Exception:
                    continue
                if await _is_model_picker_candidate(candidate):
                    return candidate

        raise AdapterMismatch("ChatGPT model picker could not be located")

    async def _model_options(self, page: Page) -> list[_Choice]:
        picker = await self._model_picker(page)
        items = await _opened_option_items(page, picker, _MODEL_OPTION_SELECTOR, kind="model")
        choices: list[_Choice] = []
        seen: set[str] = set()
        for item in items:
            native_id = await item.get_attribute("data-testid")
            label = await _locator_label(item)
            parsed = _model_choice(label, native_id)
            if parsed is None:
                continue
            public_id, display = parsed
            if public_id in seen:
                continue
            seen.add(public_id)
            choices.append(_Choice(
                locator=item,
                id=public_id,
                label=display,
                native_id=native_id,
                selected=await _is_selected(item),
            ))
        if not choices:
            await _close_popup(page)
            raise AdapterMismatch("ChatGPT model picker opened but no scoped model choices could be recognized")
        return choices

    async def _effort_options(self, page: Page) -> list[_Choice]:
        picker = await self._effort_picker(page)
        if picker is None:
            return []
        items = await _opened_option_items(page, picker, _EFFORT_OPTION_SELECTOR, kind="effort")
        choices: list[_Choice] = []
        seen: set[str] = set()
        for item in items:
            label = await _locator_label(item)
            native_id = await item.get_attribute("data-testid")
            effort = _normalize_effort(label) or _normalize_effort(native_id)
            if effort is None or effort in seen:
                continue
            seen.add(effort)
            choices.append(_Choice(
                locator=item,
                id=effort,
                label=_headline(label) or native_id or effort,
                native_id=native_id,
                selected=await _is_selected(item),
            ))
        if not choices:
            await _close_popup(page)
            raise AdapterMismatch("ChatGPT effort picker opened but no scoped effort choices could be recognized")
        return choices


__all__ = ["ChatGPTAdapter"]
