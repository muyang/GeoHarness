"""Bounded dependency plans over installed, version-locked node capabilities."""
import asyncio,copy,hashlib,json,re,uuid
from datetime import datetime,timezone
from geonexus.registration import RegistrationError
from .core import read_json,validate_arguments,write_private

REF={'type':'object','properties':{'$step':{'type':'string'},'path':{'type':'string','pattern':'^/'}},'required':['$step','path'],'additionalProperties':False}

def ref_schema(schema):
    if not isinstance(schema,dict):return schema
    value=copy.deepcopy(schema)
    if isinstance(value.get('properties'),dict):value['properties']={k:ref_schema(v) for k,v in value['properties'].items()}
    if isinstance(value.get('items'),dict):value['items']=ref_schema(value['items'])
    return {'anyOf':[value,REF]}

def references(value):
    if isinstance(value,dict):
        if '$step' in value:
            if set(value)!={'$step','path'} or not isinstance(value['path'],str) or len(value['path'])>400 or not value['path'].startswith('/'):raise RegistrationError('步骤引用需要 $step 与 JSON Pointer path。')
            if any(p.lower() in {'api_key','access_token','token','session_token','authorization','secret'} for p in value['path'].split('/')):raise RegistrationError('步骤不能引用私有凭据。')
            yield value
        else:
            for x in value.values():yield from references(x)
    elif isinstance(value,list):
        for x in value:yield from references(x)

def resolve(value, completed):
    if isinstance(value,dict):
        if '$step' in value:
            current=completed[value['$step']]
            try:
                for piece in value['path'].split('/')[1:]:
                    key=piece.replace('~1','/').replace('~0','~');current=current[int(key)] if isinstance(current,list) else current[key]
                return copy.deepcopy(current)
            except (KeyError,IndexError,ValueError,TypeError):raise RegistrationError('上游成果没有引用的字段，未执行下游步骤。') from None
        return {k:resolve(v,completed) for k,v in value.items()}
    if isinstance(value,list):return [resolve(x,completed) for x in value]
    return value

def signature(document):
    body={k:v for k,v in document.items() if k!='signature'}
    return hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def freeze_document(row, model, baseline):
    """Immutable record of a proven plan (pure; no I/O)."""
    document={
        'workflow_id':row['id'],'name':row['name'],'source':row.get('source','ui'),
        'steps':[{k:s.get(k) for k in ('id','product_id','expected_digest','arguments','depends_on')} for s in row['steps']],
        'resources':[{'product_id':s['product_id'],'digest':s['expected_digest']} for s in row['steps']],
        'model':model,'baseline':baseline,
        'frozen_at':datetime.now(timezone.utc).isoformat(),
    }
    document['signature']=signature(document)
    return document

def result_digest(result):
    if result is None:return None
    return hashlib.sha256(json.dumps(result,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def compare_baseline(baseline, current):
    """Per-step drift: mismatching result digests, missing results, status changes."""
    drift=[]
    for step_id, expected in (baseline or {}).items():
        actual=current.get(step_id)
        if actual is None:
            drift.append({'step':step_id,'reason':'missing','expected':expected})
            continue
        if expected.get('status')!=actual.get('status'):
            drift.append({'step':step_id,'reason':'status','expected':expected.get('status'),'actual':actual.get('status')})
        elif expected.get('result_digest')!=actual.get('result_digest'):
            drift.append({'step':step_id,'reason':'result','expected':expected.get('result_digest'),'actual':actual.get('result_digest')})
    return drift

class Workflows:
    def __init__(self, wb):
        self.wb=wb;self.root=wb.root/'plans';self.rows={};self.tasks={}
        for p in self.root.glob('*.json'):
            r=read_json(p)
            if r['status'] in {'queued','running','stopping'}:r.update(status='interrupted',error='运行时重启，计划未自动重提。');write_private(p,r)
            self.rows[r['id']]=r
    def save(self, row):write_private(self.root/(row['id']+'.json'),row)
    def get(self, identity):
        if identity not in self.rows:raise RegistrationError('当前账号没有该计划。')
        value=copy.deepcopy(self.rows[identity])
        for step in value['steps']:
            if step.get('execution_id') in self.wb.jobs:
                execution=self.wb.status(step['execution_id'])
                step['execution']=execution
                if step['status']=='running':step['status']=execution['status']
        return value
    def list(self):return [self.get(r['id']) for r in sorted(self.rows.values(),key=lambda r:r['created_at'],reverse=True)[:100]]
    def create(self, name, steps, source='ui'):
        if source not in {'ui','agent'}:raise RegistrationError('计划来源无效。')
        if not isinstance(name,str) or not 1<=len(name.strip())<=100 or not isinstance(steps,list) or not 1<=len(steps)<=8:raise RegistrationError('计划需要名称与1–8个步骤。')
        previous=set();spec=[]
        for s in steps:
            if not isinstance(s,dict) or set(s)-{'id','product_id','arguments','depends_on','expected_digest','reuse_execution_id'}:raise RegistrationError('步骤字段无效。')
            identity=s.get('id');deps=s.get('depends_on',[])
            if not isinstance(identity,str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_-]{0,39}',identity) or identity in previous:raise RegistrationError('步骤编号无效或重复。')
            if not isinstance(deps,list) or any(not isinstance(d,str) or d not in previous for d in deps):raise RegistrationError('依赖必须指向此前定义的步骤，不能有循环。')
            if not isinstance(s.get('product_id'),str) or not isinstance(s.get('expected_digest'),str):raise RegistrationError('产品编号与摘要必须是字符串。')
            d=self.wb.describe(s['product_id'])
            if not d['executable'] or s.get('expected_digest')!=d['digest']:raise RegistrationError('请先安装、授权并读取每步产品的最新契约。')
            args=s.get('arguments',{})
            if not isinstance(args,dict):raise RegistrationError('步骤参数必须是对象。')
            for ref in references(args):
                if ref['$step'] not in deps:raise RegistrationError('成果引用必须声明为已知依赖。')
            validate_arguments(ref_schema(d['input_schema']),args)
            spec.append({'id':identity,'product_id':d['product_id'],'name':d['name'],'expected_digest':d['digest'],'arguments':args,'depends_on':list(dict.fromkeys(deps)),'status':'planned'})
            if s.get('reuse_execution_id'):
                old=self.wb.status(s['reuse_execution_id'])
                if old['status']!='completed' or old['product_id']!=d['product_id'] or old['digest']!=d['digest']:raise RegistrationError('只能复用当前工作空间已完成且版本一致的运行。')
                spec[-1]['reuse_execution_id']=old['id']
            previous.add(identity)
        packed=json.dumps({'name':name.strip(),'steps':[{k:v for k,v in s.items() if k not in {'name','status'}} for s in spec]},sort_keys=True,ensure_ascii=False)
        row={'id':uuid.uuid4().hex,'name':name.strip(),'digest':hashlib.sha256(packed.encode()).hexdigest(),'steps':spec,'status':'planned','source':source,'created_at':datetime.now(timezone.utc).isoformat()}
        self.rows[row['id']]=row;self.save(row);return self.get(row['id'])
    def _model(self):
        llm=self.wb.settings.value.get('llm',{}) if getattr(self.wb,'settings',None) else {}
        return {'id':llm.get('model') or None,'params':{'temperature':llm.get('temperature')}}

    def _baseline(self, row):
        baseline={}
        for step in row['steps']:
            execution=step.get('execution_id')
            if not execution:continue
            try:job=self.wb.status(execution)
            except Exception:continue
            baseline[step['id']]={'status':job.get('status'),'result_digest':result_digest(job.get('result'))}
        return baseline

    def freeze(self, identity, version=None):
        row=self.get(identity)
        if row['status']!='completed':raise RegistrationError('只有已完成的计划可以冻结。')
        document=freeze_document(row,self._model(),self._baseline(row))
        target=self.root.parent/'frozen'/f"{row['id']}-v{version or 1}.json"
        write_private(target,document)
        row.setdefault('frozen',[]).append({'version':version or 1,'signature':document['signature'],'at':document['frozen_at']})
        self.save(row)
        return document

    def frozen(self, identity, version=None):
        row=self.rows.get(identity)
        if not row:raise RegistrationError('计划不存在。')
        entries=row.get('frozen') or []
        if not entries:raise RegistrationError('该计划尚未冻结。')
        chosen=entries[-1] if version is None else next((e for e in entries if e['version']==version),None)
        if not chosen:raise RegistrationError('冻结版本不存在。')
        document=read_json(self.root.parent/'frozen'/f"{row['id']}-v{chosen['version']}.json")
        if not document or signature(document)!=document.get('signature'):
            raise RegistrationError('冻结记录签名校验失败。')
        return document

    async def replay(self, identity, version=None):
        document=self.frozen(identity,version)
        drift_contract=[r for r in document['resources'] if self.wb.describe(r['product_id'])['digest']!=r['digest']]
        if drift_contract:raise RegistrationError('产品契约已变化，冻结版本不能回放。')
        plan=self.create(document['name']+' · 回放',document['steps'],source=document.get('source','ui'))
        await self.start(plan['id'],plan['digest'])
        task=self.tasks.get(plan['id'])
        if task:await asyncio.shield(task)
        current=self._baseline(self.rows[plan['id']])
        return {'workflow_id':document['workflow_id'],'version':version or (self.rows[identity]['frozen'][-1]['version']),
                'plan':self.get(plan['id']),'drift':compare_baseline(document['baseline'],current)}

    def repair(self, identity, steps):
        old=self.get(identity)
        if old['status'] in {'queued','running','stopping'}:raise RegistrationError('请先停止正在执行的计划，再修正。')
        steps=copy.deepcopy(steps)
        if not isinstance(steps,list):raise RegistrationError('修正计划需要步骤列表。')
        for step in steps:
            source=next((s for s in old['steps'] if s['id']==step.get('id')),None)
            if source and source['status']=='completed' and all(source[k]==step.get(k,[] if k=='depends_on' else {}) for k in ['product_id','expected_digest','arguments','depends_on']):step['reuse_execution_id']=source['execution_id']
        row=self.create(old['name']+' · 修正',steps);self.rows[row['id']]['repaired_from']=identity;self.save(self.rows[row['id']]);return self.get(row['id'])

    async def start(self, identity, digest):
        row=self.rows.get(identity)
        if not row or row['digest']!=digest:raise RegistrationError('计划不存在或版本已变化。')
        if row['status']!='planned':return self.get(identity)
        for s in row['steps']:
            if self.wb.describe(s['product_id'])['digest']!=s['expected_digest']:raise RegistrationError('产品版本已变化，请重新生成计划。')
        row['status']='queued';self.save(row);self.tasks[identity]=asyncio.create_task(self.run(row));return self.get(identity)
    async def run(self, row):
        completed={};row['status']='running';self.save(row)
        try:
            for step in row['steps']:
                args=resolve(step['arguments'],completed)
                if step.get('reuse_execution_id'):
                    job=self.wb.status(step['reuse_execution_id'])
                    if job['arguments']!=args:raise RegistrationError('复用输入与本次参数不一致，未复用旧成果。')
                else:job=await self.wb.submit(step['product_id'],args,step['expected_digest'],source=row.get('source','ui'))
                step.update(status='running',execution_id=job['id'],resolved_arguments=args);self.save(row)
                if not step.get('reuse_execution_id'):await asyncio.shield(self.wb.tasks[job['id']])
                job=self.wb.status(job['id'])
                step.update(status=job['status'],result_id=job.get('result_id'));self.save(row)
                if job['status']!='completed':raise RegistrationError(job.get('error','上游未完成，停止下游执行。'))
                completed[step['id']]=job;row['result_id']=job.get('result_id')
            row['status']='completed'
        except asyncio.CancelledError:
            row.update(status='interrupted',error='停止工作台等待，远程节点任务需另外核对。')
        except Exception as e:row.update(status='failed',error=self.wb.redact(e)[:1000])
        finally:self.save(row)
    async def stop(self, identity):
        row=self.rows.get(identity)
        if not row:raise RegistrationError('计划不存在。')
        task=self.tasks.get(identity)
        if task and not task.done():task.cancel();await asyncio.gather(task,return_exceptions=True)
        return self.get(identity)
    async def close(self):
        for task in self.tasks.values():
            if not task.done():task.cancel()
        if self.tasks:await asyncio.gather(*self.tasks.values(),return_exceptions=True)
