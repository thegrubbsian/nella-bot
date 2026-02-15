"""Tests for NotificationRouter."""

import pytest

from src.notifications.router import NotificationRouter

# -- Helpers -----------------------------------------------------------------


class FakeChannel:
    """Minimal channel implementation for testing."""

    def __init__(self, channel_name: str = "fake") -> None:
        self._name = channel_name
        self.sent: list[tuple[str, str]] = []
        self.sent_rich: list[tuple[str, str, dict]] = []
        self.sent_photos: list[tuple[str, bytes, dict]] = []

    @property
    def name(self) -> str:
        return self._name

    async def send(self, user_id: str, message: str) -> bool:
        self.sent.append((user_id, message))
        return True

    async def send_rich(
        self,
        user_id: str,
        message: str,
        *,
        buttons: list[list[dict[str, str]]] | None = None,
        parse_mode: str | None = None,
    ) -> bool:
        self.sent_rich.append((user_id, message, {"buttons": buttons, "parse_mode": parse_mode}))
        return True

    async def send_photo(
        self,
        user_id: str,
        photo: bytes,
        *,
        caption: str | None = None,
    ) -> bool:
        self.sent_photos.append((user_id, photo, {"caption": caption}))
        return True


class FailChannel(FakeChannel):
    """Channel that always fails to send."""

    async def send(self, user_id: str, message: str) -> bool:
        return False

    async def send_rich(self, user_id: str, message: str, **kwargs) -> bool:
        return False

    async def send_photo(self, user_id: str, photo: bytes, **kwargs) -> bool:
        return False


# -- Fixtures ----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_router():
    """Reset the singleton before and after each test."""
    NotificationRouter._reset()
    yield
    NotificationRouter._reset()


# -- Registration ------------------------------------------------------------


def test_register_and_list() -> None:
    router = NotificationRouter.get()
    ch = FakeChannel("telegram")
    router.register_channel(ch)
    assert router.list_channels() == ["telegram"]
    assert router.get_channel("telegram") is ch


def test_register_duplicate_raises() -> None:
    router = NotificationRouter.get()
    router.register_channel(FakeChannel("telegram"))
    with pytest.raises(ValueError, match="already registered"):
        router.register_channel(FakeChannel("telegram"))


def test_get_channel_missing_returns_none() -> None:
    router = NotificationRouter.get()
    assert router.get_channel("nonexistent") is None


# -- Default channel ---------------------------------------------------------


def test_set_default_channel() -> None:
    router = NotificationRouter.get()
    router.register_channel(FakeChannel("telegram"))
    router.set_default_channel("telegram")
    assert router.default_channel_name == "telegram"


def test_set_default_unregistered_raises() -> None:
    router = NotificationRouter.get()
    with pytest.raises(KeyError, match="not registered"):
        router.set_default_channel("missing")


# -- Singleton ---------------------------------------------------------------


def test_singleton_same_instance() -> None:
    a = NotificationRouter.get()
    b = NotificationRouter.get()
    assert a is b


def test_reset_creates_new_instance() -> None:
    a = NotificationRouter.get()
    NotificationRouter._reset()
    b = NotificationRouter.get()
    assert a is not b


# -- Send dispatch -----------------------------------------------------------


async def test_send_via_default_channel() -> None:
    router = NotificationRouter.get()
    ch = FakeChannel("telegram")
    router.register_channel(ch)
    router.set_default_channel("telegram")

    ok = await router.send("123", "hello")
    assert ok is True
    assert ch.sent == [("123", "hello")]


async def test_send_via_named_channel() -> None:
    router = NotificationRouter.get()
    tg = FakeChannel("telegram")
    sms = FakeChannel("sms")
    router.register_channel(tg)
    router.register_channel(sms)
    router.set_default_channel("telegram")

    ok = await router.send("123", "hello", channel="sms")
    assert ok is True
    assert sms.sent == [("123", "hello")]
    assert tg.sent == []


async def test_send_fallback_to_only_channel() -> None:
    router = NotificationRouter.get()
    ch = FakeChannel("telegram")
    router.register_channel(ch)
    # No default set — falls back to only registered channel

    ok = await router.send("1", "hi")
    assert ok is True
    assert ch.sent == [("1", "hi")]


async def test_send_no_channel_returns_false() -> None:
    router = NotificationRouter.get()
    # No channels registered at all
    ok = await router.send("1", "hi")
    assert ok is False


async def test_send_ambiguous_no_default_returns_false() -> None:
    router = NotificationRouter.get()
    router.register_channel(FakeChannel("a"))
    router.register_channel(FakeChannel("b"))
    # Two channels, no default set
    ok = await router.send("1", "hi")
    assert ok is False


# -- Send rich ---------------------------------------------------------------


async def test_send_rich_dispatch() -> None:
    router = NotificationRouter.get()
    ch = FakeChannel("telegram")
    router.register_channel(ch)
    router.set_default_channel("telegram")

    buttons = [[{"text": "OK", "callback_data": "ok"}]]
    ok = await router.send_rich("1", "Pick one", buttons=buttons, parse_mode="HTML")
    assert ok is True
    assert len(ch.sent_rich) == 1
    assert ch.sent_rich[0][0] == "1"
    assert ch.sent_rich[0][1] == "Pick one"
    assert ch.sent_rich[0][2]["buttons"] == buttons
    assert ch.sent_rich[0][2]["parse_mode"] == "HTML"


async def test_send_rich_no_channel_returns_false() -> None:
    router = NotificationRouter.get()
    ok = await router.send_rich("1", "hello")
    assert ok is False


# -- Send photo ----------------------------------------------------------------


async def test_send_photo_routes_correctly() -> None:
    router = NotificationRouter.get()
    ch = FakeChannel("telegram")
    router.register_channel(ch)
    router.set_default_channel("telegram")

    photo_data = b"\x89PNG..."
    ok = await router.send_photo("123", photo_data, caption="test caption")
    assert ok is True
    assert len(ch.sent_photos) == 1
    assert ch.sent_photos[0][0] == "123"
    assert ch.sent_photos[0][1] == photo_data
    assert ch.sent_photos[0][2]["caption"] == "test caption"


async def test_send_photo_no_channel_returns_false() -> None:
    router = NotificationRouter.get()
    ok = await router.send_photo("1", b"\x89PNG...")
    assert ok is False
