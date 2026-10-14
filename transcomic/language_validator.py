"""Offline language evidence. VALID is not a semantic correctness certificate."""
from dataclasses import dataclass
from difflib import SequenceMatcher
import re
import unicodedata
from .languages import language
from .quality import PLACEHOLDER

VALID = 'VALID'
WRONG_LANGUAGE_CONFIRMED = 'WRONG_LANGUAGE_CONFIRMED'
SUSPECTED_WRONG_LANGUAGE = 'SUSPECTED_WRONG_LANGUAGE'
INSUFFICIENT_EVIDENCE = 'INSUFFICIENT_EVIDENCE'
REASONS = {
    'source_copy': 'Bản dịch trùng nguyên nguồn sau chuẩn hóa',
    'near_source_copy': 'Bản dịch gần như sao chép nguồn',
    'copied_vietnamese_segment': 'Còn một đoạn tiếng Việt đủ dài trùng nguồn',
    'copied_clauses': 'Nhiều cụm tiếng Việt bị giữ nguyên từ nguồn',
    'vietnamese_grammar_and_accents': 'Còn nhiều từ ngữ pháp và dấu tiếng Việt',
    'possible_source_fragment': 'Có thể còn đoạn nguồn; cần người đọc kiểm tra',
}

def display_reason(reason):
    return REASONS.get(reason, reason)

VI = set('của những đang không người đã với một trong này là có rồi khi mà nhưng còn cũng ấy cô anh ta tôi em chúng vì để được nói thấy như lại vào ra lên xuống rất chỉ sẽ phải cho lấy'.split())
EN = set('the and was were with she he her his that this they their you your from into have had to of it is not said could would'.split())

def fold(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text.casefold().replace('đ','d')) if not unicodedata.combining(c))

def tokens(text, context=None):
    text = PLACEHOLDER.sub(' ', text)
    text = re.sub(r'https?://\S+|www\.\S+|\b[\w.-]+@[\w.-]+\b|\b\w+[._:/-]\w+\b', ' ', text)
    for retained in (context or {}).get('preserve_terms', ()):
        text = re.sub(re.escape(retained), ' ', text, flags=re.I)
    return re.findall(r'[^\W\d_]+', unicodedata.normalize('NFC', text).casefold())

@dataclass(frozen=True)
class LanguageCheck:
    conclusion: str
    reason: str
    confidence: str
    line_id: str | None = None

class TranslationLanguageValidator:
    def validate(self, source, target, source_locale, target_locale, line_id=None, context=None):
        def result(conclusion, reason, confidence='low'):
            return LanguageCheck(conclusion, reason, confidence, line_id)
        try: a,b=language(source_locale),language(target_locale)
        except (ValueError, TypeError): return result(INSUFFICIENT_EVIDENCE,'unsupported_locale')
        if a.locale.split('-')[0] == b.locale.split('-')[0]:
            return result(INSUFFICIENT_EVIDENCE,'related_locale')
        s,t=tokens(source,context),tokens(target,context)
        if len(t)<4: return result(INSUFFICIENT_EVIDENCE,'short_or_protected_text')
        if a.locale!='vi':
            from .quality import language_evidence
            kind,_=language_evidence(source,target,source_locale,target_locale)
            return result(SUSPECTED_WRONG_LANGUAGE if kind=='suspected' else VALID if kind=='compatible' else INSUFFICIENT_EVIDENCE,'locale_heuristic')
        sf,tf=[fold(w) for w in s],[fold(w) for w in t]
        vf={fold(w) for w in VI}
        src_vi=sum(w in vf for w in sf)
        dst_vi=sum(w in VI for w in t)
        dst_fold_vi=sum(w in vf for w in tf)
        eng=sum(w in EN for w in t)
        matcher=SequenceMatcher(None,sf,tf,autojunk=False)
        blocks=[block for block in matcher.get_matching_blocks() if block.size>=5]
        copied=sum(block.size for block in blocks)
        longest=max((block.size for block in blocks),default=0)
        source_evidence=src_vi>=3 and len(s)>=6
        if source_evidence and sf==tf:
            return result(WRONG_LANGUAGE_CONFIRMED,'source_copy','high')
        if source_evidence and matcher.ratio()>=.82 and dst_fold_vi>=3:
            return result(WRONG_LANGUAGE_CONFIRMED,'near_source_copy','high')
        for block in blocks:
            segment=tf[block.b:block.b+block.size]
            if source_evidence and block.size>=7 and sum(w in vf for w in segment)>=3:
                return result(WRONG_LANGUAGE_CONFIRMED,'copied_vietnamese_segment','high')
        if source_evidence and copied>=10 and copied/len(t)>=.35 and dst_fold_vi>=4:
            return result(WRONG_LANGUAGE_CONFIRMED,'copied_clauses','high')
        if b.locale not in ('en','en-CA'):
            from .quality import language_evidence
            kind,_=language_evidence(source,target,source_locale,target_locale)
            return result(SUSPECTED_WRONG_LANGUAGE if kind=='suspected' else VALID if kind=='compatible' else INSUFFICIENT_EVIDENCE,'locale_heuristic')
        # Accent evidence alone is insufficient; require several grammatical words.
        accented=sum(fold(w)!=w for w in t)
        if dst_vi>=5 and accented>=4 and (dst_vi>=eng+3 or dst_vi/len(t)>=.25):
            return result(WRONG_LANGUAGE_CONFIRMED,'vietnamese_grammar_and_accents','high')
        if dst_vi>=3 and accented>=2 or source_evidence and longest>=5:
            return result(SUSPECTED_WRONG_LANGUAGE,'possible_source_fragment','medium')
        return result(VALID if eng>=2 else INSUFFICIENT_EVIDENCE,'no_strong_language_fault')

validator = TranslationLanguageValidator()

def export_faults(document, rows):
    """Inspect exactly the translation/source fallback the renderers will use."""
    from .status import usable
    from .documents import translatable
    faults=[]
    for row in rows:
        if not translatable(row['source']): continue
        target=row['translation'] if usable(row) else row['source']
        check=validator.validate(row['source'],target,document['source_lang'],document['target_lang'],row['id'])
        if check.conclusion==WRONG_LANGUAGE_CONFIRMED:
            faults.append({'id':row['id'],'ordinal':row['ordinal'],'reason':check.reason})
    return faults
