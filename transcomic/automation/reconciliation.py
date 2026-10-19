"""Rebuild stage labels from owned, current artifacts at lifecycle boundaries."""
from pathlib import Path
import json
from .repository import file_hash, fingerprint
from .validation import speakable, plan_parts
from ..documents import translatable
from ..status import usable


class Reconciliation:
    def audio_ready(self, group):
        from ..tts.documents import segments
        meta=group['data'];run=meta.get('tts_run');tts=self.services.tts_store
        if not run:return False
        try:
            rows=[self.repo.store.line(i) for i in meta['slots']]
            docs=tts.docs(run);items=tts.items(run)
            cfg=self.repo.workset(group['workset_id'])['config']
            if json.loads(tts.run(run)['config'])!=self.services.kokoro.config(cfg):return False
            if not rows or not docs or len(items)!=len(rows):return False
            from ..tts.output import Outputs
            folder,manifest=Outputs(tts).manifest(docs[0])
            for row,item in zip(rows,items):
                text=row['translation'] if row['translation'] is not None else row['source']
                record=manifest['segments'].get(item['id'],{})
                if translatable(row['source']) and not usable(row):return False
                if not speakable(text) or segments(text,'none')[0]['text']!=item['text'] or item['state']!='success':return False
                path=folder/item['filename']
                if not item['sha256'] or record.get('sha256')!=item['sha256'] or not path.is_file() or file_hash(path)!=item['sha256']:return False
            return True
        except (OSError,ValueError,KeyError,IndexError,TypeError):return False

    def reconcile_stages(self, id):
        """Never called from paint/refresh; callers hold no active stage workers."""
        from .adapters import project_hash
        from ..line_structure import validate_snapshot
        groups=self.repo.groups(id);cfg=self.repo.workset(id)['config'];pending=self.pending_retry_groups(id)
        states={};ready=set();completed=set()
        for group in groups:
            rows=self.repo.store.units(group['document_id']);meta=group['data']
            if group['id'] in pending:state='waiting'
            elif meta.get('error') and meta['state'] in ('needs_attention','stale'):state='needs_attention'
            elif any(not usable(r) for r in rows if translatable(r['source'])):
                state='needs_attention' if any(r['state'] in ('error','unknown','wrong_target_language') for r in rows) else 'waiting'
            elif validate_snapshot(self.repo.store.document(group['document_id']),rows).structural:state='needs_attention'
            elif self.audio_ready(group):state='waiting_capcut';ready.add(group['id'])
            else:state='waiting_tts'
            states[group['id']]=state
        try:
            artifacts=self.repo.artifacts(id)
            for part in plan_parts([dict(g,path=self.repo.store.document(g['document_id'])['path']) for g in groups],cfg):
                ids=[g['id'] for g in part.groups]
                if not set(ids)<=ready:continue
                unit=fingerprint(ids);payload=dict(id=unit,name=part.name,group_ids=ids,groups=part.groups)
                try:
                    scans=self.services.capcut.scans(part.groups);fp=self.services.capcut.fingerprint(scans,payload,cfg)
                    match=next((a for a in reversed(artifacts) if a['kind']=='capcut' and a['unit']==unit and a['state']=='complete' and a['fingerprint']==fp and Path(a['path']).is_dir() and project_hash(Path(a['path']))==a['sha256']),None)
                    if match:
                        for gid in ids:states[gid]='completed';completed.add(gid)
                except (OSError,ValueError,KeyError):pass
        except ValueError:pass
        for group in groups:self.repo.update_group(group['id'],state=states[group['id']])
        return ready,completed
