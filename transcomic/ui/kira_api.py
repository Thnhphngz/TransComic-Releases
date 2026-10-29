"""Small Kira management surface. Refresh never edits or decrypts credentials."""
import json
import time
from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtWidgets import (QLineEdit, QListWidget, QHBoxLayout, QLabel,
    QInputDialog, QMessageBox, QFormLayout, QCheckBox)
from .controls import QSpinBox
from .glass import GlassButton


class KiraApiMixin:
    def build_kira_controls(self, layout):
        self.kira_name_input=QLineEdit();self.kira_name_input.setPlaceholderText('Tên hiển thị (tùy chọn)')
        layout.addWidget(self.kira_name_input)
        self.kira_keys_list=QListWidget();self.kira_keys_list.setMaximumHeight(155)
        self.kira_keys_list.itemChanged.connect(self.toggle_kira_item)
        layout.addWidget(self.kira_keys_list)
        row=QHBoxLayout()
        for title,fn in [('Đổi tên',self.rename_kira_key),('Nhóm tài khoản',self.group_kira_account),('Xóa key',self.delete_kira_key)]:
            b=GlassButton(title);b.clicked.connect(fn);row.addWidget(b)
        layout.addLayout(row)
        note=QLabel('Luồng 1–30 cho MỖI key. Chỉ ghép nhóm khi đã xác nhận cùng tài khoản. Lỗi dịch vụ chỉ tạm chờ và tự phục hồi khi hết cooldown; không cần khôi phục key bằng tay. Auth/quota có bằng chứng được chặn riêng.')
        note.setWordWrap(True);layout.addWidget(note)
        form=QFormLayout();self.kira_limits={}
        for key,title,default,maximum in [('kira_account_limit','Trần đồng thời tài khoản',30,100000),('kira_rpm','RPM tài khoản (trần cục bộ)',60,1000000),('kira_tpm','TPM tài khoản (trần cục bộ)',1000000,1000000000)]:
            box=QSpinBox();box.setRange(1,maximum);box.setValue(int(self.store.setting(key,str(default))))
            box.valueChanged.connect(lambda value,k=key:self.store.set_setting(k,str(value)))
            form.addRow(title,box);self.kira_limits[key]=box
        layout.addLayout(form)
        recovery=QFormLayout();self.kira_recovery_controls={}
        for key,title,default,maximum in [('kira_retry_limit','Kira: số lần thử/batch (policy hữu hạn)',4,20),
            ('kira_retry_budget','Kira: tổng retry (policy hữu hạn)',30,10000),
            ('kira_request_limit','Kira: trần request/lượt (0 = không đặt trần)',0,1000000),
            ('kira_token_limit','Kira: trần token/lượt (0 = không đặt trần)',0,1000000000),
            ('kira_recovery_seconds','Kira: giây phục hồi (policy hữu hạn)',600,86400),
            ('rate_wait_budget','Kira: giây chờ (policy hữu hạn)',300,3600),
            ('kira_retry_concurrency','Kira: tối đa request retry đồng thời',4,30),
            ('kira_retry_backoff','Kira: cooldown cơ sở (giây)',1,30)]:
            box=QSpinBox();box.setRange(0,maximum);box.setValue(int(self.store.setting(key,str(default))))
            if key in ('kira_recovery_seconds','kira_retry_concurrency'):box.setMinimum(1)
            box.valueChanged.connect(lambda value,k=key:self.store.set_setting(k,str(value)))
            recovery.addRow(title,box);self.kira_recovery_controls[key]=box
        layout.addLayout(recovery)
        self.kira_unknown_consent=QCheckBox('Policy hữu hạn cũ: cho phép gửi lại timeout/504/unknown trong ngân sách đã đặt')
        self.kira_unknown_consent.setChecked(self.store.setting('kira_allow_unknown_resend','0')=='1')
        self.kira_unknown_consent.setToolTip('Tùy chọn của policy hữu hạn. Lệnh mới dùng chính sách dịch đến khi đủ và được phép gửi lại theo yêu cầu; có thể phát sinh thêm phí. Không sửa quyền trong snapshot job cũ.')
        self.kira_unknown_consent.toggled.connect(lambda value:self.store.set_setting('kira_allow_unknown_resend','1' if value else '0'))
        layout.addWidget(self.kira_unknown_consent)
        cost_button=GlassButton('Trần chi phí phục hồi…');cost_button.clicked.connect(self.edit_kira_recovery_cost);layout.addWidget(cost_button)
        policy=QLabel('Lệnh Kira mới tự phục hồi đến khi dịch đủ, kể cả 504/timeout/unknown; việc gửi lại có thể phát sinh thêm phí. Không áp dụng các trần retry/request/token/chi phí cục bộ của policy hữu hạn. Giữ quota dịch vụ, giới hạn đồng thời và Pause/Stop. Hết số dư/quota thực, key sai hoặc đầu vào không hợp lệ cần xử lý đúng nguyên nhân. Job cũ giữ snapshot đã lưu.')
        policy.setWordWrap(True);layout.addWidget(policy)
        self.kira_metrics=QLabel();self.kira_metrics.setWordWrap(True);layout.addWidget(self.kira_metrics)
        self.refresh_kira_keys()

    def edit_kira_recovery_cost(self):
        raw=self.store.setting('kira_recovery_cost_policy','{"kira_additional_cost_limit": null, "kira_token_cost_upper_bound": null, "kira_cost_source": ""}')
        text,ok=QInputDialog.getMultiLineText(self,'Trần chi phí phục hồi USD','Trần request/token áp dụng khi được đặt lớn hơn 0. Tùy chọn: trần chi phí request thêm, giá trần USD/token và nguồn giá đã xác minh. Thiếu giá/nguồn sẽ chặn retry khi đặt trần tiền; không coi đây là hóa đơn.',raw)
        if not ok:return
        try:
            value=json.loads(text)
            if not isinstance(value,dict) or set(value)-{'kira_additional_cost_limit','kira_token_cost_upper_bound','kira_cost_source'}:raise ValueError('Trường cấu hình không hợp lệ')
            from ..kira_recovery import frozen_policy
            frozen_policy(self.store,{'kira_multi_key':True,'kira_recovery_version':4,**value})
            self.store.set_setting('kira_recovery_cost_policy',json.dumps(value))
        except (ValueError,TypeError):QMessageBox.warning(self,'Trần chi phí','Giá/trần phải hữu hạn và không âm; source phải là nguồn giá được kiểm tra. Không lưu API key trong trường này.')

    def refresh_kira_keys(self):
        if not hasattr(self,'kira_keys_list'):return
        rows=self.store.kira_keys()
        scopes={k['id']:self.store.kira_effective_scope(k['id']) for k in rows}
        pool=getattr(getattr(self,'scheduler',None),'provider',None)
        per_key=max(1,min(30,int(self.store.setting('concurrency','30'))))
        metrics=pool.snapshot(per_key) if getattr(pool,'multi_key',False) else {}
        if metrics:
            # Show the selected run's key/model state, not an old model's
            # persisted global status. This is a detached display copy only.
            for row in rows:
                current=metrics['per_key'].get(row['id'])
                if current and row['enabled']:row.update(status=current['status'],service_state=current['service_state'])
        signature=repr((rows,scopes))
        available=sum(k['enabled'] and (k['status']=='READY' or k['status']=='COOLDOWN' and 0<k['cooldown_until']<=time.time()) for k in rows)
        if metrics:available=metrics['keys']
        self.kira_metrics.setText(f"{sum(bool(k['enabled']) for k in rows)} key bật · {available} khả dụng · Luồng/key {per_key} · lý thuyết {available*per_key} · trần mỗi tài khoản {self.store.setting('kira_account_limit','30')}")
        if metrics:
            reasons={'ready':'sẵn sàng','no_pending_work':'hết batch chưa gửi','key_slots_full':'đủ slot/key',
                'account_slots_full':'đủ slot tài khoản','account_rpm':'chờ RPM tài khoản',
                'account_tpm':'chờ TPM tài khoản','account_cooldown':'tài khoản cooldown',
                'key_cooldown':'key cooldown','network_paused':'tạm dừng do mạng','disabled':'đã tắt',
                'credential_unavailable':'không đọc được key','removed':'đã xóa',
                'invalid':'key không hợp lệ','quota_exhausted':'quota model · chờ reset/xác minh','unknown_error':'cần kiểm tra lỗi',
                'permission_denied':'không có quyền model','model_unavailable':'model không khả dụng',
                'account_quota_exhausted':'nhóm đã xác nhận · quota model'}
            details='\n'.join(f"{v['name']} (…{k[-6:]}): {v['busy']} slot bận · gửi {v['requests']} · thành công {v['successful_requests']} · {v['batches']} batch/{v['translated_lines']} dòng đã lưu · lỗi {v['errors']} · {reasons.get(v['wait_reason'],v['wait_reason'])}" for k,v in metrics['per_key'].items())
            self.kira_metrics.setText(self.kira_metrics.text()+f" · {metrics['accounts']} nhóm · tổng trần {metrics['maximum']}")
            self.kira_metrics.setText(self.kira_metrics.text()+'\n'+details)
            self.kira_metrics.setToolTip('Thống kê lượt dịch hiện tại; thành công là phản hồi hợp lệ, batch/dòng là kết quả đã lưu. Không suy ra chi phí từ số request.\n'+json.dumps(metrics,ensure_ascii=False,indent=2))
        else:
            self.kira_metrics.setToolTip('Chưa có thống kê lượt dịch hiện tại. Số key bật không chứng minh request đã được gửi.')
        if getattr(self,'_kira_list_signature',None)!=signature:
            current=self.kira_keys_list.currentItem();key_id=current.data(Qt.UserRole) if current else None
            blocker=QSignalBlocker(self.kira_keys_list);self.kira_keys_list.clear()
            for k in rows:
                labels={'READY':'Sẵn sàng cục bộ','COOLDOWN':'Giới hạn tốc độ · tự chờ','TEMPORARY_ERROR':'Lỗi tạm thời · tự phục hồi',
                    'INVALID':'Xác thực không hợp lệ','PERMISSION_DENIED':'Không có quyền dùng model','MODEL_UNAVAILABLE':'Model/request không khả dụng',
                    'QUOTA_EXHAUSTED':'Quota model · chờ reset/xác minh','CREDENTIAL_ERROR':'Không giải mã được key','UNKNOWN_ERROR':'Cần chẩn đoán','DISABLED':'Đã tắt'}
                text='Đang thử kết nối lại' if k.get('service_state')=='PROBING' else labels.get(k['status'],k['status'])
                self.kira_keys_list.addItem(f"{k['name']} · •••••••• · {text}")
                item=self.kira_keys_list.item(self.kira_keys_list.count()-1)
                item.setData(Qt.UserRole,k['id']);item.setCheckState(Qt.Checked if k['enabled'] else Qt.Unchecked)
                scope=scopes[k['id']]
                group='Chung / chưa xác định' if scope=='shared' else '…'+scope[-6:]
                item.setToolTip('ID '+k['id']+'\n'+k['status']+' · nhóm tài khoản: '+group+'\nĐổi nhóm áp dụng lượt mới; quota không tự khôi phục nếu chưa rõ reset')
                if key_id==k['id']:self.kira_keys_list.setCurrentItem(item)
            del blocker;self._kira_list_signature=signature
        if hasattr(self,'kira_manage_button'):
            self.kira_manage_button.setText(f'Kira: {sum(bool(k["enabled"]) for k in rows)} key')
            self.kira_manage_button.setToolTip('Mở Kira Live Monitor: theo dõi từng key đang dịch file nào, request, dòng đã lưu và lý do chờ. Không gọi API hoặc tốn token khi mở.')
        self.refresh_api_headers()

    def group_kira_account(self):
        key_id=self.selected_kira_key()
        if not key_id:return
        rows=self.store.kira_keys()
        scopes=list(dict.fromkeys(['shared']+[k['id'] for k in rows]+
            [self.store.kira_account_scope(k['id']) for k in rows]))
        names={k['id']:k['name'] for k in rows}
        labels=['Chung / chưa xác định' if scope=='shared' else
            f"Tài khoản của {names.get(scope,'key đã xóa')} (…{scope[-6:]})" for scope in scopes]
        current=scopes.index(self.store.kira_account_scope(key_id))
        label,ok=QInputDialog.getItem(self,'Nhóm tài khoản Kira',
            'Chỉ chọn cùng nhóm khi bạn xác nhận các key cùng tài khoản. Chưa xác định: xử lý riêng từng key. Áp dụng lượt mới.',
            labels,current,False)
        if ok:self.store.set_kira_account_scope(key_id,scopes[labels.index(label)])
        self.refresh_kira_keys()

    def selected_kira_key(self):
        item=self.kira_keys_list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def toggle_kira_item(self,item):
        self.store.change_kira_key(item.data(Qt.UserRole),enabled=item.checkState()==Qt.Checked)
        self.refresh_kira_keys()

    def rename_kira_key(self):
        key_id=self.selected_kira_key()
        if not key_id:return
        name,ok=QInputDialog.getText(self,'Tên key','Tên hiển thị')
        if ok:
            try:self.store.change_kira_key(key_id,name=name)
            except Exception as exc:QMessageBox.warning(self,'Không đổi được tên',type(exc).__name__)
        self.refresh_kira_keys()

    def delete_kira_key(self):
        key_id=self.selected_kira_key()
        try:
            if not key_id:return
            self.credential_idle('kira')
            row=self.store.db.execute('SELECT encrypted FROM kira_keys WHERE id=?',(key_id,)).fetchone()
            if not row:return
            old=[bytes(row[0])]
            if QMessageBox.question(self,'Xóa Kira key','Xóa Kira key đã chọn (ID …'+key_id[-6:]+') khỏi kho bảo mật? Không xóa bản dịch.',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:return
            if self._closed:return
            self.credential_idle('kira');self.store.change_kira_key(key_id,delete=True)
            self.clear_credential_caches('kira',key_id,old)
        except ValueError as exc:QMessageBox.information(self,'Không xóa được key',str(exc))
        self.refresh_kira_keys()
