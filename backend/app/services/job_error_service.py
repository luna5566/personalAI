from app.storage.storage_service import StorageBackendChangedError


class PublicJobError(RuntimeError):
    pass


def public_job_error_message(
    error: Exception,
    fallback: str,
    *,
    max_length: int = 500,
) -> str:
    if isinstance(error, (PublicJobError, StorageBackendChangedError)):
        message = str(error).strip()
        if message:
            return message[:max_length]
    return fallback[:max_length]
