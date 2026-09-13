"""锁定 .env.example 与 Settings 字段的一致性。

新增配置字段时必须在 .env.example 中同步记录（活动行或注释行均可），
否则此测试失败，避免示例配置与实际可配置项漂移。
"""

import re
from pathlib import Path

from app.core.config import Settings

ENV_EXAMPLE_PATH = Path(__file__).resolve().parents[1] / ".env.example"

_KEY_PATTERN = re.compile(r"^#?\s*([A-Z][A-Z0-9_]+)=", re.MULTILINE)


def _documented_env_keys() -> set[str]:
    content = ENV_EXAMPLE_PATH.read_text(encoding="utf-8")
    return set(_KEY_PATTERN.findall(content))


def _settings_env_names() -> set[str]:
    return {name.upper() for name in Settings.model_fields}


def test_every_documented_env_key_is_a_real_settings_field() -> None:
    unknown = _documented_env_keys() - _settings_env_names()

    assert not unknown, f".env.example 中的键不是 Settings 字段：{sorted(unknown)}"


def test_every_settings_field_is_documented_in_env_example() -> None:
    missing = _settings_env_names() - _documented_env_keys()

    assert not missing, f"Settings 字段缺少 .env.example 记录：{sorted(missing)}"
