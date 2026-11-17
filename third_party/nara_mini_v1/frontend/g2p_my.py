import re
import sys
from pathlib import Path
KINZI = 'င်္'
INDEP_TO_A = [('ဣ', 'အိ'), ('ဤ', 'အီ'), ('ဥ', 'အု'), ('ဦ', 'အူ'), ('ဧ', 'အေ'), ('ဩ', 'အော'), ('ဪ', 'အော်')]
STACK = re.compile('([\\u1000-\\u1021])\\u1039')

def normalize(text: str) -> str:
    text = text.replace('\u200b', '').replace('\ufeff', '')
    text = text.replace('့်', '့်')
    text = text.replace('သြော်', 'ဪ')
    text = text.replace('သြ', 'ဩ')
    for a, b in INDEP_TO_A:
        text = text.replace(a, b)
    text = text.replace(KINZI, 'င်')
    text = STACK.sub('\\1်', text)
    text = text.replace('ဿ', 'သ်သ')
    text = text.replace('၎င်း', 'လည်းကောင်း')
    text = text.replace('၌', 'နှိုက်').replace('၍', 'ရွေ့').replace('၏', 'အိ')
    return text
CONS = 'က-အ'
INDEP = 'ဣ-ဧဩဪ'
ASAT = '်'
_LATIN_RUN = re.compile("[A-Za-z][A-Za-z']*")
_SYL_BREAK = re.compile('(?<![' + CONS + '])(?=[' + CONS + INDEP + '])|(?<=[' + CONS + '])(?=[' + CONS + INDEP + '])(?!(?:[' + CONS + ']' + ASAT + '))')

def split_syllables(text: str):
    out, cur = ([], '')
    i, n = (0, len(text))
    while i < n:
        ch = text[i]
        if re.match('[' + CONS + INDEP + ']', ch):
            is_final = i + 1 < n and text[i + 1] == ASAT
            if cur and (not is_final):
                out.append(cur)
                cur = ch
            else:
                cur += ch
            i += 1
        elif ch in 'ါာိီုူေဲံ့း်ျြွှ\ue001':
            cur += ch
            i += 1
        else:
            if cur:
                out.append(cur)
                cur = ''
            m = _LATIN_RUN.match(text, i)
            if m:
                out.append(m.group())
                i = m.end()
                continue
            out.append(ch)
            i += 1
    if cur:
        out.append(cur)
    return out
ONSET = {'က': 'k', 'ခ': 'kʰ', 'ဂ': 'g', 'ဃ': 'g', 'င': 'ŋ', 'စ': 's', 'ဆ': 'sʰ', 'ဇ': 'z', 'ဈ': 'z', 'ည': 'ɲ', 'ဉ': 'ɲ', 'ဋ': 't', 'ဌ': 'tʰ', 'ဍ': 'd', 'ဎ': 'd', 'ဏ': 'n', 'တ': 't', 'ထ': 'tʰ', 'ဒ': 'd', 'ဓ': 'd', 'န': 'n', 'ပ': 'p', 'ဖ': 'pʰ', 'ဗ': 'b', 'ဘ': 'b', 'မ': 'm', 'ယ': 'j', 'ရ': 'j', 'လ': 'l', 'ဝ': 'w', 'သ': 'θ', 'ဟ': 'h', 'ဠ': 'l', 'အ': 'ʔ'}
VELAR_PAL = {'k': 'tɕ', 'kʰ': 'tɕʰ', 'g': 'dʑ'}
ASPIRATE = {'m': 'm̥', 'n': 'n̥', 'ɲ': 'ɲ̥', 'ŋ': 'ŋ̊', 'l': 'l̥', 'j': 'ʃ', 'w': 'w̥'}
INDEP_SYL = {'ဣ': ('ʔ', 'i', 'ˀ'), 'ဤ': ('ʔ', 'i', '˧'), 'ဥ': ('ʔ', 'u', 'ˀ'), 'ဦ': ('ʔ', 'u', '˧'), 'ဧ': ('ʔ', 'e', '˧'), 'ဩ': ('ʔ', 'ɔ', '˥'), 'ဪ': ('ʔ', 'ɔ', '˧')}
V = {'': ('a', 'ˀ'), 'ာ': ('a', '˧'), 'ိ': ('i', 'ˀ'), 'ီ': ('i', '˧'), 'ု': ('u', 'ˀ'), 'ူ': ('u', '˧'), 'ေ': ('e', '˧'), 'ဲ': ('ɛ', '˥'), 'ော': ('ɔ', '˥'), 'ို': ('o', '˧')}
F_K, F_S, F_T, F_N, F_NG, F_NY = ('ကဂ', 'စဇ', 'တဒပဗဋဍသ', 'နမဏ', 'င', 'ဉ')
RHYME_CLOSED = {('', 'F_K'): 'ɛʔ', ('', 'F_S'): 'ɪʔ', ('', 'F_T'): 'aʔ', ('ိ', 'F_T'): 'eɪʔ', ('ု', 'F_T'): 'oʊʔ', ('ွ', 'F_T'): 'ʊʔ', ('ို', 'F_K'): 'aɪʔ', ('ော', 'F_K'): 'aʊʔ', ('ွ', 'F_S'): 'ɪʔ', ('ိ', 'F_S'): 'ɪʔ', ('ု', 'F_S'): 'ʊʔ', ('', 'F_NG'): 'ɪɴ', ('', 'F_NY'): 'ɪɴ', ('', 'F_N'): 'aɴ', ('ာ', 'F_T'): 'aʔ', ('ာ', 'F_N'): 'aɴ', ('ေ', 'F_T'): 'ɪʔ', ('ု', 'F_K'): 'oʊʔ', ('ာ', 'F_NY'): 'ɪɴ', ('ိ', 'F_K'): 'eɪʔ', ('ိ', 'F_NG'): 'eɪɴ', ('ို', 'F_N'): 'aɪɴ', ('ိ', 'F_N'): 'eɪɴ', ('ု', 'F_N'): 'oʊɴ', ('ွ', 'F_N'): 'ʊɴ', ('ို', 'F_NG'): 'aɪɴ', ('ော', 'F_NG'): 'aʊɴ'}

def final_class(c):
    if c in F_K:
        return 'F_K'
    if c in F_S:
        return 'F_S'
    if c in F_T:
        return 'F_T'
    if c in F_N:
        return 'F_N'
    if c in F_NG:
        return 'F_NG'
    if c in F_NY:
        return 'F_NY'
    return None
PUNCT = {'၊': ',', '။': '.', ',': ',', '.': '.', '?': '?', '!': '!', ' ': ' '}

class SylParseError(Exception):
    pass

def parse_syllable(s: str) -> str:
    if s in INDEP_SYL:
        o, r, t = INDEP_SYL[s]
        return f'{o}-{r}-{t}'
    m = re.match('^([' + CONS + '])([ျြွှ]*)([ါာိီုူေဲ]*)(?:([' + CONS + '])်)?(ံ?)(့?)(း?)(့?)$', s)
    if not m:
        raise SylParseError(s)
    base, meds, vows, fin, anusvara, dot1, visarga, dot2 = m.groups()
    dot = dot1 or dot2
    onset = ONSET[base]
    medial = ''
    if 'ှ' in meds:
        onset = ASPIRATE.get(onset, onset)
    if 'ျ' in meds or 'ြ' in meds:
        if onset in VELAR_PAL:
            onset = VELAR_PAL[onset]
        elif onset == 'ŋ':
            onset = 'ɲ'
        elif onset == 'ʃ':
            pass
        elif onset == 'j':
            pass
        else:
            medial = 'j'
    has_w = 'ွ' in meds
    vows = vows.replace('ါ', 'ာ')
    vkey = ''.join(sorted(vows, key='ေိီုူာဲ'.find))
    vkey = {'ော': 'ော', 'ို': 'ို'}.get(vkey, vkey)
    if fin or anusvara:
        fc = 'F_N' if anusvara else final_class(fin)
        if fin and fin in 'ယ':
            rhyme, tone = ('o', '˧') if vkey == 'ို' else ('ɛ', '˧')
        elif fin and fin in 'လဟ':
            rhyme, tone = V.get(vkey, (None, None))
            if rhyme is None:
                raise SylParseError(s)
            tone = '˧'
        elif fin and fin == 'ည':
            rhyme, tone = ('ɛ', '˧') if vkey == 'ေ' else ('e', '˧')
        elif fc:
            wkey = 'ွ' if has_w and ('ွ', fc) in RHYME_CLOSED and (not vkey) else vkey
            if wkey == 'ွ':
                has_w = False
            rhyme = RHYME_CLOSED.get((wkey, fc))
            if rhyme is None:
                raise SylParseError(s)
            if base == 'ဝ' and (not vkey):
                rhyme = {'aʔ': 'ʊʔ', 'aɴ': 'ʊɴ'}.get(rhyme, rhyme)
            tone = None if rhyme.endswith('ʔ') else '˧'
        else:
            raise SylParseError(s)
    else:
        if vkey not in V:
            raise SylParseError(s)
        rhyme, tone = V[vkey]
    if tone is not None:
        if visarga:
            tone = '˥'
        elif dot:
            tone = 'ˀ'
    parts = [onset]
    if has_w:
        medial = medial + 'w' if medial else 'w'
    if medial:
        parts.append(medial)
    parts.append(rhyme)
    if tone:
        parts.append(tone)
    return '-'.join(parts)

def _fix_aw(s):
    return s
LEX_PATH = Path(__file__).parent / 'lexicon_exceptions.tsv'

def load_lexicon():
    lex = {}
    if LEX_PATH.exists():
        for line in LEX_PATH.read_text(encoding='utf-8').splitlines():
            if not line or line.startswith('#'):
                continue
            k, v = line.split('\t')[:2]
            k = normalize(k).replace('ော်', '\ue001').replace('ေါ်', '\ue001')
            lex[k] = v
    return lex

def load_mined():
    v, s = (set(), set())
    p = Path(__file__).parent / 'mined_rules.tsv'
    if p.exists():
        for line in p.read_text(encoding='utf-8').splitlines():
            if not line or line.startswith('#'):
                continue
            kind, ctx, syl = line.split('\t')[:3]
            (v if kind == 'voicing' else s).add((ctx, syl))
    return (v, s)
VOICE_MAP = {'k': 'g', 'kʰ': 'g', 's': 'z', 'sʰ': 'z', 't': 'd', 'tʰ': 'd', 'p': 'b', 'pʰ': 'b', 'tɕ': 'dʑ', 'tɕʰ': 'dʑ', 'θ': 'ð'}
CLASSIFIERS = {'ယောက်', 'ခု', 'ခါ', 'နေ့', 'ချက်', 'ချောင်း', 'လုံး', 'ဖက်', 'ကောင်', 'ရက်', 'မျိုး', 'ပတ်', 'ခေါက်', 'စု', 'ပါး', 'စီး', 'ဆူ', 'ရွက်', 'စောင်', 'လက်', 'ပင်', 'အုပ်', 'ထည်', 'ခွန်း', 'လှမ်း', 'ဝိုင်း', 'သျှူး', 'ချောင်', 'နာရီ', 'မိနစ်', 'လ', 'နှစ်', 'ကြိမ်', 'ဦး', 'ပုဒ်', 'ခန်း', 'တန်း'}
_VOWEL_OR_FINAL = set('ါာိီုူေဲံ့း်')
_TONES = set('ˀ˥˧˩˨˦') | {'ˀ', '˥', '˧', '˩', '˨', '˦'}

def _is_minor_syllable(syl):
    return bool(syl) and (not _VOWEL_OR_FINAL & set(syl))

def _to_schwa(parse):
    parts = parse.split('-')
    if len(parts) > 1 and parts[-1] in _TONES:
        parts = parts[:-1]
    if len(parts) > 1:
        parts = parts[:-1]
    return '-'.join(parts + ['ə'])

def _tit_reduces(chunk, i):
    nxt = chunk[i + 1]
    if nxt in CLASSIFIERS:
        return True
    if i > 0:
        big = (chunk[i - 1], chunk[i])
        if tuple(chunk[i + 1:i + 3]) == big:
            return False
        if i >= 3 and tuple(chunk[i - 3:i - 1]) == big:
            return False
        if chunk[i - 1] == nxt:
            return False
    return True

def _apply_mined(chunk, parses, mined_v, mined_s):
    out = list(parses)
    for i, (syl, p) in enumerate(zip(chunk, out)):
        if p is None:
            continue
        parts = p.split('-')
        if syl == 'တစ်' and i + 1 < len(chunk) and _tit_reduces(chunk, i):
            out[i] = 't-ə'
            continue
        voiced = schwa = False
        if i > 0 and (chunk[i - 1], syl) in mined_v and (parts[0] in VOICE_MAP):
            parts[0] = VOICE_MAP[parts[0]]
            out[i] = '-'.join(parts)
            voiced = True
        if i + 1 < len(chunk) and (chunk[i + 1], syl) in mined_s:
            out[i] = parts[0] + '-ə'
            schwa = True
        del voiced, schwa
    return out

def g2p(text, lex=None, mined=None):
    lex = load_lexicon() if lex is None else lex
    mined_v, mined_s = load_mined() if mined is None else mined
    text = normalize(text)
    text = text.replace('ော်', '\ue001').replace('ေါ်', '\ue001')
    out, errors = ([], [])
    keys = sorted(lex, key=len, reverse=True)
    _MIDSYL = set('ါာိီုူေဲံ့း်ျြွှ')
    chunks = []
    i, n = (0, len(text))
    while i < n:
        hit = None
        for k in keys:
            if text.startswith(k, i):
                j = i + len(k)
                if j < n and text[j] in _MIDSYL:
                    continue
                hit = k
                break
        if hit:
            chunks.append(('PHON', lex[hit]))
            i += len(hit)
        else:
            chunks.append(('RAW', text[i]))
            i += 1

    def flush(buf):
        syls = split_syllables(buf)
        run, runsyl = ([], [])

        def close_run():
            if not runsyl:
                return
            parses = []
            for s in runsyl:
                try:
                    if s == '\ue001':
                        parses.append('ʔ-ɔ-˧')
                    elif '\ue001' in s:
                        p = parse_syllable(s.replace('\ue001', 'ော'))
                        parses.append(re.sub('ɔ-˥$', 'ɔ-˧', p))
                    else:
                        parses.append(parse_syllable(s))
                except SylParseError:
                    parses.append(None)
                    errors.append(s)
            for p in _apply_mined(runsyl, parses, mined_v, mined_s):
                if p is not None:
                    out.append(p)
            runsyl.clear()
        for syl in syls:
            if re.match('[' + CONS + INDEP + ']', syl) or '\ue001' in syl:
                runsyl.append(syl)
            else:
                close_run()
                if syl in PUNCT:
                    out.append(PUNCT[syl])
                elif syl.strip():
                    out.append(syl)
                else:
                    out.append(' ')
        close_run()
    buf = ''
    for kind, val in chunks:
        if kind == 'RAW':
            buf += val
        else:
            if buf:
                flush(buf)
                buf = ''
            out.append(val)
    if buf:
        flush(buf)

    def _is_en(tok):
        return '-' not in tok and bool(re.search('[A-Za-zæðθŋʒɐ-ʯᵻˈˌː]', tok))
    merged = []
    for idx, tok in enumerate(out):
        if tok == ' ':
            nxt = next((x for x in out[idx + 1:] if x != ' '), None)
            if merged and merged[-1] not in (',', '.', '?', '!') and (not _is_en(merged[-1])) and (nxt is None or not _is_en(nxt)):
                merged.append(',')
        elif tok in ('.', '?', '!', ','):
            if merged and merged[-1] == ',':
                merged[-1] = tok
            elif merged and merged[-1] in ('.', '?', '!'):
                merged.append(tok) if tok != merged[-1] else None
            else:
                merged.append(tok)
        else:
            merged.append(tok)
    while merged and merged[-1] == ',':
        merged.pop()
    while merged and merged[0] in (',', '.', '?', '!'):
        merged.pop(0)
    phon = ' '.join(merged)
    return (phon, errors)
