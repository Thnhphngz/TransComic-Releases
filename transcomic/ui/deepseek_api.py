"""Compact DeepSeek settings in the existing API page; no paid health checks."""
import json
from decimal import Decimal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QDialog, QPlainTextEdit, QDialogButtonBox
from .glass import GlassButton
from .controls import QComboBox, QSpinBox
from .. import deepseek
from ..deepseek_pricing import load, label, load_catalog, validate_catalog
from ..deepseek_models import MODELS, MODEL, MODEL_NAMES
from .api_accordion import ApiAccordionMixin


class DeepSeekApiMixin(ApiAccordionMixin):
    def build_deepseek_api(self):
        panel = QWidget(); layout = QVBoxLayout(panel); layout.setSpacing(6)
        self.deepseek_api_panel = panel
        row = QHBoxLayout()
        self.deepseek_key_input = QLineEdit(); self.deepseek_key_input.setEchoMode(QLineEdit.Password)
        self.deepseek_key_input.setPlaceholderText('API key DeepSeek · lưu riêng bằng Windows DPAPI')
        row.addWidget(self.deepseek_key_input, 1)
        self.deepseek_save_button = GlassButton('Lưu key'); self.deepseek_save_button.clicked.connect(self.save_deepseek_key); row.addWidget(self.deepseek_save_button)
        self.deepseek_delete_button = GlassButton('Xóa key'); self.deepseek_delete_button.clicked.connect(self.delete_deepseek_key); row.addWidget(self.deepseek_delete_button)
        layout.addLayout(row)
        self.deepseek_status = QLabel(); self.deepseek_status.setWordWrap(True); layout.addWidget(self.deepseek_status)
        self.deepseek_price = QLabel(); self.deepseek_price.setWordWrap(True); layout.addWidget(self.deepseek_price)
        row = QHBoxLayout(); row.addWidget(QLabel('Output cơ sở / batch 3 dòng'))
        tokens = QSpinBox(); tokens.setRange(128, 8192); tokens.setValue(int(self.store.setting('deepseek_max_tokens', '2048')))
        tokens.valueChanged.connect(lambda v:self.store.set_setting('deepseek_max_tokens', str(v)))
        tokens.setToolTip('Batch 3 giữ giới hạn này. Batch lớn tự nâng theo độ dài nguồn và ID, tối đa 8192 output token/request; lượt mới tự phục hồi phần dịch chưa hoàn tất.')
        row.addWidget(tokens)
        prices = GlassButton('Giá / chi tiết…'); prices.clicked.connect(self.edit_deepseek_prices); row.addWidget(prices)
        layout.addLayout(row)
        row=QHBoxLayout();row.addWidget(QLabel('Prompt cho job mới'))
        from ..translation_policy import VERSION, CANDIDATE_VERSION, V4_VERSION
        self.deepseek_prompt=QComboBox()
        for title,version in (('V2 · mặc định',VERSION),('V3 · tùy chọn',CANDIDATE_VERSION),('V4 · tùy chọn',V4_VERSION)):
            self.deepseek_prompt.addItem(title,version)
        selected=deepseek.selected_prompt(self.store)
        self.deepseek_prompt.setCurrentIndex(self.deepseek_prompt.findData(selected))
        self.deepseek_prompt.setToolTip('Chỉ áp dụng cho job DeepSeek mới. Job/checkpoint đã tạo giữ prompt, context và facts đã chốt; không tự dịch lại. V2 vẫn là mặc định khi chưa chọn.')
        self.deepseek_prompt.currentIndexChanged.connect(lambda _:self.store.set_setting('deepseek_prompt_version',self.deepseek_prompt.currentData()))
        row.addWidget(self.deepseek_prompt,1);layout.addLayout(row)
        note = QLabel('Không tự gọi API kiểm tra key (có thể tốn token). Lưu key chỉ xác minh khả năng đọc DPAPI. '
                      'Lượt mới tự thử lại lỗi tạm thời/timeout đến khi dịch đủ; gửi lại có thể phát sinh thêm phí. Pause/Stop luôn có hiệu lực. Có thể dịch ở mọi khung giờ.')
        note.setWordWrap(True); layout.addWidget(note)
        self.pages.widget(2).layout().insertWidget(2, panel)
        self.deepseek_translation_price = QLabel(); self.deepseek_translation_price.setWordWrap(True)
        self.deepseek_translation_price.setVisible(False)
        self.controls_widget.parentWidget().layout().addWidget(self.deepseek_translation_price, 3, 0, 1, 2)
        self.refresh_deepseek_display()

    def save_deepseek_key(self):
        try:
            self.credential_idle('deepseek')
            from ..api_credentials import saved_state
            old = saved_state(self.store,'deepseek')
            if old and QMessageBox.question(self,'Thay DeepSeek key','Thay thế DeepSeek key đã lưu bằng key mới? Không thay đổi job hoặc bản dịch.',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:return
            if self._closed:return
            self.credential_idle('deepseek')
            deepseek.save_key(self.store, self.deepseek_key_input.text())
            self.clear_credential_caches('deepseek',old_blobs=old)
            self.deepseek_key_input.clear(); self.refresh_deepseek_display();self.refresh_api_headers()
        except ValueError as exc:
            QMessageBox.information(self,'DeepSeek',str(exc))
        except Exception:
            QMessageBox.warning(self, 'DeepSeek', 'Không lưu được key; kiểm tra dữ liệu và Windows DPAPI.')

    def delete_deepseek_key(self):
        from ..api_credentials import saved_state
        try:
            self.credential_idle('deepseek');old=saved_state(self.store,'deepseek')
            if not old:return
            if QMessageBox.question(self,'Xóa DeepSeek key','Xóa DeepSeek key đã lưu khỏi kho DPAPI? Không xóa key Kira/Gemini, job hoặc bản dịch.',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:return
            if self._closed:return
            self.credential_idle('deepseek');deepseek.delete_key(self.store)
            self.clear_credential_caches('deepseek',old_blobs=old)
            self.refresh_deepseek_display();self.refresh_api_headers()
        except ValueError as exc:QMessageBox.information(self,'Không xóa được key',str(exc))
        except Exception:QMessageBox.warning(self,'DeepSeek','Không xóa được key khỏi kho bảo mật.')

    def refresh_deepseek_display(self):
        if not hasattr(self, 'deepseek_status'): return
        try:
            catalog = load_catalog(self.store)
            self.deepseek_price.setText('\n'.join(label(catalog['models'][model],model=model) for model,name in MODELS))
            model = self.selected_model_id() if self.provider_id()=='deepseek' else MODEL
            if model not in MODEL_NAMES:model=MODEL
            config = catalog['models'][model];text = label(config,model=model)
            tooltip = '\n'.join(f"{name}: {catalog['models'][mid]['source']} · xác minh {catalog['models'][mid]['verified']}" for mid,name in MODELS)
            tooltip += '\nUSD = (input không cache × giá input + cache hit × giá cache + output × giá output) / 1.000.000.\nThiếu usage: chưa xác định phí; thiếu chi tiết cache: ước tính không cache.'
        except (ValueError, TypeError, KeyError):
            config = None; text = 'Giá DeepSeek không hợp lệ; mở Giá / chi tiết để sửa'; tooltip = text
        if not config:self.deepseek_price.setText(text)
        self.deepseek_price.setToolTip(tooltip)
        self.deepseek_translation_price.setVisible(self.provider_id() == 'deepseek')
        cost = ''
        scheduler = getattr(self, 'scheduler', None)
        if config and scheduler and getattr(scheduler, 'provider', None).__class__ is deepseek.DeepSeekProvider:
            # Aggregate usage is maintained by Scheduler, without scanning the document on repaint.
            from ..deepseek_pricing import estimate
            frozen = scheduler.provider.pricing
            rates = {k:max(Decimal(str(frozen[p][k])) for p in ('peak','offpeak')) for k in ('input','cached','output')}
            total = estimate(scheduler.usage, rates)
            run_name=MODEL_NAMES[scheduler.provider.model]+' · batch '+str(scheduler.provider.batch_size)
            cost = (' · Lượt '+run_name+' — Ước tính bảo thủ: $'+total['usd']) if total and scheduler.usage_received_count == scheduler.request_count else ' · Lượt '+run_name+' — chi phí chưa xác định đầy đủ'
        self.deepseek_translation_price.setText(text+cost); self.deepseek_translation_price.setToolTip(tooltip)

    def edit_deepseek_prices(self):
        dialog = QDialog(self); dialog.setWindowTitle('DeepSeek · giá tham khảo USD / 1 triệu token')
        layout = QVBoxLayout(dialog)
        note = QLabel('Sửa giá riêng từng model, nguồn và ngày xác minh. Chọn model ở tab Dịch/Automation. holiday_years chỉ gồm năm có lịch Trung Quốc đã xác minh đầy đủ; holidays là YYYY-MM-DD. Không dùng lịch giá để trì hoãn dịch.')
        note.setWordWrap(True); layout.addWidget(note)
        editor = QPlainTextEdit(); layout.addWidget(editor)
        try: config = load_catalog(self.store)
        except (ValueError, TypeError, KeyError):
            config = load_catalog()
        editor.setPlainText(json.dumps(config, ensure_ascii=False, indent=2))
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel); layout.addWidget(buttons)
        buttons.rejected.connect(dialog.reject)
        def save():
            try: config = validate_catalog(json.loads(editor.toPlainText()))
            except (ValueError, TypeError):
                QMessageBox.warning(dialog, 'Cấu hình giá', 'JSON, giá hoặc ngày không hợp lệ'); return
            self.store.set_setting('deepseek_pricing', json.dumps(config)); self.refresh_deepseek_display(); dialog.accept()
        buttons.accepted.connect(save); dialog.resize(620, 470); dialog.exec()
