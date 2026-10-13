"""Account-local durable dialogue, including bounded tool history."""
import copy,re,uuid
from datetime import datetime,timezone
from geonexus.registration import RegistrationError
from .core import read_json,write_private

class Conversations:
    def __init__(self, root, redact):
        self.root=root/'conversations';self.redact=redact;self.active=set()
    def get(self, identity):
        if not isinstance(identity,str) or not re.fullmatch('[a-f0-9]{32}',identity):raise RegistrationError('对话编号无效。')
        path=self.root/(identity+'.json')
        if not path.is_file():raise RegistrationError('当前账号没有该对话。')
        record=read_json(path)
        if 'turns' not in record and record.get('question'):
            record.update(title=record['question'][:60],turns=[{'question':record['question'],'answer':record.get('answer',''),'events':record.get('events',[]),'status':'completed'}],messages=[{'role':'user','content':record['question']},{'role':'assistant','content':record.get('answer','')}])
        return record
    def list(self):
        rows=[]
        for p in self.root.glob('*.json'):
            r=read_json(p);rows.append({k:r.get(k) for k in ['id','title','updated_at','status']})
        return sorted(rows,key=lambda r:r.get('updated_at') or '',reverse=True)[:100]
    def begin(self, identity, text):
        record=self.get(identity) if identity else {'id':uuid.uuid4().hex,'title':self.redact(text)[:60],'turns':[],'messages':[]}
        if record['id'] in self.active:raise RegistrationError('该对话正在另一入口回复，请稍后继续。')
        self.active.add(record['id']);return record
    def save(self, record, status):
        record['status']=status;record['updated_at']=datetime.now(timezone.utc).isoformat()
        write_private(self.root/(record['id']+'.json'),record)
    def history(self, record):
        # New system/map context is always supplied for this turn; old permissions
        # are never carried forward as authority.
        history=copy.deepcopy(record.get('messages',[]))
        while len(history)>40 or len(str(history))>100_000:
            if len(history)<2:return []
            history.pop(0)
            while history and history[0].get('role')!='user':history.pop(0)
        return history
    def end(self, record, question, answer, events, messages, status):
        clean=lambda x: __import__('json').loads(self.redact(__import__('json').dumps(x,ensure_ascii=False)))
        record['messages']=clean(messages)
        record.setdefault('turns',[]).append(clean({'question':question,'answer':answer,'events':events,'status':status}))
        record['turns']=record['turns'][-30:];self.save(record,status);self.active.discard(record['id'])
