"""Stage 2 desktop controls, keeping the manuscript editor and single-file flows."""
import asyncio
import json
import threading
import time
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, QSignalBlocker
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QMenu, QFileDialog, QMessageBox, QDialog, QListWidget, QDialogButtonBox, QLineEdit, QFormLayout,
    QSpinBox, QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView, QScrollArea, QInputDialog)
from ..bulk import import_many, plan_exports, write_exports, workspace_status
from ..gemini import GeminiProvider, QuotaLimiter
from ..models import KIRA_MODELS
from ..providers import KiraProvider
from ..translation import Scheduler
from .controls import QComboBox, QSpinBox
from .glass import GlassButton as QPushButton
from .kira_api import KiraApiMixin


class Stage2Mixin(KiraApiMixin):
    def setup_stage2(self):
        self.workspace_ids = []
        self.workspace_positions = {}
        self.extra_targets = json.loads(self.store.setting('extra_targets', '[]'))
        from ..languages import language
        saved_order=self.store.setting('target_order','')
        try:
            order=[language(n).name for n in json.loads(saved_order or '[]')]
        except (ValueError,TypeError):order=[]
        self._saved_target_order=order if saved_order else None
        if order:
            self.target_lang.setCurrentText(order[0]);self.extra_targets=order[1:]
        self.import_busy = False
        self.metadata_busy = False
        self.export_busy = False
        self.background_threads = []
        self.provider_selector = QComboBox()
        self.provider_selector.addItem('Kira', 'kira'); self.provider_selector.addItem('Gemini', 'gemini')
        column = QVBoxLayout(); column.setSpacing(4)
        column.addWidget(QLabel('Provider')); column.addWidget(self.provider_selector)
        self.controls_widget.layout().insertLayout(0, column)
        self.provider_selector.currentIndexChanged.connect(self.change_provider)
        self.provider_selector.setCurrentIndex(max(0, self.provider_selector.findData(self.store.setting('provider', 'kira'))))
        self.import_button.clicked.disconnect(self.import_file)
        self.import_button.clicked.connect(self.choose_files)
        self.import_button.setToolTip('Nhập nhiều TXT/DOCX; có thể kéo thả file và thư mục.')
        self.export_many_button = QPushButton('Xuất hàng loạt…')
        self.export_many_button.clicked.connect(self.export_many)
        self.setAcceptDrops(True)
        self.build_gemini_api()
        api = self.pages.widget(2); self.pages.removeWidget(api)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(api); scroll.setFrameShape(QScrollArea.NoFrame)
        self.pages.insertWidget(2, scroll)
        self.build_live_queue()
        self.bridge.stage2.connect(self.stage2_result)
        self.queue_timer = QTimer(self); self.queue_timer.setInterval(750)
        self.queue_timer.timeout.connect(self.refresh_stage2)
        self.queue_timer.start()
        self.change_provider()

    def provider_id(self):
        return self.provider_selector.currentData() if hasattr(self, 'provider_selector') else 'kira'

    def change_provider(self, *_):
        if not hasattr(self, 'provider_selector'): return
        if hasattr(self, 'gemini_verified'): self.gemini_verified.setChecked(False)
        provider = self.provider_id()
        self.model_caption.setText('Mô hình Kira' if provider == 'kira' else 'Mô hình Gemini')
        self.store.set_setting('provider', provider)
        self.concurrency.blockSignals(True)
        self.model_name.blockSignals(True); self.model_name.clear()
        if provider == 'kira':
            for label, model in KIRA_MODELS: self.model_name.addItem(label, model)
            saved = self.store.setting('kira_model', 'kira-2.5-flash')
            self.concurrency.setMaximum(30)
            self.concurrency.setToolTip('Số request đồng thời tối đa MỖI key Kira (1–30); các key cùng nhóm tài khoản chia sẻ trần tài khoản/RPM/TPM.')
            self.concurrency.setValue(int(self.store.setting('concurrency', '30')))
        else:
            self.concurrency.setToolTip('Concurrency theo quota Gemini đã xác minh; không nhân theo số key.')
            cache = json.loads(self.store.setting('gemini_models', '{"models":[]}'))
            for model in cache.get('models', []): self.model_name.addItem(model['displayName'], model['name'])
            saved = self.store.setting('gemini_model')
            maximum = int(self.store.setting('gemini_concurrency', '1'))
            self.concurrency.setMaximum(maximum)
            self.concurrency.setValue(min(self.concurrency.value(), maximum))
        self.concurrency.blockSignals(False)
        if saved: self.set_model_id(saved)
        self.model_name.blockSignals(False)
        self.retry_504_check.setEnabled(False)
        self.retry_504_check.setToolTip('Kira Multi-Key không tự gửi lại batch 504/timeout/lỗi. Cấu hình cũ chỉ dành cho lịch sử trước nâng cấp.')
        if hasattr(self,'auto_retry_combo'):self.auto_retry_combo.setEnabled(provider!='kira')
        if hasattr(self, 'gemini_offline'):
            self.gemini_offline.setText('Danh sách cache/offline; chưa gọi kiểm tra kết nối. '+str(self.model_name.count())+' model khi chọn Gemini.')
        if hasattr(self,'kira_manage_button'):self.kira_manage_button.setVisible(provider=='kira')

    def choose_targets(self):
        dialog = QDialog(self); dialog.setWindowTitle('Ngôn ngữ đích của lượt dịch mới')
        layout = QVBoxLayout(dialog); listing = QListWidget()
        ordered=list(self.target_languages());selected=set(ordered)
        for i in range(self.target_lang.count()):
            name = self.target_lang.itemText(i)
            if name == self.source_lang.currentText(): continue
            listing.addItem(name); listing.item(listing.count()-1).setCheckState(Qt.Checked if name in selected else Qt.Unchecked)
        def changed(item):
            if item.text() in ordered:ordered.remove(item.text())
            if item.checkState()==Qt.Checked:ordered.append(item.text())
        listing.itemChanged.connect(changed)
        layout.addWidget(listing)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
        if dialog.exec() == QDialog.Accepted:
            targets = ordered
            if not targets: QMessageBox.information(self, 'Ngôn ngữ đích', 'Chọn ít nhất một ngôn ngữ.'); return
            self.extra_targets = targets[1:];self.target_lang.blockSignals(True);self.target_lang.setCurrentText(targets[0]);self.target_lang.blockSignals(False)
            self.sync_target_chips()
            self.store.set_setting('extra_targets', json.dumps(self.extra_targets, ensure_ascii=False))
            self.notice.setText('Đích lượt mới: '+', '.join(targets))

    def target_languages(self):
        if hasattr(self,'target_chips'):
            return [n for n in self._target_order if self.target_chips[n].isChecked() and self.target_chips[n].isEnabled()]
        return list(dict.fromkeys([self.target_lang.currentText()]+self.extra_targets))

    def choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Nhập nhiều tài liệu', self.store.setting('last_import_dir'), 'TXT/DOCX (*.txt *.docx)')
        if paths: self.import_paths(paths)

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, 'Nhập thư mục và thư mục con', self.store.setting('last_import_dir'))
        if path: self.import_paths([path])

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(u.isLocalFile() for u in event.mimeData().urls()): event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths: self.import_paths(paths); event.acceptProposedAction()

    def import_paths(self, paths):
        if self.import_busy: return
        self.import_busy = True
        source, target = self.source_lang.currentText(), self.target_lang.currentText()
        self.notice.setText('Đang nhập tài liệu; chưa gửi API…')
        existing_ids = list(self.workspace_ids)
        def run():
            try: result = import_many(self.store, paths, source, target, existing_ids=existing_ids)
            except Exception as exc: result = {'document_ids': [], 'supported_files': 0, 'errors': [{'error': type(exc).__name__}]}
            self.bridge.stage2.emit({'kind': 'import', 'result': result})
        worker = threading.Thread(target=run, daemon=True); self.background_threads.append(worker); worker.start()

    def stage2_result(self, payload):
        if self._closed: return
        kind, result = payload['kind'], payload['result']
        if kind == 'import':
            self.import_busy = False
            self.workspace_ids.extend(result['document_ids'])
            self.workspace_ids = list(dict.fromkeys(self.workspace_ids))
            if result['document_ids']: self.open_document(result['document_ids'][0])
            elif result.get('duplicate_ids'): self.open_document(result['duplicate_ids'][0])
            self.refresh_workspace_choices()
            self.notice.setText(f"Nhập {len(result['document_ids'])}/{result['supported_files']} file hợp lệ · {len(result['errors'])} file lỗi/không hỗ trợ · không gửi API")
            self.import_errors = result['errors']
            if result.get('duplicate_ids'):
                self.notice.setText('File đã có trong danh sách' + (' · Nguồn trên ổ đĩa đã thay đổi; giữ nguyên bản đang biên tập' if result.get('changed_source_ids') else ''))
                self.statusBar().showMessage(self.notice.text(), 8000)
            if hasattr(self, 'import_details'): self.import_details.setVisible(bool(self.import_errors))
        elif kind == 'models':
            self.metadata_busy = False; self.refresh_models_button.setEnabled(True)
            if 'error' in result:
                self.gemini_offline.setText('Offline · giữ cache cũ · '+result['error'])
            else:
                self.store.set_setting('gemini_models', json.dumps(result, ensure_ascii=False))
                if self.provider_id() == 'gemini': self.change_provider()
                self.gemini_offline.setText(f"Đã tải {len(result['models'])} model · {result['pages']} request metadata · chưa xác minh quyền generateContent của từng model"+(' · danh sách còn trang tiếp theo' if result.get('nextPageToken') else ''))
        elif kind == 'export':
            self.export_busy = False; self.export_many_button.setEnabled(True)
            success = [r for r in result if r['state'] == 'exported']
            if success:
                current = next((r for r in success if r['document_id'] == self.doc_id), success[-1])
                self.last_export = Path(current['path'])
            self.notice.setText(f"Đã xuất {len(success)}/{len(result)} workspace; {sum(r['state']=='error' for r in result)} lỗi, {sum(r['state']=='cancelled' for r in result)} bỏ qua")
            self.refresh()
            structural=[r for r in result if r['state']=='blocked_structure']
            if structural:
                QMessageBox.warning(self,'Không thể xuất: phát hiện lỗi cấu trúc dòng.',
                    '\n'.join(Path(self.store.document(r['document_id'])['path']).name+' · '+str(len(r['faults']))+' vấn đề' for r in structural))
                if any(r['document_id']==self.doc_id for r in structural):self.line_check.open_list()
            blocked=[r for r in result if r['state']=='blocked_language']
            if blocked:
                from ..language_validator import display_reason
                from PySide6.QtWidgets import QDialog, QVBoxLayout, QListWidget
                from .glass import GlassButton as QPushButton
                dialog=QDialog(self); dialog.setWindowTitle('Không thể xuất: sai ngôn ngữ đích')
                layout=QVBoxLayout(dialog); listing=QListWidget(); layout.addWidget(listing)
                for entry in blocked:
                    doc=self.store.document(entry['document_id'])
                    for fault in entry['faults']:
                        listing.addItem(f"{Path(doc['path']).name} · {doc['target_lang']} · Dòng {fault['ordinal']+1} · {display_reason(fault['reason'])}")
                        listing.item(listing.count()-1).setData(Qt.UserRole,(doc['id'],fault['id']))
                def navigate(item):
                    doc_id,line_id=item.data(Qt.UserRole); self.open_document(doc_id); self.navigate_to_line(line_id)
                listing.itemClicked.connect(navigate)
                retry=QPushButton('Xem dòng sai và xác nhận dịch lại'); layout.addWidget(retry)
                def review():
                    item=listing.currentItem() or listing.item(0)
                    navigate(item); dialog.accept(); self.show_warnings()
                retry.clicked.connect(review)
                self.notice.setText(f"Đã xuất {len(success)}; chặn {len(blocked)} tài liệu/ngôn ngữ sai")
                dialog.resize(850,420); dialog.exec()

    def refresh_workspace_choices(self):
        if hasattr(self, 'document_panel'): self.refresh_document_panel()

    def build_gemini_api(self):
        panel = QWidget(); layout = QVBoxLayout(panel)
        title = QLabel('GOOGLE GEMINI · API chính thức · nhiều key theo thứ tự ưu tiên'); title.setWordWrap(True); layout.addWidget(title)
        self.gemini_keys_list = QListWidget(); self.gemini_keys_list.setMaximumHeight(110); layout.addWidget(self.gemini_keys_list)
        form = QFormLayout()
        self.gemini_key_input = QLineEdit(); self.gemini_key_input.setEchoMode(QLineEdit.Password)
        self.gemini_key_input.setPlaceholderText('Dán một/nhiều key; khoảng trắng hoặc xuống dòng phân cách')
        self.gemini_project = QLineEdit(); self.gemini_project.setPlaceholderText('Project ID đã xác minh; để trống thì không tự đổi project/quota')
        form.addRow('Key đã che', self.gemini_key_input); form.addRow('Dự án/quota', self.gemini_project); layout.addLayout(form)
        controls = QHBoxLayout()
        for label, action in [('Thêm key', self.add_gemini_keys), ('Xóa key', lambda: self.edit_gemini_key(delete=True)), ('Ưu tiên ↑', lambda: self.edit_gemini_key(direction=-1)), ('Ưu tiên ↓', lambda: self.edit_gemini_key(direction=1))]:
            b = QPushButton(label); b.clicked.connect(action); controls.addWidget(b)
        layout.addLayout(controls)
        self.refresh_models_button = QPushButton('Làm mới model · tối đa 1 GET metadata…'); self.refresh_models_button.clicked.connect(self.refresh_gemini_models); layout.addWidget(self.refresh_models_button)
        self.gemini_offline = QLabel('Offline · danh sách cache; không tự kiểm tra key'); self.gemini_offline.setWordWrap(True); layout.addWidget(self.gemini_offline)
        limits = QHBoxLayout()
        self.gemini_limit_controls = {}
        for key, label, default, maximum in [('rpm', 'RPM', 1, 100000), ('tpm', 'TPM input', 3000, 100000000), ('rpd', 'RPD còn lại', 1, 1000000), ('concurrency', 'Đồng thời', 1, 30)]:
            box = QSpinBox(); box.setRange(1, maximum); box.setValue(int(self.store.setting('gemini_'+key, str(default))))
            box.valueChanged.connect(lambda v, k=key: self.store.set_setting('gemini_'+k, str(v)))
            limits.addWidget(QLabel(label)); limits.addWidget(box); self.gemini_limit_controls[key] = box
        layout.addLayout(limits)
        self.gemini_verified = QCheckBox('Tôi đã đối chiếu các giới hạn còn lại cho model/dự án này trong AI Studio')
        self.gemini_verified.setChecked(False); layout.addWidget(self.gemini_verified)
        self.model_name.currentIndexChanged.connect(lambda *_: self.gemini_verified.setChecked(False))
        for key, control in self.gemini_limit_controls.items():
            control.valueChanged.connect(lambda *_: self.gemini_verified.setChecked(False))
        self.gemini_limit_controls['concurrency'].valueChanged.connect(self.update_gemini_concurrency)
        note = QLabel('Không tăng tốc qua nhiều key. HTTP 429 tạm thời/auth/quyền: tạm dừng. Chỉ đổi sang dự án quota độc lập đã khai báo khi có bằng chứng daily quota; batch bị từ chối không tự gửi lại.')
        note.setWordWrap(True); layout.addWidget(note)
        self.pages.widget(2).layout().insertWidget(2, panel)
        self.refresh_gemini_keys()

    def update_gemini_concurrency(self, value):
        if self.provider_id() == 'gemini': self.concurrency.setMaximum(value)

    def refresh_gemini_keys(self):
        blocker = QSignalBlocker(self.gemini_keys_list)
        selected = self.gemini_keys_list.currentItem()
        selected_id = selected.data(Qt.UserRole) if selected else None
        self.gemini_keys_list.clear()
        for i, key in enumerate(self.store.gemini_keys()):
            self.gemini_keys_list.addItem(f"{i+1}. Key …{key['id'][-6:]} · {key['status']} · project {key['project'] or 'chưa xác minh'}")
            self.gemini_keys_list.item(i).setData(Qt.UserRole, key['id'])
            if key['id'] == selected_id: self.gemini_keys_list.setCurrentRow(i)

    def add_gemini_keys(self):
        if getattr(self, '_editing_gemini_keys', False): return
        self._editing_gemini_keys = True
        try:
            added, duplicates = self.store.add_gemini_keys(self.gemini_key_input.text(), self.gemini_project.text())
            self.gemini_verified.setChecked(False)
            self.gemini_key_input.clear(); self.refresh_gemini_keys()
            self.gemini_offline.setText(f'Đã mã hóa {added} key · bỏ qua {duplicates} key trùng · chưa gọi API')
        except Exception as exc: QMessageBox.warning(self, 'Không lưu được key', type(exc).__name__)
        finally: self._editing_gemini_keys = False

    def edit_gemini_key(self, **options):
        if getattr(self, '_editing_gemini_keys', False): return
        item = self.gemini_keys_list.currentItem()
        if not item: return
        key_id = item.data(Qt.UserRole)
        del item  # Never retain a QListWidgetItem across the modal event loop.
        if not key_id: return
        self._editing_gemini_keys = True
        try:
            if options.get('delete') and QMessageBox.question(self, 'Xóa Gemini key', 'Xóa key đã chọn khỏi TransComic?', QMessageBox.Yes|QMessageBox.No, QMessageBox.No) != QMessageBox.Yes: return
            if self._closed: return
            self.store.change_gemini_key(key_id, **options)
            self.gemini_verified.setChecked(False)
        except ValueError as exc: QMessageBox.information(self, 'Không thay đổi được key', str(exc))
        finally:
            if not self._closed: self.refresh_gemini_keys()
            self._editing_gemini_keys = False

    def refresh_gemini_models(self):
        if self.metadata_busy: return
        try: keys = self.store.gemini_keys(decrypt=True)
        except Exception as exc:
            QMessageBox.warning(self, 'Gemini key', type(exc).__name__); return
        if not keys: QMessageBox.information(self, 'Cần Gemini key', 'Thêm key trước; thêm key không gọi API.'); return
        if QMessageBox.question(self, 'Quyền tải model', 'Gửi tối đa 1 GET models.list bằng key ưu tiên? Đây là request metadata riêng, không phải request dịch; không retry/đổi key.', QMessageBox.Yes|QMessageBox.No, QMessageBox.No) != QMessageBox.Yes: return
        self.metadata_busy = True; self.refresh_models_button.setEnabled(False)
        for key in keys: self.store.log.register_secret(key['secret'])
        def run():
            try:
                provider = GeminiProvider(keys, 'metadata-only')
                result = asyncio.run(provider.list_models(observer=lambda event, **data: self.store.log.emit(event, provider='gemini', **data)))
            except Exception as exc:
                result = {'error': type(exc).__name__}
                self.store.log.emit('failure', provider='gemini', request_kind='model_list', exception=type(exc).__name__, state='offline')
            self.bridge.stage2.emit({'kind': 'models', 'result': result})
        worker = threading.Thread(target=run, daemon=True); self.background_threads.append(worker); worker.start()

    def make_provider(self, job, kira_key=None):
        if job['provider'] == 'kira':
            from ..kira_recovery import adopt_authorized_recovery
            adopt_authorized_recovery(self.store,job)
            if self.store.kira_keys():
                from ..kira_pool import KiraPoolProvider
                return KiraPoolProvider(self.store,job['model'],timeout=job['timeout'],prompt_version=job['prompt_version'])
            return KiraProvider(kira_key or self._key(), job['model'], timeout=job['timeout'], prompt_version=job['prompt_version'])
        config = json.loads(job['config'])
        all_keys = {k['id']: k for k in self.store.gemini_keys(decrypt=True)}
        keys = [dict(all_keys[k], project=config.get('key_projects', {}).get(k, '')) for k in config.get('key_ids', []) if k in all_keys]
        if len(keys) != len(config.get('key_ids', [])): raise ValueError('Key snapshot no longer available')
        def status(key_id, state):
            self.store.gemini_key_status(key_id, state)
            self.store.log.emit('key_state', provider='gemini', model=job['model'], key_alias=key_id, state=state)
        # Conservatively share this budget across every key/project for the model.
        # Rotation cannot reset the locally reserved quota or a restarted run.
        scope = 'all-projects:'+job['model']
        limiter = QuotaLimiter(config['rpm'], config['tpm'], config['rpd'],
            reservation=lambda cost, rpm, tpm, rpd: self.store.reserve_gemini_quota(scope, cost, rpm, tpm, rpd))
        return GeminiProvider(keys, job['model'], limiter=limiter, on_status=status, timeout=job['timeout'], prompt_version=job['prompt_version'])

    def start_stage2(self):
        if self.import_busy: QMessageBox.information(self, 'Đang nhập', 'Chờ nhập tài liệu xong trước khi bắt đầu.'); return
        targets = self.target_languages()
        from ..languages import validate_pair
        if self.source_lang.currentText() in targets:
            QMessageBox.information(self, 'Ngôn ngữ đích', 'Mỗi đích phải khác nguồn.'); return
        model = self.selected_model_id()
        if not model: QMessageBox.information(self, 'Chọn model', 'Gemini cần danh sách model cache từ thao tác Làm mới được phép.'); return
        provider, config, key = self.provider_id(), {}, None
        if provider == 'kira':
            key = self._key()
            if not key: return
            config={'kira_multi_key':True,'retry_504':False}
        else:
            if not self.gemini_verified.isChecked(): QMessageBox.information(self, 'Giới hạn Gemini', 'Đối chiếu và xác nhận quota/model trong Quản lý API trước khi chạy.'); return
            keys = self.store.gemini_keys()
            if not keys: QMessageBox.information(self, 'Cần Gemini key', 'Thêm key trong Quản lý API.'); return
            config = {k: control.value() for k, control in self.gemini_limit_controls.items()}
            if self.concurrency.value() > config['concurrency']:
                QMessageBox.information(self, 'Gemini quota', 'Concurrency exceeds the verified limit.'); return
            config['key_ids'] = [k['id'] for k in keys]; config['key_projects'] = {k['id']: k['project'] for k in keys}
        try:
            run_id, jobs = self.store.create_run(self.workspace_ids or [self.doc_id], targets, provider=provider, model=model,
                source_lang=self.source_lang.currentText(), concurrency=self.concurrency.value(), timeout=self.timeout_spin.value(), config=config)
            first = self.store.job(jobs[0]); adapter = self.make_provider(first, key)
            self.scheduler = Scheduler(self.store, adapter, self.bridge.changed.emit)
            self.scheduler.job_ids, self.scheduler.run_id = jobs, run_id
            self.current_job_ids = {r['id'] for j in jobs for b in self.store.batches(j) for r in b['payload']}
            self.workspace_ids = list(dict.fromkeys(self.workspace_ids+[self.store.job(j)['document_id'] for j in jobs]))
            self.refresh_workspace_choices(); self.scheduler.start(jobs[0]); self.refresh()
        except Exception as exc: QMessageBox.information(self, 'Không bắt đầu được lượt dịch', str(exc) if isinstance(exc, ValueError) else type(exc).__name__)

    def build_live_queue(self):
        panel = QWidget(); layout = QVBoxLayout(panel); layout.setContentsMargins(0, 0, 0, 0)
        self.run_summary = QLabel('Chưa có lượt dịch trong phiên này'); self.run_summary.setWordWrap(True); layout.addWidget(self.run_summary)
        row = QHBoxLayout()
        for label, action in [('Tạm dừng / Tiếp tục toàn lượt', self.pause_or_resume), ('Dừng toàn lượt', self.stop_translation), ('Xuất hàng loạt…', self.export_many)]:
            b = QPushButton(label); b.clicked.connect(action); row.addWidget(b)
        layout.addLayout(row)
        self.run_table = QTableWidget(0, 8)
        self.run_table.setHorizontalHeaderLabels(['File', 'Đích', 'Model', 'Thành công', 'Lỗi/?', 'Chưa dịch', 'Tiến độ', 'Trạng thái'])
        self.run_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.run_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.run_table.setEditTriggers(QTableWidget.NoEditTriggers); self.run_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.run_table.setMinimumHeight(120); self.run_table.setMaximumHeight(250)
        self.run_table.cellDoubleClicked.connect(self.open_queue_workspace); layout.addWidget(self.run_table)
        self.queue_page = QWidget(); queue_layout = QVBoxLayout(self.queue_page)
        queue_layout.addWidget(QLabel("HÀNG ĐỢI · Lượt dịch hiện tại")); queue_layout.addWidget(panel, 1)
        self.run_table.setMaximumHeight(16777215)
        self.pages.addWidget(self.queue_page)

    def open_queue_workspace(self, row, column=0):
        item = self.run_table.item(row, 0)
        if item: self.open_document(item.data(Qt.UserRole)); self.pages.setCurrentIndex(0)

    def refresh_stage2(self):
        if self._closed: return
        self.background_threads = [t for t in self.background_threads if t.is_alive()]
        if self.pages.currentIndex() == 2: self.refresh_gemini_keys()
        self.refresh_kira_keys()
        if self.scheduler:
            jobs = [self.store.job(j) for j in self.scheduler.job_ids or [self.scheduler.job_id] if j]
            docs = list(dict.fromkeys(j['document_id'] for j in jobs if j))
            if getattr(self.scheduler,'current_locale',None):
                self.run_summary.setToolTip('Dịch tuần tự · Đang xử lý '+self.scheduler.current_locale)
        else:
            jobs = []; docs = self.workspace_ids
        self.refresh_workspace_choices()
        if self.pages.currentIndex() == 5:
            self.run_table.setRowCount(len(docs)); totals = {'total': 0, 'done': 0, 'errors': 0, 'unknown': 0, 'missing': 0}
            for i, doc_id in enumerate(docs):
                doc = self.store.document(doc_id); job = next((j for j in jobs if j['document_id'] == doc_id), {})
                s = workspace_status(self.store.lines(doc_id), job.get('state'))
                for key in totals: totals[key] += s[key]
                values = [Path(doc['path']).name, doc['target_lang'], job.get('model', '—'), str(s['done']), str(s['errors']+s['unknown']), str(s['missing']), str(s['progress'])+'%', s['state']]
                for col, value in enumerate(values): self.run_table.setItem(i, col, QTableWidgetItem(value))
                self.run_table.item(i, 0).setData(Qt.UserRole, doc_id)
            files = len({self.store.document(d)['source_instance'] for d in docs})
            active = self.scheduler.active if self.scheduler else 0
            elapsed = time.monotonic()-(self.scheduler.started_at or time.monotonic()) if self.scheduler else 0
            speed = f"{totals['done']*60/elapsed:.1f} dòng/phút" if elapsed >= 5 else 'đang đo tốc độ'
            self.run_summary.setText(f"{files} file · {len(docs)} file/ngôn ngữ · {totals['done']}/{totals['total']} thành công · {totals['errors']} lỗi · {totals['unknown']} không rõ · {totals['missing']} chưa dịch · {active} request · {elapsed:.0f}s · {speed}")
        if self.scheduler and len(jobs)>1:
            ids = {r['id'] for j in jobs for b in self.store.batches(j['id']) for r in b['payload']}
            rows = [r for d in docs for r in self.store.lines(d) if r['id'] in ids]
            self.total_progress.setValue(int(sum(r['state']=='done' for r in rows)*100/len(rows)) if rows else 0)

    def export_many(self):
        self.export_documents(list(self.workspace_ids))

    def export_documents(self, ids):
        from .exporting import choose_export_plan
        if self.export_busy or not ids: return
        chosen = choose_export_plan(self, ids)
        if chosen is None: return
        plan, policy = chosen
        self.export_busy = True; self.export_many_button.setEnabled(False)
        def run():
            result = write_exports(self.store, plan, existing=policy, allow_incomplete=True)
            self.bridge.stage2.emit({'kind': 'export', 'result': result})
        worker = threading.Thread(target=run, daemon=True)
        self.background_threads.append(worker); worker.start()
