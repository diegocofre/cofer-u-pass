from __future__ import annotations

import json
from importlib import resources
from typing import Type

from cofer_u_pass.adapters.base import AdapterManifest, AdapterRules, ProviderAdapter


class AdapterRegistry:
    def __init__(self):
        from cofer_u_pass.adapters.generic.adapter import GenericAdapter
        from cofer_u_pass.adapters.chatgpt.diagnostic import ChatGPTAdapter
        from cofer_u_pass.adapters.gemini.adapter import GeminiAdapter
        from cofer_u_pass.adapters.deepseek.adapter import DeepSeekAdapter
        self._types: dict[str, Type[ProviderAdapter]] = {
            "generic": GenericAdapter,
            "chatgpt": ChatGPTAdapter,
            "gemini": GeminiAdapter,
            "deepseek": DeepSeekAdapter,
        }

    def providers(self) -> list[str]:
        return sorted(self._types)

    def create(self, provider: str) -> ProviderAdapter:
        provider = provider.lower()
        cls = self._types.get(provider)
        if not cls:
            raise KeyError(f"unknown provider: {provider}")
        package = f"cofer_u_pass.adapters.{provider}"
        package_files = resources.files(package)
        rules = AdapterRules.model_validate(json.loads(package_files.joinpath("rules.json").read_text(encoding="utf-8")))
        manifest = AdapterManifest.model_validate(json.loads(package_files.joinpath("manifest.json").read_text(encoding="utf-8")))
        if manifest.provider != rules.provider or manifest.provider != provider:
            raise ValueError(f"adapter manifest/rules provider mismatch for {provider}")
        if manifest.rule_version != rules.version or manifest.rule_schema_version != rules.schema_version:
            raise ValueError(f"adapter manifest/rules version mismatch for {provider}")
        if set(manifest.allowed_origins) != set(rules.allowed_origins):
            raise ValueError(f"adapter manifest/rules origin mismatch for {provider}")
        if set(manifest.capabilities) != set(rules.capabilities):
            raise ValueError(f"adapter manifest/rules capability mismatch for {provider}")
        if manifest.engine_contract.split('.')[0] != '1':
            raise ValueError(f"adapter {provider} requires unsupported engine contract {manifest.engine_contract}")
        return cls(rules, manifest)
