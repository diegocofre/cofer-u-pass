from __future__ import annotations

import asyncio
import math

from playwright.async_api import Locator, Page

from cofer_u_pass.domain.errors import AdapterMismatch
from cofer_u_pass.domain.models import ProviderModel

from .adapter import (
    ChatGPTAdapter as _BaseChatGPTAdapter,
    _Choice,
    _EFFORT_OPTION_SELECTOR,
    _EFFORT_PICKER_SELECTORS,
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

_EFFORT_PICKER_FALLBACK_SELECTORS = (
    "button[aria-haspopup]",
    "[role='button'][aria-haspopup]",
)

_POPUP_SCOPE_SELECTOR = "[role='menu'], [role='listbox']"
_PREEXISTING_OPTION_MARKER = "data-cofer-u-pass-preexisting-option"
_PREEXISTING_POPUP_MARKER = "data-cofer-u-pass-preexisting-popup"
_MAX_PICKER_DISTANCE_PX = 760.0
_MAX_PICKER_VIEWPORT_RATIO = 0.45
_MAX_PICKER_CENTER_X_DELTA_PX = 480.0
_MAX_OPTION_DISTANCE_PX = 520.0
_MAX_OPTION_VIEWPORT_RATIO = 0.32
_MAX_OPTION_LEFT_GAP_PX = 220.0
_SIDEBAR_SURFACE_SELECTOR = (
    "aside, nav, [data-sidebar-item], [data-testid*='sidebar' i], "
    "[data-testid*='history' i], [aria-label*='chat history' i], "
    "[aria-label*='conversation history' i], a[href^='/c/']"
)


async def _is_sidebar_like(candidate: Locator) -> bool:
    try:
        return bool(await candidate.evaluate(
            "element => Boolean(element.closest(arguments[1]))",
            _SIDEBAR_SURFACE_SELECTOR,
        ))
    except Exception:
        return False


async def _is_composer_local(candidate: Locator) -> bool:
    """Require weak picker evidence to be structurally and spatially local to the composer."""
    try:
        return bool(await candidate.evaluate(
            """(element, limits) => {
                const composer =
                    document.querySelector("[data-testid='composer']") ||
                    document.querySelector("#prompt-textarea");
                if (!composer) return false;

                let common = composer;
                while (common && !common.contains(element)) common = common.parentElement;
                if (!common || common === document.body || common === document.documentElement) {
                    return false;
                }

                const composerRect = composer.getBoundingClientRect();
                const candidateRect = element.getBoundingClientRect();
                if (!composerRect.width || !composerRect.height ||
                    !candidateRect.width || !candidateRect.height) {
                    return false;
                }

                const composerCx = composerRect.left + composerRect.width / 2;
                const composerCy = composerRect.top + composerRect.height / 2;
                const candidateCx = candidateRect.left + candidateRect.width / 2;
                const candidateCy = candidateRect.top + candidateRect.height / 2;
                const diagonal = Math.hypot(window.innerWidth || 1280, window.innerHeight || 720);
                const maxDistance = Math.min(limits.maxDistance, diagonal * limits.viewportRatio);

                return Math.hypot(candidateCx - composerCx, candidateCy - composerCy) <= maxDistance &&
                    Math.abs(candidateCx - composerCx) <= limits.maxCenterXDelta;
            }""",
            {
                "maxDistance": _MAX_PICKER_DISTANCE_PX,
                "viewportRatio": _MAX_PICKER_VIEWPORT_RATIO,
                "maxCenterXDelta": _MAX_PICKER_CENTER_X_DELTA_PX,
            },
        ))
    except Exception:
        return False


async def _guarded_inference_click(page: Page, target: Locator, *, purpose: str) -> None:
    """Click an already-visible inference control without allowing Playwright auto-scroll."""
    if await _is_sidebar_like(target):
        raise AdapterMismatch(f"ChatGPT {purpose} resolved inside chat history/sidebar; refusing click")

    try:
        probe = await target.evaluate(
            """(element, sidebarSelector) => {
                const describe = node => {
                    if (!node) return null;
                    return {
                        tag: node.tagName ? node.tagName.toLowerCase() : null,
                        id: node.id || null,
                        role: node.getAttribute?.('role') || null,
                        testid: node.getAttribute?.('data-testid') || null,
                        sidebarItem: node.getAttribute?.('data-sidebar-item') || null,
                        ariaLabel: node.getAttribute?.('aria-label') || null,
                        href: node.getAttribute?.('href') || null,
                        text: (node.innerText || node.textContent || '')
                            .replace(/\s+/g, ' ').trim().slice(0, 120),
                    };
                };

                const rect = element.getBoundingClientRect();
                const x = rect.left + rect.width / 2;
                const y = rect.top + rect.height / 2;
                const inViewport = rect.width > 0 && rect.height > 0 &&
                    x >= 0 && y >= 0 && x < window.innerWidth && y < window.innerHeight;
                const hit = inViewport ? document.elementFromPoint(x, y) : null;
                const sidebarHit = hit ? hit.closest(sidebarSelector) : null;
                return {
                    x,
                    y,
                    inViewport,
                    hitIsTarget: Boolean(hit && (hit === element || element.contains(hit))),
                    target: describe(element),
                    hit: describe(hit),
                    sidebarHit: describe(sidebarHit),
                };
            }""",
            _SIDEBAR_SURFACE_SELECTOR,
        )
    except Exception as exc:
        raise AdapterMismatch(f"ChatGPT {purpose} could not be hit-tested safely: {exc}") from exc

    if not probe.get("inViewport"):
        raise AdapterMismatch(
            f"ChatGPT {purpose} is outside the viewport; refusing Playwright auto-scroll; "
            f"target={probe.get('target')!r}"
        )

    if not probe.get("hitIsTarget"):
        raise AdapterMismatch(
            f"ChatGPT {purpose} is blocked before click; target={probe.get('target')!r}; "
            f"hit={probe.get('hit')!r}; sidebar_hit={probe.get('sidebarHit')!r}"
        )

    await page.mouse.click(float(probe["x"]), float(probe["y"]))


async def _is_model_picker_candidate(candidate: Locator) -> bool:
    """Accept strong model controls globally and weak text evidence only near the composer."""
    try:
        role = (await candidate.get_attribute("role") or "").strip().lower()
        if role in {"menuitem", "menuitemradio", "option"}:
            return False

        native_id = (await candidate.get_attribute("data-testid") or "").strip()
        aria_label = (await candidate.get_attribute("aria-label") or "").strip()
        label = await _locator_label(candidate)
    except Exception:
        return False

    if await _is_sidebar_like(candidate):
        return False
    if "model-switcher" in native_id.lower():
        return True
    if "model" in aria_label.lower():
        return True

    parsed = _model_choice(label, native_id)
    if parsed is None:
        return False
    if _headline(label).casefold() != _headline(parsed[1]).casefold():
        return False
    return await _is_composer_local(candidate)


async def _is_effort_picker_candidate(candidate: Locator) -> bool:
    """Accept strong effort controls globally and weak text evidence only near the composer."""
    try:
        role = (await candidate.get_attribute("role") or "").strip().lower()
        if role in {"menuitem", "menuitemradio", "option"}:
            return False

        native_id = (await candidate.get_attribute("data-testid") or "").strip()
        aria_label = (await candidate.get_attribute("aria-label") or "").strip()
        label = await _locator_label(candidate)
    except Exception:
        return False

    if await _is_sidebar_like(candidate):
        return False
    structural = f"{native_id} {aria_label}".lower()
    if any(token in structural for token in ("intelligence", "reasoning", "thinking", "effort")):
        return True

    if _normalize_effort(label) is None and _normalize_effort(native_id) is None:
        return False
    return await _is_composer_local(candidate)


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


async def _is_surface_near_picker(page: Page, picker: Locator, surface: Locator) -> bool:
    """Reject unowned surfaces unless they are spatially close to the picker."""
    if await _is_sidebar_like(surface):
        return False
    try:
        picker_box = await picker.bounding_box()
        item_box = await surface.bounding_box()
        if not picker_box or not item_box:
            return False

        picker_cx = picker_box["x"] + picker_box["width"] / 2
        picker_cy = picker_box["y"] + picker_box["height"] / 2
        item_cx = item_box["x"] + item_box["width"] / 2
        item_cy = item_box["y"] + item_box["height"] / 2

        viewport = page.viewport_size or {"width": 1280, "height": 720}
        diagonal = math.hypot(viewport["width"], viewport["height"])
        max_distance = min(_MAX_OPTION_DISTANCE_PX, diagonal * _MAX_OPTION_VIEWPORT_RATIO)

        distance = math.hypot(item_cx - picker_cx, item_cy - picker_cy)
        left_gap = picker_box["x"] - (item_box["x"] + item_box["width"])
        return distance <= max_distance and left_gap <= _MAX_OPTION_LEFT_GAP_PX
    except Exception:
        return False


async def _opened_option_items(
    page: Page,
    picker: Locator,
    selector: str,
    *,
    kind: str,
) -> list[Locator]:
    """Open one picker and return only options that can be tied to that control."""
    await _close_popup(page)
    await _mark_currently_visible(page, selector, _PREEXISTING_OPTION_MARKER)
    await _mark_currently_visible(page, _POPUP_SCOPE_SELECTOR, _PREEXISTING_POPUP_MARKER)

    try:
        await _guarded_inference_click(page, picker, purpose=f"{kind} picker")
        await asyncio.sleep(0.1)

        controlled = await _controlled_popup_scopes(page, picker, selector, kind=kind)
        if len(controlled) > 1:
            raise AdapterMismatch(f"ChatGPT {kind} picker controls multiple matching popups")
        if controlled:
            return await _matching_items(controlled[0], selector, kind=kind)

        opened_scopes = [
            scope
            for scope in await _new_popup_scopes(page, selector, kind=kind)
            if await _is_surface_near_picker(page, picker, scope)
        ]
        if len(opened_scopes) > 1:
            raise AdapterMismatch(f"ChatGPT {kind} picker opened multiple matching popups")
        if opened_scopes:
            return await _matching_items(opened_scopes[0], selector, kind=kind)

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
            if matched and await _is_surface_near_picker(page, picker, item):
                revealed.append(item)

        if not revealed:
            raise AdapterMismatch(
                f"ChatGPT {kind} picker opened without a safely scoped option surface"
            )
        return revealed
    finally:
        await _clear_marker(page, _PREEXISTING_OPTION_MARKER)
        await _clear_marker(page, _PREEXISTING_POPUP_MARKER)


class ChatGPTAdapter(_BaseChatGPTAdapter):
    """Current ChatGPT adapter with resilient, evidence-based picker discovery."""

    adapter_version = "1.2.4"

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

    async def _effort_picker(self, page: Page) -> Locator | None:
        picker = await self._first_visible(page, _EFFORT_PICKER_SELECTORS)
        if picker is not None and await _is_effort_picker_candidate(picker):
            return picker

        for selector in _EFFORT_PICKER_FALLBACK_SELECTORS:
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
                if await _is_effort_picker_candidate(candidate):
                    return candidate
        return None

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

    async def _select_model(self, page: Page, model_id: str) -> _Choice:
        choices = await self._model_options(page)
        match = next((choice for choice in choices if choice.id == model_id), None)
        if match is None:
            await _close_popup(page)
            available = ", ".join(choice.id for choice in choices)
            raise AdapterMismatch(
                f"ChatGPT model {model_id!r} is not selectable; available models: {available or '(none)'}"
            )
        await _guarded_inference_click(page, match.locator, purpose=f"model option {model_id}")
        await asyncio.sleep(0.1)
        return match

    async def _select_effort(self, page: Page, effort: str) -> _Choice:
        choices = await self._effort_options(page)
        match = next((choice for choice in choices if choice.id == effort), None)
        if match is None:
            await _close_popup(page)
            available = ", ".join(choice.id for choice in choices)
            raise AdapterMismatch(
                f"ChatGPT effort {effort!r} is not selectable; available efforts: {available or '(none)'}"
            )
        await _guarded_inference_click(page, match.locator, purpose=f"effort option {effort}")
        await asyncio.sleep(0.1)
        return match

    async def discover_models(self, page: Page) -> list[ProviderModel]:
        await self.ensure_authenticated(page)
        original = await self.read_inference_state(page)
        choices = await self._model_options(page)
        discovered: list[ProviderModel] = []
        try:
            for index, choice in enumerate(choices):
                if index == 0:
                    await _guarded_inference_click(
                        page,
                        choice.locator,
                        purpose=f"model option {choice.id}",
                    )
                    await asyncio.sleep(0.1)
                else:
                    await self._select_model(page, choice.id)
                efforts = [item.id for item in await self._effort_options(page)]
                await _close_popup(page)
                discovered.append(ProviderModel(
                    id=choice.id,
                    provider=self.provider,
                    display_name=choice.label,
                    supported_efforts=efforts,
                    native_id=choice.native_id,
                    native_label=choice.label,
                ))
        finally:
            if original is not None:
                try:
                    await self._select_model(page, original.model)
                    if original.effort is not None:
                        await self._select_effort(page, original.effort)
                except Exception:
                    pass
        return discovered


__all__ = ["ChatGPTAdapter"]
