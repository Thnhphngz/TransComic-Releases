"""Windows publisher identity verification; default commands unconditionally locked."""
import json
import re
from urllib.parse import urlsplit
from ..release_adapters import commands_or_default, execute, safe_path
from .metadata import UpdateError


class AuthenticodeAdapter:
    def __init__(self,signtool,powershell,thumbprint,subject,commands=None):
        if not re.fullmatch('[0-9A-Fa-f]{40}',thumbprint or '') or not subject:raise UpdateError('AUTHENTICODE_CERTIFICATE_NOT_READY')
        self.signtool=safe_path(signtool);self.powershell=safe_path(powershell)
        self.thumbprint=thumbprint.upper();self.subject=subject;self.commands=commands_or_default(commands)

    def sign(self,path,timestamp_url='https://timestamp.digicert.com'):
        path=safe_path(path);url=urlsplit(timestamp_url)
        if url.scheme!='https' or url.hostname not in ('timestamp.digicert.com',) or url.username or url.password or url.query or url.fragment or url.port not in (None,443):raise UpdateError('TRUSTED_TIMESTAMP_SERVICE_REQUIRED')
        execute(self.commands,[str(self.signtool),'sign','/sha1',self.thumbprint,'/fd','SHA256','/tr',timestamp_url,'/td','SHA256',str(path)],path.parent,120)
        return self.verify(path)

    def verify(self,path):
        path=safe_path(path)
        execute(self.commands,[str(self.signtool),'verify','/pa','/all',str(path)],path.parent,120)
        literal="'"+str(path).replace("'","''")+"'"
        script="$s=Get-AuthenticodeSignature -LiteralPath "+literal+"; [pscustomobject]@{status=$s.Status.ToString(); thumbprint=$s.SignerCertificate.Thumbprint; subject=$s.SignerCertificate.Subject; timestamped=($null -ne $s.TimeStamperCertificate)} | ConvertTo-Json -Compress"
        raw=execute(self.commands,[str(self.powershell),'-NoProfile','-NonInteractive','-Command',script],path.parent,30)
        try:proof=json.loads(raw)
        except ValueError:raise UpdateError('AUTHENTICODE_PROOF_INVALID') from None
        if proof.get('status')!='Valid' or proof.get('thumbprint','').upper()!=self.thumbprint or proof.get('subject')!=self.subject or proof.get('timestamped') is not True:raise UpdateError('AUTHENTICODE_SIGNER_OR_TIMESTAMP_MISMATCH')
        return True
