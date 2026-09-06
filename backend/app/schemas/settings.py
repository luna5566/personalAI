from pydantic import BaseModel, Field


class RuntimeSettingsRead(BaseModel):
    app_env: str
    llm_provider: str
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_base_url_configured: bool
    llm_api_key_configured: bool
    embedding_provider: str
    embedding_base_url: str | None = None
    embedding_model: str
    embedding_dimensions: int
    embedding_base_url_configured: bool
    embedding_api_key_configured: bool
    storage_backend: str
    ocr_provider: str
    ocr_base_url: str | None = None
    ocr_model: str
    ocr_base_url_configured: bool
    ocr_api_key_configured: bool
    speech_to_text_provider: str
    speech_to_text_base_url: str | None = None
    speech_to_text_model: str
    speech_to_text_base_url_configured: bool
    speech_to_text_api_key_configured: bool


class RuntimeSettingsUpdate(BaseModel):
    llm_provider: str = Field(min_length=1, max_length=64)
    llm_base_url: str | None = Field(default=None, max_length=500)
    llm_model: str | None = Field(default=None, max_length=255)
    llm_api_key: str | None = Field(default=None, max_length=500)
    clear_llm_api_key: bool = False
    embedding_provider: str = Field(min_length=1, max_length=64)
    embedding_base_url: str | None = Field(default=None, max_length=500)
    embedding_model: str = Field(min_length=1, max_length=255)
    embedding_dimensions: int = Field(ge=1, le=4096)
    embedding_api_key: str | None = Field(default=None, max_length=500)
    clear_embedding_api_key: bool = False
    ocr_provider: str | None = Field(default=None, min_length=1, max_length=64)
    ocr_base_url: str | None = Field(default=None, max_length=500)
    ocr_model: str | None = Field(default=None, max_length=255)
    ocr_api_key: str | None = Field(default=None, max_length=500)
    clear_ocr_api_key: bool = False
    speech_to_text_provider: str | None = Field(default=None, min_length=1, max_length=64)
    speech_to_text_base_url: str | None = Field(default=None, max_length=500)
    speech_to_text_model: str | None = Field(default=None, max_length=255)
    speech_to_text_api_key: str | None = Field(default=None, max_length=500)
    clear_speech_to_text_api_key: bool = False
