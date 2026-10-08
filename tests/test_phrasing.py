from robot_lipsync.phrasing import split_ready_phrases, split_timed_first_phrase


def test_complete_sentence_commits():
    ready, tail = split_ready_phrases("Good evening. Next")
    assert ready == ["Good evening."]
    assert tail == " Next"


def test_short_comma_clause_waits():
    ready, tail = split_ready_phrases("I am Unit One,")
    assert ready == []
    assert tail == "I am Unit One,"


def test_first_long_clause_can_commit_early():
    text = "I can hear every careful word you say,"
    ready, tail = split_ready_phrases(text, first_phrase=True)
    assert ready == [text]
    assert tail == ""


def test_timeout_keeps_possible_partial_token():
    ready, tail = split_timed_first_phrase("I have considered every possible explan")
    assert ready == ["I have considered every possible"]
    assert tail == " explan"


def test_timeout_rejects_connector():
    text = "I have considered every possibility and "
    ready, tail = split_timed_first_phrase(text)
    assert ready == []
    assert tail == text
