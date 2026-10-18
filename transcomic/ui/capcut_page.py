"""One CapCut page, existing media only; all probes/export run off Qt's thread."""
from dataclasses import replace
from pathlib import Path
import threading
from PySide6.QtCore import Qt,Signal,QUrl,QSize
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget,QFileDialog,QDialog,QMessageBox,QMenu,QLineEdit,QAbstractItemDelegate
from .capcut_media import Thumbnails
from .capcut_import import MultiGroupDialog
from ..capcut.media import MediaGroup,scan_group,Cancelled,checkpoint
from ..capcut.state import GroupManager


class CapcutPage(QWidget):
    completed=Signal(int,object,str)
    progress=Signal(int,str)
    scan_progress=Signal(int,int,str)
    def __init__(self,store,owner):
        super().__init__(owner);self.store=store;self.owner=owner;self.manager=GroupManager(store)
        self.scans={};self.selected_group_id=None;self.generation=0;self.worker=None;self.busy=False;self.operation=None;self.cancel=threading.Event();self.closed=False;self.last_output=None
        self.completed.connect(self.on_completed,Qt.QueuedConnection);self.progress.connect(self.on_progress,Qt.QueuedConnection)
        self.scan_progress.connect(self.on_scan_progress,Qt.QueuedConnection)
        from .capcut_cards import build_page
        self.active_details=None;self.player=None;self.scan_failure=''
        self.thumbs=Thumbnails(self);self.preview_cache=Thumbnails(self,QSize(700,190),2)
        build_page(self);self.render_groups();self.set_busy(False)
        # Restored groups are validated in the background, never silently dropped.
        if self.manager.groups:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0,self.scan_all)

    def safe(self,fn):
        try:return fn()
        except Exception as exc:self.status.setText(str(exc));return None

    def is_busy(self):return self.busy
    def set_busy(self,busy):
        for w in (self.add_button,self.scan_button,self.mode,self.project_name,self.output,self.output_browse):w.setEnabled(not busy)
        self.project_name.setEnabled(not busy and self.manager.mode in ('merged','split'))
        self.export_button.setEnabled(not busy and bool(self.manager.groups));self.cancel_button.setEnabled(busy)
        self.clear_button.setEnabled(bool(self.manager.groups) and (not busy or self.operation=='scan'))
        self.update_split_controls()
        self.split_preview.setEnabled(not busy)
        self.render_group_list()
        self.select_group(self.selected_group_id)

    def save_options(self,*_):
        self.manager.mode=self.mode.currentData();self.manager.output=self.output.text().strip();self.manager.name=self.project_name.text().strip() or 'TransComic';self.manager.part_count=self.part_count.value();self.manager.save()
        self.project_name.setEnabled(not self.is_busy() and self.manager.mode in ('merged','split'));self.update_split_controls()

    def update_split_controls(self,*_):
        from ..capcut.planning import project_plan
        count=len(self.manager.groups);split=self.mode.currentData()=='split'
        self.split_controls.setVisible(split);self.part_count.blockSignals(True)
        self.part_count.setMaximum(max(2,count));self.part_count.blockSignals(False)
        self.part_count.setEnabled(split and count>=2 and not self.busy)
        if self.manager.part_count!=self.part_count.value():
            self.manager.part_count=self.part_count.value();self.manager.save()
        parts=project_plan(self.manager.groups,'split',self.project_name.text(),self.part_count.value(),self.manager.custom_names,validate=False) if split and count>=2 else ()
        self.split_model.load(parts);self.split_preview.ensurePolished()
        height=self.split_preview.horizontalHeader().sizeHint().height()+23*max(1,min(2,len(parts)))+2*self.split_preview.frameWidth()
        self.split_preview.setFixedHeight(min(94,height))
        self.update_name_validation()

    def update_name_validation(self):
        split=self.mode.currentData()=='split';count=len(self.manager.groups);errors=self.split_model.errors if split else {}
        message=' · '.join(f'Part {i}: {error}' for i,error in errors.items())
        visible=next((f'Part {i}: {error}' for i,error in errors.items()),'')
        if len(errors)>1:visible+=f' · Còn {len(errors)-1} part cần sửa (xem tooltip).'
        self.split_notice.setText(visible if errors else ('Cần ít nhất 2 nhóm để chia project.' if split and count<2 else 'Nhấp đúp vào tên project để đổi tên · Chuột phải: Dùng tên mặc định'))
        self.split_notice.setToolTip(message or self.split_notice.text());self.split_notice.setMaximumHeight(45)
        self.split_notice.setObjectName('capcutStatus');self.split_notice.setProperty('scanState','review' if errors else 'pending')
        self.split_notice.style().unpolish(self.split_notice);self.split_notice.style().polish(self.split_notice)
        self.export_button.setEnabled(not self.busy and bool(count) and (not split or count>=2) and not errors)
        self.update_totals()

    def part_name_menu(self,position):
        if self.busy:return
        index=self.split_preview.indexAt(position)
        if not index.isValid():return
        menu=QMenu(self);action=menu.addAction('Dùng tên mặc định')
        if menu.exec(self.split_preview.viewport().mapToGlobal(position)) is action:self.reset_part_name(index.row())

    def reset_part_name(self,row):
        if self.busy or not 0<=row<len(self.split_model.parts):return
        def reset():self.manager.set_part_name(row+1,None);self.update_split_controls()
        self.safe(reset)

    def commit_part_editor(self):
        editors=[e for e in self.split_preview.findChildren(QLineEdit) if e.isVisible()]
        if editors:
            editor=editors[0]
            delegate=self.split_preview.itemDelegate();delegate.commitData.emit(editor);delegate.closeEditor.emit(editor,QAbstractItemDelegate.NoHint)

    def choose_output(self):
        folder=QFileDialog.getExistingDirectory(self,'Thư mục project CapCut',self.output.text())
        if folder:self.output.setText(folder);self.save_options()

    def add_group(self):
        if self.is_busy():return
        dialog=MultiGroupDialog(self,self.manager.groups)
        if dialog.exec()==QDialog.Accepted:
            def add():self.manager.add_many(dialog.result_groups);self.render_groups();self.scan_all()
            self.safe(add)

    def edit_group(self,id):
        if self.is_busy():return
        group=next(g for g in self.manager.groups if g.id==id);dialog=MultiGroupDialog(self,self.manager.groups,group)
        if dialog.exec()==QDialog.Accepted:
            def edit():self.manager.replace(dialog.result_groups[0]);self.scans.pop(id,None);self.render_groups();self.scan_all()
            self.safe(edit)

    def remove_group(self,id):
        if self.is_busy():return
        scan=self.scans.get(id)
        if scan:
            paths=[f.path for p in scan.rows for f in p.images+p.audios]
            self.thumbs.forget(paths);self.preview_cache.forget(paths)
        self.stop_audio();self.manager.remove(id);self.scans.pop(id,None);self.render_groups();self.refresh_details()
    def move_group(self,id,delta):
        if self.is_busy():return
        self.manager.move(id,delta);self.render_groups()

    def confirm_clear_all(self):
        dialog=QMessageBox(self);dialog.setObjectName('capcutClearDialog');dialog.setWindowTitle('Xóa toàn bộ nhóm')
        dialog.setIcon(QMessageBox.Warning);dialog.setText(f'Xóa toàn bộ {len(self.manager.groups)} nhóm khỏi danh sách?')
        dialog.setInformativeText('Chỉ xóa các nhóm khỏi workspace TransComic. Không xóa thư mục ảnh, voice, file nguồn, project CapCut đã xuất hoặc bất kỳ file nào trên ổ đĩa.')
        cancel=dialog.addButton('Hủy',QMessageBox.RejectRole);confirm=dialog.addButton('Xóa toàn bộ nhóm',QMessageBox.DestructiveRole)
        dialog.setDefaultButton(cancel);dialog.setEscapeButton(cancel);dialog.exec()
        return dialog.clickedButton() is confirm

    def clear_all(self):
        if self.closed or not self.manager.groups or (self.busy and self.operation!='scan'):return
        if self.confirm_clear_all():self.safe(self.clear_workspace)

    def clear_workspace(self):
        # Recheck after the modal event loop; never invalidate an export snapshot.
        if self.closed or (self.busy and self.operation!='scan'):return
        self.manager.clear()  # Save first: failure leaves the current UI/scan intact.
        self.cancel.set();self.generation+=1;self.stop_audio()
        self.select_group(None);self.group_search.clear()
        for cache in (self.thumbs,self.preview_cache):
            cache.forget([key[0] for key in (*cache.cache,*cache.pending)])
        self.scans.clear();self.active_details=None;self.scan_failure=''
        self.busy=False;self.operation=None;self.render_groups();self.set_busy(False)
        self.bar.setValue(0);self.status.setText('Đã xóa toàn bộ nhóm khỏi workspace · Giữ nguyên ảnh, voice và project đã xuất.')

    def select_group(self,id):
        from .capcut_workspace import select_group
        select_group(self,id)
    def group_current_changed(self,index,*_):
        self.select_group(index.data(Qt.UserRole) if index.isValid() else None)
    def filter_groups(self,text):
        self.groups.selectionModel().blockSignals(True)
        self.group_proxy.setFilterFixedString(text)
        self.groups.selectionModel().blockSignals(False)
        if self.selected_group_id:
            source=next((self.group_model.index(i,0) for i,item in enumerate(self.group_model.items) if item[0].id==self.selected_group_id),None)
            if source is None or not self.group_proxy.mapFromSource(source).isValid():self.select_group(None)
        self.render_group_list(reload=False)
    def render_group_list(self,reload=True):
        from .capcut_workspace import refresh_groups
        refresh_groups(self,reload=reload)
    def show_group(self,id,scroll=True):
        for i,item in enumerate(self.group_model.items):
            if item[0].id==id:
                index=self.group_proxy.mapFromSource(self.group_model.index(i,0))
                if index.isValid():
                    self.groups.setCurrentIndex(index);self.select_group(id)
                    if scroll:self.groups.scrollTo(index)
                else:self.select_group(None)
                return
        self.select_group(None)
    def change_sort(self,id,mode):
        if self.is_busy():return
        group=next(g for g in self.manager.groups if g.id==id)
        self.manager.replace(replace(group,image_sort=mode));self.scan_all()
    def render_groups(self):
        ids={g.id for g in self.manager.groups};self.render_group_list()
        self.export_button.setEnabled(not self.is_busy() and bool(ids))
        self.clear_button.setEnabled(bool(ids) and (not self.busy or self.operation=='scan'))
        self.update_split_controls()
    def update_totals(self):
        groups=self.manager.groups;scans=[self.scans[g.id] for g in groups if g.id in self.scans]
        images=sum(len(p.images) for scan in scans for p in scan.rows);audio=sum(len(p.audios) for scan in scans for p in scan.rows)
        errors=sum(s.error_count or (not s.valid) for s in scans)
        name_issues=self.split_model.errors if self.mode.currentData()=='split' else {}
        errors+=len(name_issues)+bool(self.scan_failure)
        if not groups:state='empty';status='Chưa có nhóm'
        elif self.busy and self.operation=='scan':state='scanning';status='Đang kiểm tra'
        elif self.scan_failure or any(not s.valid for s in scans) or name_issues:state='review';status='Quét thất bại' if self.scan_failure else ('Cần sửa tên project' if name_issues else 'Cần kiểm tra')
        elif self.mode.currentData()=='split' and len(groups)<2:state='pending';status='Cần ít nhất 2 nhóm để chia'
        elif len(scans)==len(groups):state='ready';status='Sẵn sàng'
        else:state='pending';status='Chưa kiểm tra đủ nhóm'
        self.totals.setText(f'{len(groups)} nhóm · {images} ảnh · {audio} voice · {sum(s.matched for s in scans)} cặp hợp lệ · {errors} mục lỗi · {status}')
        self.totals.setToolTip(self.totals.text()+('\n'+self.scan_failure if self.scan_failure else ''))
        self.totals.set_state(state);self.page_header.reflow()
    def repaint_visible_tables(self,*_):self.details.table.viewport().update()
    def refresh_details(self):
        self.stop_audio();self.select_group(self.selected_group_id)
    def play_audio(self,details,pair=None):
        pair=pair if pair is not None else details.selected_pair
        if not pair or len(pair.audios)!=1 or pair.audios[0].error:return
        if not pair.audios[0].unchanged():self.status.setText('Audio đã thay đổi; hãy kiểm tra lại nhóm.');return
        self.stop_audio();self.active_details=details
        details.audio_pair=pair
        if not self.player:
            from .capcut_preview import CapcutPlayer
            self.player=CapcutPlayer(self,compact=True);self.player.error.connect(self.status.setText)
            self.player.player.playbackStateChanged.connect(self.details.sync_audio)
            self.player.error.connect(self.details.audio_error)
            self.player.closed.connect(self.details.sync_audio)
        self.player.hide();self.player.play([(pair.audios[0].path,'Voice có sẵn')]);details.sync_audio()
    def stop_audio(self):
        if self.player:
            self.player.stop();self.player.hide()
            self.player.entries=[];self.player.index=-1
            # A deleted/collapsed card must never own the one shared player.
            if self.active_details:self.active_details.player_layout.removeWidget(self.player)
            self.player.setParent(self)
        self.active_details=None
        if hasattr(self,'details'):self.details.audio_pair=None;self.details.sync_audio()
    def hideEvent(self,event):
        self.stop_audio();super().hideEvent(event)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'settings_toggle') and not self.settings_manual:
            self.settings_toggle.setChecked(self.height()<760)

    def launch(self,fn,*,operation='export'):
        if self.is_busy():return
        self.busy=True;self.operation=operation
        self.generation+=1;generation=self.generation;self.cancel=threading.Event();cancel=self.cancel;self.set_busy(True);self.bar.setValue(0)
        def work():
            try:result=fn(cancel);error=''
            except Cancelled as exc:result=None;error=str(exc) or 'Đã hủy an toàn'
            except Exception as exc:result=None;error=str(exc) or type(exc).__name__
            try:self.completed.emit(generation,result,error)
            except RuntimeError:pass
        self.worker=threading.Thread(target=work,daemon=True,name='capcut-work')
        threads=[t for t in getattr(self.owner,'background_threads',[]) if t.is_alive()];threads.append(self.worker);self.owner.background_threads=threads;self.worker.start()
    def scan_all(self):
        if self.is_busy() or not self.manager.groups:return
        self.scan_failure=''
        self.scans.clear();self.render_groups();self.refresh_details()
        groups=tuple(self.manager.groups);generation=self.generation+1
        def scan(cancel):
            result=[]
            for i,group in enumerate(groups):
                checkpoint(cancel);self.scan_progress.emit(generation,int(i*100/len(groups)),'Kiểm tra '+group.name);result.append(scan_group(group,cancel))
            return ('scan',tuple(result))
        self.launch(scan,operation='scan')
    def export_projects(self):
        if self.is_busy():return
        self.safe(self.start_export)
    def start_export(self):
        self.commit_part_editor();self.part_count.interpretText();self.save_options()
        if not self.manager.output:raise ValueError('Chọn thư mục đầu ra')
        scans=tuple(self.scans[g.id] for g in self.manager.groups if g.id in self.scans)
        if len(scans)!=len(self.manager.groups):raise ValueError('Kiểm tra tất cả nhóm trước khi xuất')
        from ..capcut.media import freeze
        freeze(scans)
        output=self.manager.output;name=self.manager.name;mode=self.manager.mode;part_count=self.part_count.value();custom_names=dict(self.manager.custom_names)
        if mode=='split':
            from ..capcut.planning import project_plan
            project_plan(scans,mode,name,part_count,custom_names)
        self.last_output=Path(output)
        def export(cancel):
            from ..capcut.exporter import export_projects
            return ('export',export_projects(scans,output,mode=mode,name=name,part_count=part_count,custom_names=custom_names,cancel=cancel,progress=lambda n,msg:self.progress.emit(n,msg)))
        self.launch(export)
    def on_progress(self,value,text):
        if not self.closed:self.bar.setValue(value);self.status.setText(text)
    def on_scan_progress(self,generation,value,text):
        if generation==self.generation:self.on_progress(value,text)
    def on_completed(self,generation,result,error):
        if self.closed or generation!=self.generation:return
        operation=self.operation;self.busy=False;self.operation=None
        if operation=='scan':self.scan_failure=error
        self.set_busy(False)
        if error:self.status.setText(error);return
        if result[0]=='scan':
            self.scans={s.group.id:s for s in result[1]};self.render_groups();self.refresh_details();self.status.setText('Đã kiểm tra · '+str(sum(s.error_count for s in self.scans.values()))+' mục lỗi. Rê chuột vào thống kê nhóm để xem lỗi thư mục/số thứ tự.')
        else:
            from ..capcut.exporter import reference
            self.last_output=Path(result[1][0]).parent;self.status.setText('Đã xuất '+str(len(result[1]))+' project · '+reference(self.last_output))
        self.bar.setValue(100)
    def request_stop(self):self.cancel.set();self.stop_audio()
    def open_output(self):
        path=self.last_output or (Path(self.output.text()) if self.output.text() else None)
        if path and path.is_dir():
            from ..capcut.exporter import reference
            QDesktopServices.openUrl(QUrl.fromLocalFile(reference(path)))
    def shutdown(self):self.closed=True;self.request_stop();self.thumbs.shutdown();self.preview_cache.shutdown()
