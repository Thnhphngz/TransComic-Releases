"""Durable user requests, consumed only by the Automation translation lane."""
import time
import uuid
from ..documents import translatable
from ..status import usable


class Retranslation:
    def retry_requests(self, id):
        return self.repo.workset(id)['checkpoint'].get('translation_retries', [])

    def enqueue_retry(self, line_ids):
        with self.lock, self.services.translation.dispatch_lock, self.repo.store.transaction():
            id = self.repo.active()
            if not id or not self.busy or getattr(self, 'closing_translation', False):
                raise ValueError('Automation đang kết thúc; chờ Dừng an toàn hoàn tất rồi dịch lại.')
            if self.stop_event.is_set() or self.repo.workset(id)['state'] != 'running':
                raise ValueError('Đang dừng an toàn; chờ dừng hoàn tất rồi dịch lại.')
            groups = {g['document_id']: g for g in self.repo.groups(id)}
            rows = [self.repo.store.line(i) for i in dict.fromkeys(line_ids)]
            cfg = self.repo.workset(id)['config']
            if any(r['document_id'] not in groups for r in rows):
                raise ValueError('Tài liệu không thuộc bộ Automation đang chạy; dừng an toàn trước khi dịch thủ công.')
            if any(groups[r['document_id']]['data'].get('validation') for r in rows):
                raise ValueError('Nhóm chưa hợp lệ; dừng an toàn và kiểm tra nguồn/mapping trước khi dịch lại.')
            if cfg['provider'] == 'deepseek':
                from ..deepseek import read_key
                keys = [True] if read_key(self.repo.store) else []
            elif cfg['provider'] == 'kira':
                keys = [k for k in self.repo.store.kira_keys() if k['enabled'] and k['status'] in ('READY', 'COOLDOWN', 'TEMPORARY_ERROR')]
            else:
                keys = [k for k in self.repo.store.gemini_keys() if k['status'] not in ('invalid', 'disabled', 'exhausted', 'authentication', 'permission', 'quota_exhausted', 'model_not_found')]
            if not keys:
                raise ValueError('Không có API key hợp lệ cho provider của bộ Automation; kiểm tra API key/quota.')
            requests = self.retry_requests(id)
            occupied = {i for q in requests if q['state'] in ('pending', 'running') for i in q['line_ids']}
            # Include jobs not yet claimed, as well as active HTTP requests.
            for job in self.repo.store.jobs():
                if job['state'] in ('ready','running','paused','pausing','stopping','user_paused','waiting_rate_limit','retry_scheduled','network_waiting','provider_recovering'):
                    for batch in self.repo.store.batches(job['id']):
                        if batch['state'] in ('pending','inflight','retry_wait'):
                            occupied.update(p['id'] for p in batch['payload'])
            ids = [r['id'] for r in rows if translatable(r['source']) and r['state'] != 'processing' and r['id'] not in occupied]
            if ids:
                request = dict(id=str(uuid.uuid4()), line_ids=ids, state='pending', started=False, created=time.time(),
                               revisions={r['id']:r['translation_revision'] for r in rows if r['id'] in ids})
                self.checkpoint(id, translation_retries=[*requests, request])
                for gid in {groups[r['document_id']]['id'] for r in rows if r['id'] in ids}:
                    self.repo.update_group(gid, translation_ready_cycle=None)
                self.repo.event(id, None, 'translation', f'Đã đưa {len(ids)} dòng vào hàng đợi dịch của Tự động hóa.')
        self.changed()
        return len(ids)

    def pending_retry_groups(self, id):
        documents = {self.repo.store.line(i)['document_id'] for q in self.retry_requests(id)
                     if q['state'] in ('pending', 'running') for i in q['line_ids']}
        return {g['id'] for g in self.repo.groups(id) if g['document_id'] in documents}

    def run_retry(self, id, request, groups, cfg):
        """Called by the same stage executor after its previous scheduler joined."""
        with self.lock, self.repo.store.transaction():
            if self.stop_event.is_set():return
            requests = self.retry_requests(id)
            current = next(q for q in requests if q['id'] == request['id'])
            if not current['started']:
                for line_id in current['line_ids']:
                    row=self.repo.store.line(line_id)
                    if usable(row) and row['translation_revision']!=current.get('revisions',{}).get(line_id,row['translation_revision']):continue
                    self.repo.store.db.execute("UPDATE lines SET translation_source_revision=NULL, state='pending' WHERE id=?", (line_id,))
                current['started'] = True
            current['state'] = 'running'
            self.checkpoint(id, translation_retries=requests)
        finished=False
        try:
            self.services.translation.run(id, groups, cfg, self.stop_event, self.changed,
                                          line_ids=set(current['line_ids']), scope='retry:'+current['id'])
            finished=True
        finally:
            # Keep a stopped request recoverable; usable replies are never sent again.
            with self.lock, self.repo.store.transaction():
                requests = self.retry_requests(id)
                current = next(q for q in requests if q['id'] == request['id'])
                current['state'] = 'pending' if self.stop_event.is_set() or not finished else 'done'
                self.checkpoint(id, translation_retries=requests)
            for line_id in current['line_ids']:
                self.repo.line_edited(line_id)
            if not self.stop_event.is_set():
                from ..line_structure import validate_snapshot
                for group in groups:
                    self.repo.store.validate_document_language(group['document_id'])
                    rows=self.repo.store.units(group['document_id'])
                    if all(usable(r) for r in rows if translatable(r['source'])) and not validate_snapshot(self.repo.store.document(group['document_id']),rows).structural:
                        self.repo.update_group(group['id'],translation_ready_cycle=self.repo.workset(id)['cycle'],translation_ready_at=time.monotonic_ns(),error='')

    def normal_translation(self, id, groups, cfg):
        pending = {i for q in self.retry_requests(id) if q['state'] in ('pending', 'running') for i in q['line_ids']}
        self.services.translation.run(id, groups, cfg, self.stop_event, self.changed, exclude_ids=pending)
