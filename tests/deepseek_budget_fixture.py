"""Synthetic test-only prepaid ledger/transport; no campaign data or live keys."""
import hashlib,json,os,sqlite3,threading,time
from pathlib import Path
from decimal import Decimal
from datetime import datetime,timezone
import httpx
from transcomic.deepseek_models import MODEL_NAMES
from transcomic.deepseek_batch import validate_size
from transcomic.deepseek_pricing import load,period,estimate
AUTHORIZATION='synthetic-budget-fixture'
FX_SOURCE='synthetic-fixture'
FX_CHECKED='synthetic-fixture'
FX_QUOTED=Decimal('26030')
FX_RESERVE=Decimal('30000')
SAFETY=Decimal('1.15')
OUT=Path('.')

def save(path,data):
    path.write_text(json.dumps(data),encoding='utf8')

def unconfigured(request):
    raise AssertionError('Test fixture requires an explicit MockTransport handler')

class BudgetStop(ValueError):pass

class BudgetLedger:
    def __init__(self,path,*,operating=4000):
        if not 0<operating<=4000:raise ValueError('Operating ceiling cannot exceed 4000 VND')
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        # Exclusive creation is also a process-level campaign lock. Existing
        # ledgers are never resumed, reset, or silently replayed after a crash.
        fd=os.open(self.path,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(fd)
        self.lock=threading.RLock();self.db=sqlite3.connect(self.path,check_same_thread=False)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''CREATE TABLE meta(id INTEGER PRIMARY KEY,data TEXT NOT NULL);
        CREATE TABLE requests(id INTEGER PRIMARY KEY,request_key TEXT UNIQUE,model TEXT,batch_size INTEGER,
        line_count INTEGER,input_bound INTEGER,output_limit INTEGER,reserved_vnd TEXT,accounted_vnd TEXT,
        state TEXT,started TEXT,http_status INTEGER,usage TEXT,estimated_usd TEXT,elapsed REAL,error TEXT);''')
        self.operating=Decimal(operating)
        self.meta=dict(authorization=AUTHORIZATION,operating_vnd=operating,absolute_vnd=5000,max_requests=42,
                       fx_quoted=str(FX_QUOTED),fx_reserve=str(FX_RESERVE),fx_source=FX_SOURCE,fx_checked=FX_CHECKED,
                       safety=str(SAFETY),pricing={m:load(model=m) for m in MODEL_NAMES},state='active')
        self.db.execute('INSERT INTO meta VALUES (1,?)',(json.dumps(self.meta),));self.db.commit()

    def rows(self):
        with self.lock:return [dict(r) for r in self.db.execute('SELECT * FROM requests ORDER BY id')]

    def reserve(self,key,model,batch,line_count,input_bound,output_limit):
        validate_size(batch)
        if model not in MODEL_NAMES or type(line_count) is not int or not 1<=line_count<=batch:raise BudgetStop('Invalid model/batch')
        if any(type(n) is not int or n<=0 for n in (input_bound,output_limit)) or output_limit>8192:raise BudgetStop('Invalid finite token reservation')
        rates=self.meta['pricing'][model]['peak']
        usd=(Decimal(input_bound)*Decimal(rates['input'])+Decimal(output_limit)*Decimal(rates['output']))/1000000
        reserved=usd*FX_RESERVE*SAFETY
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                if self.meta['state']!='active':raise BudgetStop('Campaign is stopped')
                rows=self.rows();used=sum((Decimal(r['accounted_vnd']) for r in rows),Decimal(0))
                group=[r for r in rows if r['model']==model and r['batch_size']==batch]
                if len(rows)>=42 or len(group)>=(30+batch-1)//batch or sum(r['line_count'] for r in group)+line_count>30:
                    raise BudgetStop('Request/line/configuration ceiling reached')
                if used+reserved>self.operating:raise BudgetStop('Insufficient prepaid operating budget')
                cursor=self.db.execute('INSERT INTO requests(request_key,model,batch_size,line_count,input_bound,output_limit,reserved_vnd,accounted_vnd,state,started) VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (key,model,batch,line_count,input_bound,output_limit,str(reserved),str(reserved),'reserved_before_http',datetime.now(timezone.utc).isoformat()))
                self.db.commit();return cursor.lastrowid
            except sqlite3.IntegrityError:
                self.db.rollback();raise BudgetStop('This batch was already reserved; replay forbidden') from None
            except BaseException:self.db.rollback();raise

    def settle(self,id,*,usage=None,status=None,elapsed=None,error=None):
        with self.lock,self.db:
            row=dict(self.db.execute('SELECT * FROM requests WHERE id=?',(id,)).fetchone())
            if row['state']!='reserved_before_http':raise BudgetStop('Attempt already settled')
            config=self.meta['pricing'][row['model']];key,_=period(config,datetime.fromisoformat(row['started']))
            if period(config)[0]!=key:key='peak'  # Cross-window billing estimate stays conservative.
            measured=estimate(usage,config[key])
            valid=status==200 and measured is not None and measured['input_tokens']<=row['input_bound'] and measured['output_tokens']<=row['output_limit']
            if valid:
                rates=config['peak']
                # Settlement still assumes peak prices and no cache; keep markup.
                conservative=(Decimal(measured['input_tokens'])*Decimal(rates['input'])+Decimal(measured['output_tokens'])*Decimal(rates['output']))/1000000*FX_RESERVE*SAFETY
                accounted=str(max(Decimal(0),conservative))
            else:accounted=row['reserved_vnd']
            self.db.execute('UPDATE requests SET accounted_vnd=?,state=?,http_status=?,usage=?,estimated_usd=?,elapsed=?,error=? WHERE id=?',
                (accounted,'usage_known' if valid else 'uncertain',status,json.dumps(usage) if valid else None,measured['usd'] if valid else None,elapsed,error,id))
            if not valid:self.stop('usage_unknown_or_out_of_bound')
            return valid

    def stop(self,reason):
        with self.lock:
            self.meta.update(state='stopped',reason=reason)
            self.db.execute('UPDATE meta SET data=? WHERE id=1',(json.dumps(self.meta),));self.db.commit()

    def snapshot(self):
        rows=self.rows();known=[r for r in rows if r['estimated_usd'] is not None]
        conservative=sum((Decimal(r['accounted_vnd']) for r in rows),Decimal(0))
        unknown=sum((Decimal(r['accounted_vnd']) for r in rows if r['state']!='usage_known'),Decimal(0))
        usd=sum((Decimal(r['estimated_usd']) for r in known),Decimal(0)) if known else None
        return dict(**self.meta,requests=rows,request_count=len(rows),usage_estimated_usd=str(usd) if usd is not None else None,
                    usage_estimated_vnd=str(usd*FX_QUOTED) if usd is not None else None,
                    conservative_vnd=str(conservative),uncertain_reserved_vnd=str(unknown),remaining_absolute_vnd=str(Decimal(5000)-conservative))

    def close(self):self.db.close()

class PrepaidTransport(httpx.MockTransport):
    def __init__(self,ledger,model,batch,scheduler):
        self.ledger=ledger;self.model=model;self.batch=batch;self.scheduler=scheduler
        self.inner=httpx.MockTransport(unconfigured)
        self.last_error=None;self.http_calls=0;self.overhead=[]

    async def handle_async_request(self,request):
        if not isinstance(self.inner,httpx.MockTransport):raise AssertionError('Budget fixture is mock-only')
        body=json.loads(request.content)
        rows=json.loads(body['messages'][1]['content'])['lines']
        assert str(request.url)=='https://api.deepseek.com/chat/completions'
        assert body['model']==self.model and body['thinking']=={'type':'disabled'}
        assert body['response_format']=={'type':'json_object'} and body['stream'] is False
        assert 1<=len(rows)<=self.batch and len({r['id'] for r in rows})==len(rows)
        # A UTF-8 byte bound for the FULL serialized request, plus 2048 tokens
        # for message framing. No char/4 estimate and no cache assumption.
        input_bound=len(request.content)+2048
        key=f'{self.model}:{self.batch}:'+hashlib.sha256(json.dumps([r['id'] for r in rows]).encode()).hexdigest()
        try:id=self.ledger.reserve(key,self.model,self.batch,len(rows),input_bound,body['max_tokens'])
        except BudgetStop:
            self.last_error='preflight_budget_stop';self.scheduler._stopped.set();raise httpx.RequestError('Budget preflight blocked; no HTTP sent') from None
        reference=json.loads(body['messages'][1]['content']).get('reference_only',[])
        self.overhead.append(dict(system_utf8_bytes=len(body['messages'][0]['content'].encode()),
                                  context_utf8_bytes=len(json.dumps(reference,ensure_ascii=False).encode()),
                                  full_request_utf8_bytes=len(request.content)))
        self.http_calls+=1;start=time.monotonic();settled=False
        try:
            response=await self.inner.handle_async_request(request);await response.aread()
            try:
                raw=response.json().get('usage')
                usage={k:v for k,v in raw.items() if k in ('prompt_tokens','completion_tokens','total_tokens','prompt_cache_hit_tokens','prompt_cache_miss_tokens','prompt_tokens_details')}
            except (ValueError,AttributeError,TypeError):usage=None
            safe=self.ledger.settle(id,usage=usage,status=response.status_code,elapsed=time.monotonic()-start)
            settled=True
            if response.status_code!=200 or not safe:
                self.last_error='http_error_or_usage_unknown';self.scheduler._stopped.set()
                self.ledger.stop(self.last_error)
            save(OUT/'budget.json',self.ledger.snapshot())
            return response
        except BaseException as exc:
            if not settled:self.ledger.settle(id,elapsed=time.monotonic()-start,error=type(exc).__name__)
            self.last_error='transport_unknown';self.scheduler._stopped.set();self.ledger.stop(self.last_error)
            save(OUT/'budget.json',self.ledger.snapshot());raise

    async def aclose(self):await self.inner.aclose()
