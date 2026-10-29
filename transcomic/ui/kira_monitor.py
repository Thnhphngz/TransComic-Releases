"""Non-modal Kira monitor. Widgets only consume detached worker snapshots."""
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer, QEvent
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QWidget, QFrame, QTableView, QHeaderView, QAbstractItemView, QSizePolicy)
from .glass import GlassButton
from ..kira_telemetry import counters


RUN_STATES = {'not_started':'Chưa bắt đầu','running':'Đang dịch','user_paused':'Tạm dừng',
    'waiting_rate_limit':'Kira giới hạn tốc độ · tự chờ và tiếp tục','network_waiting':'Chờ mạng phục hồi',
    'provider_recovering':'Chờ Kira/key phục hồi','retry_scheduled':'Đang tự xử lý dòng lỗi',
    'stopped':'Đã dừng','finished':'Đã hoàn thành','interrupted':'Đã gián đoạn',
    'needs_intervention':'Cần kiểm tra','quota_exhausted':'Chờ key',
    'blocked':'Bị chặn · kiểm tra quyền/ngân sách','completed_with_errors':'Hoàn thành còn lỗi'}
REASONS = {'ready':'Sẵn sàng nhưng rảnh','no_pending_work':'Không có batch chưa gửi',
    'account_slots_full':'Đã hết slot tài khoản','key_slots_full':'Đã hết slot key',
    'account_rpm':'Chờ RPM','account_tpm':'Chờ TPM','account_cooldown':'Đang cooldown',
    'key_cooldown':'Đang cooldown','cooldown':'Đang cooldown','quota_exhausted':'Quota model · chờ reset/xác minh','invalid':'Key không hợp lệ',
    'disabled':'Đã tắt','removed':'Đã xóa key','unknown_error':'Lỗi chưa phân loại',
    'credential_unavailable':'Không đọc được key','network_paused':'Tạm dừng do mạng',
    'adaptive_pacing':'Đang giảm tốc độ gửi','temporary_error':'Lỗi tạm thời · tự phục hồi',
    'permission_denied':'Không có quyền dùng model','model_unavailable':'Model không khả dụng','credential_error':'Không giải mã được key',
    'request_exceeds_tpm':'Batch vượt trần TPM'}
REASONS['account_quota_exhausted']='Nhóm đã xác nhận: provider báo hết quota model'
RUN_STATES.update(needs_reconciliation='Cần đối chiếu kết quả',blocked_auth='Key không hợp lệ',
    blocked_quota='Hết quota',blocked_budget='Đã đạt giới hạn phục hồi')


def kira_pool(owner):
    scheduler=getattr(owner,'scheduler',None)
    candidates=[scheduler]+list(reversed(getattr(scheduler,'children',())))
    for candidate in candidates:
        pool=getattr(candidate,'provider',None)
        if getattr(pool,'multi_key',False) and pool.monitor.run_id:return pool
    return None


def idle_snapshot(owner):
    rows=owner.store.kira_keys(); per_key=max(1,min(30,int(owner.store.setting('concurrency','30'))))
    limit=int(owner.store.setting('kira_account_limit','30')); groups={}; keys={}
    import time
    for row in rows:
        ready=row['enabled'] and (row['status']=='READY' or row['status']=='COOLDOWN' and 0<row['cooldown_until']<=time.time())
        scope=owner.store.kira_effective_scope(row['id'])
        if ready:groups[scope]=groups.get(scope,0)+per_key
        reason='ready' if ready else 'disabled' if not row['enabled'] else row['status'].lower()
        keys[row['id']]={**counters(),**row,'account_scope':scope,'slot_limit':min(limit,per_key),
            'busy':0,'wait_reason':reason,'files':[],'mean_seconds':0,'lines_per_minute':0,
            'unique_translated_lines':0,'in_flight_lines':0,'in_flight_requests':0}
    return dict(run_id=None,state='not_started',per_key=keys,enabled=sum(bool(r['enabled']) for r in rows),
        keys=sum(n//per_key for n in groups.values()),maximum=sum(min(n,limit) for n in groups.values()),
        busy=0,active_files=0,requests=0,successful_requests=0,failed_requests=0,unknown_requests=0,
        translated_lines=0,unique_translated_lines=0,detail_available=False)


class MonitorFiles(QAbstractTableModel):
    HEADERS=('Tài liệu · Đích','Đang dịch','Đã lưu','Lỗi','Unknown')
    def __init__(self,parent):
        super().__init__(parent); self.rows=[]; self.positions={}
    def rowCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.rows)
    def columnCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.HEADERS)
    def headerData(self,section,orientation,role=Qt.DisplayRole):
        if role==Qt.DisplayRole and orientation==Qt.Horizontal:return self.HEADERS[section]
    def data(self,index,role=Qt.DisplayRole):
        if not index.isValid() or not 0<=index.row()<len(self.rows):return None
        row=self.rows[index.row()]
        if role==Qt.UserRole:return row['document_id'],row['target_language']
        if role==Qt.DisplayRole:
            return (row['name']+' · '+row['target_language'].upper(),row['in_flight_lines'],
                row['translated_lines'],row['failed_lines'],row['unknown_lines'])[index.column()]
        if role==Qt.TextAlignmentRole and index.column():return Qt.AlignCenter
        if role==Qt.ToolTipRole:
            return (f"{row['name']} · {row['target_language']}\nID {row['document_id']}\n"
                f"{row['requests']} request · {row['in_flight_requests']} đang chờ HTTP\n"
                f"{row['unique_translated_lines']} dòng hoàn thành duy nhất · {row['rejected_lines']} dòng bị từ chối revision")
    def update_rows(self,rows):
        # Stable append order and incremental updates preserve selection/scroll.
        for row in rows:
            key=(row['document_id'],row['target_language'])
            if key not in self.positions:
                position=len(self.rows);self.beginInsertRows(QModelIndex(),position,position)
                self.positions[key]=position;self.rows.append(dict(row));self.endInsertRows()
            else:
                position=self.positions[key]
                if self.rows[position]!=row:
                    self.rows[position]=dict(row)
                    self.dataChanged.emit(self.index(position,0),self.index(position,4))


class KeyCard(QFrame):
    def __init__(self,dialog,key_id):
        super().__init__();self.setObjectName('card');self.dialog=dialog;self.key_id=key_id
        self.expanded=False
        layout=QVBoxLayout(self);layout.setContentsMargins(10,8,10,8);layout.setSpacing(6)
        self.header=GlassButton();self.header.clicked.connect(self.toggle);layout.addWidget(self.header)
        self.header.setMinimumWidth(0);self.header.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Fixed)
        self.body=QWidget();body=QVBoxLayout(self.body);body.setContentsMargins(0,0,0,0);body.setSpacing(6)
        self.details=QLabel();self.details.setWordWrap(True);self.details.setTextFormat(Qt.PlainText);body.addWidget(self.details)
        self.files=QTableView();self.model=MonitorFiles(self.files);self.files.setModel(self.model)
        self.files.setEditTriggers(QAbstractItemView.NoEditTriggers);self.files.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.files.setSelectionMode(QAbstractItemView.SingleSelection);self.files.verticalHeader().hide()
        self.files.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.files.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.files.setWordWrap(False);self.files.setTextElideMode(Qt.ElideMiddle)
        self.files.horizontalHeader().setSectionResizeMode(0,QHeaderView.Stretch)
        for col in range(1,5):self.files.horizontalHeader().setSectionResizeMode(col,QHeaderView.ResizeToContents)
        self.files.clicked.connect(lambda index:dialog.choose_file(index.data(Qt.UserRole)))
        body.addWidget(self.files);layout.addWidget(self.body);self.body.hide()
        self._header_text=''
    def toggle(self):
        self.expanded=not self.expanded;self.body.setVisible(self.expanded);self._header()
    def _header(self):
        full=('▾ ' if self.expanded else '▸ ')+self._header_text
        self.header.setText(self.header.fontMetrics().elidedText(full,Qt.ElideRight,max(1,self.header.width()-28)))
        self.header.setAccessibleName(full);self.header.setToolTip(full)
    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'_header_text'):self._header()
    def update_data(self,value,state):
        reason=REASONS.get(value['wait_reason'],value['wait_reason'])
        primary=('Đang dịch' if value.get('in_flight_requests') else
            'Đang lưu kết quả' if value.get('committing_requests') else
            'Chuẩn bị request' if value.get('claimed_not_sent') else
            'Tạm dừng' if state=='user_paused' and value['wait_reason'] in ('ready','no_pending_work') else reason)
        self._header_text=f"{value['name']} · {value['busy']}/{value['slot_limit']} luồng · {value['translated_lines']} dòng đã lưu · {primary}"
        self._header()
        scope=value['account_scope'];group='Chung / chưa phân nhóm' if scope=='shared' else '…'+scope[-6:]
        mean=f"{value.get('mean_seconds',0):.2f}s" if value.get('latency_samples') else 'Chưa đủ dữ liệu'
        text=(f"Nhóm tài khoản: {group} · {primary}\n"
            f"Gửi {value['requests']} · Thành công {value['successful_requests']} · Lỗi {value.get('failed_requests',0)} · Unknown {value.get('unknown_requests',0)}\n"
            f"{value['translated_lines']} dòng đã lưu · {value.get('unique_translated_lines',0)} dòng duy nhất · {value.get('lines_per_minute',0):.1f} dòng/phút · TB {mean}\n"
            f"Đang chờ HTTP {value.get('in_flight_lines',0)} dòng · {reason} · Request dịch lại {value.get('retranslation_requests',0)}")
        if self.details.text()!=text:self.details.setText(text)
        self.details.setToolTip('Dòng đã lưu tính theo lần xử lý; dòng duy nhất tính theo document ID/ngôn ngữ/line ID. Không tính context hoặc chỉnh sửa tay. Slot bận có thể gồm chuẩn bị và commit. Tốc độ trung bình từ khi bắt đầu lượt.')
        scroll=self.files.verticalScrollBar().value();self.model.update_rows(value.get('files',()))
        header=max(self.files.horizontalHeader().height(),self.files.horizontalHeader().sizeHint().height())
        rows=len(self.model.rows)*self.files.verticalHeader().defaultSectionSize()
        self.files.setFixedHeight(min(180,max(70,header+rows+2*self.files.frameWidth())))
        self.files.verticalScrollBar().setValue(scroll)
        self.files.setVisible(bool(self.model.rows))


class KiraMonitorDialog(QDialog):
    def __init__(self,owner):
        super().__init__(owner);self.owner=owner;self.cards={};self._run_id=object();self._source=object();self._archive=None
        self._navigation_note=''
        self.setWindowTitle('Kira Live Monitor');self.setWindowModality(Qt.NonModal)
        layout=QVBoxLayout(self);layout.setContentsMargins(14,12,14,12);layout.setSpacing(8)
        self.summary=QLabel();self.summary.setWordWrap(True);self.summary.setTextFormat(Qt.PlainText);layout.addWidget(self.summary)
        self.note=QLabel();self.note.setWordWrap(True);self.note.setObjectName('muted');layout.addWidget(self.note)
        self.scroll=QScrollArea();self.scroll.setWidgetResizable(True);self.scroll.setFrameShape(QFrame.NoFrame)
        self.content=QWidget();self.card_layout=QVBoxLayout(self.content);self.card_layout.setContentsMargins(0,0,0,0)
        self.card_layout.setSpacing(8);self.card_layout.addStretch();self.scroll.setWidget(self.content);layout.addWidget(self.scroll,1)
        footer=QHBoxLayout();self.manage=GlassButton('Quản lý API');self.manage.clicked.connect(self.manage_api)
        footer.addWidget(self.manage);footer.addStretch();self.close_button=GlassButton('Đóng');self.close_button.clicked.connect(self.reject)
        footer.addWidget(self.close_button);layout.addLayout(footer)
        self.watch=QTimer(self);self.watch.setInterval(750);self.watch.timeout.connect(self.refresh_data)
        owner.installEventFilter(self)

    def fit_screen(self):
        area=self.owner.screen().availableGeometry()
        width=max(1,min(self.owner.width()-16,area.width()-24));height=max(1,int(min(self.owner.height(),area.height())*.8))
        self.setMaximumSize(width,height);self.resize(min(720,width),min(580,height))
        center=self.owner.frameGeometry().center()
        frame=self.frameGeometry()
        self.move(max(area.left()+8,min(center.x()-frame.width()//2,area.right()-frame.width()-8)),
            max(area.top()+8,min(center.y()-frame.height()//2,area.bottom()-frame.height()-8)))

    def clamp_position(self):
        if not self.isVisible():return
        area=self.screen().availableGeometry();frame=self.frameGeometry()
        x=max(area.left()+8,min(frame.left(),area.right()-frame.width()-8))
        y=max(area.top()+8,min(frame.top(),area.bottom()-frame.height()-8))
        if x!=frame.left() or y!=frame.top():self.move(x,y)

    def eventFilter(self,obj,event):
        if obj is self.owner and event.type()==QEvent.Resize and self.isVisible():self.fit_screen()
        return super().eventFilter(obj,event)

    def refresh_data(self):
        if self.owner._closed or self.owner._exit_pending:self.watch.stop();return
        pool=kira_pool(self.owner)
        if pool:
            per_key=max(1,min(30,int(self.owner.store.setting('concurrency','30'))))
            snapshot=pool.redact(pool.monitor_snapshot(per_key))
            self._archive=snapshot;self._source=pool
        else:
            if self._source is not None:
                from ..kira_monitor_store import load_latest
                self._archive=load_latest(self.owner.store);self._source=None
            current=idle_snapshot(self.owner)
            if self._archive:
                from copy import deepcopy
                snapshot=deepcopy(self._archive)
                for name in ('enabled','keys','maximum'):snapshot[name]=current[name]
                for key,value in current['per_key'].items():
                    if key not in snapshot['per_key']:snapshot['per_key'][key]=value
                    else:
                        for field in ('name','enabled','status','slot_limit','wait_reason'):
                            snapshot['per_key'][key][field]=value[field]
                for key,value in snapshot['per_key'].items():
                    if key not in current['per_key']:value.update(status='REMOVED',enabled=False,wait_reason='removed',slot_limit=0)
            else:snapshot=current
        self.render(snapshot)

    def render(self,snapshot):
        run_id=snapshot['run_id']
        if self._run_id!=run_id:
            for card in self.cards.values():self.card_layout.removeWidget(card);card.deleteLater()
            self.cards.clear();self._run_id=run_id;self.scroll.verticalScrollBar().setValue(0)
            self._navigation_note=''
        scroll=self.scroll.verticalScrollBar().value()
        for key in set(self.cards)-set(snapshot['per_key']):
            card=self.cards.pop(key);self.card_layout.removeWidget(card);card.deleteLater()
        state=snapshot['state'];state_text=RUN_STATES.get(state,state)
        if snapshot.get('recovery_phase') and state in ('running','retry_scheduled','provider_recovering','waiting_rate_limit'):
            state_text=f"Rà soát lỗi lần {snapshot['recovery_phase']}/2 · {state_text}"
        self.summary.setText(f"Kira Live Monitor — {state_text}\n"
            f"{snapshot['enabled']} key bật · {snapshot['keys']} khả dụng · {snapshot['busy']}/{snapshot['maximum']} luồng · {snapshot['active_files']} file đang xử lý\n"
            f"{snapshot['translated_lines']} dòng đã lưu · {snapshot['unique_translated_lines']} dòng duy nhất\n"
            f"Request: gửi {snapshot['requests']} · thành công {snapshot['successful_requests']} · lỗi {snapshot['failed_requests']} · unknown {snapshot['unknown_requests']} · RPM TB {snapshot.get('effective_rpm',0):.1f} · chờ {snapshot.get('queued_batches',0)}")
        self.note.setText(self._navigation_note or ('Chưa có lượt dịch để theo dõi. Không có dữ liệu chi tiết cho lịch sử trước Live Monitor.' if not run_id else
            ('Chưa có batch được cấp trong lượt này.' if state=='running' else 'Không có dữ liệu chi tiết của lượt cũ.') if not snapshot.get('detail_available') else
            ('Lượt gần nhất đã lưu · ' if snapshot.get('archived') else '')+'Chọn tên file để xem bản dịch. Đang dịch chỉ tính dòng đã gửi và đang chờ HTTP.'))
        if snapshot.get('persistence_error'):
            self.note.setText(self.note.text()+'\nChưa lưu được summary; thống kê hiện tại vẫn có trong bộ nhớ.')
        if snapshot.get('intervention_reason'):
            from ..kira_recovery import reason_label
            self.note.setText(self.note.text()+'\n'+reason_label(snapshot['intervention_reason']))
        for key,value in snapshot['per_key'].items():
            if key not in self.cards:
                card=KeyCard(self,key);self.cards[key]=card;self.card_layout.insertWidget(self.card_layout.count()-1,card)
            self.cards[key].update_data(value,state)
        self.scroll.verticalScrollBar().setValue(scroll)

    def choose_file(self,key):
        if not key:return
        document_id,language=key
        if document_id not in self.owner.workspace_ids:
            self._navigation_note='Tài liệu này không còn trong danh sách đang mở; thống kê lịch sử vẫn được giữ.'
            self.note.setText(self._navigation_note);return
        try:doc=self.owner.store.document(document_id)
        except KeyError:
            self.note.setText('Tài liệu không còn tồn tại.');return
        from ..languages import language as resolve
        if resolve(doc['target_lang']).locale!=language:
            self.note.setText('Không xác định được đúng ngôn ngữ của tài liệu.');return
        self.owner.period_warning.remember_editor()
        self.owner._kira_monitor_navigating=True
        generation=getattr(self.owner,'_kira_monitor_navigation',0)+1
        self.owner._kira_monitor_navigation=generation
        self.owner.raise_();self.owner.activateWindow()
        self.hide();self.owner.pages.setCurrentIndex(0)
        if self.owner.doc_id!=document_id:self.owner.open_document(document_id)
        def focus_restored():
            def release():
                if self.owner._kira_monitor_navigation==generation:self.owner._kira_monitor_navigating=False
            if self.owner._closed or self.owner._exit_pending:release();return
            if self.owner.doc_id==document_id:
                editor=self.owner.table.itemDelegate().active_editor
                (editor or self.owner.table).setFocus(Qt.OtherFocusReason)
            QTimer.singleShot(80,release)
        QTimer.singleShot(0,focus_restored)

    def manage_api(self):self.hide();self.owner.pages.setCurrentIndex(2)
    def showEvent(self,event):
        self._source=object();self._navigation_note=''
        self.refresh_data();self.fit_screen();self.watch.start();super().showEvent(event)
        QTimer.singleShot(0,self.clamp_position)
    def hideEvent(self,event):self.watch.stop();super().hideEvent(event)


def open_monitor(owner):
    if owner._closed or owner._exit_pending:return
    if not hasattr(owner,'kira_monitor_dialog'):owner.kira_monitor_dialog=KiraMonitorDialog(owner)
    owner.kira_monitor_dialog.show();owner.kira_monitor_dialog.raise_();owner.kira_monitor_dialog.activateWindow()
