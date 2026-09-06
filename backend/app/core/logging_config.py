"""应用日志配置：默认人类可读，生产可切换为结构化 JSON。"""

from __future__ import annotations

import json
import logging
import sys

from app.core.config import settings
from app.core.observability import request_id_var

JSON_LOG_FORMAT = "json"


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, str] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    if settings.log_format.strip().casefold() == JSON_LOG_FORMAT:
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(levelname)s %(name)s %(message)s")
        )
    root = logging.getLogger()
    root.handlers = [handler]
    if not root.level or root.level > logging.INFO:
        root.setLevel(logging.INFO)
