from text_processing import correct_vocabulary, filter_filler_words


def test_correct_vocabulary_is_case_insensitive():
    text = "I love Cloud code and Open Cloud."
    corrections = {"cloud code": "claude code", "open cloud": "openclaw"}

    corrected = correct_vocabulary(text, corrections)

    assert corrected == "I love claude code and openclaw."


def test_correct_vocabulary_keeps_unmatched_text():
    text = "No corrections needed."

    corrected = correct_vocabulary(text, {"cloud code": "claude code"})

    assert corrected == text


def test_filter_filler_words_cleans_spacing_and_punctuation():
    text = "嗯， Cloud code 啊，测试。"

    filtered = filter_filler_words(text, ["嗯", "啊"])

    assert filtered == "Cloud code，测试。"


def test_filter_filler_words_deduplicates_remaining_punctuation():
    text = "呃，，今天 啊 。。"

    filtered = filter_filler_words(text, ["呃", "啊"])

    assert filtered == "今天。"
