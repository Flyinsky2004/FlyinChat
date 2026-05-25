from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Footer, Header, Static


class FlyinChatApp(App[None]):
    TITLE = "FlyinChat"

    CSS = """
    Screen {
        align: center middle;
    }

    #content {
        width: 60;
        height: auto;
        border: round $accent;
        padding: 1 2;
    }

    #title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }

    Button {
        margin-top: 1;
    }
    """

    BINDINGS = [("q", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="content"):
            yield Static("FlyinChat", id="title")
            yield Static("Textual app is ready.")
            yield Button("Quit", id="quit", variant="primary")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "quit":
            self.exit()


def run() -> None:
    FlyinChatApp().run()
