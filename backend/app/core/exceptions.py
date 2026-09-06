import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.pagination import PaginationError


logger = logging.getLogger(__name__)
DATABASE_UNAVAILABLE_MESSAGE = "数据库暂时不可用，请稍后重试"
VALIDATION_ERROR_MESSAGE = "请求参数不合法"
PRIVATE_RESPONSE_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
}

_VALIDATION_ERROR_MESSAGES = {
    "missing": "缺少必填字段",
    "string_too_short": "文本长度不足",
    "string_too_long": "文本长度超过限制",
    "too_short": "项目数量不足",
    "too_long": "项目数量超过限制",
    "literal_error": "输入值不符合要求",
    "enum": "输入值不在允许范围内",
    "uuid_parsing": "ID 格式无效",
    "uuid_type": "ID 格式无效",
    "int_parsing": "请输入有效整数",
    "int_type": "请输入有效整数",
    "float_parsing": "请输入有效数值",
    "float_type": "请输入有效数值",
    "finite_number": "数值格式无效",
    "bool_parsing": "请输入有效布尔值",
    "bool_type": "请输入有效布尔值",
    "greater_than": "数值低于允许范围",
    "greater_than_equal": "数值低于允许范围",
    "less_than": "数值超过允许范围",
    "less_than_equal": "数值超过允许范围",
    "list_type": "输入数据结构无效",
    "tuple_type": "输入数据结构无效",
    "set_type": "输入数据结构无效",
    "dict_type": "输入数据结构无效",
    "model_type": "输入数据结构无效",
    "json_invalid": "请求 JSON 格式无效",
    "date_parsing": "日期格式无效",
    "date_type": "日期格式无效",
    "datetime_parsing": "日期时间格式无效",
    "datetime_type": "日期时间格式无效",
    "url_parsing": "URL 格式无效",
    "url_type": "URL 格式无效",
    "extra_forbidden": "包含不允许的字段",
    "value_error": "输入内容格式无效",
}


class AppError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(PaginationError, pagination_exception_handler)
    app.add_exception_handler(AppError, app_exception_handler)
    app.add_exception_handler(OperationalError, database_unavailable_handler)
    app.add_exception_handler(SQLAlchemyTimeoutError, database_unavailable_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else "请求失败"
    return JSONResponse(
        status_code=exc.status_code,
        content={"message": message, "detail": jsonable_encoder(exc.detail)},
        headers=exc.headers,
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [
        {
            "type": str(error.get("type") or "validation_error"),
            "loc": jsonable_encoder(error.get("loc", ())),
            "msg": _public_validation_message(error),
        }
        for error in exc.errors()
    ]
    first_message = errors[0].get("msg") if errors else None
    return JSONResponse(
        status_code=422,
        content={"message": first_message or "请求参数不合法", "detail": errors},
    )


async def pagination_exception_handler(
    request: Request,
    exc: PaginationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"message": exc.message, "detail": exc.message},
    )


def _public_validation_message(error: dict) -> str:
    error_type = error.get("type")
    if error_type == "value_error":
        location = error.get("loc")
        if (
            isinstance(location, (list, tuple))
            and location
            and location[-1] == "email"
        ):
            return "邮箱格式无效"
    if not isinstance(error_type, str):
        return VALIDATION_ERROR_MESSAGE
    return _VALIDATION_ERROR_MESSAGES.get(error_type, VALIDATION_ERROR_MESSAGE)


async def app_exception_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"message": exc.message, "detail": exc.message})


async def database_unavailable_handler(
    request: Request,
    exc: OperationalError | SQLAlchemyTimeoutError,
) -> JSONResponse:
    logger.warning(
        "Database unavailable while processing %s %s (%s)",
        request.method,
        request.url.path,
        type(exc).__name__,
    )
    message = DATABASE_UNAVAILABLE_MESSAGE
    return JSONResponse(
        status_code=503,
        content={"message": message, "detail": message},
        headers={"Retry-After": str(settings.database_retry_after_seconds)},
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "Unhandled exception while processing %s %s",
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    message = "服务器内部错误"
    return JSONResponse(
        status_code=500,
        content={"message": message, "detail": message},
        headers=PRIVATE_RESPONSE_HEADERS,
    )
