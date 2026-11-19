"""Folder drops share the Automation table and its stable group IDs."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from time import monotonic

from ..automation.folder_inputs import DOCUMENTS, WORD, scan_folder
from ..automation.validation import ValidationSuperseded, check_current


FOLDER_SCAN_WORKERS = 10


def local_paths(event):
    urls = event.mimeData().urls()
    return [Path(url.toLocalFile()) for url in urls] if all(url.isLocalFile() for url in urls) else []


class AutomationDrops:
    def init_folder_scans(self):
        self.folder_pool = ThreadPoolExecutor(max_workers=FOLDER_SCAN_WORKERS, thread_name_prefix='automation-folder-scan')
        self.folder_queue_lock = Lock()
        self.folder_queue = {}
        self.folder_running = set()

    def folder_scans_active(self):
        with self.folder_queue_lock:
            return bool(self.folder_queue or self.folder_running)

    def stop_folder_scans(self):
        # The session cancel flag is set before this call. Submitted jobs still
        # run their cleanup; wait for them through the normal exit checks.
        with self.folder_queue_lock:
            self.folder_queue.clear()
            self.folder_pool.shutdown(wait=False)

    def drop_paths(self, paths, id=None):
        self.safe(lambda: self.route_drop(paths, id))

    def route_drop(self, paths, target):
        if self.draft_cancel.is_set() or self.repo.session_closing.is_set():
            return
        if self.controller.busy:
            raise ValueError('Dừng an toàn trước khi thêm tài liệu hoặc thư mục ảnh.')
        paths = [Path(path) for path in paths]
        folders = [path for path in paths if path.is_dir()]
        documents = [path for path in paths if path not in folders and path.is_file() and path.suffix.lower() in DOCUMENTS]
        if len(folders) + len(documents) != len(paths):
            self.notice.setText('Chỉ hỗ trợ tài liệu DOCX/TXT và thư mục ảnh.')
        if not (folders or documents):
            return
        has_word = any(path.suffix.lower() == WORD for path in documents)
        draft = self.repo.folder_draft(target) if target else None
        if draft and not folders:
            if len(documents) != len(paths) or len(documents) != 1 or not has_word:
                raise ValueError('Kéo đúng một file DOCX vào dòng chờ Word.')
            if draft.busy:
                raise ValueError('Chờ dòng này quét ảnh xong trước khi kéo DOCX vào.')
            if draft.state != 'waiting_word':
                raise ValueError('Bỏ dòng này rồi thả lại thư mục để quét ảnh.')
            self.bind_folder_word(draft, documents[0])
            return
        if target and not folders and has_word:
            raise ValueError('Dòng này đã có tài liệu. Hãy thả file vào vùng trống để thêm dòng mới.')
        if target and len(folders) == len(paths) == 1:
            if draft:
                raise ValueError('Dòng này đã có thư mục ảnh. Hãy kéo DOCX vào dòng hoặc thả thư mục khác vào vùng trống.')
            self.pair_folder(target, folders[0])
            return
        if not self.current:
            self.create_workset((folders[0] if folders else documents[0]).stem)
        if folders:
            self.add_folders(folders)
        if documents:
            self.queue_documents(documents, auto_images=has_word)

    def add_folders(self, paths):
        workset = self.current
        drafts = [draft for path in paths if (draft := self.repo.reserve_folder(workset, path))]
        if not drafts:
            self.notice.setText('Thư mục đã có trong bộ công việc.')
            return
        self.proof = None
        self.validation_generation += 1
        self.start.setEnabled(False)
        self.refresh()

        with self.folder_queue_lock:
            self.folder_queue.update((draft.id, draft) for draft in drafts)
            self.dispatch_folder_scans()

    def dispatch_folder_scans(self):
        # Caller holds the queue lock. Refill from the completing worker so the
        # next folder need not wait for a Qt event or for the rest to finish.
        while self.folder_queue and len(self.folder_running) < FOLDER_SCAN_WORKERS:
            if self.draft_cancel.is_set() or self.repo.session_closing.is_set():
                return
            id = next(iter(self.folder_queue))
            draft = self.folder_queue.pop(id)
            self.folder_running.add(id)
            self.folder_pool.submit(self.inspect_folder, draft)

    def inspect_folder(self, draft):
        scanned = None
        imported = False
        error = ''
        last_progress = monotonic()

        def cancelled():
            return self.draft_cancel.is_set() or self.repo.session_closing.is_set() or draft.cancelled.is_set()

        def progress(done, total):
            nonlocal last_progress
            now = monotonic()
            if not cancelled() and (done == total or now - last_progress >= .25):
                last_progress = now
                self.folder_progress.emit(draft, f'Đang quét ảnh {done}/{total}')

        try:
            try:
                check_current(cancelled)
                self.folder_progress.emit(draft, 'Đang quét ảnh')
                scanned = scan_folder(draft.path, cancelled=cancelled, progress=progress, inspection=True)
                check_current(cancelled)
                if len(scanned.words) == 1:
                    imported = bool(self.repo.add(draft.workset, [draft.path / scanned.words[0]],
                                                 cancelled=cancelled, folder=(draft, scanned)))
                    if not imported:
                        error = 'DOCX này đã có trong một dòng khác.'
            except ValidationSuperseded:
                return
            except Exception as exc:
                error = str(exc) or 'Không đọc được thư mục hoặc DOCX.'
            if not cancelled():
                self.folder_result.emit(draft, (scanned, imported, error))
        finally:
            with self.folder_queue_lock:
                self.folder_running.remove(draft.id)
                self.dispatch_folder_scans()

    def dequeue_folders(self, ids):
        with self.folder_queue_lock:
            for id in ids:
                self.folder_queue.pop(id, None)

    def cancel_folder_scan(self, id):
        draft = self.repo.folder_draft(id)
        if not draft or draft.state not in ('folder_queued', 'folder_scan'):
            return
        self.dequeue_folders((id,))
        self.repo.remove_group(id, keep_folder=True)
        draft.busy = False
        draft.state = 'folder_scan_cancelled'
        draft.status = 'Đã hủy'
        self.mark_dirty()
        self.finish_folder_batch(draft.workset)

    def finish_folder_batch(self, workset):
        if any(draft.busy for draft in self.repo.folder_drafts(workset)):
            return
        if not self.repo.owns(workset):
            return
        self.folder_validation_needed.add(workset)
        if self.current == workset and not self.import_busy:
            self.folder_validation_needed.discard(workset)
            if self.repo.group_summaries(workset):
                self.queue_validation(initial=True)

    def show_folder_progress(self, draft, status):
        if self.draft_cancel.is_set() or self.repo.session_closing.is_set() or draft.cancelled.is_set() or not draft.busy:
            return
        draft.state = 'folder_scan'
        draft.status = status
        if self.current == draft.workset:
            self.mark_dirty()

    def show_folder_result(self, draft, result):
        if self.draft_cancel.is_set() or self.repo.session_closing.is_set() or draft.cancelled.is_set():
            return
        scanned, imported, error = result
        draft.scan = scanned
        draft.busy = False
        draft.error = error
        draft.state = 'waiting_word' if scanned else 'folder_scan_error'
        draft.status = 'Quét lỗi' if scanned is None or scanned.error else 'Đã quét xong'
        empty = scanned is not None and not (scanned.images or scanned.words)
        if imported or empty:
            self.repo.finish_folder(draft)
        if not imported and (empty or scanned is None) and self.current == draft.workset:
            failure = error or (scanned.error if scanned else '') or 'Không tìm thấy DOCX hoặc ảnh hợp lệ.'
            self.notice.setText(f'{draft.path.name} · {failure}')
        self.mark_dirty()
        self.finish_folder_batch(draft.workset)

    def bind_folder_word(self, draft, path):
        self.repo.editable(draft.workset)
        draft.busy = True
        draft.state = 'folder_importing'
        draft.status = 'Đang nhập DOCX…'
        self.proof = None
        self.start.setEnabled(False)
        self.mark_dirty()

        def cancelled():
            return self.draft_cancel.is_set() or draft.cancelled.is_set()

        def attach():
            try:
                added = self.repo.add(draft.workset, [path], cancelled=cancelled, folder=(draft,draft.scan))
                return bool(added), '' if added else 'DOCX này đã có trong một dòng khác.'
            except ValidationSuperseded:
                return False, ''
            except Exception as exc:
                return False, str(exc)

        def attached(result):
            if cancelled():
                return
            imported, error = result
            self.show_folder_result(draft, (draft.scan, imported, error))
        self.background(attach, attached)
