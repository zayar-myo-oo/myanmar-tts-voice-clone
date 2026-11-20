"""Number consistency between Chinese source lines and translations."""
from recap_engine.numcheck import cn2num, mismatch


def test_chinese_numerals():
    assert (cn2num("三十"), cn2num("两百五十"), cn2num("一万"), cn2num("十")) == (30, 250, 10000, 10)


def test_flags_changed_numbers_only():
    assert mismatch("前往宗门以西三十里乱葬岗", "မိုင် ၂၀ အကွာ")["unexpected"] == [20.0]  # 30 -> 20
    assert mismatch("我有两个孩子", "I have 3 kids")
    assert mismatch("前往宗门以西三十里", "အနောက်ဘက် ၃၀ မိုင်") is None
    assert mismatch("设备累计损失45亿", "ပျက်စီးမှု ၄.၅ ဘီလီယံ") is None  # 45亿 = 4.5 billion
    assert mismatch("您珍藏的10亿元的机甲", "ယွမ် ၁ ဘီလီယံတန်") is None
    assert mismatch("这单 你给几星", "ဘယ်နှစ်ကြယ် ပေးမလဲ") is None  # no digits -> nothing to check
    assert mismatch("前往宗门以西三十里", "thirty miles west") is None  # spelled numbers aren't checked
    assert mismatch("โรงพยาบาล", "ห้อง ๕") is not None  # Thai digits read too
