"""Structural validation of detached export snapshots, independent of providers/UI.

Rows own both source and target: their stable ID is the one-to-one mapping. The
original bytes establish positions/endings/OOXML locators, not semantic accuracy.
"""
from collections import Counter
from dataclasses import dataclass
import hashlib
from .documents import decode_txt, translatable
from .status import usable


@dataclass(frozen=True)
class LineReport:
    document_id: str
    total: int
    positions: int
    required: int
    translated: int
    skipped: int
    pending: int
    processing: int
    errors: int
    missing: int
    structural: tuple
    issues: tuple

    @property
    def state(self):
        return 'structure_error' if self.structural else 'complete' if self.total and self.required and not self.missing else 'incomplete'


def source_layout(document):
    if document['format'] == 'docx':
        from .docx_document import inspect_docx
        return tuple((u.text, '', u.locator) for u in inspect_docx(document['snapshot']).units)
    return tuple((u.text, u.ending, None) for u in decode_txt(document['snapshot'], document['encoding']).lines)


def validate_snapshot(document, rows, layout=None):
    """Read only. Input order matters for export; ID response order does not."""
    doc_id = document['id']; faults = {}; notices = {}
    def add(row, code, message, structural=True, ordinal=None):
        number = row.get('ordinal') if row is not None else ordinal
        key = (row.get('id') if row else None, number)
        target = faults if structural else notices
        item = target.setdefault(key, {'id': row.get('id') if row else None, 'document_id': doc_id,
            'ordinal': number, 'messages': [], 'codes': [], 'preview': str((row or {}).get('translation') or '')[:120]})
        if code not in item['codes']: item['codes'].append(code); item['messages'].append(message)
    try:
        if document.get('digest') and hashlib.sha256(document['snapshot']).hexdigest() != document['digest']:
            raise ValueError('Snapshot checksum mismatch')
        layout = source_layout(document) if layout is None else layout
    except (ValueError, UnicodeError, KeyError):
        layout = (); add(None, 'snapshot', 'Không xác minh được snapshot nhập gốc')
    total = len(layout)
    ids = Counter(r.get('id') for r in rows)
    ordinals = Counter(r.get('ordinal') for r in rows)
    owned = {r.get('id'): r for r in rows}
    for number in range(total):
        if not ordinals[number]: add(None, 'missing_position', 'Thiếu vị trí dòng so với bản nhập gốc', ordinal=number)
    for position, row in enumerate(rows):
        number = row.get('ordinal'); line_id = row.get('id')
        if not isinstance(line_id, str) or not line_id or ids[line_id] > 1:
            add(row, 'duplicate_id', 'ID dòng thiếu hoặc trùng')
        if row.get('document_id') != doc_id: add(row, 'owner', 'ID dòng thuộc tài liệu khác')
        valid_position = isinstance(number, int) and not isinstance(number, bool) and 0 <= number < total
        if not valid_position: add(row, 'extra_position', 'Vị trí dòng thừa hoặc ngoài snapshot gốc')
        elif ordinals[number] > 1: add(row, 'duplicate_position', 'Trùng vị trí dòng gốc')
        if valid_position and number != position: add(row, 'order', 'Thứ tự dòng không khớp vị trí nguồn')
        for field, label in (('source','Nguồn'),('translation','Bản dịch')):
            value = row.get(field)
            if value is not None and (not isinstance(value, str) or '\r' in value or '\n' in value):
                add(row, 'newline_'+field, label+' chứa xuống dòng thực tế hoặc dữ liệu không hợp lệ')
        if valid_position:
            original, ending, locator = layout[number]
            if (not row.get('source_revision',0) and row.get('source') != original and
                    row.get('source') not in document.get('_structure_inherited_sources',{}).get(number, ())):
                add(row, 'source_mapping', 'Nguồn không khớp vị trí gốc và không có revision chỉnh sửa')
            if document['format'] == 'docx':
                if row.get('locator') != locator: add(row, 'locator', 'Sai hoặc thiếu ánh xạ đơn vị DOCX')
            elif row.get('ending') != ending: add(row, 'ending', 'Dấu kết thúc dòng không khớp bản nhập gốc')
            elif number == total-1 and ending == '' and row.get('source') == '':
                add(row, 'empty_final_unit', 'Dòng cuối rỗng không có dấu kết thúc sẽ mất vị trí khi xuất TXT')
    if document['format'] == 'docx' and '_structure_units' in document:
        mappings = document['_structure_units']
        if (len(mappings) != total or Counter(u['line_id'] for u in mappings) != ids or
                any(u['document_id'] != doc_id for u in mappings)):
            add(None, 'unit_mapping', 'Bảng ánh xạ DOCX không khớp các ID nguồn')
    # Only unresolved structural evidence from the captured batch is relevant.
    # HTTP timeouts/authentication errors alone are not proof of broken mapping.
    for batch in document.get('_structure_batches', ()):
        diagnostics = batch.get('diagnostics') or {}
        evidence = diagnostics.get('structure_errors') or ()
        if not evidence and diagnostics.get('failure_kind') in ('partial_response','invalid_line_response','invalid_schema'):
            evidence = ({'code':'batch_mapping','line_ids':[p['id'] for p in batch['payload']]},)
        if not evidence and any(s in (batch.get('error') or '') for s in ('line ID','line IDs','line IDs/values')):
            evidence = ({'code':'batch_mapping','line_ids':[p['id'] for p in batch['payload']]},)
        for failure in evidence:
            if any(item['id'] not in owned for item in batch['payload']):
                add(None, 'batch_owner', 'Batch tham chiếu ID không còn thuộc tài liệu')
            affected = set(failure.get('line_ids') or [p['id'] for p in batch['payload']])
            unresolved = []
            for item in batch['payload']:
                row = owned.get(item['id'])
                if item['id'] not in affected or row is None: continue
                if row.get('source_revision',0) != item.get('source_revision',0): continue
                # Exact-ID acceptance is positive evidence at the current pair
                # of revisions. An old response-level warning is not a defect
                # in the current document; real ownership/order faults above
                # remain blocking, irrespective of this evidence.
                if (usable(row) and row.get('state')=='done' and
                        row.get('verified_source_revision')==row.get('source_revision') and
                        row.get('verified_translation_revision')==row.get('translation_revision')):continue
                # Unmapped extra IDs are batch-wide: all verified results may have
                # been saved at revision +1; a later successful edit/run supersedes it.
                allowance = 1 if not failure.get('line_ids') else 0
                if (isinstance(row.get('source'),str) and isinstance(row.get('translation'),str) and
                        usable(row) and row.get('translation_revision',0) > item.get('translation_revision',0)+allowance): continue
                unresolved.append(row)
            for row in unresolved:
                add(row, 'batch_'+failure['code'], 'Kết quả API sai cấu trúc ID/số lượng ('+failure['code']+')')
    required = translated = skipped = pending = processing = errors = 0
    for row in rows:
        if isinstance(row.get('source'),str) and not translatable(row['source']):
            skipped += 1; continue
        required += 1
        row_usable = isinstance(row.get('source'),str) and isinstance(row.get('translation'),str) and usable(row)
        if row_usable: translated += 1
        if row.get('state') in ('error','unknown','wrong_target_language'): errors += 1
        if row_usable and row.get('state') in ('error','unknown','wrong_target_language'):
            add(row, 'retained_translation', 'Lượt dịch mới lỗi; đang giữ bản dịch hợp lệ trước đó', structural=False)
        if not row_usable:
            state = row.get('state')
            if state == 'processing': processing += 1; message = 'Đang dịch'
            elif state in ('error','unknown','wrong_target_language'): message = 'Lỗi dịch / kết quả chưa xác minh'
            else: pending += 1; message = 'Chưa có bản dịch hợp lệ'
            add(row, 'unfinished', message, structural=False)
    # Combine messages into one detail entry per source position.
    issues = dict(notices)
    for key, item in faults.items():
        previous = issues.get(key)
        if previous:
            item = {**item, 'messages': item['messages']+previous['messages'], 'codes':item['codes']+previous['codes']}
        issues[key] = item
    ordered = lambda items: tuple(sorted(items, key=lambda i:(i['ordinal'] is None, i['ordinal'] if isinstance(i['ordinal'],int) else -1, str(i['id']))))
    return LineReport(doc_id,total,len(rows),required,translated,skipped,pending,processing,errors,
                      required-translated,ordered(faults.values()),ordered(issues.values()))
