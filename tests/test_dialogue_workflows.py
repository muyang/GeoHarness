import asyncio,copy,json
import pytest
from geonexus.registration import RegistrationError
from geo_harness.core import read_json
from geo_harness.workbench import Workbench
from test_workbench_security import build,TestSettings

LEGACY={'definitions':{},'run':None}

def steps(w):
 digest=w.describe('reviewed.operator')['digest']
 return [{'id':'source','product_id':'reviewed.operator','expected_digest':digest,'arguments':{'radius':10}}, {'id':'next','product_id':'reviewed.operator','expected_digest':digest,'depends_on':['source'],'arguments':{'radius':{'$step':'source','path':'/result/summary/radius'}}}]

class Dialogue(TestSettings):
    def __init__(self):self.requests=[]
    async def completion(self,messages,definitions):
        self.requests.append(copy.deepcopy(messages))
        return {'choices':[{'message':{'role':'assistant','content':'已记住研究地区。' if len(self.requests)==1 else '继续使用此前的香港研究地区。'}}]}

def test_real_dialogue_retains_protocol_and_reloads_history(tmp_path):
 async def check():
  w,p,r,_=build(tmp_path);w.settings=Dialogue()
  first=[e async for e in w.chat({'message':'研究地区是香港'},'http://testserver',LEGACY)]
  identity=first[-1]['conversation_id'];second=[e async for e in w.chat({'message':'研究地区是什么？','conversation_id':identity},'http://testserver',LEGACY)]
  assert identity==second[-1]['conversation_id']
  assert any(m.get('content')=='研究地区是香港' for m in w.settings.requests[-1])
  assert len(w.conversations.get(identity)['turns'])==2
  other=Workbench(tmp_path,p,None,r,w.settings,w.invoke)
  assert len(other.conversations.get(identity)['turns'])==2
  for invalid in ['../private-settings','f'*32]:
   with pytest.raises(RegistrationError):other.conversations.get(invalid)
  await w.close();await other.close()
 asyncio.run(check())

def test_same_conversation_cannot_be_written_from_two_surfaces(tmp_path):
 w,_,_,_=build(tmp_path);record=w.conversations.begin(None,'first');w.conversations.save(record,'running')
 with pytest.raises(RegistrationError):w.conversations.begin(record['id'],'second')
 w.conversations.end(record,'first','answer',[],[],'completed')
 assert w.conversations.begin(record['id'],'third')['id']==record['id']

@pytest.mark.parametrize('mutation',['cycle','duplicate','undeclared_ref','private_ref','invalid_literal','stale_digest','unknown_product'])
def test_plan_rejects_bad_dependency_contract_and_secret_reference_before_execution(tmp_path,mutation):
 w,_,_,calls=build(tmp_path);spec=steps(w)
 if mutation=='cycle':spec[0]['depends_on']=['next']
 if mutation=='duplicate':spec[1]['id']='source'
 if mutation=='undeclared_ref':spec[1]['depends_on']=[]
 if mutation=='private_ref':spec[1]['arguments']['radius']['path']='/result/api_key'
 if mutation=='invalid_literal':spec[0]['arguments']['radius']=1000
 if mutation=='stale_digest':spec[1]['expected_digest']='b'*64
 if mutation=='unknown_product':spec[0]['product_id']='not-installed'
 with pytest.raises(RegistrationError):w.workflows.create('plan',spec)
 assert not calls and not w.workflows.rows

def test_dependency_result_is_resolved_and_completed_once(tmp_path):
 async def check():
  w,_,saved,calls=build(tmp_path)
  async def invoke(product,body):
   calls.append(body);return {'outputs':{'status':'completed','summary':{'radius':body['arguments']['radius']+1},'artifact_refs':{}}}
  w.invoke=invoke
  # Real saved metadata carries the result of the owning node, not model guesses.
  original=saved.save
  def save(product,tool,result):return {**original(product,tool,result),'summary':result['outputs']['summary']}
  saved.save=save
  row=w.workflows.create('two stages',steps(w));await w.workflows.start(row['id'],row['digest']);await w.workflows.start(row['id'],row['digest'])
  await w.workflows.tasks[row['id']]
  final=w.workflows.get(row['id']);assert final['status']=='completed' and len(calls)==2
  assert calls[0]['arguments']['radius']==10 and calls[1]['arguments']['radius']==11
  await w.workflows.start(row['id'],row['digest']);assert len(calls)==2
  case=w.save_workflow_case(row['id'],'完整方案');recipe=w.saved_case(case['id'])['recipe']
  assert len(recipe['steps'])==2 and recipe['steps'][1]['depends_on']==['source']
  assert 'private-artifact-test-token' not in json.dumps(recipe)
  await w.close()
 asyncio.run(check())

def test_failed_upstream_and_missing_result_stop_downstream(tmp_path):
 async def check():
  w,_,_,calls=build(tmp_path,result={'outputs':{'status':'failed','error':'test failure'}})
  row=w.workflows.create('stop on failure',steps(w));await w.workflows.start(row['id'],row['digest']);await w.workflows.tasks[row['id']]
  assert w.workflows.get(row['id'])['status']=='failed' and len(calls)==1
  await w.close()
 asyncio.run(check())

def test_changed_product_blocks_start_and_restart_does_not_resubmit(tmp_path):
 async def check():
  w,p,r,calls=build(tmp_path);row=w.workflows.create('plan',steps(w));p.installed['reviewed.operator']['digest']='new-version'
  with pytest.raises(RegistrationError):await w.workflows.start(row['id'],row['digest'])
  w.workflows.rows[row['id']]['status']='running';w.workflows.save(w.workflows.rows[row['id']])
  new=Workbench(tmp_path,p,None,r,w.settings,w.invoke)
  assert new.workflows.get(row['id'])['status']=='interrupted' and not calls
  await new.close();await w.close()
 asyncio.run(check())

def test_inspection_turn_never_exposes_workflow_execution(tmp_path):
 class Model(TestSettings):
  async def completion(self,messages,definitions):
   names={d['function']['name'] for d in definitions}
   assert 'workflow_plan' in names and 'workflow_status' in names
   assert 'workflow_execute' not in names and 'workflow_case_save' not in names
   return {'choices':[{'message':{'content':'只查看，不执行。'}}]}
 async def check():
  w,_,_,calls=build(tmp_path);w.settings=Model()
  events=[e async for e in w.chat({'message':'只看计划'},'http://testserver',LEGACY)]
  assert events[-1]['type']=='done' and not calls
  await w.close()
 asyncio.run(check())


def test_repair_keeps_completed_upstream_without_reexecution(tmp_path):
 async def check():
  w,_,saved,calls=build(tmp_path)
  async def invoke(product,body):
   calls.append(body);return {'outputs':{'status':'completed','summary':{'radius':body['arguments']['radius']+1}}}
  w.invoke=invoke;original=saved.save
  saved.save=lambda p,t,r:{**original(p,t,r),'summary':r['outputs']['summary']}
  bad=steps(w);bad[1]['arguments']['radius']['path']='/result/missing'
  row=w.workflows.create('repair',bad);await w.workflows.start(row['id'],row['digest']);await w.workflows.tasks[row['id']]
  assert w.workflows.get(row['id'])['status']=='failed' and len(calls)==1
  repaired=w.workflows.repair(row['id'],steps(w));assert repaired['steps'][0]['reuse_execution_id']
  await w.workflows.start(repaired['id'],repaired['digest']);await w.workflows.tasks[repaired['id']]
  assert w.workflows.get(repaired['id'])['status']=='completed' and len(calls)==2
  await w.close()
 asyncio.run(check())
