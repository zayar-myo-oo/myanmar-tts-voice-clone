import re
from .g2p_my import g2p, load_lexicon, load_mined
from .char_map import syl_to_chars, RHYME_SPLIT
from .nara_names import replace_names
LEX, MINED = (load_lexicon(), load_mined())

def prepare_names(text):
    return replace_names(text)

def phonemize(text):
    phon, errors = g2p(text, LEX, MINED)
    out = []
    for tok in phon.split():
        try:
            if tok in (',', '.', '?', '!'):
                out.append(tok)
            elif '-' in tok or tok in RHYME_SPLIT:
                out.append(syl_to_chars(tok) if '-' in tok else tok)
            elif re.search('[A-Za-zæðθŋʒɐ-ʯᵻˈˌː]', tok):
                out.append(tok)
            elif re.match('^[^\\W\\d]', tok):
                out.append(syl_to_chars(tok))
        except KeyError:
            continue
    return ' '.join(out)
