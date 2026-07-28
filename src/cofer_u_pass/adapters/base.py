from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from abc import ABC
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from playwright.async_api import Locator, Page, TimeoutError as PlaywrightTimeoutError
from pydantic import BaseModel, ConfigDict, Field

from cofer_u_pass.domain.blocks import block_to_markdown, block_to_text
from cofer_u_pass.domain.errors import AdapterActionError, AdapterMismatch, AuthenticationRequired, TransientFailure
from cofer_u_pass.domain.models import Block, FailureClass, InferenceSelection, InferenceState, ProviderModel

EventCallback = Callable[[str, dict[str, Any]], Awaitable[None]]


class LocatorRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = "css"
    value: str
    name: str | None = None
    exact: bool = False


class AdapterManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "1.0"
    provider: str
    adapter_version: str
    engine_contract: str = "1.0"
    rule_version: str
    rule_schema_version: str = "1.0"
    capabilities: list[str]
    allowed_origins: list[str]
    supports_headless_execution: bool = False
    supports_headless_authentication_check: bool = False
    compatibility: dict[str, str] = Field(default_factory=dict)


class AdapterRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "1.0"
    provider: str
    version: str
    home_url: str
    allowed_origins: list[str]
    auth_origins: list[str] = Field(default_factory=list)
    capabilities: list[str]
    authenticated: list[LocatorRule]
    unauthenticated: list[LocatorRule] = Field(default_factory=list)
    message_input: list[LocatorRule]
    send_button: list[LocatorRule] = Field(default_factory=list)
    user_message: list[LocatorRule] = Field(default_factory=list)
    response: list[LocatorRule]
    generation_active: list[LocatorRule] = Field(default_factory=list)
    attachment_input: list[LocatorRule] = Field(default_factory=list)
    attachment_button: list[LocatorRule] = Field(default_factory=list)
    attachment_ready: list[LocatorRule] = Field(default_factory=list)
    artifact: list[LocatorRule] = Field(default_factory=list)


@dataclass(slots=True)
class ActionEvidence:
    data: dict[str, Any]


CANONICALIZE_JS = r"""
(el) => {
  function textNode(value) { return {type:'text', text:value, children:[], attrs:{}}; }
  function walk(node) {
    if (node.nodeType === Node.TEXT_NODE) {
      const t = node.textContent || '';
      return t ? textNode(t) : null;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return null;
    const tag = node.tagName.toLowerCase();
    if (['script','style','svg','button'].includes(tag)) return null;
    const children = Array.from(node.childNodes).map(walk).filter(Boolean);
    const direct = Array.from(node.childNodes)
      .filter(n => n.nodeType === Node.TEXT_NODE)
      .map(n => n.textContent || '').join('').trim();
    if (/^h[1-6]$/.test(tag)) return {type:'heading', level:Number(tag[1]), text:(node.innerText||'').trim(), children:[], attrs:{}};
    if (tag === 'p') return {type:'paragraph', text: direct || null, children, attrs:{}};
    if (tag === 'pre') {
      const code = node.querySelector('code');
      const cls = code ? (code.className || '') : '';
      const m = String(cls).match(/language-([\w+-]+)/);
      return {type:'code', text:(code ? code.innerText : node.innerText)||'', language:m ? m[1] : null, children:[], attrs:{}};
    }
    if (tag === 'code') return {type:'code', text:node.innerText||'', language:null, children:[], attrs:{}};
    if (tag === 'blockquote') return {type:'blockquote', text:null, children, attrs:{}};
    if (tag === 'ul' || tag === 'ol') return {type:'list', text:null, children, attrs:{ordered:tag==='ol'}};
    if (tag === 'li') return {type:'list_item', text: direct || null, children, attrs:{}};
    if (tag === 'a') return {type:'link', text:(node.innerText||'').trim(), href:node.href||null, children:[], attrs:{}};
    if (tag === 'img') return {type:'image', text:node.alt||'', href:node.src||null, children:[], attrs:{}};
    if (tag === 'hr') return {type:'thematic_break', text:null, children:[], attrs:{}};
    if (tag === 'br') return textNode('\n');
    if (children.length === 1 && children[0].type === 'text') return children[0];
    return {type:'unknown', text: direct || null, children, attrs:{tag}};
  }
  const children = Array.from(el.childNodes).map(walk).filter(Boolean);
  return {type:'document', text:null, children, attrs:{}};
}
"""

MUTATION_INIT_JS = r"""
(el) => {
  window.__coferUPassMutations = [];
  if (window.__coferUPassObserver) window.__coferUPassObserver.disconnect();
  window.__coferUPassObserver = new MutationObserver((mutations) => {
    for (const m of mutations) {
      window.__coferUPassMutations.push({
        type:m.type,
        added:m.addedNodes ? m.addedNodes.length : 0,
        removed:m.removedNodes ? m.removedNodes.length : 0,
        ts:Date.now()
      });
    }
  });
  window.__coferUPassObserver.observe(el, {subtree:true, childList:true, characterData:true});
}
"""


class ProviderAdapter(ABC):
    provider: str
    adapter_version = "1.0.0"
    rule_filename = "rules.json"

    def __init__(self, rules: AdapterRules, manifest: AdapterManifest):
        self.rules = rules
        self.manifest = manifest
        self.provider = rules.provider
        self.adapter_version = manifest.adapter_version
        self._response_count_before_send = 0

    @property
    def capabilities(self) -> set[str]:
        return set(self.manifest.capabilities)

    @property
    def allowed_origins(self) -> set[str]:
        return set(self.rules.allowed_origins) | set(self.rules.auth_origins)

    @property
    def supports_headless_execution(self) -> bool:
        return self.manifest.supports_headless_execution

    @property
    def supports_headless_authentication_check(self) -> bool:
        return self.manifest.supports_headless_authentication_check

    async def _locator_from_rule(self, page: Page, rule: LocatorRule) -> Locator:
        if rule.kind == "role":
            return page.get_by_role(rule.value, name=rule.name, exact=rule.exact)
        if rule.kind == "label":
            return page.get_by_label(rule.value, exact=rule.exact)
        if rule.kind == "placeholder":
            return page.get_by_placeholder(rule.value, exact=rule.exact)
        if rule.kind == "text":
            return page.get_by_text(rule.value, exact=rule.exact)
        if rule.kind == "css":
            return page.locator(rule.value)
        raise AdapterMismatch(f"unsupported locator rule kind: {rule.kind}")

    async def resolve(self, page: Page, rules: list[LocatorRule], *, visible: bool = True, unique: bool = True) -> Locator:
        diagnostics: list[str] = []
        for rule in rules:
            loc = await self._locator_from_rule(page, rule)
            try:
                count = await loc.count()
            except Exception as exc:
                diagnostics.append(f"{rule.kind}:{rule.value}: {exc}")
                continue
            if count == 0:
                diagnostics.append(f"{rule.kind}:{rule.value}: no match")
                continue
            candidates: list[Locator] = []
            for i in range(count):
                candidate = loc.nth(i)
                if not visible or await candidate.is_visible():
                    candidates.append(candidate)
            if not candidates:
                diagnostics.append(f"{rule.kind}:{rule.value}: no visible match")
                continue
            if unique and len(candidates) != 1:
                diagnostics.append(f"{rule.kind}:{rule.value}: ambiguous ({len(candidates)} visible)")
                continue
            return candidates[0]
        raise AdapterMismatch("locator resolution failed: " + "; ".join(diagnostics[-8:]))

    async def _has_visible_match(self, page: Page, rules: list[LocatorRule]) -> bool:
        for rule in rules:
            try:
                loc = await self._locator_from_rule(page, rule)
                if await loc.count() and await loc.first.is_visible():
                    return True
            except Exception:
                continue
        return False

    async def is_authenticated(self, page: Page) -> bool:
        # Some providers expose a usable composer to anonymous visitors.  A
        # positive application signal is therefore insufficient when the page
        # simultaneously exposes an explicit login/signup state.
        if self.rules.unauthenticated and await self._has_visible_match(page, self.rules.unauthenticated):
            return False
        return await self._has_visible_match(page, self.rules.authenticated)

    async def navigate_home(self, page: Page) -> None:
        await page.goto(self.rules.home_url, wait_until="domcontentloaded")

    async def wait_until_authenticated(
        self,
        page: Page,
        *,
        timeout_seconds: float = 15.0,
        poll_seconds: float = 0.5,
    ) -> bool:
        """Wait for the provider's authenticated application state to become observable.

        Provider shells often mount asynchronously after DOMContentLoaded.  Keeping
        this bounded wait in the adapter contract prevents callers from making
        inconsistent one-shot authentication decisions.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0.0, timeout_seconds)
        while True:
            if await self.is_authenticated(page):
                return True
            remaining = deadline - loop.time()
            if remaining <= 0:
                return False
            await asyncio.sleep(min(max(0.05, poll_seconds), remaining))

    async def ensure_authenticated(
        self,
        page: Page,
        *,
        timeout_seconds: float = 15.0,
        poll_seconds: float = 0.5,
    ) -> None:
        if not await self.wait_until_authenticated(
            page, timeout_seconds=timeout_seconds, poll_seconds=poll_seconds
        ):
            raise AuthenticationRequired(f"profile is not authenticated for {self.provider}")

    async def open_conversation(self, page: Page, mode: str, conversation: dict[str, Any] | None = None) -> ActionEvidence:
        await self.navigate_home(page)
        await self.ensure_authenticated(page)
        if mode in {"continue", "imported"}:
            if not conversation or not conversation.get("url"):
                raise AdapterMismatch("explicit continuation requires an imported conversation URL")
            await page.goto(conversation["url"], wait_until="domcontentloaded")
            await self.ensure_authenticated(page)
        return ActionEvidence({"url": page.url, "conversation_external_id": self.extract_conversation_id(page.url)})

    def extract_conversation_id(self, url: str) -> str | None:
        return None

    async def discover_models(self, page: Page) -> list[ProviderModel]:
        """Return provider models visible to the authenticated account.

        Model discovery is optional.  Adapters must advertise
        `inference.model.discover` before callers depend on this method.
        """
        return []

    async def read_inference_state(self, page: Page) -> InferenceState | None:
        """Read effective inference state when the provider exposes it reliably."""
        return None

    def verified_inference_evidence(
        self,
        selection: InferenceSelection,
        state: InferenceState | None,
    ) -> ActionEvidence:
        if state is None or not state.verified:
            raise AdapterMismatch("provider inference state could not be verified")
        if state.model != selection.model:
            raise AdapterMismatch(
                f"provider selected model {state.model!r}; requested {selection.model!r}"
            )
        if selection.effort is not None and state.effort != selection.effort:
            raise AdapterMismatch(
                f"provider selected effort {state.effort!r}; requested {selection.effort!r}"
            )
        return ActionEvidence({
            "requested_model": selection.model,
            "requested_effort": selection.effort,
            "effective_model": state.model,
            "effective_effort": state.effort,
            "native_model": state.native_model,
            "native_effort": state.native_effort,
            "verified": True,
            "metadata": state.metadata,
        })

    async def configure_inference(self, page: Page, selection: InferenceSelection) -> ActionEvidence:
        """Apply and verify provider inference selection.

        Provider-specific adapters override this method.  The default fails closed
        rather than pretending inference selection succeeded.
        """
        raise AdapterMismatch(f"adapter {self.provider} does not support inference selection")

    async def attach_files(self, page: Page, files: list[Path]) -> ActionEvidence:
        if not files:
            return ActionEvidence({"files": []})
        try:
            input_locator = await self.resolve(page, self.rules.attachment_input, visible=False)
        except AdapterMismatch:
            if not self.rules.attachment_button:
                raise
            button = await self.resolve(page, self.rules.attachment_button)
            await button.click()
            input_locator = await self.resolve(page, self.rules.attachment_input, visible=False)
        effect_possible = False
        try:
            await input_locator.set_input_files([str(p) for p in files])
            effect_possible = True
            if self.rules.attachment_ready:
                await self.resolve(page, self.rules.attachment_ready, unique=False)
            return ActionEvidence({"files": [p.name for p in files], "count": len(files)})
        except AdapterActionError:
            raise
        except Exception as exc:
            raise AdapterActionError(
                f"attachment upload could not be confirmed: {exc}",
                failure_class=FailureClass.OUTCOME_UNKNOWN if effect_possible else FailureClass.ADAPTER_MISMATCH,
                external_effect_possible=effect_possible,
            ) from exc

    async def _collection_count(self, page: Page, rules: list[LocatorRule]) -> int:
        counts = []
        for rule in rules:
            try:
                counts.append(await (await self._locator_from_rule(page, rule)).count())
            except Exception:
                continue
        return max(counts, default=0)

    async def send_message(self, page: Page, text: str) -> ActionEvidence:
        self._response_count_before_send = await self._collection_count(page, self.rules.response)
        user_count_before = 0
        if self.rules.user_message:
            try:
                user_count_before = await (await self.resolve(page, self.rules.user_message, unique=False)).count()
            except AdapterMismatch:
                user_count_before = 0
        input_locator = await self.resolve(page, self.rules.message_input)
        await input_locator.fill(text)
        external_effect_possible = False
        try:
            if self.rules.send_button:
                button = await self.resolve(page, self.rules.send_button)
                await button.click()
            else:
                await input_locator.press("Enter")
            external_effect_possible = True
            # A sent-message count increase is strongest evidence. Fallback: input cleared and response starts.
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                if self.rules.user_message:
                    try:
                        count = await (await self.resolve(page, self.rules.user_message, unique=False)).count()
                        if count > user_count_before:
                            return ActionEvidence({"submitted": True, "user_message_count": count, "response_count_before": self._response_count_before_send})
                    except AdapterMismatch:
                        pass
                value = await input_locator.input_value() if await input_locator.evaluate("el => 'value' in el") else (await input_locator.text_content() or "")
                responses = await self._collection_count(page, self.rules.response)
                if not str(value).strip() and responses > self._response_count_before_send:
                    return ActionEvidence({"submitted": True, "response_started": True, "response_count": responses, "response_count_before": self._response_count_before_send})
                await asyncio.sleep(0.2)
            raise AdapterActionError(
                "message submission could not be confirmed",
                failure_class=FailureClass.OUTCOME_UNKNOWN,
                external_effect_possible=True,
            )
        except AdapterActionError:
            raise
        except Exception as exc:
            raise AdapterActionError(
                f"message submission failed: {exc}",
                failure_class=FailureClass.OUTCOME_UNKNOWN if external_effect_possible else FailureClass.TRANSIENT,
                external_effect_possible=external_effect_possible,
            ) from exc

    async def generation_active(self, page: Page) -> bool:
        for rule in self.rules.generation_active:
            try:
                loc = await self._locator_from_rule(page, rule)
                for i in range(await loc.count()):
                    if await loc.nth(i).is_visible():
                        return True
            except Exception:
                pass
        return False

    async def capture_response(
        self,
        page: Page,
        *,
        timeout_seconds: float,
        stability_seconds: float,
        emit: EventCallback,
    ) -> tuple[Block, dict[str, Any]]:
        deadline = time.monotonic() + timeout_seconds
        target: Locator | None = None
        while time.monotonic() < deadline:
            try:
                responses = await self.resolve(page, self.rules.response, unique=False)
                count = await responses.count()
                if count > self._response_count_before_send or (self._response_count_before_send == 0 and count > 0):
                    target = responses.nth(count - 1)
                    if await target.is_visible():
                        break
            except AdapterMismatch:
                pass
            await asyncio.sleep(0.2)
        if target is None:
            raise TransientFailure("timed out waiting for provider response")

        await target.evaluate(MUTATION_INIT_JS)
        await emit("response.started", {"provider": self.provider})
        last_html = ""
        last_change = time.monotonic()
        sequence = 0
        saw_active = False
        while time.monotonic() < deadline:
            observed = await page.evaluate("() => (window.__coferUPassMutations || []).splice(0)")
            for mutation in observed:
                if mutation.get("removed", 0) and not mutation.get("added", 0):
                    mutation_kind = "remove"
                elif mutation.get("added", 0) and not mutation.get("removed", 0):
                    mutation_kind = "append"
                else:
                    mutation_kind = "replace"
                sequence += 1
                await emit("response.delta", {
                    "kind": mutation_kind, "sequence": sequence, "source": "mutation_observer",
                    "mutation": mutation,
                })
            html = await target.inner_html()
            active = await self.generation_active(page)
            saw_active = saw_active or active
            if html != last_html:
                delta = html[len(last_html):] if html.startswith(last_html) else html
                kind = "append" if html.startswith(last_html) else "replace"
                sequence += 1
                await emit("response.delta", {"kind": kind, "sequence": sequence, "source": "reconciliation", "html": delta})
                last_html = html
                last_change = time.monotonic()
            stable = time.monotonic() - last_change >= stability_seconds
            if stable and not active and (saw_active or sequence > 0):
                break
            await asyncio.sleep(0.2)
        else:
            raise TransientFailure("response did not reach a stable completed state")

        data = await target.evaluate(CANONICALIZE_JS)
        block = Block.model_validate(data)
        markdown = block_to_markdown(block)
        text = block_to_text(block)
        mutations = await page.evaluate("() => window.__coferUPassMutations || []")
        await emit("response.completed", {"markdown": markdown, "text": text, "mutation_count": len(mutations)})
        return block, {"url": page.url, "mutation_count": len(mutations), "markdown": markdown, "text": text}

    async def download_artifacts(self, page: Page, download_dir: Path) -> list[tuple[Path, str]]:
        if not self.rules.artifact:
            return []
        try:
            loc = await self.resolve(page, self.rules.artifact, unique=False)
        except AdapterMismatch:
            return []
        results: list[tuple[Path, str]] = []
        count = min(await loc.count(), 50)
        download_dir.mkdir(parents=True, exist_ok=True)
        for i in range(count):
            item = loc.nth(i)
            if not await item.is_visible():
                continue
            href = await item.get_attribute("href")
            label = (await item.text_content() or f"artifact-{i+1}").strip()
            try:
                async with page.expect_download(timeout=5000) as info:
                    await item.click()
                download = await info.value
                suggested = Path(download.suggested_filename).name
                target = download_dir / f"{uuid.uuid4()}-{suggested}"
                await download.save_as(target)
                results.append((target, href or label))
            except PlaywrightTimeoutError:
                # A visible artifact control that did not produce a browser download is ignored,
                # rather than using provider-controlled paths or executing it.
                continue
        return results

    async def reconcile(self, page: Page, checkpoint: dict[str, Any]) -> bool:
        expected_url = checkpoint.get("current_url")
        if expected_url:
            await page.goto(expected_url, wait_until="domcontentloaded")
        await self.ensure_authenticated(page)
        logical = checkpoint.get("logical_state") or {}
        action_type = logical.get("action_type")
        evidence = checkpoint.get("evidence") or {}
        if action_type == "checkpoint" and isinstance(evidence.get("prior"), dict):
            prior = evidence["prior"]
            action_type = prior.get("action_type")
            evidence = prior.get("evidence") or {}
        if action_type in {None, "open_conversation", "finalize", "download_artifacts"}:
            if expected_url:
                expected = urlparse(expected_url)
                current = urlparse(page.url)
                if (expected.scheme, expected.netloc, expected.path) != (current.scheme, current.netloc, current.path):
                    return False
            return True
        if action_type == "configure_inference":
            requested_model = evidence.get("requested_model")
            requested_effort = evidence.get("requested_effort")
            if not isinstance(requested_model, str):
                return False
            state = await self.read_inference_state(page)
            if state is None or not state.verified or state.model != requested_model:
                return False
            if requested_effort is not None and state.effort != requested_effort:
                return False
            return True
        if action_type == "send_message":
            expected_users = evidence.get("user_message_count")
            if isinstance(expected_users, int) and self.rules.user_message:
                return await self._collection_count(page, self.rules.user_message) >= expected_users
            expected_responses = evidence.get("response_count")
            if isinstance(expected_responses, int):
                return await self._collection_count(page, self.rules.response) >= expected_responses
            return False
        if action_type == "capture_response":
            expected_text = evidence.get("text")
            if not isinstance(expected_text, str):
                return False
            try:
                responses = await self.resolve(page, self.rules.response, unique=False)
            except AdapterMismatch:
                return False
            for i in range(await responses.count()):
                candidate = responses.nth(i)
                if not await candidate.is_visible():
                    continue
                try:
                    data = await candidate.evaluate(CANONICALIZE_JS)
                    block = Block.model_validate(data)
                    if block_to_text(block).strip() == expected_text.strip():
                        return True
                except Exception:
                    continue
            return False
        return False
