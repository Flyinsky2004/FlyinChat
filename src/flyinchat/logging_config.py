import json
import logging
from datetime import datetime, timezone
from pathlib import Path


class StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for attr in (
            "turn_id",
            "tool_name",
            "tool_use_id",
            "error_code",
            "elapsed_ms",
            "event_type",
            "conversation_id",
            "model_name",
            "strategy",
            "tokens_before",
            "tokens_after",
            "ok",
            "round",
            "max_rounds",
            "status",
            "tool_rounds",
            "input_tokens",
            "output_tokens",
        ):
            value = getattr(record, attr, None)
            if value is not None:
                payload[attr] = value
        if record.exc_info and record.exc_info[1]:
            payload["exception"] = str(record.exc_info[1])
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: int = logging.INFO, log_path: Path | None = None) -> None:
    target_path = log_path if log_path is not None else Path.cwd() / ".flyinchat" / "flyinchat.log"
    target_path.parent.mkdir(parents=True, exist_ok=True)

    handler = logging.FileHandler(target_path, mode="w", encoding="utf-8")
    handler.setFormatter(StructuredFormatter())
    root = logging.getLogger("flyinchat")
    root.setLevel(level)
    for existing_handler in root.handlers:
        existing_handler.close()
    root.handlers.clear()
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"flyinchat.{name}")
