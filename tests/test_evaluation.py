import numpy as np
import pytest

from myanmar_voice_studio.evaluation import audio_metrics, prepare_text


VOCAB = set("မင်္ဂလာပါနကေ်း ")


def test_preserves_burmese_combining_marks_and_reports_punctuation():
    result = prepare_text("မင်္ဂလာပါ။", VOCAB)
    assert result.spoken == "မင်္ဂလာပါ"
    assert result.warnings


@pytest.mark.parametrize("text", ["မင်္ဂလာပါ AI", "၉ နာရီ", "123", "မင်္ဂလာပါ🙂", "မင်္ဂလာပါ\u200b"])
def test_unsupported_content_is_never_silently_dropped(text):
    with pytest.raises(ValueError, match="Unsupported"):
        prepare_text(text, VOCAB)


@pytest.mark.parametrize("text", ["", "   ", "။", "မ" * 401])
def test_rejects_empty_punctuation_only_and_long_text(text):
    with pytest.raises(ValueError):
        prepare_text(text, VOCAB)


def test_audio_metrics_detect_silence_clipping_and_bad_data():
    assert not audio_metrics(np.zeros(100), 16000)["signal_check_passed"]
    assert not audio_metrics(np.ones(100), 16000)["signal_check_passed"]
    assert audio_metrics(np.full(100, 0.1), 16000)["signal_check_passed"]
    for audio in (np.array([]), np.array([np.nan]), np.zeros((2, 2))):
        with pytest.raises(ValueError):
            audio_metrics(audio, 16000)
