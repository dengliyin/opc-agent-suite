from finished_video_manager.web import (
    captions_match,
    normalize_hashtag,
    type_tiktok_hashtag,
)


class FakeKeyboard:
    def __init__(self):
        self.calls = []

    def type(self, value, delay):
        self.calls.append(("type", value, delay))

    def insert_text(self, value):
        self.calls.append(("insert_text", value))


class FakePage:
    def __init__(self):
        self.keyboard = FakeKeyboard()
        self.waits = []

    def wait_for_timeout(self, milliseconds):
        self.waits.append(milliseconds)


def test_type_tiktok_hashtag_inserts_accent_as_unicode_text():
    page = FakePage()

    type_tiktok_hashtag(page, "#ca\u0301marahd")

    assert page.keyboard.calls == [
        ("type", "#c", 40),
        ("insert_text", "á"),
        ("type", "marahd", 40),
    ]
    assert page.waits == [40]


def test_hashtag_comparison_normalizes_composed_and_decomposed_accents():
    assert normalize_hashtag(" #CÁMARAhD ") == normalize_hashtag("#ca\u0301marahd")
    assert captions_match("Texto #cámarahd", "Texto #ca\u0301marahd")
