"""Explicit signing interface. Production remains unavailable in B1."""
import base64
from dataclasses import dataclass
from .metadata import canonical, verify_signature, UpdateError


def sign_payload(payload, key_id, private_key):
    """Caller owns the key; tests use memory-only ephemeral keys."""
    return {'payload': payload, 'signature': {
        'algorithm': 'ed25519', 'key_id': key_id,
        'value': base64.b64encode(private_key.sign(canonical(payload))).decode('ascii')}}


@dataclass(frozen=True)
class TrustPolicy:
    pinned: dict
    revoked: frozenset = frozenset()

    def verify(self, envelope):
        key_id = envelope.get('signature', {}).get('key_id')
        if key_id in self.revoked:
            raise UpdateError('Signing key revoked')
        if verify_signature(envelope['payload'], envelope['signature'], self.pinned) != 'VERIFIED_ED25519':
            raise UpdateError('Signing key not pinned')
        return True


def production_sign(*args, **kwargs):
    raise UpdateError('STAGE_A_LOCKED: production signing needs reviewed B2 activation')
