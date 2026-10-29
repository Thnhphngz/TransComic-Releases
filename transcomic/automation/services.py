"""Application-owned service instances, shared with their existing views."""
from pathlib import Path
from .adapters import Translation,Kokoro,Capcut


class Services:
    def __init__(self,repo):
        from ..tts.storage import TtsStore
        from ..tts.models import ModelManager
        from ..tts.setup import RuntimeRegistry
        from ..tts.acceleration import AccelerationPacks,packaged_descriptor
        root=repo.store.path.parent/'TTS';self.repo=repo
        self.tts_store=TtsStore(root/'tts.sqlite3');self.tts_store.automation=repo;self.manager=ModelManager(root/'Models')
        repo.tts_store=self.tts_store
        descriptor=packaged_descriptor();legacy=AccelerationPacks(root/'AccelerationPacks',descriptor,previous=descriptor.get('previous',[]) if descriptor else ())
        self.packs=RuntimeRegistry(root/'Runtimes',legacy)
        self.translation=Translation(repo);self.kokoro=Kokoro(repo,self.tts_store,self.manager,self.packs);self.capcut=Capcut(repo,self.tts_store)
    def preflight(self,config):
        self.preflight_translation(config);self.preflight_kokoro(config)
    def preflight_section(self,section,config):
        # Preserve the existing injectable preflight seam used by offline fixtures.
        if 'preflight' in self.__dict__:return self.preflight(config)
        if section=='translation':self.preflight_translation(config)
        elif section=='kokoro':self.preflight_kokoro(config)
    def validation_identity(self,section,config):
        if section!='translation':return None
        if config['provider']=='deepseek':
            from ..deepseek import key_identity
            return dict(provider='deepseek', credential=key_identity(self.repo.store))
        keys=self.repo.store.kira_keys() if config['provider']=='kira' else self.repo.store.gemini_keys()
        accounts=[(row['id'],self.repo.store.kira_account_scope(row['id']),self.repo.store.setting('kira_account_confirmed:'+row['id'],'')) for row in keys] if config['provider']=='kira' else []
        return dict(keys=[{k:row.get(k) for k in ('id','enabled','status','project')} for row in keys],accounts=accounts,
                    limits=[self.repo.store.setting('gemini_'+k,'') for k in ('concurrency','rpm','tpm','rpd')]+[self.repo.store.setting('kira_account_limit','')])
    def preflight_translation(self,config):
        store=self.repo.store
        if config['provider']=='deepseek':
            from ..deepseek import read_key
            from ..deepseek_models import validate_model
            validate_model(config['model'])
            if not read_key(store):raise ValueError('Chưa có key DeepSeek; mở trang API để cấu hình')
            if not 1<=config['workers']<=30:raise ValueError('DeepSeek hỗ trợ 1–30 worker')
        elif config['provider']=='kira':
            from ..models import KIRA_MODELS
            if config['model'] not in {id for label,id in KIRA_MODELS}:raise ValueError('Model Kira không nằm trong danh sách hiện có; chọn lại model.')
            if not any(k['enabled'] and k['status'] not in ('INVALID','DISABLED','PERMISSION_DENIED','QUOTA_EXHAUSTED','MODEL_UNAVAILABLE','CREDENTIAL_ERROR') for k in store.kira_keys()):raise ValueError('Kira chưa có key bật/khả dụng; mở Quản lý API.')
        else:
            from ..gemini import model_name
            model_name(config['model'])
            if not any(k['status'] not in ('invalid','disabled','exhausted','authentication','permission','quota_exhausted','model_not_found') for k in store.gemini_keys()):raise ValueError('Gemini chưa có key khả dụng; mở Quản lý API.')
            if config['workers']>int(store.setting('gemini_concurrency','1')):raise ValueError('Luồng vượt giới hạn Gemini đã cấu hình trong Quản lý API.')
        import shutil
        if shutil.disk_usage(store.path.parent).free<16*1024*1024:raise ValueError('Không đủ dung lượng lưu checkpoint SQLite.')
    def preflight_kokoro(self,config):
        if not self.manager.ready(config['variant']):raise ValueError('Kokoro model/voice chưa sẵn sàng; mở Cài đặt TTS.')
        # Runtime registry verifies installed manifests without synthesis/download.
        from .adapters import runtime_for
        runtime=runtime_for(self.packs,config)
        if runtime is None:
            from ..tts.engine import language_available,providers
            if not language_available(config['tts_language']) or not providers():raise ValueError('Kokoro runtime chưa sẵn sàng; dùng thiết lập TTS hiện có.')
    def close(self):
        self.tts_store.close()
        from ..tts.runtime import logger
        log=logger(self.tts_store.path.parent/'Logs')
        for handler in list(log.handlers):handler.close();log.removeHandler(handler)
