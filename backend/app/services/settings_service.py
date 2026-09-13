import hashlib
import os
import tempfile
import threading
from pathlib import Path
from uuid import UUID

from app.ai.embedding_provider import build_embedding_index_id
from app.core.config import DATABASE_VECTOR_DIMENSIONS, settings
from app.schemas.settings import RuntimeSettingsRead, RuntimeSettingsUpdate

ENV_PATH = Path(".env")
ALLOWED_LLM_PROVIDERS = {"local_extractive", "openai_compatible"}
ALLOWED_EMBEDDING_PROVIDERS = {"local_hash", "openai_compatible"}
ALLOWED_OCR_PROVIDERS = {"disabled", "openai_compatible"}
ALLOWED_SPEECH_TO_TEXT_PROVIDERS = {"disabled", "openai_compatible"}
EDITABLE_ENVIRONMENTS = {"local", "dev", "development"}
_RUNTIME_SETTINGS_UPDATE_LOCK = threading.Lock()


class RuntimeSettingsAccessError(PermissionError):
    pass


class RuntimeSettingsValidationError(ValueError):
    pass


def ensure_runtime_settings_access(user_id: UUID, *, write: bool = False) -> None:
    if user_id != settings.runtime_settings_admin_user_id:
        raise RuntimeSettingsAccessError("只有管理员可以访问模型设置")
    if write and settings.app_env.lower() not in EDITABLE_ENVIRONMENTS:
        raise RuntimeSettingsAccessError("当前环境不允许在线修改模型设置")


def runtime_settings_read() -> RuntimeSettingsRead:
    return RuntimeSettingsRead(
        app_env=settings.app_env,
        llm_provider=settings.llm_provider,
        llm_base_url=settings.llm_base_url,
        llm_model=settings.llm_model,
        llm_base_url_configured=bool(settings.llm_base_url),
        llm_api_key_configured=bool(settings.llm_api_key),
        embedding_provider=settings.embedding_provider,
        embedding_base_url=settings.embedding_base_url,
        embedding_model=settings.embedding_model,
        embedding_dimensions=settings.embedding_dimensions,
        embedding_base_url_configured=bool(settings.embedding_base_url),
        embedding_api_key_configured=bool(settings.embedding_api_key),
        storage_backend=settings.storage_backend,
        ocr_provider=settings.ocr_provider,
        ocr_base_url=settings.ocr_base_url,
        ocr_model=settings.ocr_model,
        ocr_base_url_configured=bool(settings.ocr_base_url),
        ocr_api_key_configured=bool(settings.ocr_api_key),
        speech_to_text_provider=settings.speech_to_text_provider,
        speech_to_text_base_url=settings.speech_to_text_base_url,
        speech_to_text_model=settings.speech_to_text_model,
        speech_to_text_base_url_configured=bool(settings.speech_to_text_base_url),
        speech_to_text_api_key_configured=bool(settings.speech_to_text_api_key),
    )


def embedding_configuration_fingerprint() -> str:
    index_id = embedding_index_id()
    if settings.embedding_provider != "openai_compatible":
        return index_id
    credential_hash = hashlib.sha256(
        (settings.embedding_api_key or "").encode("utf-8")
    ).hexdigest()[:16]
    return f"{index_id}:credential-{credential_hash}"


def embedding_index_id() -> str:
    return build_embedding_index_id(
        provider=settings.embedding_provider,
        base_url=settings.embedding_base_url,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
    )


def update_runtime_settings(payload: RuntimeSettingsUpdate) -> RuntimeSettingsRead:
    with _RUNTIME_SETTINGS_UPDATE_LOCK:
        return _update_runtime_settings(payload)


def _update_runtime_settings(payload: RuntimeSettingsUpdate) -> RuntimeSettingsRead:
    if payload.llm_provider not in ALLOWED_LLM_PROVIDERS:
        raise RuntimeSettingsValidationError("不支持的 LLM Provider")
    if payload.embedding_provider not in ALLOWED_EMBEDDING_PROVIDERS:
        raise RuntimeSettingsValidationError("不支持的 Embedding Provider")
    if payload.embedding_dimensions != DATABASE_VECTOR_DIMENSIONS:
        raise RuntimeSettingsValidationError(
            f"当前数据库向量维度固定为 {DATABASE_VECTOR_DIMENSIONS}"
        )
    if payload.ocr_provider is not None and payload.ocr_provider not in ALLOWED_OCR_PROVIDERS:
        raise RuntimeSettingsValidationError("不支持的 OCR Provider")
    if (
        payload.speech_to_text_provider is not None
        and payload.speech_to_text_provider not in ALLOWED_SPEECH_TO_TEXT_PROVIDERS
    ):
        raise RuntimeSettingsValidationError("不支持的语音转文字 Provider")
    _validate_provider_configuration(payload)

    updates: dict[str, str] = {
        "LLM_PROVIDER": payload.llm_provider,
        "LLM_BASE_URL": _clean_optional(payload.llm_base_url),
        "LLM_MODEL": _clean_optional(payload.llm_model),
        "EMBEDDING_PROVIDER": payload.embedding_provider,
        "EMBEDDING_BASE_URL": _clean_optional(payload.embedding_base_url),
        "EMBEDDING_MODEL": payload.embedding_model.strip(),
        "EMBEDDING_DIMENSIONS": str(payload.embedding_dimensions),
    }
    if payload.clear_llm_api_key:
        updates["LLM_API_KEY"] = ""
    elif payload.llm_api_key is not None and payload.llm_api_key.strip():
        updates["LLM_API_KEY"] = payload.llm_api_key.strip()

    if payload.clear_embedding_api_key:
        updates["EMBEDDING_API_KEY"] = ""
    elif payload.embedding_api_key is not None and payload.embedding_api_key.strip():
        updates["EMBEDDING_API_KEY"] = payload.embedding_api_key.strip()

    if payload.ocr_provider is not None:
        updates.update(
            {
                "OCR_PROVIDER": payload.ocr_provider,
                "OCR_BASE_URL": _clean_optional(payload.ocr_base_url),
                "OCR_MODEL": _clean_optional(payload.ocr_model) or settings.ocr_model,
            }
        )
        if payload.clear_ocr_api_key:
            updates["OCR_API_KEY"] = ""
        elif payload.ocr_api_key is not None and payload.ocr_api_key.strip():
            updates["OCR_API_KEY"] = payload.ocr_api_key.strip()

    if payload.speech_to_text_provider is not None:
        updates.update(
            {
                "SPEECH_TO_TEXT_PROVIDER": payload.speech_to_text_provider,
                "SPEECH_TO_TEXT_BASE_URL": _clean_optional(payload.speech_to_text_base_url),
                "SPEECH_TO_TEXT_MODEL": _clean_optional(payload.speech_to_text_model)
                or settings.speech_to_text_model,
            }
        )
        if payload.clear_speech_to_text_api_key:
            updates["SPEECH_TO_TEXT_API_KEY"] = ""
        elif payload.speech_to_text_api_key is not None and payload.speech_to_text_api_key.strip():
            updates["SPEECH_TO_TEXT_API_KEY"] = payload.speech_to_text_api_key.strip()

    _write_env_updates(ENV_PATH, updates)
    _apply_runtime_updates(updates)
    return runtime_settings_read()


def _apply_runtime_updates(updates: dict[str, str]) -> None:
    key_to_attr = {
        "LLM_PROVIDER": "llm_provider",
        "LLM_BASE_URL": "llm_base_url",
        "LLM_API_KEY": "llm_api_key",
        "LLM_MODEL": "llm_model",
        "EMBEDDING_PROVIDER": "embedding_provider",
        "EMBEDDING_BASE_URL": "embedding_base_url",
        "EMBEDDING_API_KEY": "embedding_api_key",
        "EMBEDDING_MODEL": "embedding_model",
        "EMBEDDING_DIMENSIONS": "embedding_dimensions",
        "OCR_PROVIDER": "ocr_provider",
        "OCR_BASE_URL": "ocr_base_url",
        "OCR_API_KEY": "ocr_api_key",
        "OCR_MODEL": "ocr_model",
        "SPEECH_TO_TEXT_PROVIDER": "speech_to_text_provider",
        "SPEECH_TO_TEXT_BASE_URL": "speech_to_text_base_url",
        "SPEECH_TO_TEXT_API_KEY": "speech_to_text_api_key",
        "SPEECH_TO_TEXT_MODEL": "speech_to_text_model",
    }
    for key, value in updates.items():
        attr = key_to_attr[key]
        if key == "EMBEDDING_DIMENSIONS":
            setattr(settings, attr, int(value))
        else:
            setattr(settings, attr, value or None)


def _write_env_updates(path: Path, updates: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    next_lines: list[str] = []
    for line in lines:
        key = _env_key(line)
        if key is None or key not in updates:
            next_lines.append(line)
            continue
        next_lines.append(f"{key}={_format_env_value(updates[key])}")
        seen.add(key)

    for key, value in updates.items():
        if key not in seen:
            next_lines.append(f"{key}={_format_env_value(value)}")

    _atomic_write_text(path, "\n".join(next_lines) + "\n")


def _atomic_write_text(path: Path, content: str) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f"{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _env_key(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    return stripped.split("=", 1)[0].strip()


def _format_env_value(value: str) -> str:
    if value == "":
        return ""
    if any(char.isspace() for char in value) or any(char in value for char in ['"', "#", "="]):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _clean_optional(value: str | None) -> str:
    return value.strip() if value is not None else ""


def _validate_provider_configuration(payload: RuntimeSettingsUpdate) -> None:
    _require_openai_configuration(
        label="LLM",
        provider=payload.llm_provider,
        model=_next_value(payload.llm_model, settings.llm_model),
        api_key=_next_api_key(
            payload.llm_api_key,
            payload.clear_llm_api_key,
            settings.llm_api_key,
        ),
    )
    _require_openai_configuration(
        label="Embedding",
        provider=payload.embedding_provider,
        model=payload.embedding_model,
        api_key=_next_api_key(
            payload.embedding_api_key,
            payload.clear_embedding_api_key,
            settings.embedding_api_key,
        ),
    )
    _require_openai_configuration(
        label="OCR",
        provider=payload.ocr_provider or settings.ocr_provider,
        model=_next_value(payload.ocr_model, settings.ocr_model),
        api_key=_next_api_key(
            payload.ocr_api_key,
            payload.clear_ocr_api_key,
            settings.ocr_api_key,
        ),
    )
    _require_openai_configuration(
        label="语音转文字",
        provider=payload.speech_to_text_provider or settings.speech_to_text_provider,
        model=_next_value(payload.speech_to_text_model, settings.speech_to_text_model),
        api_key=_next_api_key(
            payload.speech_to_text_api_key,
            payload.clear_speech_to_text_api_key,
            settings.speech_to_text_api_key,
        ),
    )


def _require_openai_configuration(
    *,
    label: str,
    provider: str,
    model: str | None,
    api_key: str | None,
) -> None:
    if provider != "openai_compatible":
        return
    if not model or not model.strip():
        raise RuntimeSettingsValidationError(
            f"{label} 使用 openai_compatible 时必须配置模型"
        )
    if not api_key or not api_key.strip():
        raise RuntimeSettingsValidationError(
            f"{label} 使用 openai_compatible 时必须配置 API Key"
        )


def _next_value(new_value: str | None, current_value: str | None) -> str | None:
    if new_value is None:
        return current_value
    return new_value.strip() or None


def _next_api_key(
    new_value: str | None,
    clear: bool,
    current_value: str | None,
) -> str | None:
    if clear:
        return None
    return _next_value(new_value, current_value)
