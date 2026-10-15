"""Debounced validation off the GUI thread; never calls a translation provider."""
import threading
from pathlib import Path
from PySide6.QtCore import QTimer, Qt, Signal, Slot
from .glass import CompactStatusButton as GlassButton
from ..line_structure import validate_snapshot, source_layout


class LineCheck(GlassButton):
    ready = Signal(object)

    def __init__(self, owner):
        super().__init__('◷ Chưa có tài liệu', owner)
        self.owner = owner; self.dialog = None; self.report = None; self.rows = ()
        self._signature = None; self._busy = False; self._stopped = False
        self._layout_key = None; self._layout = None
        self.setObjectName('lineCheck'); self.setFocusPolicy(Qt.NoFocus)
        self.setToolTip('Kiểm tra số vị trí, ID, thứ tự và mức hoàn thành của tài liệu đang xem. Không xác nhận ngữ nghĩa bản dịch.')
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.setInterval(100)
        self.timer.timeout.connect(self.recount); self.ready.connect(self.apply_result, Qt.QueuedConnection)
        self.clicked.connect(self.open_list)

    def signature(self):
        with self.owner.store.lock: return (self.owner.doc_id, self.owner.store.db.total_changes)

    def schedule(self, *_):
        if self.owner._closed or self.owner._exit_pending or self._stopped: return
        if self.report is not None and self.report.document_id != self.owner.doc_id:
            self.report = None; self.rows = (); self.setText('◷ Đang kiểm tra dòng…'); self.setProperty('glassRole','secondary')
            if self.dialog is not None:self.dialog.update_rows(())
        if self.signature() != self._signature and not self.timer.isActive(): self.timer.start()

    def recount(self):
        owner = self.owner
        if owner._closed or owner._exit_pending or self._stopped: return
        signature = self.signature(); doc_id = signature[0]
        if not doc_id:
            self._signature = signature; self.report = None; self.rows = ()
            self.setText('◷ Chưa có tài liệu'); self.setProperty('glassRole','secondary')
            if self.dialog is not None:self.dialog.update_rows(())
            return
        if signature == self._signature or self._busy: return
        if self.report is None or self.report.document_id != doc_id:
            self.report = None; self.rows = (); self.setText('◷ Đang kiểm tra dòng…'); self.setProperty('glassRole','secondary')
            if self.dialog is not None:self.dialog.update_rows(())
        self._busy = True
        def inspect():
            try:
                (doc, rows), = owner.store.export_snapshot([doc_id])
                key = (doc_id, doc['digest'], doc['format'])
                try:layout = self._layout if key == self._layout_key else source_layout(doc)
                except ValueError:layout = None
                report = validate_snapshot(doc, rows, layout)
                payload = (signature, doc, report, key, layout)
            except Exception:
                payload = (signature, None, None, None, None)
            if not owner._closed and not self._stopped:
                try:self.ready.emit(payload)
                except RuntimeError:pass  # Accepted close may have destroyed the QObject.
        worker = threading.Thread(target=inspect, daemon=True)
        owner.background_threads[:] = [t for t in owner.background_threads if t.is_alive()]
        owner.background_threads.append(worker); worker.start()

    @Slot(object)
    def apply_result(self, payload):
        self._busy = False
        owner = self.owner
        if owner._closed or owner._exit_pending or self._stopped:return
        signature, doc, report, key, layout = payload
        if owner.doc_id != signature[0]:self.schedule();return
        self._signature = signature
        if report is None:
            self.setText('⚠ Không xác minh được số dòng'); self.setProperty('glassRole','warning')
            self.rows = (); self.report = None
        else:
            self._layout_key = key; self._layout = layout; self.report = report
            self.rows = tuple({'id':i['id'],'document_id':doc['id'],'ordinal':i['ordinal'],
                'preview':' · '.join(i['messages'])+(' — '+i['preview'] if i['preview'] else ''),
                'document':Path(doc['path']).name,'language':doc['target_lang']} for i in report.issues)
            if report.state == 'structure_error':
                self.setText(f'⚠\ufe0e Lỗi cấu trúc · {len(report.structural)} dòng'); self.setProperty('glassRole','warning')
            elif report.state == 'complete':
                self.setText(f'✓ Gốc {report.total} · Dịch {report.positions}'); self.setProperty('glassRole','success')
            elif not report.required:
                self.setText(f'◷ Gốc {report.total} · Giữ nguyên {report.skipped}'); self.setProperty('glassRole','secondary')
            else:
                self.setText(f'◷ Gốc {report.total} · Đã dịch {report.translated}/{report.required}'); self.setProperty('glassRole','secondary')
        self.update()
        if self.dialog is not None:self.dialog.update_rows(self.rows)
        self.schedule()

    def dialog_summary(self):
        r = self.report
        if r is None:return 'Chưa có tài liệu hoặc đang xác minh snapshot; chưa kết luận cấu trúc.'
        return (f'Gốc {r.total} · Vị trí dịch {r.positions} · Thành công {r.translated}/{r.required} · '
                f'Giữ nguyên {r.skipped}\nChờ/chưa dịch {r.pending} · Đang dịch {r.processing} · '
                f'Lỗi dịch {r.errors} · Lỗi cấu trúc {len(r.structural)}')

    def dialog_empty_text(self):
        return 'Không phát hiện lỗi cấu trúc dòng' if self.report is not None else 'Chưa có kết quả kiểm tra; không kết luận khớp dòng.'

    def open_list(self):
        from .period_dialog import PeriodDialog
        if self.owner._closed or self._stopped:return
        self.recount()
        if self.dialog is None:self.dialog = PeriodDialog(self, structure=True)
        self.dialog.update_rows(self.rows); self.dialog.fit_screen()
        self.dialog.show(); self.dialog.raise_(); self.dialog.activateWindow()

    def choose(self, key):
        if key[0] != self.owner.doc_id or not key[1]: self.recount();return
        self.owner.period_warning.navigate_key(key, self.dialog)

    def shutdown(self):
        self._stopped = True; self.timer.stop()
        if self.dialog is not None:self.dialog.close()
