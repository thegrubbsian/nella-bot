"""Tests for the split_message() chunking utility."""

from src.notifications.chunking import DEFAULT_MAX_LENGTH, split_message

# -- Fast path / edge cases --------------------------------------------------


def test_short_text_returns_single_element() -> None:
    result = split_message("Hello, world!")
    assert result == ["Hello, world!"]


def test_empty_string_returns_single_element() -> None:
    result = split_message("")
    assert result == [""]


def test_exact_boundary_returns_single_chunk() -> None:
    text = "a" * DEFAULT_MAX_LENGTH
    result = split_message(text)
    assert result == [text]


# -- Paragraph splitting (double newline) ------------------------------------


def test_paragraph_splitting() -> None:
    para1 = "A" * 2500
    para2 = "B" * 2500
    text = para1 + "\n\n" + para2

    chunks = split_message(text)
    assert len(chunks) == 2
    assert chunks[0] == para1
    assert chunks[1] == para2


# -- Markdown header splitting -----------------------------------------------


def test_header_splitting() -> None:
    section1 = "x" * 3500
    section2 = "## Section Two\n" + "y" * 2000
    text = section1 + "\n" + section2

    chunks = split_message(text)
    assert len(chunks) >= 2
    assert chunks[1].startswith("## Section Two")


# -- Single newline splitting ------------------------------------------------


def test_single_newline_splitting() -> None:
    # Build text with single newlines, no double newlines or headers
    lines = ["Line " + str(i) + " " + "x" * 80 for i in range(60)]
    text = "\n".join(lines)

    chunks = split_message(text)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk) <= DEFAULT_MAX_LENGTH


# -- Sentence boundary splitting ---------------------------------------------


def test_sentence_splitting() -> None:
    # One long "paragraph" with sentences — no newlines at all
    sentence = "This is a sentence. "
    repetitions = (DEFAULT_MAX_LENGTH // len(sentence)) + 10
    text = sentence * repetitions

    chunks = split_message(text)
    assert len(chunks) >= 2
    # Each chunk (except possibly the last) should end after a period
    for chunk in chunks[:-1]:
        assert chunk.rstrip().endswith(".")


# -- Word boundary splitting -------------------------------------------------


def test_word_boundary_splitting() -> None:
    # Words without sentence-ending punctuation
    word = "abcdefghij "
    repetitions = (DEFAULT_MAX_LENGTH // len(word)) + 100
    text = word * repetitions

    chunks = split_message(text)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk) <= DEFAULT_MAX_LENGTH


# -- Hard cut (no whitespace) -----------------------------------------------


def test_hard_cut_no_whitespace() -> None:
    text = "a" * 10_000
    chunks = split_message(text)
    assert len(chunks) >= 3
    for chunk in chunks:
        assert len(chunk) <= DEFAULT_MAX_LENGTH
    assert "".join(chunks) == text


# -- Custom max_length -------------------------------------------------------


def test_custom_max_length() -> None:
    text = "Hello world, this is a longer sentence."
    chunks = split_message(text, max_length=15)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk) <= 15


# -- All chunks fit within limit ---------------------------------------------


def test_all_chunks_within_limit() -> None:
    """Regardless of content, every chunk must respect max_length."""
    # Mix of paragraphs, headers, and long lines
    text = (
        "# Introduction\n\n"
        + "A" * 2000
        + "\n\n## Details\n\n"
        + "B" * 3000
        + "\n\n### More\n"
        + "C" * 1500
    )
    chunks = split_message(text)
    for chunk in chunks:
        assert len(chunk) <= DEFAULT_MAX_LENGTH


# -- Real-world-ish Markdown test -------------------------------------------


def test_realistic_markdown_briefing() -> None:
    """Simulate a ~4,400 char daily briefing that should split into 2 chunks."""
    briefing = (
        "# Good Morning! Here's your daily briefing\n\n"
        "## Weather\n"
        "Today will be sunny with a high of 72F. " * 10
        + "\n\n"
        "## Calendar\n"
        "- 9:00 AM: Team standup\n"
        "- 10:30 AM: 1:1 with Sarah\n"
        "- 12:00 PM: Lunch with Alex\n"
        "- 2:00 PM: Sprint planning\n"
        "- 4:00 PM: Code review session\n"
        * 5
        + "\n\n"
        "## Tasks\n"
        "Here are your top priorities for today:\n"
        "1. Review the PR for the auth refactor\n"
        "2. Deploy the staging environment\n"
        "3. Write unit tests for the new chunking module\n"
        * 8
        + "\n\n"
        "## News Highlights\n"
        "Several interesting developments in tech today. " * 20
    )
    assert len(briefing) > DEFAULT_MAX_LENGTH

    chunks = split_message(briefing)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk) <= DEFAULT_MAX_LENGTH
