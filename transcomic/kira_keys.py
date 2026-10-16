"""DPAPI-only key storage; no networking or translation data access."""
import hashlib
import hmac
import secrets
import uuid

STATES = {'READY', 'COOLDOWN', 'QUOTA_EXHAUSTED', 'INVALID', 'DISABLED', 'UNKNOWN_ERROR'}


class KiraKeysMixin:
    def kira_account_scope(self, key_id):
        # Unknown ownership remains shared. A key ID is an opaque, stable group ID,
        # not a credential or an assertion learned from the provider.
        return self.setting('kira_account:' + key_id, 'shared')

    def set_kira_account_scope(self, key_id, scope):
        with self.transaction():
            ids = {r['id'] for r in self.db.execute('SELECT id FROM kira_keys')}
            scopes = {self.kira_account_scope(k) for k in ids}
            if key_id not in ids or scope not in ids | scopes | {'shared'}:
                raise ValueError('Invalid Kira account group')
            self.set_setting('kira_account:' + key_id, scope)

    def migrate_kira_key(self):
        # Copy ciphertext without decrypting: recovery is one atomic/idempotent transaction.
        with self.transaction():
            if self.setting('kira_keys_migrated', ''): return
            old = self.db.execute("SELECT encrypted FROM secrets WHERE key='kira'").fetchone()
            if old:
                self.db.execute("INSERT OR IGNORE INTO kira_keys(id,name,encrypted) VALUES ('legacy-kira','Kira 1',?)", (old['encrypted'],))
            self.db.execute("INSERT INTO settings VALUES ('kira_keys_migrated','1')")

    def kira_keys(self, decrypt=False):
        from .security import unprotect_key
        with self.lock:
            rows = self.db.execute('SELECT * FROM kira_keys ORDER BY rowid').fetchall()
            result = []
            for row in rows:
                item = dict(row); blob = item.pop('encrypted'); item.pop('fingerprint')
                if not item['enabled']:item['status']='DISABLED'
                if decrypt and item['enabled']:
                    item['secret'] = unprotect_key(blob)
                    self.log.register_secret(item['secret'])
                result.append(item)
            return result

    def add_kira_keys(self, text, name=''):
        from .security import protect_key, unprotect_key
        # Encrypt everything before inserting; any DPAPI failure leaves the batch intact.
        keys = list(dict.fromkeys(text.split()))
        if not keys: return 0, 0
        encrypted = [(key, protect_key(key)) for key in keys]
        with self.transaction():
            salt_row = self.db.execute("SELECT encrypted FROM secrets WHERE key='kira-fingerprint-salt'").fetchone()
            if salt_row: salt = bytes.fromhex(unprotect_key(salt_row[0]))
            else:
                salt = secrets.token_bytes(32)
                self.db.execute("INSERT INTO secrets VALUES ('kira-fingerprint-salt',?)", (protect_key(salt.hex()),))
            def digest(key): return hmac.new(salt, key.encode(), hashlib.sha256).hexdigest()
            # Imported legacy ciphertext is fingerprinted lazily, never lost on DPAPI failure.
            for row in self.db.execute('SELECT id,encrypted FROM kira_keys WHERE fingerprint IS NULL').fetchall():
                self.db.execute('UPDATE kira_keys SET fingerprint=? WHERE id=?', (digest(unprotect_key(row['encrypted'])), row['id']))
            added = duplicates = 0
            protected_names=[unprotect_key(row[0]) for row in self.db.execute('SELECT encrypted FROM kira_keys').fetchall()]+keys
            for key, blob in encrypted:
                fingerprint = digest(key)
                self.log.register_secret(key)
                if self.db.execute('SELECT 1 FROM kira_keys WHERE fingerprint=?', (fingerprint,)).fetchone():
                    duplicates += 1; continue
                alias = name.strip() if name.strip() else f'Kira {len(self.kira_keys())+1}'
                if any(secret in alias for secret in protected_names) or len(alias) > 80: raise ValueError('Tên key không hợp lệ')
                self.db.execute('INSERT INTO kira_keys(id,name,encrypted,fingerprint) VALUES (?,?,?,?)',
                                (str(uuid.uuid4()), alias, blob, fingerprint))
                added += 1
            return added, duplicates

    def change_kira_key(self, key_id, *, name=None, enabled=None, delete=False, restore=False):
        with self.transaction():
            if not self.db.execute('SELECT 1 FROM kira_keys WHERE id=?', (key_id,)).fetchone(): raise ValueError('Key không còn tồn tại')
            if delete:
                self.db.execute('DELETE FROM kira_keys WHERE id=?', (key_id,))
                if key_id=='legacy-kira':self.db.execute("DELETE FROM secrets WHERE key='kira'")
                return
            if name is not None:
                if not name.strip() or len(name) > 80: raise ValueError('Tên key không hợp lệ')
                # Never allow a pasted secret to become an unencrypted display label.
                from .security import unprotect_key
                blobs = self.db.execute('SELECT encrypted FROM kira_keys').fetchall()
                if any(unprotect_key(r[0]) in name for r in blobs): raise ValueError('Tên key không được chứa API key')
                self.db.execute('UPDATE kira_keys SET name=? WHERE id=?', (name.strip(),key_id))
            if enabled is not None:
                self.db.execute("UPDATE kira_keys SET enabled=?,status=CASE WHEN status='DISABLED' THEN 'READY' ELSE status END WHERE id=?", (int(enabled),key_id))
            if restore:
                self.db.execute("UPDATE kira_keys SET status=CASE WHEN enabled=1 THEN 'READY' ELSE 'DISABLED' END,cooldown_until=0 WHERE id=?", (key_id,))

    def kira_key_status(self, key_id, state, until=0):
        if state not in STATES: raise ValueError('Invalid key state')
        with self.transaction():
            self.db.execute("UPDATE kira_keys SET status=?,cooldown_until=? WHERE id=?", (state,until,key_id))
