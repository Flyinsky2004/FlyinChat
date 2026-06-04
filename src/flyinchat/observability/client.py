from __future__ import annotations

import logging
from pathlib import Path
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
    """Langfuse v4 SDK adapter.

    v4 uses start_observation() with as_type instead of trace()/span()/generation().
    Observations are nested: root_span.start_observation() creates child spans.
    """

    def __init__(self, config: ObservabilityConfig) -> None:
        self.config = config
        self._client = self._create_client(config)

    @property
    def enabled(self) -> bool:
        return True

    # ── Trace = root observation (as_type="agent") ──────────────────────

    def start_trace(
        self,
        *,
        name: str,
        input: Any,
        metadata: dict[str, Any],
        session_id: str,
        user_id: str | None = None,
    ) -> Any:
        merged_meta = sanitize_value({**metadata, "session_id": session_id})
        if user_id:
            merged_meta["user_id"] = user_id
        return self._safe_call(
            "start_trace",
            lambda: self._client.start_observation(
                name=name,
                as_type="agent",
                input=sanitize_value(input),
                metadata=merged_meta,
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
        self._safe_call(
            "update_trace",
            lambda: trace_ref.update(
                output=sanitize_value(output),
                metadata=sanitize_value(metadata),
                status_message=status_message,
            ),
        )

    # ── Span = child observation (as_type="span") ───────────────────────

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
            lambda: trace_ref.start_observation(
                name=name,
                as_type="span",
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
        self._safe_call(
            "end_span",
            lambda: _end_observation(
                span_ref,
                output=sanitize_value(output),
                metadata=sanitize_value(metadata),
                status_message=status_message,
            ),
        )

    # ── Generation = child observation (as_type="generation") ───────────

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
            lambda: trace_ref.start_observation(
                name=name,
                as_type="generation",
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
        self._safe_call(
            "end_generation",
            lambda: _end_observation(
                generation_ref,
                output=sanitize_value(output),
                metadata=sanitize_value(metadata),
                status_message=status_message,
                usage_details=usage,
            ),
        )

    # ── Scores ──────────────────────────────────────────────────────────

    def score_trace(self, trace_ref: Any, *, name: str, value: float, comment: str = "") -> None:
        if trace_ref is None:
            return
        self._safe_call(
            "score_trace",
            lambda: trace_ref.score_trace(name=name, value=value, comment=comment or None),
        )

    # ── Lifecycle ───────────────────────────────────────────────────────

    def flush(self) -> None:
        self._safe_call("flush", lambda: self._client.flush())

    def shutdown(self) -> None:
        self._safe_call("shutdown", lambda: self._client.shutdown())

    # ── Internal ────────────────────────────────────────────────────────

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


def create_observability_client(
    config: ObservabilityConfig | None = None,
    config_path: Path | None = None,
) -> ObservabilityClient:
    if config is None:
        if config_path is not None:
            config = ObservabilityConfig.from_config_store(config_path)
        else:
            config = ObservabilityConfig.from_config_store(Path("~/.flyinchat/config.json").expanduser())
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


def _end_observation(
    ref: Any,
    *,
    output: Any | None = None,
    metadata: dict[str, Any] | None = None,
    status_message: str | None = None,
    usage_details: dict[str, Any] | None = None,
) -> None:
    """v4: update + end on a LangfuseSpan."""
    update_kwargs: dict[str, Any] = {}
    if output is not None:
        update_kwargs["output"] = output
    if metadata is not None:
        update_kwargs["metadata"] = metadata
    if status_message is not None:
        update_kwargs["status_message"] = status_message
    if usage_details is not None:
        update_kwargs["usage_details"] = usage_details
    if update_kwargs:
        ref.update(**update_kwargs)
    ref.end()