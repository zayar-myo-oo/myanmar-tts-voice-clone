import re
NAME_MAP = {'ma': 'ma→', 'daw': 'dɔ→', 'ko': 'ko→', 'u': 'ʔu↗', 'tin': 'tiɴ→', 'shwe': 'ʃwe→', 'aung': 'ʔaʊɴ→', 'kyaw': 'ʧɔ→', 'zaw': 'zɔ→', 'hla': 'ʰla→', 'htet': 'tʰɛʔ', 'naing': 'naɪɴ→', 'thu': 'θu→', 'moe': 'mo↗', 'myat': 'mjaʔ', 'min': 'miɴ→', 'nyunt': 'ɲʊɴ↓', 'khin': 'kʰiɴ→', 'mya': 'mja↗', 'hnin': 'ʰniɴ→', 'su': 'su→', 'phyo': 'pʰjo↗', 'htun': 'tʰʊɴ→', 'tun': 'tʊɴ→', 'oo': 'ʔu↗', 'zin': 'ziɴ→', 'thet': 'θɛʔ', 'nay': 'ne→', 'lin': 'liɴ→', 'kaung': 'kaʊɴ→', 'shein': 'ʃeɪɴ→', 'hein': 'heɪɴ→', 'myo': 'mjo↗', 'thant': 'θaɴ↓', 'san': 'saɴ↗', 'win': 'wɪɴ→', 'may': 'me→', 'soe': 'so↗', 'ye': 'jɛ↗', 'wai': 'we→', 'thida': 'θi→ də ɡa→'}
AMBIG = {'win', 'may', 'san', 'u', 'so', 'soe', 'ye', 'tin', 'ma'}
_NAMEWORD = re.compile('\\b[A-Z][a-z]+\\b|\\bU\\b')

def replace_names(text: str) -> str:
    words = list(_NAMEWORD.finditer(text))
    keep = set()
    for i, m in enumerate(words):
        w = m.group(0).lower()
        if w not in NAME_MAP:
            continue
        if w in AMBIG:
            prev_ok = i > 0 and words[i - 1].group(0).lower() in NAME_MAP and (text[words[i - 1].end():m.start()].strip() == '')
            nxt_ok = i + 1 < len(words) and words[i + 1].group(0).lower() in NAME_MAP and (text[m.end():words[i + 1].start()].strip() == '')
            if not (prev_ok or nxt_ok):
                continue
        keep.add(i)
    out, last = ([], 0)
    for i, m in enumerate(words):
        if i in keep:
            out.append(text[last:m.start()])
            out.append(NAME_MAP[m.group(0).lower()])
            last = m.end()
    out.append(text[last:])
    return ''.join(out)
