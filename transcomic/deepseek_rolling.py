"""Versioned Automation DeepSeek admission; no HTTP or completion decisions."""
from collections import deque


ROLLING={'version':1,'mode':'rolling'}
COHORT={'version':1,'mode':'cohort_9_of_10'}


def admission_policy(value=None):
    # Pre-policy Automation snapshots used CohortAdmission. Absence never opts in.
    if value is None:return dict(COHORT)
    if value not in (ROLLING,COHORT):raise ValueError('Unsupported DeepSeek admission policy')
    return dict(value)


def validate_checkpoint(order,state,policy):
    if state is None:return
    if (state.get('version')!=1 or tuple(state.get('order',()))!=tuple(order)
            or admission_policy(state.get('admission_policy'))!=policy):
        raise ValueError('DeepSeek admission checkpoint/policy mismatch; preserve existing lineage')
    values={key:set(state.get(key,())) for key in ('opened','active','parked','complete')}
    if (any(not v<=set(order) for v in values.values())
            or values['active']&values['parked']
            or values['active']|values['parked']!=values['opened']-values['complete']
            or len(values['active'])>10 or len(values['parked'])>10
            or len(values['opened']-values['complete'])>20):
        raise ValueError('Invalid DeepSeek admission checkpoint; preserve existing lineage')


class RollingAdmission:
    version=1
    capacity=10
    park_limit=10
    unfinished_limit=20

    def __init__(self,order,state=None,emit=lambda *args:None):
        self.order=tuple(dict.fromkeys(order));self.position={v:i for i,v in enumerate(self.order)}
        self.opened=set(state.get('opened',())) if state else set()
        self.active=set(state.get('active',())) if state else set()
        self.parked=set(state.get('parked',())) if state else set()
        # Saved completion is only a diff baseline. refresh() must receive fresh
        # certification before dispatch, including revisions changed while stopped.
        self.complete=set(state.get('complete',())) if state else set()
        self.emit=emit;self.rr=deque();self.burst=0;self.largest={}

    def ordered(self,values):return sorted(values,key=self.position.__getitem__)

    def refresh(self,complete,ready,inflight,*,can_expand=True):
        complete=set(complete)&self.position.keys();ready=set(ready);inflight=set(inflight)
        revoked=self.complete-complete
        # Re-admit invalidated certificates in source order through the same
        # bounded window; never strand a previously complete source outside it.
        self.opened-=revoked;self.active-=revoked;self.parked-=revoked
        for source in self.ordered(complete-self.complete):self.emit('source_completed',source)
        self.complete=complete;self.active-=complete;self.parked-=complete
        # Older due retries get their slots back before any fresh file is opened.
        for source in self.ordered(self.parked&ready):
            if len(self.active)>=self.capacity:
                victims=[v for v in self.active-inflight if self.position[v]>self.position[source]]
                if not victims:break
                victim=max(victims,key=self.position.__getitem__)
                self.active.remove(victim);self.parked.remove(source);self.parked.add(victim)
                self.emit('source_parked',victim)
            else:self.parked.remove(source)
            self.active.add(source);self.emit('source_restored',source)
        # Preserve the bounded cooldown escape hatch; never evict an HTTP lease.
        if can_expand and not self.active&ready and not inflight:
            for source in self.ordered(self.active-ready-inflight):
                if len(self.parked)>=self.park_limit:break
                self.active.remove(source);self.parked.add(source);self.emit('source_parked',source)
        for source in self.order:
            if source in self.opened or source in complete:continue
            if len(self.active)>=self.capacity or len(self.opened-complete)>=self.unfinished_limit:break
            self.opened.add(source);self.active.add(source);self.emit('source_admitted',source)
        assert len(self.active)<=10 and len(self.parked)<=10 and len(self.opened-complete)<=20
        return self.ordered(self.active)

    def choose(self,ready,remaining):
        ready=set(ready)&self.active
        if not ready:return None
        self.rr=deque(v for v in self.rr if v in self.active)
        for v in self.ordered(self.active-set(self.rr)):self.rr.append(v)
        for v,n in remaining.items():self.largest[v]=max(self.largest.get(v,0),n)
        if self.burst<2:
            self.burst+=1
            return min(ready,key=lambda v:(self.position[v]//10,remaining.get(v,0)/max(1,self.largest.get(v,1)),self.position[v]))
        self.burst=0
        for _ in range(len(self.rr)):
            source=self.rr[0];self.rr.rotate(-1)
            if source in ready:return source

    def snapshot(self):
        return dict(version=1,admission_policy=dict(ROLLING),order=list(self.order),opened=self.ordered(self.opened),
                    active=self.ordered(self.active),parked=self.ordered(self.parked),complete=self.ordered(self.complete))
