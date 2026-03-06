from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Dict, Iterable, Mapping


_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,31}$")


@dataclass(frozen=True)
class ProviderSpec:
    slug: str
    label: str
    base_url: str
    model: str
    wire_api: str = "chat"


def _normalize_slug(value: str) -> str:
    return (value or "").strip().lower()


def _normalize_wire_api(value: str) -> str:
    raw = (value or "").strip().lower()
    return "responses" if raw == "responses" else "chat"


def _safe_slug(value: str) -> bool:
    return bool(_SLUG_RE.match(value))


def _enabled_builtin_slugs() -> set[str]:
    raw = (os.getenv("WEB_BUILTIN_PROVIDERS", "") or "").strip().lower()
    known = {"deepseek", "openai", "codex"}
    if not raw:
        return set()
    if raw in {"*", "all"}:
        return set(known)
    out: set[str] = set()
    for token in raw.split(","):
        slug = _normalize_slug(token)
        if slug in known:
            out.add(slug)
    return out


def normalize_slug(value: str) -> str:
    return _normalize_slug(value)


def normalize_wire_api(value: str) -> str:
    return _normalize_wire_api(value)


def is_valid_slug(value: str) -> bool:
    return _safe_slug(_normalize_slug(value))


def _default_specs(settings) -> Dict[str, ProviderSpec]:
    defaults = {
        "deepseek": ProviderSpec(
            slug="deepseek",
            label="DEEPSEEK",
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
            wire_api=_normalize_wire_api(os.getenv("DEEPSEEK_WIRE_API", "chat")),
        ),
        "openai": ProviderSpec(
            slug="openai",
            label="OPENAI",
            base_url=settings.openai_base_url,
            model=settings.openai_model,
            wire_api=_normalize_wire_api(os.getenv("OPENAI_WIRE_API", "chat")),
        ),
        "codex": ProviderSpec(
            slug="codex",
            label="CODEX",
            base_url=settings.codex_base_url,
            model=settings.codex_model,
            wire_api=_normalize_wire_api(os.getenv("CODEX_WIRE_API", "chat")),
        ),
    }
    enabled = _enabled_builtin_slugs()
    if not enabled:
        return {}
    return {k: v for k, v in defaults.items() if k in enabled}


def _iter_extra_specs_from_json() -> Iterable[ProviderSpec]:
    raw = os.getenv("WEB_EXTRA_PROVIDERS_JSON", "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if not isinstance(data, list):
        return []

    results = []
    for item in data:
        if not isinstance(item, dict):
            continue
        slug = _normalize_slug(str(item.get("slug", "")))
        if not _safe_slug(slug):
            continue
        base_url = str(item.get("base_url", "")).strip()
        model = str(item.get("model", "")).strip()
        if not base_url or not model:
            continue
        label = str(item.get("label", "")).strip() or slug.upper()
        wire_api = _normalize_wire_api(str(item.get("wire_api", "chat")))
        results.append(
            ProviderSpec(
                slug=slug,
                label=label,
                base_url=base_url,
                model=model,
                wire_api=wire_api,
            )
        )
    return results


def _iter_extra_specs_from_list(settings) -> Iterable[ProviderSpec]:
    raw = os.getenv("WEB_EXTRA_PROVIDERS", "").strip()
    if not raw:
        return []
    out = []
    for token in raw.split(","):
        slug = _normalize_slug(token)
        if not _safe_slug(slug):
            continue
        prefix = slug.upper().replace("-", "_")
        base_url = os.getenv(f"{prefix}_BASE_URL", settings.openai_base_url).strip()
        model = os.getenv(f"{prefix}_MODEL", settings.openai_model).strip()
        label = os.getenv(f"{prefix}_LABEL", slug.upper()).strip() or slug.upper()
        wire_api = _normalize_wire_api(os.getenv(f"{prefix}_WIRE_API", "chat"))
        if not base_url or not model:
            continue
        out.append(
            ProviderSpec(
                slug=slug,
                label=label,
                base_url=base_url,
                model=model,
                wire_api=wire_api,
            )
        )
    return out


def get_provider_specs(settings) -> Dict[str, ProviderSpec]:
    specs = _default_specs(settings)

    for spec in _iter_extra_specs_from_json():
        specs[spec.slug] = spec
    for spec in _iter_extra_specs_from_list(settings):
        specs[spec.slug] = spec

    return specs


def merge_provider_specs(
    base_specs: Mapping[str, ProviderSpec],
    extra_specs: Iterable[ProviderSpec],
    allow_override: bool = False,
) -> Dict[str, ProviderSpec]:
    merged = dict(base_specs)
    for spec in extra_specs:
        if not spec.slug:
            continue
        if (not allow_override) and spec.slug in merged:
            continue
        merged[spec.slug] = spec
    return merged
