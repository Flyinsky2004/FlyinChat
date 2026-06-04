from __future__ import annotations

import logging
from typing import Any, Protocol

from .config import ObservabilityConfig
from .sanitize import sanitize_value

logger = logging.getLogger("flyinchat.observability")


class ObservabilityClient(Protocol):
    @property
    def enabled(self) -> bool:
        ...

    def start_trace(
        self,
        *,
        name: str,
        input: Any,
        metadata: dict[str, Any],
        session_id: str,
        user_id: str | None = None,
    ) -> Any:
        ...

    def update_trace(
        self,
        trace_ref: Any,
        *,
        output: Any | None = None,
        metadata: dict[str, Any] | None = None,
        status_message: str | None = None,
    ) -> None:
        ...

    def start_span(
        self,
        trace_ref: Any,
        *,
        name: str,
        input: Any,
        metadata: dict[str, Any],
    ) -> Any:
        ...

    def end_span(
        self,
        span_ref: Any,
        *,
        output: Any | None = None,
        metadata: dict[str, Any] | None = None,
        status_message: str | None = None,
    ) -> None:
        ...

    def start_generation(
        self,
        trace_ref: Any,
        *,
        name: str,
        model: str,
        input: Any,
        metadata: dict[str, Any],
        model_parameters: dict[str, Any],
    ) -> Any:
        ...

    def end_generation(
        self,
        generation_ref: Any,
        *,
        output: Any | None = None,
        usage: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        status_message: str | None = None,
    ) -> None:
        ...

    def score_trace(self, trace_ref: Any, *, name: str, value: float, comment: str = "") -> None:
        ...

    def flush(self) -> None:
        ...

    def shutdown(self) -> None:
        ...


class NoopObservabilityClient:
    @property
    def enabled(self) -> bool:
        return False

    def start_trace(
        self,
        *,
        name: str,
        input: Any,
        metadata: dict[str, Any],
        session_id: str,
        user_id: str | None = None,
    ) -> Any:
        return None

    def update_trace(
        self,
        trace_ref: Any,
        *,
        output: Any | None = None,
        metadata: dict[str, Any] | None = None,
        status_message: str | None = None,
    ) -> None:
        return None

    def start_span(
        self,
        trace_ref: Any,
        *,
        name: str,
        input: Any,
        metadata: dict[str, Any],
    ) -> Any:
        return None

    def end_span(
        self,
        span_ref: Any,
        *,
        output: Any | None = None,
        metadata: dict[str, Any] | None = None,
        status_message: str | None = None,
    ) -> None:
        return None

    def start_generation(
        self,
        trace_ref: Any,
        *,
        name: str,
        model: str,
        input: Any,
        metadata: dict[str, Any],
        model_parameters: dict[str, Any],
    ) -> Any:
        return None

    def end_generation(
        self,
        generation_ref: Any,
        *,
        output: Any | None = None,
        usage: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        status_message: str | None = None,
    ) -> None:
        return None

    def score_trace(self, trace_ref: Any, *, name: str, value: float, comment: str = "") -> None:
        return None

    def flush(self) -> None:
        return None

    def shutdown(self) -> None:
        return None


class LangfuseObservabilityClient:
    def __init__(self, config: ObservabilityConfig) -> None:
        self.config = config
        self._client = self._create_client(config)

    @property
    def enabled(self) -> bool:
        return True

    def start_trace(
        self,
        *,
        name: str,
        input: Any,
        metadata: dict[str, Any],
        session_id: str,
        user_id: str | None = None,
    ) -> Any:
        return self._safe_call(
            "start_trace",
            lambda: self._client.trace(
                name=name,
                input=sanitize_value(input),
                metadata=sanitize_value(metadata),
                session_id=session_id,
                user_id=user_id,
            ),
        )

    def update_trace(
        self,
        trace_ref: Any,
        *,
        output: Any | None = None,
        metadata: dict[str, Any] | None = None,
        status_message: str | None = None,
    ) -> None:
        if trace_ref is None:
            return
        payload = _drop_none({
            "output": sanitize_value(output),
            "metadata": sanitize_value(metadata),
            "status_message": status_message,
        })
        self._safe_call("update_trace", lambda: _call_update(trace_ref, payload))

    def start_span(
        self,
        trace_ref: Any,
        *,
        name: str,
        input: Any,
        metadata: dict[str, Any],
    ) -> Any:
        if trace_ref is None:
            return None
        return self._safe_call(
            "start_span",
            lambda: trace_ref.span(
                name=name,
                input=sanitize_value(input),
                metadata=sanitize_value(metadata),
            ),
        )

    def end_span(
        self,
        span_ref: Any,
        *,
        output: Any | None = None,
        metadata: dict[str, Any] | None = None,
        status_message: str | None = None,
    ) -> None:
        if span_ref is None:
            return
        payload = _drop_none({
            "output": sanitize_value(output),
            "metadata": sanitize_value(metadata),
            "status_message": status_message,
        })
        self._safe_call("end_span", lambda: _call_end(span_ref, payload))

    def start_generation(
        self,
        trace_ref: Any,
        *,
        name: str,
        model: str,
        input: Any,
        metadata: dict[str, Any],
        model_parameters: dict[str, Any],
    ) -> Any:
        if trace_ref is None:
            return None
        return self._safe_call(
            "start_generation",
            lambda: trace_ref.generation(
                name=name,
                model=model,
                input=sanitize_value(input),
                metadata=sanitize_value(metadata),
                model_parameters=sanitize_value(model_parameters),
            ),
        )

    def end_generation(
        self,
        generation_ref: Any,
        *,
        output: Any | None = None,
        usage: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        status_message: str | None = None,
    ) -> None:
        if generation_ref is None:
            return
        payload = _drop_none({
            "output": sanitize_value(output),
            "usage": usage,
            "usage_details": usage,
            "metadata": sanitize_value(metadata),
            "status_message": status_message,
        })
        self._safe_call("end_generation", lambda: _call_end(generation_ref, payload))

    def score_trace(self, trace_ref: Any, *, name: str, value: float, comment: str = "") -> None:
        if trace_ref is None:
            return
        self._safe_call(
            "score_trace",
            lambda: trace_ref.score(name=name, value=value, comment=comment or None),
        )

    def flush(self) -> None:
        self._safe_call("flush", lambda: self._client.flush())

    def shutdown(self) -> None:
        if hasattr(self._client, "shutdown"):
            self._safe_call("shutdown", lambda: self._client.shutdown())
        else:
            self.flush()

    @staticmethod
    def _create_client(config: ObservabilityConfig) -> Any:
        try:
            from langfuse import Langfuse
        except Exception as exc:
            raise RuntimeError("Langfuse SDK is not installed") from exc
        return Langfuse(
            public_key=config.public_key,
            secret_key=config.secret_key,
            host=config.host,
            debug=config.debug,
        )

    def _safe_call(self, action: str, call: Any) -> Any:
        try:
            return call()
        except Exception as exc:
            logger.warning(
                "Langfuse observability action failed",
                extra={"event_type": action, "error_body": str(exc)[:500]},
            )
            return None


def create_observability_client(config: ObservabilityConfig | None = None) -> ObservabilityClient:
    config = config or ObservabilityConfig.from_env()
    if not config.enabled:
        if config.disabled_reason:
            logger.info("Langfuse disabled", extra={"event_type": config.disabled_reason})
        return NoopObservabilityClient()
    try:
        return LangfuseObservabilityClient(config)
    except Exception as exc:
        logger.warning(
            "Langfuse client initialization failed; observability disabled",
            extra={"event_type": "langfuse_init_failed", "error_body": str(exc)[:500]},
        )
        return NoopObservabilityClient()


def _call_update(ref: Any, payload: dict[str, Any]) -> None:
    if hasattr(ref, "update"):
        ref.update(**payload)
    elif hasattr(ref, "end"):
        ref.end(**payload)


def _call_end(ref: Any, payload: dict[str, Any]) -> None:
    if hasattr(ref, "end"):
        try:
            ref.end(**payload)
            return
        except TypeError:
            payload = {key: value for key, value in payload.items() if key != "usage"}
            ref.end(**payload)
            return
    if hasattr(ref, "update"):
        ref.update(**payload)


def _drop_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}
