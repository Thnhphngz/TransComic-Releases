"""One release orchestrator for the future production adapters and B2.1 fakes.

The production run entry is unconditionally locked before journal reservation.
"""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
from .release import version_outputs
from .release_adapters import locked,BuildAdapter,PackageAdapter,Asset,inventory
from .release_journal import ReleaseState
from .release_provenance import build_identity,public_provenance
from .update.keytools import production_sign_encrypted
from .update.metadata import MANIFEST_NAME,canonical,release_url,asset_url,candidate,UpdateError
from .version import APP_ID,VERSION


class ProductionReleaseOperations:
    def __init__(self,builder,iscc,publisher,key_directory,password_callback,authenticode,source,tool_versions,policy='signed-stable'):
        self.builder=builder;self.iscc=iscc;self.publisher=publisher;self.key_directory=key_directory
        self.password_callback=password_callback;self.authenticode=authenticode;self.source=source;self.tool_versions=tool_versions
        if policy not in ('signed-stable','internal') or getattr(publisher,'policy',policy)!=policy:raise UpdateError('RELEASE_POLICY_MISMATCH')
        self.policy=policy

    def perform(self,phase,record):
        if phase==ReleaseState.PRECHECK:self.source.require_clean()
        elif phase==ReleaseState.TESTED:self.builder.test()
        elif phase==ReleaseState.BUILT:
            executable=self.builder.build(record['version'],self.source)
            if self.policy=='signed-stable':
                if self.authenticode is None:raise UpdateError('AUTHENTICODE_CERTIFICATE_NOT_READY')
                self.authenticode.sign(executable)
                self.authenticode.sign(executable.parent/'TransComic-UpdateHelper.exe')
            record['build_stage']=str(self.builder.stage);record['built_executable']=str(executable)
            record['version_overlay']=self.builder.build_provenance
        elif phase==ReleaseState.PACKAGED:
            self.package=PackageAdapter(self.iscc,self.builder.stage,self.builder.output/'installer')
            self.installer=self.package.package(record['version'])
            record['packaged_installer']=str(self.installer)
        elif phase==ReleaseState.SIGNED:
            if self.policy=='signed-stable':
                if self.authenticode is None:raise UpdateError('AUTHENTICODE_CERTIFICATE_NOT_READY')
                self.authenticode.sign(self.installer)  # hash AFTER Authenticode changes executable bytes
            asset=Asset.inspect(version_outputs(record['version'])['installer'],self.installer,self.builder.output)
            internal=build_identity(self.source,record['version'],self.tool_versions,asset.sha256)
            internal.update(self.builder.build_provenance)
            internal['build_id']=hashlib.sha256(canonical({k:v for k,v in internal.items() if k!='build_id'})).hexdigest()
            public=public_provenance(internal)
            record['build_id']=public['build_id'];record['internal_provenance']=internal
            payload={'app_id':APP_ID,'version':record['version'],'channel':'stable','os':'windows','architecture':'x64',
                     'installer_filename':asset.name,'installer_size':asset.size,'sha256':asset.sha256,'release_tag':'v'+record['version'],
                     'release_url':release_url('v'+record['version']),'minimum_updater_version':VERSION,'minimum_windows':'10',
                     'metadata_format':2,'signed_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'provenance':public}
            if self.policy=='internal':
                from .update.internal import manifest
                envelope=manifest(record['version'],asset.name,asset.size,asset.sha256,payload['signed_at'],public)
            else:envelope=production_sign_encrypted(self.key_directory,self.password_callback(),payload)
            directory=self.installer.parent;manifest=directory/MANIFEST_NAME
            with manifest.open('xb') as stream:stream.write(canonical(envelope))
            signed=Asset.inspect(MANIFEST_NAME,manifest,directory)
            checksum=directory/'SHA256SUMS.txt'
            with checksum.open('xb') as stream:stream.write((asset.sha256+'  '+asset.name+'\n'+signed.sha256+'  '+MANIFEST_NAME+'\n').encode())
            self.assets=[asset,signed,Asset.inspect(checksum.name,checksum,directory)];inventory(record['version'],self.assets)
            record['asset_inventory']={a.name:{'size':a.size,'sha256':a.sha256,'path':str(a.path)} for a in self.assets}
            record['public_provenance']=public
        elif phase==ReleaseState.DRAFT_CREATED:
            self.remote=self.publisher.read(record['version'])
            if self.remote is None:
                if self.policy=='internal':self.publisher.prepare_internal_tag(record['version'],record['distribution_commit'])
                self.remote=self.publisher.draft(record['version'],record['distribution_commit'],record['public_provenance'])
            elif self.remote.get('draft') is not True:raise UpdateError('EXISTING_RELEASE_REQUIRES_RECONCILIATION')
            else:
                try:notes=json.loads(self.remote.get('body','{}'))
                except ValueError:raise UpdateError('REMOTE_PROVENANCE_INVALID') from None
                if notes.get('build_id')!=record['build_id']:raise UpdateError('CONFLICTING_DRAFT_IDENTITY')
        elif phase==ReleaseState.ASSETS_UPLOADED:self.publisher.upload(record['version'],self.remote,self.assets)
        elif phase==ReleaseState.REMOTE_VERIFIED:
            self.remote=self.publisher.read(record['version']);self.publisher.verify(record['version'],self.remote,self.assets)

    def publish(self,record):return self.publisher.publish(record['version'],self.assets)

    def restore(self,record):
        from .release_adapters import safe_path
        if record.get('build_stage'):
            self.builder.stage=safe_path(record['build_stage'],self.builder.output)
            self.builder.build_provenance=record['version_overlay']
        if record.get('packaged_installer'):self.installer=safe_path(record['packaged_installer'],self.builder.output)
        if record.get('asset_inventory'):
            self.assets=[Asset.inspect(n,d['path'],self.builder.output) for n,d in record['asset_inventory'].items()]
            if any({'size':a.size,'sha256':a.sha256} != {'size':record['asset_inventory'][a.name]['size'],'sha256':record['asset_inventory'][a.name]['sha256']} for a in self.assets):raise UpdateError('RESUME_ARTIFACT_CHANGED')
        if record['last_completed'] in (ReleaseState.DRAFT_CREATED,ReleaseState.ASSETS_UPLOADED,ReleaseState.REMOTE_VERIFIED):
            self.remote=self.publisher.read(record['version'])
            if self.remote is None or not self.remote.get('draft'):raise UpdateError('DRAFT_RESUME_REQUIRES_RECONCILIATION')
            try:notes=json.loads(self.remote.get('body','{}'))
            except ValueError:raise UpdateError('REMOTE_PROVENANCE_INVALID') from None
            if notes.get('build_id')!=record['build_id']:raise UpdateError('REMOTE_BUILD_IDENTITY_MISMATCH')

    def reconcile(self,record):
        remote=self.publisher.read(record['version'])
        if remote is None:return None
        if not hasattr(self,'assets'):
            self.assets=[Asset.inspect(n,d['path'],self.builder.output) for n,d in record['asset_inventory'].items()]
        self.publisher.verify(record['version'],remote,self.assets,published=remote.get('draft') is False)
        body=json.loads(remote.get('body','{}'))
        if body.get('build_id')!=record['build_id']:raise UpdateError('REMOTE_BUILD_IDENTITY_MISMATCH')
        return {'tag':remote['tag_name'],'build_id':body['build_id'],'assets_verified':True,
                'published':remote['draft'] is False,'draft':remote['draft'] is True}


class FakeReleaseOperations:
    def __init__(self):self.calls=[];self.fail=None;self.remote=None;self.unknown_publish=False
    def perform(self,phase,record):
        self.calls.append(phase)
        if self.fail==phase:raise UpdateError('MOCK_PHASE_FAILURE')
        if phase==ReleaseState.DRAFT_CREATED:self.remote={'tag':'v'+record['version'],'build_id':record['build_id'],'draft':True,'published':False,'assets_verified':False}
        if phase==ReleaseState.REMOTE_VERIFIED:self.remote['assets_verified']=True
    def publish(self,record):
        self.calls.append('publish')
        if self.fail=='publish':raise UpdateError('COMMAND_TIMEOUT_OUTCOME_UNKNOWN')
        self.remote.update(draft=False,published=True)
        if self.unknown_publish:raise UpdateError('COMMAND_TIMEOUT_OUTCOME_UNKNOWN')
        return self.remote
    def reconcile(self,record):
        self.calls.append('reconcile')
        if self.fail=='reconcile':raise UpdateError('REMOTE_UNKNOWN')
        return self.remote
    def restore(self,record):self.calls.append('restore_readonly')


class ReleaseCoordinator:
    def __init__(self,journal):self.journal=journal
    def run(self,operations,*args,**kwargs):
        locked()
        return self._execute(operations,*args,**kwargs)
    def simulate(self,operations,*args,**kwargs):
        if type(operations) is not FakeReleaseOperations:raise UpdateError('Concrete fake release operations required')
        return self._execute(operations,*args,**kwargs)
    def _execute(self,operations,current=VERSION,choice='patch',build_id='mock-build',distribution_commit=None):
        with self.journal.exclusive():
            record=self.journal.load()
            policy=getattr(operations,'policy','signed-stable')
            if record and record.get('distribution_policy',policy)!=policy:raise UpdateError('RELEASE_STATE_UNCERTAIN: policy changed during reservation')
            if record and record['state']!=ReleaseState.PUBLISHED and record.get('origin_id',record['build_id'])!=build_id:raise UpdateError('RELEASE_STATE_UNCERTAIN: PENDING_SOURCE_IDENTITY_CHANGED')
            if record and record['state'] in (ReleaseState.UNKNOWN_REMOTE_OUTCOME,ReleaseState.PUBLISHED,ReleaseState.FAILED) and record['last_completed'] in (ReleaseState.REMOTE_VERIFIED,ReleaseState.PUBLISHED):
                evidence=operations.reconcile(record)
                confirmed=self.journal.reconcile(record,evidence)
                if confirmed['state']==ReleaseState.PUBLISHED and confirmed.get('origin_id')!=build_id:
                    record=self.journal.next_release(confirmed,evidence,build_id,choice)
                else:return confirmed
            if record:operations.restore(record)
            record=self.journal.reserve(current,choice,build_id)
            record['distribution_policy']=policy
            if distribution_commit:record['distribution_commit']=distribution_commit
            try:
                phases=[ReleaseState.PRECHECK,ReleaseState.TESTED,ReleaseState.BUILT,ReleaseState.PACKAGED,ReleaseState.SIGNED,
                        ReleaseState.DRAFT_CREATED,ReleaseState.ASSETS_UPLOADED,ReleaseState.REMOTE_VERIFIED]
                # Resume fake phases idempotently; real adapter recovery requires preserved artifact inventory.
                last=record['last_completed']
                start=phases.index(last)+1 if last in phases else 0
                for phase in phases[start:]:
                    operations.perform(phase,record);record=self.journal.checkpoint(record,phase)
                # Persist uncertainty BEFORE the network write. Crash before request is reconciled, never blind publish.
                record=self.journal.checkpoint(record,ReleaseState.UNKNOWN_REMOTE_OUTCOME)
                operations.publish(record)
                evidence=operations.reconcile(record)
                return self.journal.reconcile(record,evidence)
            except Exception as exc:
                if record['state']!=ReleaseState.UNKNOWN_REMOTE_OUTCOME:
                    record=self.journal.checkpoint(record,ReleaseState.UNKNOWN_REMOTE_OUTCOME if 'OUTCOME_UNKNOWN' in str(exc) else ReleaseState.FAILED)
                raise
