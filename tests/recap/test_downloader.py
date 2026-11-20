from recap_engine.importer import _ydl_error_my, format_for, normalize_url, site_of


def test_share_text_and_rednote_urls():
    share = "看看【某某的笔记】好看 😆 https://www.rednote.com/discovery/item/6740517400000000070?xsec_token=AB1 复制本条信息，打开【小红书】App查看"
    u = normalize_url(share, resolve=False)
    assert u == "https://www.xiaohongshu.com/explore/6740517400000000070?xsec_token=AB1"
    assert site_of(u) == "rednote" and site_of("http://xhslink.com/a/x1") == "rednote"
    assert normalize_url("https://www.youtube.com/watch?v=abc", resolve=False) == "https://www.youtube.com/watch?v=abc"
    assert normalize_url("  plain text  ") == "plain text"


def test_rednote_format_and_error():
    assert "1080" not in format_for("https://www.xiaohongshu.com/explore/ab12")
    assert "1080" in format_for("https://www.youtube.com/watch?v=a")
    e = _ydl_error_my("ERROR: [XiaoHongShu] 6411: No video formats found!", "https://www.xiaohongshu.com/explore/6411")
    assert "login" in e.message_my
