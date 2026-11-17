"""Syllable split and SER (no ASR model needed)."""
from myanmar_voice_studio.training.asr import ser, syllables


def test_syllables_keep_stacked_and_killed_consonants_together():
    assert syllables("မင်္ဂလာပါ") == ["မင်္ဂ", "လာ", "ပါ"]
    assert syllables("ကမ္ဘာကြီး") == ["ကမ္ဘာ", "ကြီး"]
    assert syllables("ကျွန်တော့်") == ["ကျွန်", "တော့်"]
    assert syllables("ဒီနေ့ ၊ နေကောင်းလား။") == ["ဒီ", "နေ့", "နေ", "ကောင်း", "လား"]


def test_ser_ignores_spaces_and_punctuation():
    assert ser("မင်္ဂလာပါ။ ဒီနေ့", "မင်္ဂလာပါဒီနေ့") == 0.0
    assert ser("ရိုးရာ အလှကုန်", "ရွက်ရာအလှကုန်") == 0.2
    assert ser("က", "") == 1.0
