from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.exceptions import PRIVATE_RESPONSE_HEADERS


REQUEST_BODY_TOO_LARGE_MESSAGE = "请求体超过大小限制"


class RequestBodyTooLargeError(RuntimeError):
    pass


class RequestBodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_body_size_bytes: int) -> None:
        self.app = app
        self.max_body_size_bytes = max_body_size_bytes

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = _content_length(scope)
        if (
            content_length is not None
            and content_length > self.max_body_size_bytes
        ):
            await self._reject(scope, receive, send)
            return

        received_bytes = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_body_size_bytes:
                    raise RequestBodyTooLargeError
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except RequestBodyTooLargeError:
            if response_started:
                raise
            await self._reject(scope, receive, send)

    async def _reject(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        response = JSONResponse(
            status_code=413,
            content={
                "message": REQUEST_BODY_TOO_LARGE_MESSAGE,
                "detail": REQUEST_BODY_TOO_LARGE_MESSAGE,
            },
            headers=PRIVATE_RESPONSE_HEADERS,
        )
        await response(scope, receive, send)


def _content_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", []):
        if name != b"content-length":
            continue
        try:
            parsed = int(value.decode("ascii"))
        except (UnicodeDecodeError, ValueError):
            return None
        return parsed if parsed >= 0 else None
    return None
