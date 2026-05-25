import asyncio

from textual.widgets import Static

from flyinchat import FlyinChatApp


def test_app_can_be_created() -> None:
    app = FlyinChatApp()

    assert app.title == "FlyinChat"


def test_app_renders_title() -> None:
    async def run_app() -> None:
        app = FlyinChatApp()

        async with app.run_test():
            title = app.query_one("#title", Static)

            assert title.content == "FlyinChat"

    asyncio.run(run_app())
