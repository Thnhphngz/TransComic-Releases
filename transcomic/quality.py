"""Conservative editorial heuristics: warnings only, never rewrite punctuation."""
import re

PLACEHOLDER = re.compile(r"\{\{[^{}]+\}\}|\{[A-Za-z_][\w.]*\}|%\w|<[^<>]+>")


def sentence_marks(text):
    text = re.sub(r"https?://\S+|www\.\S+", "", text)
    text = re.sub(r"(?<=\d)\.(?=\d)", "", text)
    text = re.sub(r"\b(?:[A-Za-z]\.){2,}|\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|vs|etc)\.", "", text, flags=re.I)
    return re.findall(r"[.!?…]+", text)


def warnings(row):
    found = []
    source, target = row["source"], row.get("translation") or ""
    state, error = row["state"], row.get("error") or ""
    if state in ("error", "unknown"):
        kind = "HTTP 504" if "504" in error else "Client timeout" if "timeout" in error.lower() else "Không rõ kết quả" if state == "unknown" else "Lỗi phản hồi/API"
        found.append((kind, error or "Không có kết quả hợp lệ"))
        if "missing" in error.lower() or "thiếu" in error.lower():
            found.append(("Response thiếu ID", error))
        if "duplicate" in error.lower() or "invalid" in error.lower() or "unexpected" in error.lower():
            found.append(("ID trùng/không hợp lệ", error))
    if state == "wrong_target_language":
        from .language_validator import display_reason
        reason=display_reason(error) if error else "Nội dung còn ngôn ngữ nguồn"
        if target and row.get('translation_source_revision') is not None and row.get('translation_source_revision')==row.get('source_revision'):
            reason='Phản hồi mới bị từ chối; bản dịch cũ được giữ: '+reason
        found.append(("Sai ngôn ngữ đích",reason))
    if target and row.get("source_lang") and row.get("target_lang"):
        from .language_validator import validator, WRONG_LANGUAGE_CONFIRMED, SUSPECTED_WRONG_LANGUAGE, display_reason
        check=validator.validate(source,target,row["source_lang"],row["target_lang"],row.get("id"))
        if check.conclusion in (WRONG_LANGUAGE_CONFIRMED,SUSPECTED_WRONG_LANGUAGE):
            note=("Sai ngôn ngữ đích" if check.conclusion==WRONG_LANGUAGE_CONFIRMED else "Nghi sai ngôn ngữ",display_reason(check.reason))
            if note not in found: found.append(note)
    if state == "stale":
        found.append(("Cần kiểm tra lại", "Nguồn đã thay đổi sau bản dịch"))
    if not target and state != "skip":
        found.append(("Chưa có bản dịch", "Chưa có văn bản dịch hợp lệ"))
    if target:
        from .translation_policy import SEMANTIC_VERSIONS
        semantic=row.get('translation_policy') in SEMANTIC_VERSIONS
        found.extend(language_warnings(source,target,row.get('source_lang'),row.get('target_lang'),semantic=semantic))
        src, dst = sentence_marks(source), sentence_marks(target)
        if not semantic and sum("." in x for x in dst) > sum("." in x for x in src):
            found.append(("Thêm dấu chấm", "Có thể đã chia câu khác nguồn; cần kiểm tra thủ công"))
        def end(text):
            clean = text.rstrip().rstrip('"\u201d\u2019\'')
            marks = sentence_marks(clean)
            return marks[-1] if marks and clean.endswith(marks[-1]) else ""
        if not semantic and end(source) != end(target):
            found.append(("Dấu câu cuối", "Dấu câu cuối không khớp nguồn (heuristic)"))
        if sorted(PLACEHOLDER.findall(source)) != sorted(PLACEHOLDER.findall(target)):
            found.append(("Placeholder", "Placeholder nguồn và bản dịch không khớp"))
    return found


def language_evidence(source,target,source_lang,target_lang):
    """Conservative local evidence, never a semantic correctness score."""
    from .languages import language
    import unicodedata
    try: a,b=language(source_lang),language(target_lang)
    except ValueError:return 'insufficient',[]
    clean=PLACEHOLDER.sub('',target)
    letters=[c for c in clean if c.isalpha()]
    tokens=re.findall(r'[^\W\d_]+',clean.lower())
    if len(letters)<12 or len(tokens)<3 and b.script=='Latin':return 'insufficient',[]
    notes=[]
    if a.locale!=b.locale and a.locale.split('-')[0]!=b.locale.split('-')[0] and source.strip().casefold()==target.strip().casefold():
        notes.append(('Giữ nguyên nguồn','Có thể chưa dịch; heuristic, kiểm tra tên riêng/thuật ngữ'))
    count=lambda name:sum(name in unicodedata.name(c,'') for c in letters)
    if b.locale=='hi' and count('DEVANAGARI')/len(letters)<.15:
        notes.append(('Nghi sai ngôn ngữ','Hindi thiếu hệ chữ Devanagari; heuristic'))
    if b.locale in ('ja','zh-CN'):
        han=count('CJK');kana=count('HIRAGANA')+count('KATAKANA')
        if (han+kana)/len(letters)<.15:
            notes.append(('Nghi sai ngôn ngữ','Thiếu chữ Nhật/Hán phù hợp; heuristic'))
        if b.locale=='zh-CN' and sum(c in '這個們說為與來過時會學國體見愛無後發長開門書車東萬聲讓還頭實現對' for c in clean)>=3:
            notes.append(('Nghi chữ phồn thể','Nhiều chữ phồn thể thường gặp; không phải kiểm định toàn bộ chữ Hán'))
    # Word evidence is deliberately sparse: Latin script alone never identifies a language.
    bags={
        'en':{'the','was','were','with','she','he','her','his','that','and'},
        'vi':{'của','những','đang','không','người','đã','với','một','trong','này'},
        'de':{'der','die','das','und','nicht','sie','mit','ein','eine','ist'},
        'id':{'yang','dan','tidak','itu','dengan','adalah','seorang','karena','bisa','sudah'},
        'ms':{'yang','dan','tidak','itu','dengan','ialah','kerana','boleh','sudah','seorang'},
        'fil':{'ang','ng','mga','si','ni','hindi','isang','nang','sa','ay'},
        'fr':{'le','la','les','une','un','et','elle','il','pas','avec','dans'},
    }
    base=b.locale.split('-')[0];expected=bags.get(base,set())
    scores={k:sum(t in bag for t in tokens) for k,bag in bags.items()}
    best=max(scores,key=scores.get); own=sum(t in expected for t in tokens)
    if b.script=='Latin' and len(tokens)>=10 and best!=base and scores[best]>=5 and scores[best]>=own+4:
        notes.append(('Nghi sai ngôn ngữ',f'Dấu hiệu từ vựng {best} nhiều hơn {b.locale}; heuristic'))
    if b.locale=='ms' and sum(t in {'karena','bisa','nggak','banget'} for t in tokens)>=3:
        notes.append(('Nghi Malay/Indonesia','Nhiều từ thường gặp ở Indonesia; kiểm tra thủ công'))
    return ('suspected' if notes else 'insufficient' if b.script=='Latin' and own<3 else 'compatible'),notes


def language_warnings(source,target,source_lang,target_lang,*,semantic=False):
    evidence,notes=language_evidence(source,target,source_lang,target_lang)
    # Insufficient evidence is an information state, not a warning on an otherwise valid row.
    # Specific user-provided failure fixtures, no speculative rewriting.
    if not semantic and re.search(r'\b(sao|ư)\s*$',source,re.I) and not any(mark in target for mark in ('?','？')):
        notes.append(('Sắc thái câu hỏi','Nguồn có sao/ư; kiểm tra xem bản dịch có giữ nghi vấn'))
    if 'ly hôn' in source.casefold() and re.search(r'\byou\b',target,re.I):
        notes.append(('Đối tượng lời thoại','Có thêm you trong câu ly hôn; đối chiếu ngữ cảnh'))
    if 'dài như sớ' in source.casefold() and re.search(r'\b(petition|memorial|edict)\b',target,re.I):
        notes.append(('Thành ngữ','Có thể dịch sát chữ dài như sớ; kiểm tra cách nói tự nhiên'))
    if re.search(r'\bpangeri\b|\bboss akhir\b',target,re.I):
        notes.append(('Từ vựng Indonesia','Mẫu người dùng báo cần kiểm tra; không tự sửa tên riêng'))
    try:
        from .languages import language
        english=language(target_lang).locale in ('en','en-CA')
    except ValueError:english=False
    if english:
        if semantic:
            if re.search(r'chết chóc|chớt chóc',source,re.I) and not re.search(r'\b(death|dead|deadly|dying|die|dies|died|lethal|fatal|murderous|carnage|slaughter|bloodshed|killing|mortal)\b',target,re.I):
                notes.append(('Thiếu ý nghĩa','Nguồn có chết/chớt chóc nhưng bản dịch có thể thiếu nghĩa tử vong; cần người đọc xác minh'))
            if re.search(r'gào|hét',source,re.I) and 'bắt lấy' in source.lower() and re.search(r'\b(shouting|yelling|screaming)\s*,?\s+grabbing\b',target,re.I):
                notes.append(('Câu mệnh lệnh','Có thể đã biến lời hô bắt giữ thành hành động đang diễn ra; cần đối chiếu lời thoại'))
            question='?' in source or bool(re.search(r'\b(sao|ư|hả|chăng)\s*[.!?]*$|\bcó\s+[^,;]{1,160}\bkhông\s*(?:[,!?!.]|$)',source,re.I))
            interrogative=any(m in target for m in ('?','？')) or re.search(r'\b(what|why|how|who|where|when|whether)\b',target,re.I) or re.search(r'(?:^|[,:;.!]\s*)(?:is|are|was|were|do|does|did|can|could|will|would|shall|should|has|have)\b',target,re.I)
            if question and not interrogative:notes.append(('Sắc thái câu hỏi','Có thể đã đổi nghi vấn thành câu kể; đối chiếu nghĩa, không dựa riêng dấu hỏi'))
            if re.search(r'không hề|không phải|chưa từng|không bao giờ|chẳng hề',source,re.I) and not re.search(r"\b(not|never|no|cannot|without|yet|lacks?|failed)\b|n['’]t",target,re.I):
                notes.append(('Phủ định','Có thể thiếu nghĩa phủ định; cần đối chiếu thủ công'))
        male=re.match(r'\s*(cậu ta|anh ta|anh ấy|ông ta|ông ấy)\b',source,re.I)
        female=re.match(r'\s*(cô ta|cô ấy|bà ta|bà ấy)\b',source,re.I)
        if male and re.match(r'\s*she\b',target,re.I) or female and re.match(r'\s*he\b',target,re.I):
            notes.append(('Đại từ','Đại từ đầu câu có dấu hiệu đổi giới tính so với nguồn; kiểm tra ngữ cảnh và khả năng nguồn bị sai'))
    # Names are evidence only when distinctive and explicitly present; no character profile.
    names=set(re.findall(r'\b(?:Cael|Evelyn|Jacqueline|Damian|Reina|Emily)\b',source,re.I))
    if names and target_lang in ('Tiếng Anh','Tiếng Indonesia','en','id'):
        absent=[n for n in names if not re.search(r'\b'+re.escape(n)+r'\b',target,re.I)]
        if absent:notes.append(('Tên riêng','Có thể thiếu tên: '+', '.join(sorted(absent))+'; heuristic'))
    return notes


def collect(rows):
    result = []
    for r in rows:
        found = warnings(r)
        if found:
            result.append({"id": r["id"], "ordinal": r["ordinal"], "state": r["state"],
                           "source_revision": r["source_revision"], "translation_revision": r["translation_revision"], "warnings": found})
    return result
