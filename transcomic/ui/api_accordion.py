"""Three persistent, mutually exclusive API sections; hidden bodies keep drafts."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QSizePolicy
from .glass import GlassButton
from .theme import colors,DARK
from ..api_credentials import saved_state,describe,ensure_idle


class ApiSection(QWidget):
    def __init__(self, provider, body, toggle):
        super().__init__()
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(5)
        self.header=GlassButton();self.header.setCheckable(True)
        self.header.setMinimumHeight(56);self.header.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed)
        row=QHBoxLayout(self.header);row.setContentsMargins(16,8,16,8)
        name=QLabel(provider.upper());self.name=name
        self.summary=QLabel();self.summary.setStyleSheet('background: transparent;')
        self.arrow=QLabel();self.arrow.setStyleSheet('font-size: 18px; background: transparent;')
        for label in (name,self.summary,self.arrow):label.setAttribute(Qt.WA_TransparentForMouseEvents)
        row.addWidget(name);row.addStretch(1);row.addWidget(self.summary);row.addSpacing(10);row.addWidget(self.arrow)
        self.header.clicked.connect(lambda:toggle(provider));layout.addWidget(self.header)
        self.body=body;layout.addWidget(body);self.set_open(False)

    def set_open(self, opened):
        self.header.setChecked(opened);self.body.setVisible(opened);self.arrow.setText('▾' if opened else '▸')
        self.update_header_colors()

    def update_header_colors(self):
        palette=colors(self)
        ink=('#30231D' if palette is DARK else '#FFFCF9') if self.header.isChecked() else palette['ink']
        self.name.setStyleSheet(f'font-size:18px;font-weight:700;background:transparent;color:{ink};')
        self.summary.setStyleSheet(f'background:transparent;color:{ink};')
        self.arrow.setStyleSheet(f'font-size:18px;background:transparent;color:{ink};')


class ApiAccordionMixin:
    def build_api_accordion(self):
        layout=self.pages.widget(2).layout()
        bodies={'kira':self.kira_api_panel,'deepseek':self.deepseek_api_panel,'gemini':self.gemini_api_panel}
        for body in bodies.values():layout.removeWidget(body)
        self.api_sections={};self._api_key_signatures={};self._api_key_proofs={}
        for index,(provider,body) in enumerate(bodies.items(),1):
            section=ApiSection(provider,body,self.toggle_api_section)
            self.api_sections[provider]=section;layout.insertWidget(index,section)
        saved=self.store.setting('api_open_provider',self.provider_id())
        if saved not in bodies:saved=''
        self.open_api_section(saved,save=False);self.refresh_api_headers()

    def open_api_section(self, provider, *, save=True):
        self._api_open_provider=provider
        for name,section in self.api_sections.items():section.set_open(name==provider)
        if save:self.store.set_setting('api_open_provider',provider)

    def toggle_api_section(self, provider):
        self.open_api_section('' if self._api_open_provider==provider else provider)

    def refresh_api_headers(self):
        if not hasattr(self,'api_sections'):return
        for provider,section in self.api_sections.items():
            blobs=saved_state(self.store,provider)
            evidence=self.credential_evidence(provider,blobs)
            if self._api_key_signatures.get(provider)!=blobs or self._api_key_proofs.get(provider)!=evidence:
                self._api_key_signatures[provider]=blobs
                self._api_key_proofs[provider]=evidence
                state=describe(blobs)
                if evidence and 'không thể' not in state:
                    state=f'Đã lưu · {len(evidence)}/{len(blobs)} key có bằng chứng API thành công · quota/quyền hiện tại có thể thay đổi'
                count=f'{len(blobs)}/1 key đã lưu' if provider=='deepseek' else f'Đã lưu {len(blobs)} key'
                section.summary.setText(count);section.header.setToolTip(state)
                section.header.setAccessibleName(provider.upper()+' · '+count)
                if provider=='kira':self.key_status.setText(state)
                elif provider=='deepseek':self.deepseek_status.setText(state)
                else:self.gemini_credential_status.setText(state)
        present=bool(self._api_key_signatures.get('deepseek'))
        self.deepseek_save_button.setText('Thay key đã lưu' if present else 'Lưu key')
        self.deepseek_delete_button.setEnabled(present)

    def credential_evidence(self, provider, blobs):
        evidence=set()
        if provider=='gemini':
            evidence={bytes(r[0]) for r in self.store.db.execute("SELECT encrypted FROM gemini_keys WHERE status='available'")}
        for scheduler in self.credential_schedulers():
            adapter=getattr(scheduler,'provider',None)
            if provider=='kira' and getattr(adapter,'multi_key',False):
                evidence.update(bytes(row['encrypted']) for key,row in list(adapter.keys.items()) if adapter.stats.get(key,{}).get('successful_requests',0)>0)
            elif provider=='deepseek' and getattr(scheduler,'success_requests',0)>0:
                import hashlib
                if len(blobs)==1 and getattr(adapter,'stored_identity',None)==hashlib.sha256(blobs[0]).hexdigest():evidence.add(blobs[0])
        return frozenset(evidence.intersection(blobs))

    def credential_idle(self, provider):
        if provider=='gemini' and getattr(self,'metadata_busy',False):
            raise ValueError('Đang kiểm tra metadata Gemini; chờ thao tác hoàn tất trước khi xóa key.')
        for scheduler in self.credential_schedulers():
            thread=getattr(scheduler,'_thread',None)
            if thread and thread.is_alive():
                jobs=getattr(scheduler,'job_ids',[]) or [getattr(scheduler,'job_id',None)]
                if any(j and self.store.job(j)['provider']==provider for j in jobs):
                    raise ValueError('Lượt dịch đang hoạt động; Dừng an toàn hoàn tất trước khi sửa/xóa key.')
        ensure_idle(self.store,provider)

    def credential_schedulers(self):
        result=[]
        services=getattr(self,'automation_services',None)
        for scheduler in (getattr(self,'scheduler',None),getattr(getattr(services,'translation',None),'scheduler',None)):
            if scheduler:
                result.append(scheduler);result.extend(getattr(scheduler,'children',[]))
        return result

    def clear_credential_caches(self, provider, key_id=None, old_blobs=()):
        """Drop references from stopped adapters; durable jobs and metrics survive."""
        from ..security import unprotect_key
        secrets=[]
        for blob in old_blobs:
            try:secrets.append(unprotect_key(blob))
            except Exception:pass
        adapters=[]
        for scheduler in self.credential_schedulers():
            adapters.append(getattr(scheduler,'provider',None))
            adapters.extend(getattr(scheduler,'adapters',{}).values())
        from ..deepseek import DeepSeekProvider
        from ..gemini import GeminiProvider
        for adapter in adapters:
            if provider=='deepseek' and isinstance(adapter,DeepSeekProvider):adapter.api_key=''
            elif provider=='gemini' and isinstance(adapter,GeminiProvider):
                adapter.pool.keys[:]=[k for k in adapter.pool.keys if k['id']!=key_id]
                if adapter.api_key in secrets:adapter.api_key=''
            elif provider=='kira' and getattr(adapter,'multi_key',False):
                row=adapter.keys.pop(key_id,None)
                if row and row.get('adapter'):row['adapter'].api_key=''
            elif provider=='kira' and adapter and type(adapter).__name__=='KiraProvider' and adapter.api_key in secrets:
                adapter.api_key=''
        for secret in secrets:self.store.log.retire_secret(secret)
        if provider=='deepseek':self.deepseek_key_input.clear()
        elif provider=='kira':self.api_key_input.clear()
        else:self.gemini_key_input.clear()
