"""File-first TTS workspace, document details and right-side audio history."""
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from datetime import datetime
from uuid import uuid4
from PySide6.QtCore import Qt,Signal,QTimer,QUrl,QEvent
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,QTableView,QHeaderView,QAbstractItemView,QFileDialog,QMessageBox,QInputDialog,QDialog,QDialogButtonBox,QPlainTextEdit,QProgressBar,QLineEdit,QTabWidget,QTabBar,QSplitter,QDoubleSpinBox,QSpinBox,QScrollArea,QSizePolicy,QFrame)
from .controls import QComboBox
from .glass import GlassButton as QPushButton
from .tts_models import DocumentModel,SegmentModel,AudioModel,ActionDelegate,STATES,TtsTable,CenterCheckDelegate
from ..tts.storage import TtsStore
from ..tts.models import ModelManager
from ..tts.catalog import LANGUAGES,voice_names,REVISION
from ..tts.documents import read_document,scan,segments
from ..tts.output import Outputs
from ..tts.scheduler import Scheduler
from ..tts.player import AudioPlayer
from ..tts.runtime import diagnostics,logger,friendly
from ..documents import EncodingChoiceRequired


class TtsPage(QWidget):
    engine_name='Kokoro'
    event=Signal(str,object)
    task_done=Signal(object)
    download_progress=Signal(int,int,str)

    def __init__(self,data_directory,parent=None,*,store=None):
        super().__init__(parent);self.directory=Path(data_directory)/'TTS';self.owns_store=store is None;self.store=store or TtsStore(self.directory/'tts.sqlite3')
        self.log=logger(self.directory/'Logs');self.manager=ModelManager(self.directory/'Models');self.tasks=[];self.cancel=threading.Event()
        self.scheduler=Scheduler(self.store,self.manager,lambda k,v:self.event.emit(k,v),before_finalize=self.release_player)
        from ..tts.acceleration import AccelerationPacks,packaged_descriptor
        descriptor=packaged_descriptor();legacy=AccelerationPacks(self.directory/'AccelerationPacks',descriptor,previous=descriptor.get('previous',[]) if descriptor else ())
        from ..tts.setup import RuntimeRegistry
        self.packs=RuntimeRegistry(self.directory/'Runtimes',legacy);self.scheduler.packs=self.packs
        self.run_id=self.store.draft();self.detail_document=None;self.history_document=None;self.playing=None;self.play_generation=0;self.play_lookup={};self.runtime_ready=False;self.runtime_info={};self.probing=False;self.playing_document=None
        self.event.connect(self.on_event);self.task_done.connect(self.on_task_done);self.download_progress.connect(self.progress)
        self.input_snapshot=None;self.input_run=None;self.audio_dialog=None;self.bulk_run=self.run_id
        self.pending_items=set();self.update_timer=QTimer(self);self.update_timer.setSingleShot(True);self.update_timer.setInterval(120);self.update_timer.timeout.connect(self.flush_items)
        self.setAcceptDrops(True);layout=QVBoxLayout(self);layout.setContentsMargins(10,8,10,8);layout.setSpacing(0)
        self.splitter=QSplitter(Qt.Horizontal);layout.addWidget(self.splitter,1);self.workspace=QWidget();self.workspace.installEventFilter(self);left=QVBoxLayout(self.workspace);left.setContentsMargins(0,0,0,0);left.setSpacing(7)
        heading=QHBoxLayout();left.addLayout(heading);title=QLabel('Text to Speech');title.setObjectName('section');heading.addWidget(title)
        self.runtime_label=QLabel(self.engine_name+' · đang kiểm tra');self.runtime_label.setObjectName('muted');heading.addWidget(self.runtime_label,1)
        self.settings_button=self.button(heading,'Cài đặt',self.open_settings)
        self.controls=QWidget();self.config_grid=QGridLayout(self.controls);self.config_grid.setContentsMargins(0,0,0,0);self.config_grid.setSpacing(6)
        left.addWidget(self.controls);self.build_controls()
        self.tab_strip=QWidget();self.tab_grid=QGridLayout(self.tab_strip);self.tab_grid.setContentsMargins(0,0,0,0);self.tab_grid.setSpacing(4);left.addWidget(self.tab_strip)
        self.tab_bar=QTabBar();self.tab_bar.setExpanding(False);self.tab_bar.setDrawBase(False)
        self.tabs=QTabWidget();self.files_page=QWidget();self.input_page=QWidget();self.detail_page=QWidget()
        for page,title in ((self.files_page,'TTS Hàng Loạt'),(self.input_page,'Nhập văn bản'),(self.detail_page,'Chi tiết')):self.tabs.addTab(page,title)
        for index in range(3):self.tab_bar.addTab(self.tabs.tabText(index))
        self.tabs.tabBar().hide();self.tab_bar.setTabEnabled(2,False);self.tab_bar.currentChanged.connect(self.tabs.setCurrentIndex);self.tabs.currentChanged.connect(self.tab_changed)
        self.tab_grid.addWidget(self.tab_bar,0,0);self.tab_grid.addWidget(self.split_controls,0,1,Qt.AlignRight);self.tab_grid.setColumnStretch(1,1)
        self.content_grid=QGridLayout();self.content_grid.setContentsMargins(0,0,0,0);left.addLayout(self.content_grid,1);self.content_grid.addWidget(self.tabs,0,0)
        self.automation_context=QFrame();self.automation_context.setObjectName('card');context=QVBoxLayout(self.automation_context);context.setContentsMargins(28,28,28,28);context.addStretch()
        heading=QLabel('Kokoro đang được Automation quản lý');heading.setObjectName('section');heading.setWordWrap(True);context.addWidget(heading)
        self.automation_context_text=QLabel();self.automation_context_text.setWordWrap(True);context.addWidget(self.automation_context_text);context.addStretch();self.content_grid.addWidget(self.automation_context,0,0);self.automation_context.hide()
        self.tabs.setTabEnabled(2,False);self.build_files();self.build_input();self.build_details();self.build_history();self.content_grid.addWidget(self.player,0,0,Qt.AlignBottom|Qt.AlignHCenter)
        self.splitter.addWidget(self.workspace);self.splitter.addWidget(self.history_panel);self.splitter.setChildrenCollapsible(False);self.splitter.setStretchFactor(0,1);self.splitter.setStretchFactor(1,0);self.splitter.splitterMoved.connect(self.save_history_width)
        self.action_strip=QWidget();actions=QHBoxLayout(self.action_strip);actions.setContentsMargins(0,0,0,0);left.addWidget(self.action_strip);self.start_button=self.button(actions,'Bắt đầu',self.start);self.pause_button=self.button(actions,'Tạm dừng',self.pause);self.stop_button=self.button(actions,'Dừng',self.stop)
        self.progress_bar=QProgressBar();self.progress_bar.setMinimumWidth(60);actions.addWidget(self.progress_bar,1)
        self.notice=QLabel(self);self.notice.hide()  # compatibility text, no status strip
        from .tts_errors import ErrorDialog
        self.error_dialog=ErrorDialog(self);self.build_settings();self.apply_theme();self.refresh_files();self.load_history();self.restore_history();self.split_controls.setEnabled(False);self.update_input_counts();self.check_runtime()

    def button(self,row,title,callback):
        button=QPushButton(title);button.setToolTip(title);button.clicked.connect(lambda:self.guard(callback));row.addWidget(button);return button
    def guard(self,callback):
        try:return callback()
        except Exception as exc:self.log.exception('TTS UI action failed');self.report_error(exc,'Thao tác giao diện')
    def show_notice(self,text):
        self.notice.setText(str(text));self.runtime_label.setToolTip(str(text))
        if hasattr(self,'asset_status'):self.asset_status.setText(str(text))
    def is_busy(self):
        controller=getattr(getattr(self.store,'automation',None),'controller',None)
        return self.scheduler.busy or any(t.is_alive() for t in self.tasks) or bool(controller and controller.busy)
    def background(self,work,done=lambda result:None):
        def task():
            try:value=(True,work())
            except Exception as exc:
                import traceback
                if not hasattr(exc,'technical_traceback'):exc.technical_traceback=traceback.format_exc()
                self.log.exception('TTS background task failed');value=(False,exc)
            self.task_done.emit((done,value))
        thread=threading.Thread(target=task,daemon=True,name='tts-utility');self.tasks=[t for t in self.tasks if t.is_alive()];self.tasks.append(thread);thread.start();self.refresh()
    def on_task_done(self,value):
        if getattr(self,'_shutdown',False):return
        done,(ok,result)=value
        if ok:self.guard(lambda:done(result))
        else:
            self.probing=False
            if not isinstance(result,InterruptedError):self.report_error(result,'Tác vụ nền')
            if getattr(self,'setting_up',False):
                self.setting_up=False;self.runtime_ready=False;self.asset_progress.setRange(0,100);self.setup_button.setText('Thử lại');self.setup_button.setEnabled(True)
                self.variant.setEnabled(True);self.device_id.setEnabled(True)
                self.asset_status.setText('Đã hủy chuẩn bị Kokoro.' if isinstance(result,InterruptedError) else 'Không thể hoàn tất tải model. Vui lòng thử lại.')
        QTimer.singleShot(40,self.refresh_when_idle)
    def refresh_when_idle(self):
        if getattr(self,'_shutdown',False):return
        self.refresh()
        if self.is_busy():QTimer.singleShot(60,self.refresh_when_idle)
    def release_player(self):
        released=threading.Event();self.event.emit('release_player',released)
        if not released.wait(5):raise RuntimeError('Chờ player nhả file trước khi đổi tên thư mục. Tiến độ được giữ.')
    def request_stop(self):self.cancel.set();self.scheduler.stop(permanent=False);self.stop_playback()
    def shutdown(self):
        if self.is_busy():raise RuntimeError('Đang dừng TTS an toàn')
        self._shutdown=True;self.input_timer.stop();self.history_panel.filter_timer.stop()
        self.update_timer.stop();self.history_panel.presence_timer.stop();self.stop_playback()
        if self.owns_store:self.store.close()
        for handler in list(self.log.handlers):handler.close();self.log.removeHandler(handler)

    def build_controls(self):
        self.language=QComboBox()
        for code,(title,_,__) in LANGUAGES.items():self.language.addItem(title,code)
        self.voice=QComboBox();self.language.currentIndexChanged.connect(self.update_voices);self.update_voices()
        self.speed=QDoubleSpinBox();self.speed.setRange(.5,2);self.speed.setSingleStep(.05);self.speed.setValue(1);self.speed.setSuffix('x')
        from .tts_split import SplitControls
        self.split_controls=SplitControls(self);self.split=self.split_controls.combo;self.split_controls.changed.connect(lambda:self.update_input_counts() if hasattr(self,'input_text') else None)
        self.format=QComboBox();self.format.addItems(['WAV','MP3'])
        self.mode=QComboBox();self.mode.addItem('Cạnh file nguồn','beside');self.mode.addItem('Thư mục tùy ý','custom');self.config_fields=[]
        self.parallel_width=QComboBox()
        for title,value in [('Tự động',0),('1 đoạn',1),('2 đoạn',2),('3 đoạn',3),('4 đoạn',4)]:self.parallel_width.addItem(title,value)
        self.parallel_width.setToolTip('Số đoạn đồng thời; tự động theo benchmark và RAM/VRAM còn trống')
        self.bitrate=QComboBox();self.bitrate.addItems(['96','128','192']);self.bitrate.setCurrentText('128')
        for label,control,width in [('Ngôn ngữ',self.language,190),('Giọng đọc',self.voice,155),('Speed',self.speed,120),('Định dạng',self.format,90),('Lưu audio',self.mode,190),('Đồng thời',self.parallel_width,120),('MP3 kbps',self.bitrate,100)]:
            field=QWidget();column=QVBoxLayout(field);column.setContentsMargins(0,0,0,0);column.setSpacing(3);caption=QLabel(label);caption.setObjectName('muted');column.addWidget(caption);column.addWidget(control);field.setMaximumWidth(width);field.setMinimumWidth(min(width,90));self.config_fields.append(field)
            if hasattr(control,'view'):control.view().setMinimumWidth(max(190,width))
            signal=control.valueChanged if isinstance(control,QDoubleSpinBox) else control.currentIndexChanged
            signal.connect(lambda *_:self.refresh())
        self.layout_controls()
    def layout_controls(self):
        width=self.workspace.width() if hasattr(self,'workspace') else self.width();columns=4 if width>=650 else 3 if width>=420 else 2
        for field in self.config_fields:self.config_grid.removeWidget(field)
        for i,field in enumerate(self.config_fields):self.config_grid.addWidget(field,i//columns,i%columns,Qt.AlignLeft)
        for col in range(5):self.config_grid.setColumnStretch(col,0)
        self.config_grid.setColumnStretch(columns,1)
        if hasattr(self,'tab_grid'):
            self.tab_grid.removeWidget(self.split_controls);self.tab_grid.addWidget(self.split_controls,0 if width>=730 else 1,1 if width>=730 else 0,1,1 if width>=730 else 2,Qt.AlignRight)
    def tab_changed(self,index):
        self.tab_bar.setCurrentIndex(index);self.split_controls.setEnabled(index==1)
        target=self.bulk_run if index==0 else self.input_run if index==1 else None
        if target and self.store.run(target) and not self.scheduler.busy:self.run_id=target;self.refresh_files()
        self.refresh()
    def update_voices(self):self.voice.clear();self.voice.addItems(voice_names(self.language.currentData()))
    def config(self):
        config=dict(language=self.language.currentData(),voice=self.voice.currentText(),speed=self.speed.value(),device='Auto',device_id=self.device_id.value(),variant=self.variant.currentData(),format=self.format.currentText().lower(),bitrate=int(self.bitrate.currentText()),revision=REVISION,split=self.split.currentData())
        from ..tts.concurrency import selected
        measured={**config,'_managed_engine':self.runtime_info.get('engine_process',{})}
        config['workers']=self.parallel_width.currentData() or selected(self.store,measured)
        return config
    def table_view(self,model):
        table=TtsTable();table.setModel(model);table.setSelectionBehavior(QAbstractItemView.SelectRows);table.setSelectionMode(QAbstractItemView.ExtendedSelection);table.setAlternatingRowColors(True);table.setWordWrap(False);table.setMinimumWidth(0);table.verticalHeader().hide();table.verticalHeader().setDefaultSectionSize(38);table.setMouseTracking(True);return table
    def add_actions(self,table,columns,callback):
        for column in columns:
            delegate=ActionDelegate(table);delegate.activated.connect(lambda id,col:self.guard(lambda:callback(id,col)));table.setItemDelegateForColumn(column,delegate)
    def build_files(self):
        layout=QVBoxLayout(self.files_page);layout.setContentsMargins(6,6,6,6);row=QHBoxLayout();layout.addLayout(row)
        self.button(row,'Thêm file',self.pick_files);self.button(row,'Nhập thư mục',self.pick_folder);self.button(row,'Xóa file đã chọn',self.remove_files);self.button(row,'Xóa toàn bộ',self.clear_all);row.addStretch()
        self.manual_context_note=QLabel('Bản nháp TTS thủ công đã lưu · Các job Automation nằm trong Lịch sử.');self.manual_context_note.setObjectName('muted');self.manual_context_note.setWordWrap(True);self.manual_context_note.hide();layout.addWidget(self.manual_context_note)
        self.file_totals=QLabel('Chưa có tài liệu · Thả TXT / DOCX trực tiếp vào bảng');self.file_totals.setWordWrap(True);layout.addWidget(self.file_totals)
        self.document_model=DocumentModel(self.store,self);self.file_table=self.table_view(self.document_model);layout.addWidget(self.file_table,1);self.file_table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch)
        self.file_table.setColumnWidth(0,36)
        self.file_table.setItemDelegateForColumn(0,CenterCheckDelegate(self.file_table))
        from .tts_models import CheckHeader
        self.file_table.setHorizontalHeader(CheckHeader(self.document_model,self.file_table));self.file_table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch)
        self.file_table.setColumnWidth(0,36)
        for col,width in ((2,55),(3,90),(4,78),(5,78),(6,100),(7,70),(8,88)):self.file_table.setColumnWidth(col,width)
        self.add_actions(self.file_table,[8],lambda id,_:self.open_details(id));self.file_table.doubleClicked.connect(lambda index:self.guard(lambda:self.open_details(index.data(Qt.UserRole))))
        self.file_table.viewport().setAcceptDrops(True);self.file_table.viewport().installEventFilter(self);self.files_page.setAcceptDrops(True);self.files_page.installEventFilter(self)
    def build_input(self):
        layout=QVBoxLayout(self.input_page);layout.setContentsMargins(6,6,6,6);row=QHBoxLayout();layout.addLayout(row);row.addWidget(QLabel('Tên lượt / output'));self.input_name=QLineEdit('Văn bản nhập');row.addWidget(self.input_name,1);self.input_name.textChanged.connect(lambda _:self.refresh())
        self.input_text=QPlainTextEdit();self.input_text.setPlaceholderText('Nhập hoặc dán văn bản tại đây…');layout.addWidget(self.input_text,1);self.input_counts=QLabel();layout.addWidget(self.input_counts)
        self.input_timer=QTimer(self);self.input_timer.setSingleShot(True);self.input_timer.setInterval(120);self.input_timer.timeout.connect(self.update_input_counts);self.input_text.textChanged.connect(lambda:self.input_timer.start())
    def update_input_counts(self):
        text=self.input_text.toPlainText();count=len(segments(text,self.split.currentData()));self.input_counts.setText(f'{len(text)} ký tự · {len(text.splitlines())} dòng nguồn · {count} đoạn TTS dự kiến');self.split_controls.set_count(count);self.refresh()
    def build_details(self):
        layout=QVBoxLayout(self.detail_page);layout.setContentsMargins(6,6,6,6);row=QHBoxLayout();layout.addLayout(row);self.button(row,'‹ Quay lại',lambda:self.tabs.setCurrentIndex(0));self.detail_title=QLabel();row.addWidget(self.detail_title,1)
        self.button(row,'Mở thư mục',lambda:self.open_folder(self.detail_document));self.button(row,'Tạo lại lỗi',self.retry_errors)
        self.model=SegmentModel(self.store,self);self.model.changed.connect(self.refresh_files);self.table=self.table_view(self.model);layout.addWidget(self.table,1);self.table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch)
        for col,width in ((0,58),(2,80),(3,98),(4,90),(5,55),(6,72),(7,80)):self.table.setColumnWidth(col,width)
        self.add_actions(self.table,[6,7],lambda id,col:self.play_segment(id) if col==6 else self.retry_ids([id]))
    def open_details(self,document):
        if document and document.startswith('import:'):self.import_paths([document[len('import:'):]]);return
        doc=self.store.doc(document)
        if not doc:raise ValueError('Tài liệu không còn trong lịch sử')
        self.detail_document=document;self.model.default_format=self.format.currentText().lower();self.model.load(doc['run_id'],document);self.detail_title.setText(doc['name']);self.tabs.setTabEnabled(2,True);self.tab_bar.setTabEnabled(2,True);self.tabs.setCurrentIndex(2);self.refresh()

    def build_history(self):
        from .tts_history import HistoryPanel
        self.audio_model=AudioModel(self);self.player=AudioPlayer(compact=True);self.player.hide()
        self.player.error.connect(self.show_notice);self.player.player.playbackStateChanged.connect(lambda _:self.sync_playback());self.player.player.sourceChanged.connect(lambda _:self.sync_playback())
        self.history_panel=HistoryPanel(self)
    def restore_history(self):
        row=self.store.one("SELECT value FROM preferences WHERE name='history_width'");width=int(row['value']) if row else 320
        self.splitter.setSizes([max(300,self.width()-width),width])
    def save_history_width(self,*args):
        if not self.history_panel.isHidden():self.store.execute("INSERT OR REPLACE INTO preferences VALUES ('history_width',?)",(str(self.splitter.sizes()[1]),))
    def load_history(self):
        if not self.history_document or not self.store.doc(self.history_document):
            row=self.store.one('SELECT d.id FROM documents d JOIN runs r ON r.id=d.run_id WHERE r.history_accepted=1 ORDER BY r.created DESC,d.position LIMIT 1');self.history_document=row['id'] if row else None
        self.refresh_history()
    def refresh_history(self,changed=None):
        doc=self.store.doc(self.history_document) if self.history_document else None
        if not doc:
            self.audio_model.replace([]);self.history_panel.refresh()
            if self.audio_dialog:self.audio_dialog.refresh()
            return
        if changed is None:items=self.store.rows("SELECT * FROM segments WHERE document_id=? AND state='success' AND skip=0 ORDER BY position",(doc['id'],))
        else:
            entries={i['id']:i for i in self.audio_model.items}
            for id in changed:
                item=self.store.segment(id)
                if item and item['document_id']==doc['id']:
                    if item['state']=='success' and not item['skip']:entries[id]=item
                    else:entries.pop(id,None)
            items=sorted(entries.values(),key=lambda i:i['position'])
        self.audio_model.replace(items);self.history_panel.refresh(changed)
        if self.audio_dialog and self.audio_dialog.isVisible():self.audio_dialog.refresh(changed)

    def open_sentences(self,document):
        from .tts_audio_dialog import AudioDialog
        if not self.audio_dialog:self.audio_dialog=AudioDialog(self)
        self.history_document=document;self.audio_dialog.open_document(document)

    def resume_history(self):
        if not self.history_document:return
        if self.is_busy():raise ValueError('Chờ tác vụ hiện tại dừng an toàn')
        from ..tts.storage import RECOVERABLE
        self.run_id=self.store.doc(self.history_document)['run_id']
        if self.store.run(self.run_id)['state'] not in RECOVERABLE:raise ValueError('Lượt này không thể tiếp tục')
        self.document_model.omitted.clear();self.refresh_files();self.start(resume=True)
    def relink(self):
        if self.is_busy():raise ValueError('Dừng tác vụ trước khi liên kết lại')
        document=self.history_document
        if not document:return
        folder=QFileDialog.getExistingDirectory(self,'Chọn thư mục audio đã di chuyển')
        if folder:self.background(lambda:Outputs(self.store).relink(document,folder),lambda _:self.refresh_history())
    def delete_history(self):
        if self.is_busy():raise ValueError('Dừng tác vụ trước khi xóa bản ghi')
        doc=self.store.doc(self.history_document) if self.history_document else None
        if not doc:return
        from ..tts.storage import TERMINAL
        if self.store.run(doc['run_id'])['state'] not in TERMINAL:raise ValueError('Hủy hoặc hoàn tất lượt trước khi xóa lịch sử để giữ checkpoint')
        if QMessageBox.question(self,'Xóa lịch sử','Xóa bản ghi tài liệu này? Giữ nguyên mọi audio trên ổ đĩa.')!=QMessageBox.Yes:return
        self.player.stop();self.store.execute('DELETE FROM documents WHERE id=?',(doc['id'],))
        if not self.store.docs(doc['run_id']):self.store.delete_history([doc['run_id']])
        if not self.store.run(self.run_id):self.run_id=self.store.draft()
        self.detail_document=None;self.tabs.setTabEnabled(2,False);self.refresh_files();self.load_history()

    def clear_history(self):
        if self.is_busy():raise ValueError('Không thể xóa lịch sử khi còn tác vụ đang chạy')
        from ..tts.storage import TERMINAL
        runs=self.store.history_runs()
        if any(r['state'] not in TERMINAL for r in runs):raise ValueError('Còn lượt tạm dừng hoặc cần khôi phục. Hoàn tất/hủy các lượt đó trước khi xóa toàn bộ lịch sử.')
        if not runs:return
        if not self.confirm_clear_history():return
        self.stop_playback();self.store.delete_history([r['id'] for r in runs])
        if not self.store.run(self.run_id):self.run_id=self.store.draft()
        self.detail_document=None;self.tabs.setTabEnabled(2,False);self.tab_bar.setTabEnabled(2,False);self.refresh_files();self.load_history()

    def confirm_clear_history(self):
        dialog=QMessageBox(self);dialog.setWindowTitle('Xóa toàn bộ lịch sử TTS?')
        dialog.setText('Các bản ghi lịch sử TTS sẽ bị xóa. File audio đã xuất và tài liệu gốc sẽ được giữ nguyên. Thao tác này không thể hoàn tác.')
        dialog.setInformativeText('Áp dụng toàn bộ lịch sử, kể cả ngoài kết quả tìm kiếm.')
        cancel=dialog.addButton('Hủy',QMessageBox.RejectRole);delete=dialog.addButton('Xóa lịch sử',QMessageBox.DestructiveRole)
        delete.setObjectName('danger');delete.setStyleSheet('QPushButton { color: #e45151; }');dialog.setDefaultButton(cancel);dialog.setEscapeButton(cancel)
        dialog.exec();return dialog.clickedButton()==delete

    def play_segment(self,id):
        if self.playing==id and not self.player.player.source().isEmpty():self.stop_playback();return
        self.play_generation+=1;generation=self.play_generation
        item=self.store.segment(id)
        if not item or item['state']!='success':raise ValueError('Audio chưa hoàn tất hoặc cần kiểm tra')
        self.player.stop()  # Stop the old source while the new file is verified.
        doc=self.store.doc(item['document_id']);path=Path(doc['folder'])/item['filename'];expected=item['sha256']
        def check():
            from ..tts.audio import validate
            if validate(path)['sha256']!=expected:raise ValueError('Audio đã bị thay đổi. Kiểm tra hoặc tạo lại trước khi phát.')
            return path
        def play(path):
            if generation!=self.play_generation:return
            self.playing_document=doc['id'];self.history_document=doc['id']
            entries=self.store.rows("SELECT * FROM segments WHERE document_id=? AND state='success' AND skip=0 ORDER BY position",(doc['id'],))
            self.play_lookup={str(Path(doc['folder'])/(i['filename'] or 'missing')):i['id'] for i in entries}
            self.player.play([(str(Path(doc['folder'])/(i['filename'] or 'missing')),i['text']) for i in entries],next(n for n,i in enumerate(entries) if i['id']==id));self.sync_playback()
        self.background(check,play)
    def stop_playback(self):self.play_generation+=1;self.player.stop();self.player.hide();self.sync_playback()
    def sync_playback(self):
        from PySide6.QtMultimedia import QMediaPlayer
        source=self.player.player.source()
        self.playing=self.play_lookup.get(str(Path(source.toLocalFile()))) if not source.isEmpty() and self.player.player.playbackState()!=QMediaPlayer.StoppedState else None
        self.model.playing=self.playing;self.audio_model.playing=self.playing
        self.player.setVisible(bool(self.playing))
        for card in self.history_panel.cards.values():card.update_data(card.doc)
        if self.audio_dialog:
            self.audio_dialog.model.playing=self.playing
            if self.audio_dialog.model.rowCount():self.audio_dialog.model.dataChanged.emit(self.audio_dialog.model.index(0,0),self.audio_dialog.model.index(self.audio_dialog.model.rowCount()-1,7))
        for model in (self.model,self.audio_model):
            if model.rowCount():model.dataChanged.emit(model.index(0,0),model.index(model.rowCount()-1,model.columnCount()-1))
    def open_folder(self,document):
        doc=self.store.doc(document) if document else None
        if not doc or not doc['folder'] or not Path(doc['folder']).is_dir():raise FileNotFoundError('Không tìm thấy thư mục audio')
        QDesktopServices.openUrl(QUrl.fromLocalFile(doc['folder']))

    def report_error(self,exc,stage):
        from .tts_errors import diagnostic
        self.show_notice(friendly(exc));self.error_dialog.present(diagnostic(exc,stage,self.run_id,self.runtime_info))
    def clear_all(self):
        if self.is_busy():raise ValueError('Dừng lượt inference trước khi dọn danh sách')
        if QMessageBox.question(self,'Xóa toàn bộ','Dọn danh sách hiện tại để tạo lượt mới? Lịch sử, model và audio đã tạo được giữ nguyên.')==QMessageBox.Yes:self.new_run()
    def play_document(self,document):
        if self.playing_document==document and (self.playing or not self.player.player.source().isEmpty()):self.stop_playback();return
        row=self.store.one("SELECT id FROM segments WHERE document_id=? AND state='success' AND skip=0 ORDER BY position LIMIT 1",(document,))
        if not row:raise ValueError('Tài liệu chưa có audio hoàn thành')
        self.player.continuous.setChecked(True);self.play_segment(row['id'])

    def new_run(self):
        if self.is_busy():raise ValueError('Dừng tác vụ trước khi tạo lượt mới')
        self.document_model.omitted.clear();self.document_model.checked.clear();self.run_id=str(uuid4());self.store.execute('INSERT INTO runs(id,created) VALUES (?,?)',(self.run_id,time.time()));self.detail_document=None
        # Disabling an active Details tab emits currentChanged synchronously;
        # do not let it switch run_id back to a previous input/bulk checkpoint.
        self.tabs.blockSignals(True);self.tab_bar.blockSignals(True)
        if self.tabs.currentIndex()==2:self.tabs.setCurrentIndex(0)
        self.tabs.setTabEnabled(2,False);self.tab_bar.setTabEnabled(2,False);self.tab_bar.setCurrentIndex(self.tabs.currentIndex());self.tabs.blockSignals(False);self.tab_bar.blockSignals(False);self.split_controls.setEnabled(self.tabs.currentIndex()==1);self.model.replace([])
        if self.tabs.currentIndex()==0:self.bulk_run=self.run_id
        self.refresh_files();self.load_history()
    def require_draft(self):
        if self.store.run(self.run_id)['state']!='draft':raise ValueError('Nhấn Xóa toàn bộ để tạo lượt mới để nhập thêm tài liệu')
        if self.is_busy():raise ValueError('Chờ tác vụ nền kết thúc')
    def pick_files(self):
        paths,_=QFileDialog.getOpenFileNames(self,'Thêm tài liệu','','Văn bản (*.txt *.docx)')
        if paths:self.import_paths(paths)
    def pick_folder(self):
        folder=QFileDialog.getExistingDirectory(self,'Nhập thư mục')
        if folder:self.import_paths([folder])
    def import_paths(self,paths):
        self.require_draft();run=self.run_id;mode='lines'
        def work():
            files,errors=scan(paths);count=0
            for path in files:
                try:count+=bool(self.store.add_document(run,read_document(path),mode))
                except Exception as exc:errors.append((str(path),exc))
            for path in paths:
                if Path(path).is_file() and Path(path).suffix.lower() not in ('.txt','.docx'):errors.append((str(path),'Chỉ hỗ trợ TXT / DOCX'))
            record=self.store.one('SELECT value FROM preferences WHERE name=?',('import_errors:'+run,))
            issues={i['path']:i for i in json.loads(record['value'])} if record else {}
            for path in files:issues.pop(str(Path(path).absolute()),None)
            for path,error in errors:
                if Path(path).suffix.lower() in ('.txt','.docx'):
                    key=str(Path(path).absolute());issues[key]=dict(path=key,error=friendly(error))
            self.store.execute('INSERT OR REPLACE INTO preferences VALUES (?,?)',('import_errors:'+run,json.dumps(list(issues.values()))))
            return count,errors
        def done(result):
            count,errors=result;self.refresh_files();self.load_history();self.show_notice(f'Đã thêm {count} tài liệu.'+('\n'+'\n'.join(f'{Path(p).name}: {e}' for p,e in errors) if errors else ''))
            for path,error in errors:
                if isinstance(error,EncodingChoiceRequired):
                    encoding,ok=QInputDialog.getItem(self,'Xác nhận encoding',Path(path).name,[error.suggestion or 'utf-8','utf-8','utf-16','cp1258'],0,True)
                    if ok:
                        def retry(path=path,encoding=encoding):
                            value=self.store.add_document(run,read_document(path,encoding),mode)
                            record=self.store.one('SELECT value FROM preferences WHERE name=?',('import_errors:'+run,))
                            issues=[i for i in json.loads(record['value']) if i['path']!=str(Path(path).absolute())]
                            self.store.execute('INSERT OR REPLACE INTO preferences VALUES (?,?)',('import_errors:'+run,json.dumps(issues)));return value
                        self.background(retry,lambda _:(self.refresh_files(),self.load_history()))
        self.background(work,done)
    def remove_files(self):
        if self.is_busy():raise ValueError('Dừng tác vụ trước khi xóa file khỏi danh sách')
        ids=set(self.document_model.checked)
        if not ids:return
        if QMessageBox.question(self,'Xóa file đã chọn',f'Bỏ {len(ids)} file khỏi danh sách hiện tại? Giữ nguyên audio và lịch sử đã chạy.')!=QMessageBox.Yes:return
        if self.store.run(self.run_id)['state']=='draft':
            with self.store.transaction():
                for id in ids:self.store.execute('DELETE FROM documents WHERE id=? AND run_id=?',(id,self.run_id))
                record=self.store.one('SELECT value FROM preferences WHERE name=?',('import_errors:'+self.run_id,))
                if record:self.store.execute('UPDATE preferences SET value=? WHERE name=?',(json.dumps([i for i in json.loads(record['value']) if 'import:'+i['path'] not in ids]),'import_errors:'+self.run_id))
        else:self.document_model.omitted.update(ids)
        self.document_model.checked.clear();self.refresh_files();self.load_history()

    def resplit(self):
        if self.store.run(self.run_id)['state']=='draft' and not self.is_busy():self.store.resplit(self.run_id,self.split.currentData());self.refresh_files();self.load_history()
        else:self.show_notice('Cấu trúc lượt đã chạy được giữ nguyên. Chọn Xóa toàn bộ để dùng cách tách khác.')
        self.update_input_counts()

    def input_signature(self):
        # Editor refresh must not spawn nvidia-smi/resource probes per keystroke.
        return (self.input_name.text().strip(),self.input_text.toPlainText(),(self.language.currentData(),self.voice.currentText(),self.speed.value(),self.variant.currentData(),self.format.currentText().lower(),int(self.bitrate.currentText()),self.split.currentData(),self.parallel_width.currentData()))

    def start(self,resume=False):
        repo=getattr(self.store,'automation',None)
        if repo and (repo.active() or repo.tts_owner(self.run_id)):raise ValueError('Kokoro/lượt này thuộc Automation; dùng Dừng an toàn hoặc Tiếp tục trong bộ công việc.')
        if self.is_busy():raise ValueError('Chờ tác vụ hiện tại hoàn tất hoặc dừng an toàn')
        if not self.runtime_ready:self.show_notice('Kokoro chưa sẵn sàng. Mở Cài đặt để kiểm tra runtime và model.');self.open_settings();return
        from ..tts.storage import RECOVERABLE
        is_input=self.tabs.currentIndex()==1 and not resume
        current=self.store.run(self.run_id)
        if is_input:
            from ..tts.output import base_name
            base_name(self.input_name.text().strip())
            if not segments(self.input_text.toPlainText(),self.split.currentData()):raise ValueError('Nhập văn bản có ít nhất một đoạn hợp lệ')
            same=self.run_id==self.input_run and self.input_snapshot==self.input_signature() and current['state'] in RECOVERABLE
            if not same:
                root=QFileDialog.getExistingDirectory(self,'Chọn thư mục xuất audio')
                if not root:return
                self.new_run();config=self.config();text=self.input_text.toPlainText();self.store.add_document(self.run_id,dict(name=self.input_name.text().strip(),text=text,path=None,line_count=len(text.splitlines())),config['split'])
                output=Outputs(self.store);output.confirm(self.run_id,config,output.plan(self.run_id,'custom',root,config['format']));self.input_run=self.run_id;self.input_snapshot=self.input_signature()
        elif current['state']=='cancelled' and not resume:
            docs=self.store.docs(self.run_id);self.new_run()
            for doc in docs:self.store.add_document(self.run_id,dict(name=doc['name'],path=doc['path'],text=doc['text'],line_count=doc['line_count'],locators=json.loads(doc['locators'])),doc['mode'])
        run=self.store.run(self.run_id);docs=self.store.docs(self.run_id);needs_output=not docs or any(not d['folder'] for d in docs);root=None
        saved=json.loads(run['config']);config={**self.config(),**saved} if saved and run['state']!='draft' else self.config();config['device']='Auto'
        is_text=self.tabs.currentIndex()==1 and run['state']=='draft' and not docs
        if is_text and not segments(self.input_text.toPlainText(),config['split']):raise ValueError('Nhập văn bản có ít nhất một đoạn hợp lệ')
        if not is_text and not any(not i['skip'] for i in self.store.items(self.run_id)):raise ValueError('Thêm tài liệu có đoạn hợp lệ trước khi bắt đầu')
        if needs_output:
            mode=self.mode.currentData()
            if mode=='custom' or is_text or any(not d['path'] for d in docs):
                root=QFileDialog.getExistingDirectory(self,'Chọn thư mục xuất audio')
                if not root:return
                mode='custom'
            if is_text:
                if docs:raise ValueError('Chọn Xóa toàn bộ cho văn bản nhập trực tiếp; lượt hiện tại đang có tài liệu')
                text=self.input_text.toPlainText();self.store.add_document(self.run_id,dict(name=self.input_name.text().strip() or 'Văn bản nhập',text=text,path=None,line_count=len(text.splitlines())),config['split'])
            output=Outputs(self.store);plans=output.plan(self.run_id,mode,root,config['format']);output.confirm(self.run_id,config,plans)
        retry=[i['id'] for i in self.store.items(self.run_id) if i['state'] in ('error','unknown')]
        if retry and QMessageBox.question(self,'Tạo lại đoạn lỗi',f'Xác minh audio và tạo lại {len(retry)} đoạn chưa thành công? Audio hợp lệ khác được giữ.')==QMessageBox.Yes:
            self.player.stop();Outputs(self.store).reconcile(self.run_id);retry=[i['id'] for i in self.store.items(self.run_id) if i['state'] in ('error','unknown')]
            if retry:Outputs(self.store).retry(self.run_id,retry)
        self.stop_playback();self.store.execute('UPDATE runs SET config=? WHERE id=?',(json.dumps(config),self.run_id));self.scheduler.start(self.run_id,documents=[i['id'] for i in self.store.docs(self.run_id) if i['id'] not in self.document_model.omitted]);self.refresh_files();self.load_history()
    def pause(self):self.scheduler.pause();self.refresh()
    def stop(self,run=None):
        run=run or (self.scheduler.run_id if self.scheduler.busy else self.run_id)
        if self.scheduler.busy:
            if self.scheduler.run_id!=run:raise ValueError('Chờ tác vụ hiện tại dừng trước khi hủy lượt khác')
            self.scheduler.stop()
        else:self.store.cancel_run(run)
        self.show_notice('Đã hủy lượt. Audio hoàn thành được giữ; tạo lượt mới để chạy lại.');self.refresh_files();self.load_history()
    def retry_ids(self,ids):
        repo=getattr(self.store,'automation',None)
        if repo and any(repo.tts_owner(self.store.doc(self.store.segment(id)['document_id'])['run_id']) for id in ids):raise ValueError('Dùng Tiếp tục trong Automation để giữ checkpoint/mapping.')
        if self.is_busy():raise ValueError('Dừng tác vụ trước khi tạo lại')
        if not ids:return
        if QMessageBox.question(self,'Tạo lại đoạn',f'Tạo lại {len(ids)} đoạn? Chỉ thay audio cũ sau khi bản mới được xác minh.')!=QMessageBox.Yes:return
        run=self.store.doc(self.store.segment(ids[0])['document_id'])['run_id'];self.player.stop();Outputs(self.store).retry(run,ids);self.run_id=run;self.refresh_files();self.start()
    def retry_errors(self):
        if self.detail_document:self.retry_ids([i['id'] for i in self.store.rows("SELECT id FROM segments WHERE document_id=? AND state IN ('error','unknown','pending')",(self.detail_document,))])

    def build_settings(self):
        self.settings_dialog=QDialog(self);self.settings_dialog.setWindowTitle(self.engine_name+' · Model và runtime');outer=QVBoxLayout(self.settings_dialog);scroll=QScrollArea();scroll.setWidgetResizable(True);outer.addWidget(scroll);content=QWidget();layout=QVBoxLayout(content);scroll.setWidget(content)
        self.variant=QComboBox();self.variant.addItem('Tiêu chuẩn · 326 MB + voice','standard');self.variant.addItem('Nhẹ · 92 MB + voice','light');layout.addWidget(self.variant);self.variant.activated.connect(lambda _:self.check_runtime() if not self.is_busy() else None)
        self.device_id=QSpinBox();self.device_id.setRange(-1,7);self.device_id.setValue(-1);self.device_id.setSpecialValueText('Adapter tự động');layout.addWidget(self.device_id)
        self.asset_status=QLabel('Đang kiểm tra…');self.asset_status.setWordWrap(True);self.asset_status.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Minimum);layout.addWidget(self.asset_status);self.asset_progress=QProgressBar();layout.addWidget(self.asset_progress)
        self.setup_button=QPushButton('Tải model');self.setup_button.setToolTip('Tự tải model, giọng đọc và chuẩn bị Kokoro để tạo audio');self.setup_button.clicked.connect(lambda:self.guard(self.install_models));layout.addWidget(self.setup_button)
        rights=Path(sys.executable).parent/'ThirdParty/windows-distribution-rights.md' if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[2]/'docs/windows-distribution-rights.md'
        terms=QLabel('Nhấn Tải model nghĩa là bạn đồng ý với <a href="'+QUrl.fromLocalFile(str(rights)).toString()+'">giấy phép thành phần</a>; tăng tốc NVIDIA tùy chọn áp dụng <a href="https://docs.nvidia.com/cuda/archive/12.9.1/eula/index.html">CUDA</a> và <a href="https://docs.nvidia.com/deeplearning/cudnn/backend/v9.27.0/reference/eula.html">cuDNN</a>.')
        terms.setWordWrap(True);terms.setOpenExternalLinks(True);layout.addWidget(terms)
        for labels in ([('Kiểm tra runtime/model',self.check_runtime)],[('Hủy tải',self.cancel.set),('Gỡ model',self.remove_models)],[('Xem log',self.open_log)]):
            row=QHBoxLayout();layout.addLayout(row)
            for title,callback in labels:self.button(row,title,callback)
        self.runtime_details=QPlainTextEdit();self.runtime_details.setReadOnly(True);layout.addWidget(self.runtime_details,1);note=QLabel('Kokoro v1.0 không hỗ trợ tiếng Việt. Nhấn Tải model để tự tải giọng đọc và chuẩn bị CPU/GPU phù hợp. Không cần cài Python, pip hoặc CUDA thủ công.');note.setWordWrap(True);layout.addWidget(note)
        if self.packs.descriptor:
            row=QHBoxLayout();layout.addLayout(row);self.button(row,'Cài GPU acceleration pack',self.install_gpu_pack)
            if self.packs.descriptor.get('previous'):self.button(row,'Khôi phục GPU pack trước',self.packs.rollback)
        close=QDialogButtonBox(QDialogButtonBox.Close);close.rejected.connect(self.settings_dialog.reject);outer.addWidget(close);self.settings_dialog.resize(650,590)
    def open_settings(self):self.settings_dialog.show();self.settings_dialog.raise_()
    def install_gpu_pack(self):
        if self.is_busy():raise ValueError('Dừng tác vụ trước khi cài GPU pack')
        if not self.packs.descriptor:raise ValueError('Chưa có GPU pack chính thức')
        size=self.packs.descriptor['size']/1024**2
        if QMessageBox.question(self,'GPU acceleration pack',f'Tải {size:.0f} MiB vào dữ liệu ứng dụng? CPU, model và lịch sử được giữ; không cài driver hoặc pip hệ thống.')!=QMessageBox.Yes:return
        config=self.config();self.cancel.clear()
        def probe(runtime):
            from ..tts.pack_engine import PackEngine
            engine=PackEngine(self.manager,config,runtime)
            try:engine.probe(config['voice'],config['speed'],config['language'])
            finally:engine.close()
        def work():
            import httpx
            with httpx.Client(timeout=60,trust_env=False) as client:return self.packs.install(client,self.cancel,probe)
        self.background(work,lambda _:QTimer.singleShot(80,self.check_runtime))
    def check_runtime(self):
        if self.is_busy():return
        variant=self.variant.currentData();self.probing=True;self.runtime_ready=False;self.runtime_label.setText(self.engine_name+' · đang kiểm tra');self.asset_status.setText('Đang kiểm tra dependency và model…')
        def work():
            from ..tts.runtime_manager import RuntimeManager
            from ..tts.setup import prefer_cpu
            data=RuntimeManager(self.manager,packs=self.packs,prefer_cpu=prefer_cpu(self.directory,self.packs)).prepare(variant);self.log.info('Runtime diagnostics %s',json.dumps(data,ensure_ascii=False));return data
        def done(data):
            self.runtime_info=data;self.runtime_ready=bool(data.get('probe_seconds'));self.probing=False
            self.scheduler.prepared_backend=data.get('backend') if self.runtime_ready else None
            status=('Kokoro — Sẵn sàng\nThiết bị: '+('CUDA GPU' if data.get('backend')=='CUDAExecutionProvider' else 'CPU')) if self.runtime_ready else 'Kokoro — Chưa tải'
            self.runtime_label.setText(self.engine_name+' · '+('CUDA GPU' if data.get('backend')=='CUDAExecutionProvider' else 'CPU') if self.runtime_ready else 'Kokoro — Chưa tải');self.asset_status.setText(status+(('\n'+data['fallback_reason']) if data.get('fallback_reason') else ''));self.runtime_details.setPlainText(json.dumps(data,ensure_ascii=False,indent=2));self.setup_button.setEnabled(True);self.refresh()
        self.background(work,done)
    def install_models(self):
        if self.is_busy():raise ValueError('Chờ tác vụ hiện tại kết thúc')
        from ..tts.setup import SetupFlow
        # Probe configuration is read from controls only. Hardware discovery and
        # fingerprints belong to the utility thread, never the click handler.
        config=dict(language=self.language.currentData(),voice=self.voice.currentText(),speed=self.speed.value(),variant=self.variant.currentData(),device_id=self.device_id.value(),workers=1)
        self.cancel.clear();self.setting_up=True;self.runtime_ready=False;self.setup_button.setEnabled(False);self.variant.setEnabled(False);self.device_id.setEnabled(False);self.asset_status.setText('Đang kiểm tra thiết bị')
        def done(data):
            self.setting_up=False;self.runtime_info=data;self.runtime_ready=True;self.scheduler.prepared_backend=data['backend'];self.setup_button.setEnabled(True);self.setup_button.setText('Tải model');self.asset_progress.setRange(0,100);self.asset_progress.setValue(100)
            self.variant.setEnabled(True);self.device_id.setEnabled(True)
            backend='CUDA GPU' if data['backend']=='CUDAExecutionProvider' else 'CPU';self.runtime_label.setText(self.engine_name+' · '+backend);self.asset_status.setText('Kokoro — Sẵn sàng\nThiết bị: '+backend+(('\n'+data['fallback_reason']) if data.get('fallback_reason') else ''));self.runtime_details.setPlainText(json.dumps(data,ensure_ascii=False,indent=2));self.refresh()
        self.background(lambda:SetupFlow(self.directory,self.manager,self.packs,self.log).run(config,self.cancel,lambda a,b,c:self.download_progress.emit(a,b,c)),done)
    def progress(self,done,total,name):
        self.asset_progress.setRange(0,100 if total else 0)
        if total:self.asset_progress.setValue(round(100*done/max(1,total)))
        self.asset_status.setText(name+(f'\nĐã tải: {done/1e6:.1f} MB / {total/1e6:.1f} MB' if total>1 else ''))
    def remove_models(self):
        if self.is_busy():raise ValueError('Dừng tác vụ trước khi gỡ model')
        if QMessageBox.question(self,'Gỡ model','Chỉ gỡ model/voice, giữ audio và lịch sử?')==QMessageBox.Yes:self.background(self.manager.remove,lambda _:QTimer.singleShot(80,self.check_runtime))
    def repair_runtime(self):
        if self.is_busy():raise ValueError('Dừng tác vụ trước khi sửa runtime')
        if getattr(sys,'frozen',False):self.show_notice('Bộ cài thiếu runtime. Dùng Repair/cài lại gói TransComic đầy đủ; không cài pip vào thư mục ứng dụng.');return
        if QMessageBox.question(self,'Sửa runtime dự án','Tạo/cập nhật .venv riêng của dự án và tải dependency đã pin? Không cài vào Python hệ thống. Sau đó mở lại run_transcomic.py.')!=QMessageBox.Yes:return
        script=Path(__file__).resolve().parents[2]/'scripts/setup_tts_runtime.py'
        def work():
            with (self.directory/'Logs'/'runtime-repair.log').open('a',encoding='utf8') as stream:subprocess.run([sys.executable,str(script)],cwd=script.parent.parent,stdout=stream,stderr=subprocess.STDOUT,check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.background(work,lambda _:self.show_notice('Đã chuẩn bị runtime. Đóng ứng dụng rồi mở lại run_transcomic.py.'))
    def open_log(self):QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.directory/'Logs')))

    def refresh_files(self):
        self.document_model.load(self.run_id)
        if self.detail_document:
            doc=self.store.doc(self.detail_document)
            if doc:self.model.load(doc['run_id'],doc['id'])
        self.refresh()
    def refresh(self):
        if not hasattr(self,'start_button'):return
        self.sync_automation_context()
        if any(t.is_alive() for t in self.tasks):
            self.start_button.setEnabled(False)
            return
        run=self.store.run(self.run_id)
        if not run:return
        self.bitrate.setEnabled(self.format.currentText()=='MP3')
        counts=self.store.progress(self.run_id);docs=self.store.docs(self.run_id);total=sum(counts.values());success=counts.get('success',0);state=run['state']
        self.file_totals.setText(f'{len(docs)} tài liệu · {sum(d["line_count"] for d in docs)} dòng nguồn · {total} đoạn hợp lệ · {success} audio thành công · {counts.get("error",0)} lỗi');running=self.scheduler.busy;busy=self.is_busy();self.model.editable=not running
        from ..tts.storage import RECOVERABLE,TERMINAL
        input_mode=self.tabs.currentIndex()==1;continue_input=self.run_id==self.input_run and state in RECOVERABLE and self.input_snapshot==self.input_signature()
        label='Đang hủy' if running and self.scheduler.stop_requested else 'Đang tạm dừng' if running and self.scheduler.pause_requested else 'Đang tạo audio' if running else ('Tiếp tục' if continue_input else 'Bắt đầu') if input_mode else 'Hoàn tất' if state=='completed' else 'Bắt đầu' if state in ('draft','cancelled') else 'Tiếp tục'
        self.start_button.setText(label);valid=bool(segments(self.input_text.toPlainText(),self.split.currentData()) and self.input_name.text().strip()) if input_mode else bool(total)
        self.start_button.setEnabled(valid and not busy and self.runtime_ready and (input_mode or state!='completed'));self.start_button.setToolTip('Kokoro chưa sẵn sàng — mở Cài đặt' if not self.runtime_ready else label)
        repo=getattr(self.store,'automation',None)
        if repo and (repo.active() or repo.tts_owner(self.run_id)):
            self.start_button.setEnabled(False);self.start_button.setToolTip('Automation quản lý Kokoro/lượt này; dùng Dừng an toàn hoặc Tiếp tục trong bộ công việc.')
            self.model.editable=False
        self.pause_button.setEnabled(running and not self.scheduler.stop_requested and not self.scheduler.pause_requested);self.stop_button.setEnabled((running and not self.scheduler.stop_requested) or (not running and state not in TERMINAL and bool(total)))
        self.progress_bar.setValue(round(100*success/max(1,total)));self.progress_bar.setAlignment(Qt.AlignCenter);self.progress_bar.setFormat(f'{success}/{total} · {len(self.scheduler.active)} đang chạy · %p%');self.progress_bar.setToolTip(f'{success}/{total} audio · Đang xử lý: {len(self.scheduler.active)} đoạn')
    def sync_automation_context(self):
        """Keep the saved manual draft, but never present it as Automation's batch."""
        repo=getattr(self.store,'automation',None);active=repo.active() if repo else None
        contextual=bool(active);previous=getattr(self,'automation_context_active',False);self.automation_context_active=contextual
        has_automation=bool(repo and repo.rows('SELECT 1 FROM automation_worksets WHERE started=1 LIMIT 1'))
        self.manual_context_note.setVisible(not contextual and has_automation and self.store.run(self.run_id)['state']=='draft' and bool(self.store.docs(self.run_id)))
        self.automation_context.setVisible(contextual)
        for widget in (self.controls,self.tab_strip,self.tabs,self.action_strip):widget.setVisible(not contextual)
        self.settings_button.setEnabled(not contextual)
        self.history_panel.clear_button.setEnabled(not contextual and not self.is_busy())
        if contextual:
            work=repo.workset(active);self.automation_context_text.setText(f'Bộ công việc: {work["name"]}\nKokoro: 1 luồng · 1 nhóm mỗi lượt\n\nCác job Automation hiển thị trong Lịch sử bên phải, có nhãn Automation. Xem câu và nghe audio tại đó.\n\nBản nháp thủ công được giữ riêng và sẽ hiển thị lại sau khi Automation dừng an toàn hoặc kết thúc. Điều khiển tác vụ tại tab Tự động hóa.')
            self.runtime_label.setText('Kokoro · Automation · 1 luồng')
        elif previous:
            self.runtime_label.setText('Kokoro · bản nháp thủ công');self.runtime_label.setToolTip('Danh sách thủ công được giữ nguyên; các job Automation vẫn nằm trong Lịch sử.')
    def on_event(self,kind,value):
        if getattr(self,'_shutdown',False):
            if kind=='release_player':value.set()
            return
        if kind=='release_player':self.stop_playback();value.set();return
        if kind=='error':
            value.update(onnx_version=self.runtime_info.get('runtimes'),providers=self.runtime_info.get('providers'),executable=self.runtime_info.get('executable'));self.error_dialog.present(value);return
        if kind=='backend':self.runtime_info['backend']=value;self.scheduler.prepared_backend=value;self.runtime_label.setText(self.engine_name+' · '+('CUDA GPU' if value=='CUDAExecutionProvider' else 'CPU'));return
        if kind=='segment':
            self.pending_items.add(value)
            if not self.update_timer.isActive():self.update_timer.start()
            return
        if kind=='notice':self.show_notice(value)
        if kind=='finished':self.refresh_files();self.load_history();QTimer.singleShot(40,self.refresh_when_idle)
        self.refresh()
    def flush_items(self):
        ids,self.pending_items=self.pending_items,set()
        for id in ids:self.model.update_item(id)
        self.document_model.load(self.run_id);self.refresh_history(ids);self.refresh()
    def apply_theme(self):
        from .theme import colors
        c=colors(self);style=f"QTabBar::tab {{border-radius:9px;margin:2px;background:{c['field']};color:{c['ink']};padding:7px 10px;border:1px solid {c['border']};}} QTabBar::tab:selected {{background:{c['accent']};color:{'#30231D' if c['background']=='#1D1815' else '#FFFCF9'};}}"
        self.tabs.setStyleSheet(f"QTabWidget::pane {{border:1px solid {c['border']};border-radius:9px;}} "+style);self.tab_bar.setStyleSheet(style)
        self.history_panel.setStyleSheet(f"QFrame#ttsHistoryCard {{background:{c['field']};border:1px solid {c['border']};border-radius:10px;}}")
        self.player.setStyleSheet(f"QWidget#ttsSharedPlayer {{background:{c['field']};border:1px solid {c['accent']};border-radius:12px;}}")
    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'config_fields'):self.layout_controls()
        if hasattr(self,'history_panel'):self.history_panel.setMinimumWidth(240 if self.width()<900 else 280)
    def eventFilter(self,watched,event):
        if watched==self.workspace and event.type()==QEvent.Resize:
            if hasattr(self,'player'):self.player.setMinimumWidth(min(680,max(280,self.workspace.width()-16)))
            QTimer.singleShot(0,self.layout_controls);return False
        if event.type()==QEvent.DragEnter and event.mimeData().hasUrls():event.acceptProposedAction();return True
        if event.type()==QEvent.Drop and event.mimeData().hasUrls():self.guard(lambda:self.import_paths([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]));event.acceptProposedAction();return True
        return super().eventFilter(watched,event)
    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls():event.acceptProposedAction()
    def dropEvent(self,event):self.guard(lambda:self.import_paths([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]));event.acceptProposedAction()
