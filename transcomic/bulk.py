"""Batch imports and detached export snapshots; no provider calls."""
from collections import Counter
from pathlib import Path
import hashlib
import os
import re
from .documents import ImportedText, TextLine, import_txt, atomic_export, render_export, translatable
from .docx_document import import_docx, render_docx
from .status import usable

from .languages import LANG_CODES, language, export_name


def natural_key(path):
    return tuple((0, int(p)) if p.isdigit() else (1, p.casefold()) for p in re.split(r'(\d+)', str(path)))


def discover_files(paths):
    found, rejected, visited = {}, [], set()
    pending = list(reversed(paths))
    while pending:
        path = Path(pending.pop())
        try:
            resolved = path.resolve()
            identity = os.path.normcase(str(resolved))
            if identity in visited: continue
            visited.add(identity)
            if path.is_dir():
                children = sorted(path.iterdir(), key=natural_key)
                if not children: rejected.append({'path': str(path), 'error': 'empty_directory'})
                pending.extend(reversed(children))
            elif path.is_file() and path.suffix.lower() in ('.txt', '.docx'):
                found[identity] = resolved
            else: rejected.append({'path': str(path), 'error': 'unsupported_or_missing'})
        except (OSError, RuntimeError) as exc:
            rejected.append({'path': str(path), 'error': type(exc).__name__})
    return sorted(found.values(), key=lambda p: (natural_key(p.name), natural_key(p))), rejected


def path_identity(path):
    return os.path.normcase(str(Path(path).resolve()))


def import_many(store, paths, source_lang, target_lang, on_import=None, existing_ids=()):
    files, errors = discover_files(paths)
    document_ids = []
    existing = {path_identity(store.document(d)['path']): store.document(d) for d in existing_ids}
    duplicates, changed = [], []
    for file in files:
        try:
            prior = existing.get(path_identity(file))
            if prior:
                duplicates.append(prior['id'])
                if hashlib.sha256(file.read_bytes()).hexdigest() != prior['digest']:
                    changed.append(prior['id'])
                continue
            if file.suffix.lower() == '.docx':
                obj = import_docx(file)
                data = ImportedText(tuple(TextLine(u.text, '') for u in obj.units), 'docx', obj.raw)
                doc, _ = store.import_document(file, data, source_lang, target_lang, 'docx', [u.locator for u in obj.units])
            else:
                doc, _ = store.import_document(file, import_txt(file), source_lang, target_lang)
            document_ids.append(doc)
            if on_import: on_import(doc)
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append({'path': str(file), 'error': type(exc).__name__})
            store.log.emit('import_error', exception=type(exc).__name__, state='not_imported')
    return {'document_ids': document_ids, 'supported_files': len(files), 'errors': errors,
            'duplicate_ids': duplicates, 'changed_source_ids': changed}


def workspace_status(rows, job_state=None):
    required = [r for r in rows if translatable(r['source'])]
    done = sum(usable(r) for r in required)
    errors = sum(r['state'] in ('error','wrong_target_language') for r in required)
    unknown = sum(r['state'] == 'unknown' for r in required)
    if job_state in ('stopped', 'interrupted'): state = 'Đã dừng' if job_state == 'stopped' else 'Bị gián đoạn'
    elif job_state in ('paused', 'pausing', 'user_paused'): state = 'Tạm dừng người dùng'
    elif job_state == 'waiting_rate_limit': state = 'Chờ giới hạn API'
    elif job_state in ('quota_exhausted', 'needs_intervention'): state = 'Cần xử lý hạn mức/lỗi API'
    elif any(r['state'] == 'processing' for r in required): state = 'Đang dịch'
    elif done == len(required): state = 'Hoàn thành đầy đủ'
    elif unknown: state = 'Không rõ kết quả'
    elif errors: state = 'Còn lỗi'
    elif job_state == 'finished': state = 'Đã xử lý xong'
    else: state = 'Đang chờ'
    return {'total': len(required), 'done': done, 'errors': errors, 'unknown': unknown,
            'missing': len(required)-done, 'progress': int(done*100/len(required)) if required else 100, 'state': state}


def plan_exports(snapshots, root=None, *, mode=None):
    """Deterministic collision suffixes; root=None means beside each source."""
    counts = Counter((str(Path(d['path']).parent) if root is None else str(root), d['target_lang'], Path(d['path']).stem.casefold(), Path(d['path']).suffix.casefold()) for d, _ in snapshots)
    plan, assigned = [], set()
    sources = {str(Path(d['path']).resolve()).casefold() for d, _ in snapshots}
    for doc, rows in sorted(snapshots, key=lambda pair: (natural_key(pair[0]['path']), pair[0]['target_lang'], pair[0]['source_instance'])):
        source = Path(doc['path'])
        entry = language(doc['target_lang']); code=entry.code
        if mode not in (None, 'direct', 'transcomic', 'custom'): raise ValueError('Invalid export mode')
        if mode in ('direct', 'transcomic') and not source.is_file(): raise ValueError('Linked source no longer exists; choose another export folder')
        folder = source.parent if mode == 'direct' else source.parent/'TransComic'/entry.folder if mode == 'transcomic' else Path(root) if mode == 'custom' and root else source.parent/'TransComic'/code if root is None else Path(root)/code
        if mode == 'custom' and not root: raise ValueError('Custom folder required')
        key = (str(source.parent) if root is None else str(root), doc['target_lang'], source.stem.casefold(), source.suffix.casefold())
        suffix = '_'+hashlib.sha256((str(source.resolve())+'|'+doc['source_instance']).encode()).hexdigest()[:8] if counts[key] > 1 else ''
        name = export_name(source.with_name(source.stem+suffix+source.suffix), entry.locale, bool(workspace_status(rows)['missing']))
        target = folder/name
        if str(target.resolve()).casefold() in sources or str(target.resolve()).casefold() in assigned: raise ValueError('Unsafe duplicate export path')
        assigned.add(str(target.resolve()).casefold())
        plan.append({'document': doc, 'rows': rows, 'target': target, 'mode': mode})
    return plan


def write_exports(store, plan, *, existing='cancel', allow_incomplete=False):
    """Render captured rows; never re-read live translations during an export."""
    if existing not in ('cancel', 'overwrite', 'version'): raise ValueError('Invalid overwrite policy')
    results = []
    for item in plan:
        doc, rows, target = item['document'], item['rows'], item['target']
        try:
            from .language_validator import export_faults
            faults = export_faults(doc, rows)
            if faults:
                results.append({'document_id':doc['id'],'state':'blocked_language','faults':faults,'path':str(target)})
                continue
            content, missing = render_docx(doc['snapshot'], rows) if doc['format'] == 'docx' else render_export(rows)
            if missing and not allow_incomplete: raise ValueError('Incomplete translation requires confirmation')
            overwrite = False
            if target.exists():
                if existing == 'cancel':
                    results.append({'document_id': doc['id'], 'state': 'cancelled', 'path': str(target)}); continue
                if existing == 'overwrite': overwrite = True
                else:
                    base, count = target, 2
                    while target.exists():
                        target = base.with_name(base.stem+f'_{count}'+base.suffix); count += 1
            if item.get('mode') == 'direct':
                if not target.parent.is_dir(): raise ValueError('Source folder disappeared')
            else: target.parent.mkdir(parents=True, exist_ok=True)
            atomic_export(target, content, overwrite)
            revision = hashlib.sha256(json_revision(rows).encode()).hexdigest()
            store.set_setting('export_revision_'+doc['id'], revision)
            store.set_setting('export_path_'+doc['id'], str(target))
            store.log.emit('exported', document_id=doc['id'], target_lang=doc['target_lang'], state='exported')
            results.append({'document_id': doc['id'], 'state': 'exported', 'path': str(target), 'missing': missing})
        except (OSError, ValueError) as exc:
            store.log.emit('export_error', document_id=doc['id'], target_lang=doc['target_lang'], exception=type(exc).__name__, state='not_exported')
            results.append({'document_id': doc['id'], 'state': 'error', 'error': type(exc).__name__})
    return results


def json_revision(rows):
    import json
    return json.dumps([(r['id'], r['source_revision'], r['translation_revision'], r['state']) for r in rows])
