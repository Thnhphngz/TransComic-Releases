"""Local credential safety, independent of provider dispatch algorithms."""
import json


def ensure_idle(store, provider):
    """Called inside the storage transaction, again after any modal UI confirmation."""
    active = ('running','paused','pausing','stopping','user_paused','waiting_rate_limit',
              'retry_scheduled','network_waiting','provider_recovering')
    marks = ','.join('?' for _ in active)
    if store.db.execute(f'SELECT 1 FROM jobs WHERE provider=? AND state IN ({marks}) LIMIT 1', (provider,*active)).fetchone():
        raise ValueError('Provider đang có lượt dịch hoạt động; Dừng an toàn hoàn tất trước khi sửa/xóa key.')
    if store.db.execute("SELECT 1 FROM batches b JOIN jobs j ON j.id=b.job_id WHERE j.provider=? AND b.state='inflight' LIMIT 1", (provider,)).fetchone():
        raise ValueError('Request đang xử lý; chờ Dừng an toàn hoàn tất trước khi sửa/xóa key.')
    repo = getattr(store, 'automation', None)
    if repo and repo.active() and repo.workset(repo.active())['config']['provider'] == provider:
        raise ValueError('Tự động hóa đang sử dụng provider này; Dừng an toàn trước khi sửa/xóa key.')


def saved_state(store, provider):
    """Count ciphertext rows; successful DPAPI is never server verification."""
    if provider == 'deepseek':
        rows = store.db.execute("SELECT encrypted FROM secrets WHERE key='deepseek'").fetchall()
    else:
        table = {'kira':'kira_keys', 'gemini':'gemini_keys'}[provider]
        rows = store.db.execute('SELECT encrypted FROM '+table+' ORDER BY rowid').fetchall()
    return tuple(bytes(r[0]) for r in rows)


def describe(blobs):
    if not blobs: return 'Chưa lưu key'
    from .security import unprotect_key
    unreadable = 0
    for blob in blobs:
        try:
            if not unprotect_key(blob).strip(): unreadable += 1
        except Exception: unreadable += 1
    if unreadable: return f'Đã lưu · {unreadable} key không thể giải mã/đọc'
    return 'Đã lưu · đọc được DPAPI · chưa xác minh API cho key đã lưu'
