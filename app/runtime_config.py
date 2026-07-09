"""
In-memory store for DB-backed config overrides.
Loaded at startup from system_config table; updated by the admin API.
All LLM/embedding clients read from here first, falling back to env settings.
"""
_store: dict[str, str] = {}

ALLOWED_KEYS = {"api_key", "openai_api_base", "llm_model", "embedding_model"}


def get(key: str, default: str | None = None) -> str | None:
    return _store.get(key, default)


def set_many(mapping: dict[str, str]) -> None:
    _store.update({k: v for k, v in mapping.items() if k in ALLOWED_KEYS})


def set_one(key: str, value: str) -> None:
    if key in ALLOWED_KEYS:
        _store[key] = value


def delete(key: str) -> None:
    _store.pop(key, None)


def snapshot() -> dict[str, str]:
    return dict(_store)
