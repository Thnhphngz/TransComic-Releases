"""Bounded DeepSeek JSON compatibility; never repairs translation content."""
import hashlib
import json

from .providers import BatchResult, parse_line_response
from .translation_policy import SEMANTIC_VERSIONS

PARSER_VERSION = 'deepseek-json-root-type-v1'


def parse_translation(content, expected, prompt_version):
    """Map by stable ID, so a reordered valid result is unambiguous.

    Only semantic policies allow exactly type=json_object at the root. Unknown
    fields, duplicate JSON keys, wrappers and malformed entries remain errors.
    Every failure rejects the whole batch, including otherwise valid entries.
    """
    diag = dict(parser_version=PARSER_VERSION,
                raw_content_sha256=hashlib.sha256(content.encode('utf8',errors='surrogatepass')).hexdigest() if isinstance(content,str) else None)
    def fail(message, kind='invalid_schema'):
        diag['failure_kind']=kind
        if 'root_metadata' in diag:
            diag['metadata_decision']='rejected'
            diag['metadata_reason']=message
        return BatchResult({},message,diagnostics=diag)
    def pairs(items):
        obj={}
        for key,value in items:
            if key in obj:raise ValueError('Duplicate JSON key')
            obj[key]=value
        return obj
    try:
        obj=json.loads(content,object_pairs_hook=pairs,
                       parse_constant=lambda x:(_ for _ in ()).throw(ValueError('Invalid JSON constant')))
    except (ValueError,TypeError,UnicodeError):return fail('Phản hồi DeepSeek rỗng hoặc JSON không hợp lệ')
    if not isinstance(obj,dict):return fail('JSON sai schema')
    extras=set(obj)-{'lines'}
    if extras:
        diag['root_metadata']={key:obj[key] for key in extras if key=='type'}
        diag['extra_root_keys']=sorted(extras)
        if extras!={'type'} or prompt_version not in SEMANTIC_VERSIONS or obj['type']!='json_object':
            return fail('JSON có trường root không được phép hoặc metadata mâu thuẫn')
    if 'lines' not in obj or not isinstance(obj['lines'],list) or any(not isinstance(r,dict) or set(r)!={'id','text'} for r in obj['lines']):
        return fail('JSON sai schema dòng')
    parsed=parse_line_response(json.dumps({'lines':obj['lines']},ensure_ascii=True),set(expected))
    if parsed.error:
        diag.update(parsed.diagnostics or {})
        return fail('JSON thiếu/trùng ID hoặc nội dung không hợp lệ','invalid_line_response')
    broken=[id for id,text in parsed.values.items() if any(c in text for c in ('\u0085','\u2028','\u2029'))]
    if prompt_version in SEMANTIC_VERSIONS and broken:
        diag['structure_errors']=[dict(code='linebreak',line_ids=broken)]
        return fail('Bản dịch chứa ký tự xuống dòng Unicode','invalid_line_response')
    if extras:
        diag.update(metadata_decision='accepted',metadata_reason='Only root type=json_object; target entries and stable IDs fully validated')
    return BatchResult(parsed.values,diagnostics=diag)
