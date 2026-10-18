"""Small Kira management surface. Refresh never edits or decrypts credentials."""
import json
import time
from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtWidgets import (QLineEdit, QListWidget, QHBoxLayout, QLabel,
    QInputDialog, QMessageBox, QFormLayout)
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
        for title,fn in [('Đổi tên',self.rename_kira_key),('Nhóm tài khoản',self.group_kira_account),('Xóa key',self.delete_kira_key),('Khôi phục offline',self.restore_kira_key)]:
            b=GlassButton(title);b.clicked.connect(fn);row.addWidget(b)
        layout.addLayout(row)
        note=QLabel('Luồng 1–30 cho MỖI key. Chỉ ghép nhóm khi đã xác nhận cùng tài khoản; chưa xác định sẽ xử lý riêng từng key. Các trần bên dưới áp dụng cho mỗi nhóm đã xác nhận hoặc từng key riêng. Đổi nhóm có hiệu lực ở lượt dịch mới. Khôi phục offline không gọi HTTP hoặc gửi lại batch lỗi.')
        note.setWordWrap(True);layout.addWidget(note)
        form=QFormLayout();self.kira_limits={}
        for key,title,default,maximum in [('kira_account_limit','Trần đồng thời tài khoản',30,100000),('kira_rpm','RPM tài khoản (trần cục bộ)',60,1000000),('kira_tpm','TPM tài khoản (trần cục bộ)',1000000,1000000000)]:
            box=QSpinBox();box.setRange(1,maximum);box.setValue(int(self.store.setting(key,str(default))))
            box.valueChanged.connect(lambda value,k=key:self.store.set_setting(k,str(value)))
            form.addRow(title,box);self.kira_limits[key]=box
        layout.addLayout(form)
        recovery=QFormLayout();self.kira_recovery_controls={}
        for key,title,default,maximum in [('kira_retry_limit','Kira: thử lại an toàn mỗi batch (0 = tắt)',2,5),
            ('kira_retry_budget','Kira: tổng request thử lại mỗi lượt',30,10000),
            ('kira_request_limit','Kira: trần tổng request/lượt (0 = tự tính hữu hạn)',0,1000000),
            ('kira_token_limit','Kira: trần token dự phòng/lượt (0 = tự tính hữu hạn)',0,1000000000)]:
            box=QSpinBox();box.setRange(0,maximum);box.setValue(int(self.store.setting(key,str(default))))
            box.valueChanged.connect(lambda value,k=key:self.store.set_setting(k,str(value)))
            recovery.addRow(title,box);self.kira_recovery_controls[key]=box
        layout.addLayout(recovery)
        policy=QLabel('Lượt mới giữ key/model và ngân sách cố định. Tự phục hồi 429, JSON, timeout/504/5xx trong giới hạn; timeout/504 tối đa hai lần gửi lại mỗi batch trong toàn job, có rủi ro token trùng. Tự rà soát tối đa hai lượt cuối. Không đổi sang model trả phí. Thời gian chờ tối đa nằm trong Cài đặt. Tiếp tục lượt cũ áp dụng quyền phục hồi mới nhưng giữ nguyên trần và bộ đếm đã lưu; lượt đã tắt retry vẫn giữ nguyên.')
        policy.setWordWrap(True);layout.addWidget(policy)
        self.kira_metrics=QLabel();self.kira_metrics.setWordWrap(True);layout.addWidget(self.kira_metrics)
        self.refresh_kira_keys()

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
                if current and row['enabled']:row['status']=current['status']
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
                labels={'READY':'Sẵn sàng','COOLDOWN':'Giới hạn tốc độ · tự chờ','TEMPORARY_ERROR':'Lỗi tạm thời · tự phục hồi',
                    'INVALID':'Xác thực không hợp lệ','PERMISSION_DENIED':'Không có quyền dùng model','MODEL_UNAVAILABLE':'Model/request không khả dụng',
                    'QUOTA_EXHAUSTED':'Quota model · chờ reset/xác minh','CREDENTIAL_ERROR':'Không giải mã được key','UNKNOWN_ERROR':'Cần chẩn đoán','DISABLED':'Đã tắt'}
                self.kira_keys_list.addItem(f"{k['name']} · •••••••• · {labels.get(k['status'],k['status'])}")
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
        if key_id and QMessageBox.question(self,'Xóa Kira key','Chỉ xóa key đã chọn; request đang gửi sẽ hoàn tất. Không xóa bản dịch.',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)==QMessageBox.Yes:
            self.store.change_kira_key(key_id,delete=True)
        self.refresh_kira_keys()

    def restore_kira_key(self):
        key_id=self.selected_kira_key()
        if key_id and QMessageBox.question(self,'Khôi phục key offline','Bạn đã kiểm tra quota/quyền truy cập? Cho key nhận batch mới, không gửi lại request lỗi; không gọi API để kiểm tra.',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)==QMessageBox.Yes:
            self.store.change_kira_key(key_id,restore=True)
        self.refresh_kira_keys()
