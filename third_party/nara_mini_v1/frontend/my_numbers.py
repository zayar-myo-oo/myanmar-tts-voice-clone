import re
DIGITS = ['သုည', 'တစ်', 'နှစ်', 'သုံး', 'လေး', 'ငါး', 'ခြောက်', 'ခုနစ်', 'ရှစ်', 'ကိုး']
PLACES = {1: 'ဆယ်', 2: 'ရာ', 3: 'ထောင်', 4: 'သောင်း'}
CREAKY = {'ဆယ်': 'ဆယ့်', 'ရာ': 'ရာ့', 'ထောင်': 'ထောင့်'}
_MY2ASCII = str.maketrans('၀၁၂၃၄၅၆၇၈၉', '0123456789')
_WA_RUN = re.compile('(?:[၀-၉]|ဝ(?![ါ-ှ]))+')
_D = '[0-9၀-၉]'
_NUM = re.compile(f'(?P<int>{_D}{{1,3}}(?:,{_D}{{3}})+|{_D}+)(?:\\.(?P<frac>{_D}+))?(?P<k>[kK](?![A-Za-z]))?(?P<pct>\\s?%)?(?P<cur>\\s?(?:Ks|KS|ks|MMK|mmk|Kyats?|kyats?)\\b)?')

def _below_lakh(n: int) -> str:
    s = str(n)
    parts = []
    for i, ch in enumerate(s):
        d, place = (int(ch), len(s) - 1 - i)
        if d:
            parts.append((d, place))
    words = []
    for j, (d, place) in enumerate(parts):
        if place == 0:
            words.append(DIGITS[d])
            continue
        unit = PLACES[place]
        if j < len(parts) - 1:
            unit = CREAKY.get(unit, unit)
        lead = '' if d == 1 and place == 1 and (j == 0) else DIGITS[d]
        words.append(lead + unit)
    return ''.join(words)

def number_words(n: int) -> str:
    if n == 0:
        return DIGITS[0]
    if n < 100000:
        return _below_lakh(n)
    lakhs, rest = divmod(n, 100000)
    return number_words(lakhs) + 'သိန်း' + (_below_lakh(rest) if rest else '')

def _digit_by_digit(s: str) -> str:
    return ' '.join((DIGITS[int(c)] for c in s))

def _say(m: re.Match) -> str:
    raw = m.group('int').translate(_MY2ASCII).replace(',', '')
    frac = m.group('frac')
    if len(raw) > 1 and raw[0] == '0' and (not frac) or len(raw) > 10:
        out = _digit_by_digit(raw)
    else:
        n = int(raw)
        if m.group('k'):
            n *= 1000
        out = number_words(n)
        if frac:
            out += ' ဒသမ ' + _digit_by_digit(frac.translate(_MY2ASCII))
    if m.group('pct'):
        out += ' ရာခိုင်နှုန်း'
    if m.group('cur'):
        out += ' ကျပ်'
    return f' {out} '

def verbalize(text: str) -> str:
    if not re.search(_D, text):
        return text
    text = _WA_RUN.sub(lambda m: m.group(0).replace('ဝ', '၀') if re.search('[၀-၉]', m.group(0)) else m.group(0), text)
    text = _NUM.sub(_say, text)
    text = re.sub('[ \\t]{2,}', ' ', text)
    return re.sub(' (?=[!?.,။၊])', '', text).strip()
