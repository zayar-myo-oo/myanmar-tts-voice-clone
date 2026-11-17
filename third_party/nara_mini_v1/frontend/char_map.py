CHAR = {'k': 'k', 'g': 'ɡ', 'ŋ': 'ŋ', 's': 's', 'z': 'z', 'ɲ': 'ɲ', 't': 't', 'd': 'd', 'n': 'n', 'p': 'p', 'b': 'b', 'm': 'm', 'j': 'j', 'r': 'r', 'l': 'l', 'w': 'w', 'θ': 'θ', 'ð': 'ð', 'h': 'h', 'ʔ': 'ʔ', 'ʃ': 'ʃ', 'f': 'f', 'kʰ': 'kʰ', 'sʰ': 'sʰ', 'tʰ': 'tʰ', 'pʰ': 'pʰ', 'tɕ': 'ʧ', 'tɕʰ': 'ʧʰ', 'dʑ': 'ʤ', 'm̥': 'ʰm', 'n̥': 'ʰn', 'ɲ̥': 'ʰɲ', 'ŋ̊': 'ʰŋ', 'l̥': 'ʰl', 'w̥': 'w', 'a': 'a', 'i': 'i', 'u': 'u', 'e': 'e', 'ɛ': 'ɛ', 'ɔ': 'ɔ', 'o': 'o', 'ə': 'ə', 'ɴ': 'ɴ', 'ʔfin': 'ʔ', 'eɪ': 'A', 'oʊ': 'O', 'aɪ': 'I', 'aʊ': 'W', '˧': '→', '˥': '↗', 'ˀ': '↓'}
RHYME_SPLIT = {'ɪɴ': ('i', 'ɴ'), 'aɴ': ('a', 'ɴ'), 'eɪɴ': ('A', 'ɴ'), 'oʊɴ': ('O', 'ɴ'), 'ʊɴ': ('u', 'ɴ'), 'aɪɴ': ('I', 'ɴ'), 'aʊɴ': ('W', 'ɴ'), 'ɪʔ': ('i', 'ʔ'), 'ʊʔ': ('u', 'ʔ'), 'aʔ': ('a', 'ʔ'), 'ɛʔ': ('ɛ', 'ʔ'), 'eɪʔ': ('A', 'ʔ'), 'oʊʔ': ('O', 'ʔ'), 'aɪʔ': ('I', 'ʔ'), 'aʊʔ': ('W', 'ʔ'), 'a': ('a',), 'i': ('i',), 'u': ('u',), 'e': ('e',), 'ɛ': ('ɛ',), 'ɔ': ('ɔ',), 'o': ('o',), 'ə': ('ə',)}

def syl_to_chars(syl: str) -> str:
    parts = syl.split('-')
    tone = parts[-1] if parts[-1] in ('˧', '˥', 'ˀ') else None
    core = parts[:-1] if tone else parts
    onset, meds, rhyme = (core[0], core[1:-1], core[-1])
    out = [CHAR[onset]] + [CHAR[m] for m in meds]
    out += [CHAR[c] if c in CHAR else c for c in RHYME_SPLIT[rhyme]]
    if tone:
        out.append(CHAR[tone])
    return ''.join(out)
