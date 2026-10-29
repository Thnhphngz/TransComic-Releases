"""Versioned 9/10 source admission, independent of HTTP leases and TTS."""
from collections import deque
import math


class CohortAdmission:
    version=1
    capacity=10
    park_limit=10
    unfinished_limit=20

    def __init__(self,order,state=None,emit=lambda *args:None):
        self.order=tuple(dict.fromkeys(order));self.position={v:i for i,v in enumerate(self.order)}
        self.cohorts=[self.order[i:i+10] for i in range(0,len(self.order),10)]
        valid=state and state.get('version')==1 and tuple(state.get('order',()))==self.order
        self.opened=set(state.get('opened',()))&self.position.keys() if valid else set()
        self.active=set(state.get('active',()))&self.opened if valid else set()
        self.parked=self.opened-self.active;self.complete=set();self.frontier=0
        self.emit=emit;self.rr=deque();self.burst=0;self.largest={}

    def ordered(self,values):return sorted(values,key=self.position.__getitem__)

    def refresh(self,complete,ready,inflight,*,can_expand=True):
        complete=set(complete)&self.position.keys();ready=set(ready);inflight=set(inflight)
        for source in self.ordered(complete-self.complete):self.emit('source_completed',source)
        self.complete=complete;self.active-=complete;self.parked-=complete
        while self.frontier<len(self.cohorts)-1:
            cohort=self.cohorts[self.frontier]
            if len(set(cohort)&complete)<math.ceil(len(cohort)*.9):break
            self.frontier+=1;self.emit('cohort_unlocked',str(self.frontier))
        for source in self.ordered(self.parked&ready):
            if len(self.active)>=self.capacity:
                victims=[v for v in self.active-inflight if self.position[v]>self.position[source]]
                if not victims:break
                victim=max(victims,key=self.position.__getitem__);self.active.remove(victim);self.parked.remove(source);self.parked.add(victim)
                self.emit('source_parked',victim)
            else:self.parked.remove(source)
            self.active.add(source);self.emit('source_restored',source)
        stalled=can_expand and not self.active&ready and not inflight
        if stalled:
            for source in self.ordered(self.active-ready-inflight):
                if len(self.parked)>=self.park_limit:break
                self.active.remove(source);self.parked.add(source);self.emit('source_parked',source)
        for source in self.order:
            if source in self.opened or source in complete:continue
            if len(self.active)>=self.capacity or len(self.opened-complete)>=self.unfinished_limit:break
            if self.position[source]//10>self.frontier and not stalled:break
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
            v=self.rr[0];self.rr.rotate(-1)
            if v in ready:return v

    def snapshot(self):
        return dict(version=1,order=list(self.order),frontier=self.frontier,opened=self.ordered(self.opened),
                    active=self.ordered(self.active),parked=self.ordered(self.parked),complete=self.ordered(self.complete))
