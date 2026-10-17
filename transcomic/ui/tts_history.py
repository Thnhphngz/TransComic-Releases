"""Full-height searchable summary cards; no tables or players inside cards."""
import json
import threading
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import Qt,QTimer,Signal
from PySide6.QtWidgets import QWidget,QScrollArea,QVBoxLayout,QHBoxLayout,QLabel,QFrame,QMenu,QLineEdit,QSizePolicy
from .glass import GlassButton
from .tts_models import STATES
from ..tts.storage import RECOVERABLE,TERMINAL


class HistoryCard(QFrame):
    def __init__(self,panel,doc):
        super().__init__();self.panel=panel;self.page=panel.page;self.id=doc['id'];self.setObjectName('ttsHistoryCard');self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed)
        self.column=QVBoxLayout(self);self.column.setContentsMargins(10,9,10,9);self.column.setSpacing(5)
        row=QHBoxLayout();self.column.addLayout(row);self.name=QLabel();self.name.setWordWrap(True);row.addWidget(self.name,1)
        menu=GlassButton('⋯');menu.setMaximumWidth(36);menu.clicked.connect(self.menu);row.addWidget(menu)
        self.meta=QLabel();self.meta.setWordWrap(True);self.column.addWidget(self.meta)
        row=QHBoxLayout();self.column.addLayout(row);self.sentences=GlassButton('Xem câu');self.sentences.clicked.connect(lambda:self.page.guard(lambda:self.page.open_sentences(self.id)));row.addWidget(self.sentences)
        self.listen=GlassButton('Nghe');self.listen.clicked.connect(lambda:self.page.guard(lambda:self.page.play_document(self.id)));row.addWidget(self.listen);row.addStretch();self.update_data(doc)
    def update_data(self,doc):
        self.doc=doc;config=json.loads(doc['config']);date=datetime.fromtimestamp(doc['created']).strftime('%d/%m %H:%M');self.name.setText(doc['name']);self.name.setStyleSheet('font-weight:600;')
        backend=(doc.get('backend') or 'Chưa chạy').replace('ExecutionProvider','');self.meta.setText(f'{date} · {config.get("voice","Chưa chọn giọng")} · {config.get("speed",1)}x\n{doc["success"] or 0}/{doc["total"]} audio · {STATES.get(doc["run_state"],doc["run_state"])}\n{backend} · {config.get("format","wav").upper()}')
        self.meta.setToolTip(f'{doc.get("folder") or "Chưa tạo thư mục"}\n{doc["duration"] or 0:.1f}s')
        single_input=not doc['path'] and (config.get('split')=='none' or doc['total']<=1)
        self.single_input=single_input;missing=self.id in self.panel.missing
        if missing:self.meta.setText(self.meta.text()+' · Thiếu file')
        self.sentences.setVisible(not single_input);self.listen.setVisible(single_input and bool(doc['success']));self.listen.setEnabled(not missing);self.listen.setToolTip('Audio bị thiếu — khôi phục file hoặc Liên kết lại' if missing else 'Nghe audio đã tạo');self.listen.setText('Dừng' if self.page.playing and self.page.playing_document==self.id else 'Nghe')
    def menu(self):self.popup_menu=self.context_menu();self.popup_menu.popup(self.mapToGlobal(self.rect().topRight()))
    def context_menu(self):
        page=self.page;page.history_document=self.id;menu=QMenu(self)
        def add(title,callback,enabled=True):
            action=menu.addAction(title);action.setEnabled(enabled);action.triggered.connect(lambda:page.guard(callback))
        exists=bool(self.doc['folder'] and Path(self.doc['folder']).is_dir());add('Mở thư mục',lambda:page.open_folder(self.id),exists)
        if not exists:menu.addAction('Chưa có thư mục' if not self.doc['folder'] else 'Thư mục thiếu — dùng Liên kết lại').setEnabled(False)
        add('Liên kết lại',page.relink,not page.is_busy());add('Chi tiết',lambda:page.open_details(self.id))
        active=page.scheduler.busy and page.scheduler.run_id==self.doc['run_id'];state=self.doc['run_state']
        if state in RECOVERABLE:add('Tiếp tục lượt',page.resume_history,not page.is_busy())
        add('Tạm dừng lượt',page.pause,active);add('Dừng / Hủy lượt',lambda:page.stop(self.doc['run_id']),state not in TERMINAL and (not page.scheduler.busy or active))
        menu.addSeparator();add('Xóa bản ghi (giữ audio)',page.delete_history,not page.is_busy() and state in TERMINAL);return menu


class HistoryPanel(QWidget):
    presence_ready=Signal(object)
    def __init__(self,page):
        super().__init__();self.page=page;self.setMinimumWidth(270);self.cards={};self.limit=20;self.missing=set();self.checking=False
        layout=QVBoxLayout(self);layout.setContentsMargins(7,0,0,0);layout.setSpacing(7)
        row=QHBoxLayout();layout.addLayout(row);heading=QLabel('LỊCH SỬ');heading.setObjectName('section');row.addWidget(heading,1)
        self.clear_button=GlassButton('Xóa lịch sử');self.clear_button.setToolTip('Xóa toàn bộ lịch sử TTS');self.clear_button.clicked.connect(lambda:self.page.guard(self.page.clear_history));row.addWidget(self.clear_button)
        self.search=QLineEdit();self.search.setPlaceholderText('Tìm lịch sử TTS...');layout.addWidget(self.search)
        self.filter_timer=QTimer(self);self.filter_timer.setSingleShot(True);self.filter_timer.setInterval(150);self.filter_timer.timeout.connect(self.filter_changed);self.search.textChanged.connect(lambda _:self.filter_timer.start())
        self.scroll=QScrollArea();self.scroll.setWidgetResizable(True);self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff);layout.addWidget(self.scroll,1)
        self.content=QWidget();self.column=QVBoxLayout(self.content);self.column.setContentsMargins(0,0,3,0);self.column.setSpacing(7);self.scroll.setWidget(self.content)
        self.empty=QLabel('Chưa có lịch sử TTS');self.empty.setWordWrap(True);self.column.addWidget(self.empty)
        self.more=GlassButton('Xem thêm');self.more.clicked.connect(self.load_more);self.column.addWidget(self.more);self.column.addStretch()
        self.presence_ready.connect(self.on_presence);self.presence_timer=QTimer(self);self.presence_timer.setInterval(1500);self.presence_timer.timeout.connect(self.check_presence);self.presence_timer.start()
    def check_presence(self):
        if not self.isVisible() or self.checking:return
        paths=[]
        for id,card in self.cards.items():
            if not card.single_input or not card.doc['success']:continue
            item=self.page.store.one("SELECT filename FROM segments WHERE document_id=? AND state='success' ORDER BY position LIMIT 1",(id,))
            if item and item['filename'] and card.doc['folder']:paths.append((id,card.doc['folder'],str(Path(card.doc['folder'])/item['filename'])))
        if not paths:return
        self.checking=True
        def check():
            values=[]
            for id,folder,path in paths:
                try:missing=not Path(path).is_file()
                except OSError:missing=True
                values.append((id,folder,missing))
            try:self.presence_ready.emit(values)
            except RuntimeError:pass
        threading.Thread(target=check,daemon=True,name='tts-history-presence').start()
    def on_presence(self,values):
        self.checking=False
        for id,folder,missing in values:
            card=self.cards.get(id)
            if not card or card.doc['folder']!=folder:continue
            if missing:self.missing.add(id)
            else:self.missing.discard(id)
            card.update_data(card.doc)
    def filter_changed(self):self.limit=20;self.refresh()
    def load_more(self):self.limit+=20;self.refresh()
    def refresh(self,changed=None):
        changed=changed if changed is None else tuple(changed)
        if changed is not None:
            affected={item['document_id'] for id in changed if (item:=self.page.store.segment(id))}
            if not affected:return
            selected='SELECT d.id FROM documents d JOIN runs r ON r.id=d.run_id WHERE r.history_accepted=1 AND d.id IN ('+','.join('?' for _ in affected)+')';arguments=tuple(affected)
        else:
            query=self.search.text().strip().replace('\\','\\\\').replace('%','\\%').replace('_','\\_');term='%'+query+'%'
            selected="SELECT d.id FROM documents d JOIN runs r ON r.id=d.run_id WHERE r.history_accepted=1 AND (d.name LIKE ? ESCAPE '\\' OR json_extract(r.config,'$.voice') LIKE ? ESCAPE '\\') ORDER BY r.created DESC,d.position LIMIT ?";arguments=(term,term,self.limit+1)
        rows=self.page.store.rows("WITH selected AS ("+selected+") SELECT d.id,d.run_id,d.name,d.path,d.folder,d.position,r.config,r.created,r.state run_state,COUNT(s.id) total,SUM(s.state='success') success,SUM(CASE WHEN s.state='success' THEN s.duration ELSE 0 END) duration,GROUP_CONCAT(DISTINCT s.backend) backend FROM selected q JOIN documents d ON d.id=q.id JOIN runs r ON r.id=d.run_id LEFT JOIN segments s ON s.document_id=d.id AND s.skip=0 GROUP BY d.id ORDER BY r.created DESC,d.position",arguments)
        if changed is not None:
            for doc in rows:
                if doc['id'] in self.cards:self.cards[doc['id']].update_data(doc)
            return
        wanted={d['id'] for d in rows[:self.limit]}
        for id in list(self.cards):
            if id not in wanted:card=self.cards.pop(id);self.column.removeWidget(card);card.deleteLater()
        for n,doc in enumerate(rows[:self.limit]):
            card=self.cards.get(doc['id'])
            if not card:card=HistoryCard(self,doc);self.cards[doc['id']]=card
            else:card.update_data(doc)
            self.column.insertWidget(n,card)
        self.empty.setVisible(not rows);self.empty.setText('Không tìm thấy lịch sử phù hợp' if self.search.text() else 'Chưa có lịch sử TTS');self.more.setVisible(len(rows)>self.limit)
