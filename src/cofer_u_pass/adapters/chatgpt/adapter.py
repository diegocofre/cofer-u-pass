from __future__ import annotations

import asyncio
import re
import unicodedata
from dataclasses import dataclass

from playwright.async_api import Locator, Page

from cofer_u_pass.adapters.base import ActionEvidence, ProviderAdapter
from cofer_u_pass.domain.errors import AdapterMismatch
from cofer_u_pass.domain.models import InferenceSelection, InferenceState, ProviderModel


@dataclass(slots=True)
class _Choice:
    locator: Locator
    id: str
    label: str
    native_id: str | None = None
    selected: bool = False


_MODEL_PICKER_SELECTORS = (
    "button[data-testid='model-switcher-dropdown-button']",
    "[data-testid='model-switcher-dropdown-button']",
    "button[data-testid*='model-switcher']",
    "button[aria-label*='model' i][aria-haspopup]",
)

_MODEL_OPTION_SELECTOR = (
    "[role='menuitemradio'], [role='option'], [role='menuitem'], "
    "[data-testid^='model-switcher-']"
)

_EFFORT_PICKER_SELECTORS = (
    "button[data-testid*='intelligence' i]",
    "button[data-testid*='reasoning' i]",
    "button[data-testid*='thinking' i]",
    "button[data-testid*='effort' i]",
    "button[aria-label*='intelligence' i]",
    "button[aria-label*='reasoning' i]",
    "button[aria-label*='thinking' i]",
    "button[aria-label*='effort' i]",
)

_EFFORT_OPTION_SELECTOR = "[role='menuitemradio'], [role='option'], [role='menuitem']"

_MODEL_TESTID_EXCLUSIONS = (
    "dropdown-button",
    "submenu",
    "legacy",
    "configure",
)

_EFFORT_ALIASES = {
    "none": "none",
    "off": "none",
    "disabled": "none",
    "desactivado": "none",
    "minimal": "minimal",
    "low": "low",
    "light": "low",
    "bajo": "low",
    "ligero": "low",
    "medium": "medium",
    "standard": "medium",
    "balanced": "medium",
    "medio": "medium",
    "estandar": "medium",
    "high": "high",
    "advanced": "high",
    "extended": "high",
    "alto": "high",
    "alta": "high",
    "ampliado": "high",
    "extendido": "high",
    "extra high": "xhigh",
    "xhigh": "xhigh",
    "heavy": "xhigh",
    "extreme": "xhigh",
    "extra alto": "xhigh",
    "extra alta": "xhigh",
    "muy alto": "xhigh",
    "muy alta": "xhigh",
    "intenso": "xhigh",
    "pesado": "xhigh",
    "maximum": "max",
    "max": "max",
    "maximo": "max",
}


def _headline(value: str | None) -> str:
    if not value:
        return ""
    for line in value.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            return line
    return ""


def _slug(value: str) -> str:
    value = value.strip().lower().replace("×", "x")
    value = re.sub(r"[\s_/]+", "-", value)
    value = re.sub(r"[^a-z0-9.+-]", "", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value


def _model_display(value: str | None) -> str | None:
    text = _headline(value)
    if not text:
        return None
    # Prefer the visible model-looking fragment when aria labels include prose.
    match = re.search(
        r"(?i)(gpt[- ]?\d[\w.+-]*(?:\s+(?:sol|pro|instant|thinking|codex))?|"
        r"o\d(?:[-.][\w.+-]+)*(?:\s+pro)?|"
        r"\d+(?:\.\d+)+(?:\s+(?:sol|pro|codex))?)",
        text,
    )
    if match:
        return re.sub(r"\s+", " ", match.group(1)).strip()
    return None


def _model_choice(label: str | None, native_id: str | None = None) -> tuple[str, str] | None:
    del native_id  # retained in the signature so callers can preserve provider evidence separately.
    display = _model_display(label)
    if display is None:
        return None
    public_id = _slug(display)
    if not public_id:
        return None
    return public_id, display


def _normalize_effort(label: str | None) -> str | None:
    value = _headline(label).lower()
    if not value:
        return None
    value = "".join(
        char for char in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(char)
    )
    value = value.replace("_", " ").replace("-", " ")
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(
        r"^(?:intelligence|reasoning(?: effort)?|thinking|effort|inteligencia|razonamiento)\s*[: ]\s*",
        "",
        value,
    )
    return _EFFORT_ALIASES.get(value)


async def _visible_text(locator: Locator) -> str:
    try:
        return _headline(await locator.inner_text())
    except Exception:
        return ""


async def _locator_label(locator: Locator) -> str:
    text = await _visible_text(locator)
    if text:
        return text
    for attr in ("aria-label", "title"):
        try:
            value = _headline(await locator.get_attribute(attr))
        except Exception:
            value = ""
        if value:
            return value
    return ""


async def _is_selected(locator: Locator) -> bool:
    for attr in ("aria-checked", "aria-selected", "data-state", "data-selected"):
        try:
            value = (await locator.get_attribute(attr) or "").strip().lower()
        except Exception:
            continue
        if value in {"true", "checked", "selected", "on", "active"}:
            return True
    return False


async def _close_popup(page: Page) -> None:
    try:
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.05)
    except Exception:
        pass


class ChatGPTAdapter(ProviderAdapter):
    adapter_version = "1.2.0"

    def extract_conversation_id(self, url: str) -> str | None:
        m = re.search(r"/c/([A-Za-z0-9-]+)", url)
        return m.group(1) if m else None

    async def _first_visible(self, page: Page, selectors: tuple[str, ...]) -> Locator | None:
        for selector in selectors:
            loc = page.locator(selector)
            try:
                count = await loc.count()
            except Exception:
                continue
            for index in range(count):
                candidate = loc.nth(index)
                try:
                    if await candidate.is_visible():
                        return candidate
                except Exception:
                    continue
        return None

    async def _model_picker(self, page: Page) -> Locator:
        picker = await self._first_visible(page, _MODEL_PICKER_SELECTORS)
        if picker is not None:
            return picker
        # Last-resort structural fallback: a visible popup button whose label
        # itself contains the currently selected model.
        buttons = page.locator("button[aria-haspopup]")
        for index in range(await buttons.count()):
            candidate = buttons.nth(index)
            if not await candidate.is_visible():
                continue
            label = await _locator_label(candidate)
            if _model_choice(label) is not None:
                return candidate
        raise AdapterMismatch("ChatGPT model picker could not be located")

    async def _effort_picker(self, page: Page) -> Locator | None:
        picker = await self._first_visible(page, _EFFORT_PICKER_SELECTORS)
        if picker is not None:
            return picker
        # Some ChatGPT builds expose the current intelligence value as the
        # button text without a dedicated test id.
        buttons = page.locator("button[aria-haspopup]")
        for index in range(await buttons.count()):
            candidate = buttons.nth(index)
            if not await candidate.is_visible():
                continue
            label = await _locator_label(candidate)
            native_id = await candidate.get_attribute("data-testid")
            if _normalize_effort(label) is not None or _normalize_effort(native_id) is not None:
                return candidate
        return None

    async def _model_options(self, page: Page) -> list[_Choice]:
        picker = await self._model_picker(page)
        await picker.click()
        await asyncio.sleep(0.1)
        items = page.locator(_MODEL_OPTION_SELECTOR)
        choices: list[_Choice] = []
        seen: set[str] = set()
        for index in range(await items.count()):
            item = items.nth(index)
            if not await item.is_visible():
                continue
            native_id = await item.get_attribute("data-testid")
            if native_id and any(part in native_id.lower() for part in _MODEL_TESTID_EXCLUSIONS):
                continue
            label = await _locator_label(item)
            parsed = _model_choice(label, native_id)
            if parsed is None:
                continue
            public_id, display = parsed
            if public_id in seen:
                continue
            seen.add(public_id)
            choices.append(
                _Choice(
                    locator=item,
                    id=public_id,
                    label=display,
                    native_id=native_id,
                    selected=await _is_selected(item),
                )
            )
        if not choices:
            await _close_popup(page)
            raise AdapterMismatch("ChatGPT model picker opened but no model choices could be recognized")
        return choices

    async def _effort_options(self, page: Page) -> list[_Choice]:
        picker = await self._effort_picker(page)
        if picker is None:
            return []
        await picker.click()
        await asyncio.sleep(0.1)
        items = page.locator(_EFFORT_OPTION_SELECTOR)
        choices: list[_Choice] = []
        seen: set[str] = set()
        for index in range(await items.count()):
            item = items.nth(index)
            if not await item.is_visible():
                continue
            label = await _locator_label(item)
            native_id = await item.get_attribute("data-testid")
            effort = _normalize_effort(label) or _normalize_effort(native_id)
            if effort is None or effort in seen:
                continue
            seen.add(effort)
            choices.append(
                _Choice(
                    locator=item,
                    id=effort,
                    label=_headline(label) or native_id or effort,
                    native_id=native_id,
                    selected=await _is_selected(item),
                )
            )
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
        await match.locator.click()
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
        await match.locator.click()
        await asyncio.sleep(0.1)
        return match

    async def _selected_model_from_menu(self, page: Page) -> _Choice | None:
        choices = await self._model_options(page)
        selected = next((choice for choice in choices if choice.selected), None)
        await _close_popup(page)
        return selected

    async def _selected_effort_from_menu(self, page: Page) -> _Choice | None:
        choices = await self._effort_options(page)
        selected = next((choice for choice in choices if choice.selected), None)
        await _close_popup(page)
        return selected

    async def read_inference_state(self, page: Page) -> InferenceState | None:
        picker = await self._model_picker(page)
        model_label = await _locator_label(picker)
        parsed = _model_choice(model_label, await picker.get_attribute("data-testid"))
        if parsed is None:
            selected_model = await self._selected_model_from_menu(page)
            if selected_model is None:
                return None
            model_id, native_model = selected_model.id, selected_model.label
        else:
            model_id, native_model = parsed

        effort: str | None = None
        native_effort: str | None = None
        effort_picker = await self._effort_picker(page)
        if effort_picker is not None:
            native_effort = await _locator_label(effort_picker)
            effort = _normalize_effort(native_effort) or _normalize_effort(
                await effort_picker.get_attribute("data-testid")
            )
            if effort is None:
                selected_effort = await self._selected_effort_from_menu(page)
                if selected_effort is not None:
                    effort = selected_effort.id
                    native_effort = selected_effort.label

        return InferenceState(
            model=model_id,
            effort=effort,
            native_model=native_model,
            native_effort=native_effort or None,
            verified=True,
        )

    async def configure_inference(self, page: Page, selection: InferenceSelection) -> ActionEvidence:
        await self.ensure_authenticated(page)
        selected_model = await self._select_model(page, selection.model)
        selected_effort: _Choice | None = None
        if selection.effort is not None:
            selected_effort = await self._select_effort(page, selection.effort)

        state = await self.read_inference_state(page)
        evidence = self.verified_inference_evidence(selection, state)
        evidence.data["selected_native_model_id"] = selected_model.native_id
        if selected_effort is not None:
            evidence.data["selected_native_effort_id"] = selected_effort.native_id
        return evidence

    async def discover_models(self, page: Page) -> list[ProviderModel]:
        await self.ensure_authenticated(page)
        original = await self.read_inference_state(page)
        choices = await self._model_options(page)
        discovered: list[ProviderModel] = []
        try:
            # The picker is open after _model_options(). Selecting by freshly
            # collected locator avoids reopening it for the first candidate.
            for index, choice in enumerate(choices):
                if index == 0:
                    await choice.locator.click()
                    await asyncio.sleep(0.1)
                else:
                    await self._select_model(page, choice.id)
                efforts = [item.id for item in await self._effort_options(page)]
                # Always dismiss a picker opened for discovery, including when
                # its entries could not be normalized.
                await _close_popup(page)
                discovered.append(
                    ProviderModel(
                        id=choice.id,
                        provider=self.provider,
                        display_name=choice.label,
                        supported_efforts=efforts,
                        native_id=choice.native_id,
                        native_label=choice.label,
                    )
                )
        finally:
            if original is not None:
                try:
                    await self._select_model(page, original.model)
                    if original.effort is not None:
                        await self._select_effort(page, original.effort)
                except Exception:
                    # Discovery is non-destructive with respect to messages.
                    # A later run still configures and verifies inference before
                    # send, so restoration failure cannot cause silent fallback.
                    pass
        return discovered
