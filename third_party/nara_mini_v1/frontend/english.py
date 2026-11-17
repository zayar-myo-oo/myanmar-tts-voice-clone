import re
_LATIN = re.compile('[A-Za-z]')
_LATIN_RUN = re.compile("[A-Za-z][A-Za-z'\\-. ]*[A-Za-z]|[A-Za-z]")
_g2p = None

def _en_g2p():
    global _g2p
    if _g2p is None:
        from misaki import espeak
        _g2p = espeak.EspeakG2P(language='en-us')
    return _g2p

def to_tokens(text: str) -> str:
    if not _LATIN.search(text):
        return text
    out, last = ([], 0)
    for m in _LATIN_RUN.finditer(text):
        out.append(text[last:m.start()])
        ps, _ = _en_g2p()(m.group(0))
        ps = ps.replace('̩', '')
        out.append(ps.strip())
        last = m.end()
    out.append(text[last:])
    return re.sub('  +', ' ', ''.join(out)).strip()
