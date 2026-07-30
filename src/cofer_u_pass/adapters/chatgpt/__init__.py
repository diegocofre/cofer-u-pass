from __future__ import annotations

from playwright.async_api import Locator, Page

from cofer_u_pass.domain.errors import AdapterMismatch

from .adapter import (
    ChatGPTAdapter as _BaseChatGPTAdapter,
    _MODEL_PICKER_SELECTORS,
    _headline,
    _locator_label,
    _model_choice,
)

_MODEL_PICKER_FALLBACK_SELECTORS = (
    "[data-testid*='model-switcher' i]",
    "button[aria-label*='model' i]",
    "[role='button'][aria-label*='model' i]",
    "button",
    "[role='button']",
)


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


class ChatGPTAdapter(_BaseChatGPTAdapter):
    """Current ChatGPT adapter with resilient, evidence-based picker discovery."""

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


__all__ = ["ChatGPTAdapter"]
