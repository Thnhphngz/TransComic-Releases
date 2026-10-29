"""One completion/intervention notification per scheduler session."""
from PySide6.QtWidgets import QSystemTrayIcon, QApplication
from ..documents import translatable
from ..status import usable


def notify_scheduler(window,payload=None):
    updates=getattr(window,'translation_updates',None)
    if updates and updates.context()['kind']=='automation':return
    scheduler = window.scheduler
    if not scheduler or not scheduler.job_id: return
    if scheduler._thread and scheduler._thread.is_alive():return
    updates=getattr(window,'translation_updates',None)
    if payload is None and updates and updates.last:
        candidates=updates.last['jobs']
        if set(scheduler.job_ids or [scheduler.job_id])<={j['id'] for j in candidates.values()}:payload=updates.last
    cached=payload
    jobs=list(cached['jobs'].values()) if cached is not None else [window.store.job(j) for j in scheduler.job_ids or [scheduler.job_id]]
    intervention = any(j['state'] in ('quota_exhausted', 'needs_intervention') for j in jobs)
    finished = all(j['state'] == 'finished' for j in jobs)
    if not (intervention or finished): return
    reason = 'intervention' if intervention else 'finished'
    emitted = getattr(scheduler, '_notifications', set())
    if reason in emitted: return
    emitted.add(reason); scheduler._notifications = emitted
    if cached is not None:
        stats=cached['statuses'];missing=sum(s['missing'] for s in stats.values());affected=sum(s['missing']>0 for s in stats.values());done=sum(s['done'] for s in stats.values())
        source_count=len({d['source_instance'] for d in cached['documents'].values()})
    else:
        rows_by_file = {j['document_id']: [r for r in window.store.lines(j['document_id']) if translatable(r['source'])] for j in jobs}
        missing = sum(not usable(r) for rows in rows_by_file.values() for r in rows)
        affected = sum(any(not usable(r) for r in rows) for rows in rows_by_file.values())
        done = sum(usable(r) for rows in rows_by_file.values() for r in rows)
        source_count = len({window.store.document(d)['source_instance'] for d in rows_by_file})
    if intervention:
        title = 'TransComic — Cần xử lý hạn mức API'
        message = ', '.join(dict.fromkeys(j['provider']+' / '+j['model'] for j in jobs if j['state'] in ('quota_exhausted', 'needs_intervention'))) + ' · xem Console để kiểm tra lý do và giới hạn chờ'
    elif missing:
        title = f'TransComic — Đã xử lý xong, còn {missing} dòng lỗi'
        message = f'{affected} tài liệu bị ảnh hưởng · dùng bộ lọc lỗi hoặc Dịch lại lỗi để kiểm tra'
    else:
        title = 'TransComic — Dịch hoàn tất'
        message = f'{source_count} tài liệu · {len(set(j["target_lang"] for j in jobs))} ngôn ngữ · {done} dòng thành công'
    window.notice.setText(title+' · '+message)
    window.statusBar().showMessage(title+' · '+message, 0)
    if QSystemTrayIcon.isSystemTrayAvailable():
        if window.tray is None: window.tray = QSystemTrayIcon(window.windowIcon(), window)
        window.tray.show()
        window.tray.showMessage(title, message, QSystemTrayIcon.Warning if intervention or missing else QSystemTrayIcon.Information, 10000)
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION if intervention or missing else winsound.MB_OK)
    except (ImportError, RuntimeError):
        QApplication.beep()
    window.store.log.emit('notification', reason=reason, job_id=scheduler.job_id, missing_lines=missing, affected_files=affected)
