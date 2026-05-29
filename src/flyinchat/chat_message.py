"""Per-message Markdown widget for incremental chat rendering.

Each ChatMessage parses its markdown content once on creation and caches the
result internally (Textual's Markdown widget does this). This avoids re-parsing
the entire conversation history on every render — the key performance win when
context length grows to hundreds of messages.
"""

from textual.widgets import Markdown


class ChatMessage(Markdown):
    """A single chat message rendered as Markdown.

    Tracks message_id so the app can incrementally add/remove messages without
    rebuilding the entire conversation view.
    """

    def __init__(self, display_text: str, *, widget_id: str = ""):
        # Classes: msg-user, msg-assistant, msg-tool, msg-system via caller
        super().__init__(display_text, id=widget_id or None)
