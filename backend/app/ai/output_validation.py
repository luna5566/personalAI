PROVIDER_OUTPUT_TOO_LARGE_PUBLIC_MESSAGE = (
    "模型返回内容过长，请缩小问题或资料范围后重试"
)


class ProviderOutputTooLargeError(RuntimeError):
    pass


def validate_provider_text_length(
    value: str,
    *,
    max_length: int,
    output_name: str,
) -> str:
    if len(value) > max_length:
        raise ProviderOutputTooLargeError(
            f"{output_name} exceeded the {max_length}-character limit"
        )
    return value
