import asyncio
import hashlib
import hmac
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from geonexus.registration import RegistrationError
from geo_harness.app import create_app
from geo_harness.core import Settings, llm_base_url
from geo_harness.resource_nodes import ResourceNodes

@pytest.mark.parametrize('url,base',[
 ('https://example.org/v1','https://example.org/v1'),
 (' https://example.org/v1/chat/completions/ ','https://example.org/v1'),
 ('https://example.org/chat/completions/chat/completions','https://example.org'),
 ('https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions','https://dashscope.aliyuncs.com/compatible-mode/v1'),
])
def test_normalizes_complete_endpoint(url,base):
 assert llm_base_url(url)==base

@pytest.mark.parametrize('url',['https://user:secret@example.org/v1','https://example.org/v1?key=secret','https://example.org/v1#secret'])
def test_rejects_secret_bearing_address(url):
 with pytest.raises(RegistrationError):llm_base_url(url)

def test_draft_connection_uses_unsaved_values_and_does_not_enable_or_save(tmp_path,monkeypatch):
 app=create_app(tmp_path);seen=[];original=httpx.AsyncClient
 def handler(request):
  seen.append(request)
  return httpx.Response(200,json={'model':'qwen-plus','choices':[{'message':{'content':'OK'}}]})
 monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
 with TestClient(app) as client:
  client.get('/');csrf=client.get('/api/session').json()['csrf']
  draft={'llm':{'enabled':False,'provider':'bailian','base_url':'https://example.org/v1/chat/completions','model':'qwen-plus','api_key':'draft-private-key'}}
  r=client.post('/api/settings/test',json=draft,headers={'X-Geo-CSRF':csrf})
  assert r.status_code==200 and r.json()['response']=='OK'
  assert 'draft-private-key' not in r.text and not r.json()['saved']
  assert client.get('/api/settings').json()['llm']['model']==''
  assert not app.state.settings.path.exists()
 assert str(seen[0].url)=='https://example.org/v1/chat/completions'
 assert seen[0].headers['Authorization']=='Bearer draft-private-key'
 assert json.loads(seen[0].content)['max_tokens']==16

@pytest.mark.parametrize('status',[401,403,404,429,500,302])
def test_provider_errors_never_echo_secrets(tmp_path,monkeypatch,status):
 s=Settings(tmp_path);s.save({'llm':{'enabled':True,'base_url':'https://example.org/v1','model':'qwen-plus','api_key':'never-echo-this'}})
 original=httpx.AsyncClient
 def handler(request):return httpx.Response(status,json={'error':{'message':'never-echo-this'}})
 monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
 async def check():
  with pytest.raises(RegistrationError) as e:await s.completion([{'role':'user','content':'OK'}])
  assert str(status) in str(e.value) and 'never-echo-this' not in str(e.value)
 asyncio.run(check())

def test_preserves_saved_key_on_same_origin_but_requires_reentry_for_new_service(tmp_path):
 s=Settings(tmp_path);s.save({'llm':{'base_url':'https://a.example/v1','model':'mine','api_key':'only-for-a'}})
 assert s.preview({'llm':{'base_url':'https://a.example/v1/chat/completions','api_key':''}}).value['llm']['api_key']=='only-for-a'
 with pytest.raises(RegistrationError,match='API Key'):s.preview({'llm':{'base_url':'https://b.example/v1'}})
 assert s.value['llm']['base_url']=='https://a.example/v1'
 assert s.preview({'llm':{'base_url':'https://b.example/v1','api_key':'only-for-b'}}).value['llm']['api_key']=='only-for-b'

@pytest.mark.parametrize('model',['阿里百炼','阿里云百炼','DeepSeek'])
def test_provider_label_is_not_model_id(tmp_path,model):
 with pytest.raises(RegistrationError,match='模型 ID'):Settings(tmp_path).save({'llm':{'model':model}})

def test_request_context_keeps_two_platform_tokens_and_origins_isolated(tmp_path):
 seen=[]
 def handler(request):seen.append((str(request.url),request.headers.get('authorization')));return httpx.Response(200,json={'ok':True})
 n=ResourceNodes(tmp_path,None,transport=httpx.MockTransport(handler))
 async def one(base,key):
  reset=n._request_platform.set({'endpoint':base,'token':key})
  try:
   await asyncio.sleep(0)
   await n.request(n.platform,'GET','/api/auth/me',authenticated=True)
  finally:n._request_platform.reset(reset)
 async def check():await asyncio.gather(one('http://127.0.0.1:9305','token-9305'),one('http://127.0.0.1:9316','token-9316'))
 asyncio.run(check())
 assert set(seen)=={('http://127.0.0.1:9305/api/auth/me','Bearer token-9305'),('http://127.0.0.1:9316/api/auth/me','Bearer token-9316')}
 assert n.platform['endpoint']=='http://127.0.0.1:3301'


def test_signed_origin_cannot_be_replaced_and_is_applied_only_to_authenticated_request(tmp_path,monkeypatch):
 key='signed-origin-key';monkeypatch.setenv('GEONEXUS_HARNESS_GATEWAY_KEY',key)
 app=create_app(tmp_path)
 def signed(base):
  stamp=str(int(time.time()));path='/api/session';token='platform-session-private';parts=[stamp,'GET',path,'member-a',hashlib.sha256(token.encode()).hexdigest(),base]
  return {'X-Geo-Workbench-Time':stamp,'X-Geo-Workbench-Principal':'member-a','X-Geo-Platform-Token':token,'X-Geo-Platform-Base':base,'X-Geo-Workbench-Signature':hmac.new(key.encode(),'\n'.join(parts).encode(),hashlib.sha256).hexdigest(),'X-Forwarded-Host':base.removeprefix('http://'),'X-Forwarded-Proto':'http'}
 async def check():
  async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as c:
   headers=signed('http://127.0.0.1:9305');r=await c.get('/api/session',headers=headers)
   assert r.status_code==200 and r.json()['account']['principal']=='member-a'
   assert 'platform-session-private' not in r.text
   headers['X-Geo-Platform-Base']='http://127.0.0.1:9999';headers['X-Forwarded-Host']='127.0.0.1:9999'
   assert (await c.get('/api/session',headers=headers)).status_code==403
 asyncio.run(check())


def test_known_remote_service_without_key_fails_before_network(tmp_path,monkeypatch):
 s=Settings(tmp_path);s.save({'llm':{'enabled':True,'provider':'bailian','base_url':'https://dashscope.aliyuncs.com/compatible-mode/v1','model':'qwen-plus'}})
 def no_network(**kw):raise AssertionError('Missing key must not make a network request')
 monkeypatch.setattr(httpx,'AsyncClient',no_network)
 async def check():
  with pytest.raises(RegistrationError,match='API Key'):await s.completion([{'role':'user','content':'OK'}])
 asyncio.run(check())


def test_connection_response_redacts_key_even_if_provider_echoes_it(tmp_path,monkeypatch):
 app=create_app(tmp_path);original=httpx.AsyncClient
 def handler(request):return httpx.Response(200,json={'model':'private-response-key','choices':[{'message':{'content':'private-response-key'}}]})
 monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
 with TestClient(app) as client:
  client.get('/');csrf=client.get('/api/session').json()['csrf']
  r=client.post('/api/settings/test',json={'llm':{'base_url':'https://example.org/v1','model':'selected-model','api_key':'private-response-key'}},headers={'X-Geo-CSRF':csrf})
  assert r.status_code==200 and 'private-response-key' not in r.text
  assert r.json()['model']=='selected-model' and r.json()['response']=='[redacted]'


def test_token_plan_label_rejected_with_correct_model_hint(tmp_path):
 with pytest.raises(RegistrationError,match='qwen3.8-flash'):
  Settings(tmp_path).save({'llm':{'base_url':'https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1','model':'阿里百炼'}})


@pytest.mark.parametrize('error', [{'error':{'code':'model_not_found','message':'never-echo-this'}},{'error':{'code':'ModelNotFound'} }])
def test_model_not_found_has_specific_safe_hint(tmp_path,monkeypatch,error):
 s=Settings(tmp_path);s.save({'llm':{'enabled':True,'base_url':'https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1','model':'not-available','api_key':'never-echo-this'}})
 original=httpx.AsyncClient
 monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(lambda r:httpx.Response(404,json=error)),**kw))
 async def check():
  with pytest.raises(RegistrationError) as e:await s.completion([{'role':'user','content':'OK'}])
  assert 'model_not_found' in str(e.value) and 'qwen3.8-flash' in str(e.value) and 'never-echo-this' not in str(e.value)
 asyncio.run(check())


def test_token_plan_probe_calls_exact_route_and_disables_probe_thinking(tmp_path,monkeypatch):
 app=create_app(tmp_path);seen=[];original=httpx.AsyncClient
 def handler(request):
  seen.append(request);return httpx.Response(200,json={'choices':[{'message':{'content':'OK'}}]})
 monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
 with TestClient(app) as c:
  c.get('/');csrf=c.get('/api/session').json()['csrf']
  response=c.post('/api/settings/test',json={'llm':{'provider':'bailian-token','base_url':'https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1','model':'qwen3.8-flash','api_key':'fake-plan-secret'}},headers={'X-Geo-CSRF':csrf})
  assert response.status_code==200 and response.json()['response']=='OK'
  assert not app.state.settings.path.exists() and 'fake-plan-secret' not in response.text
 assert str(seen[0].url)=='https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions'
 body=json.loads(seen[0].content);assert body['enable_thinking'] is False and body['max_tokens']==16


def test_empty_probe_response_is_not_reported_as_success(tmp_path,monkeypatch):
 app=create_app(tmp_path);original=httpx.AsyncClient
 monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'choices':[{'message':{'content':None,'reasoning_content':'thinking'}}]})),**kw))
 with TestClient(app) as c:
  c.get('/');csrf=c.get('/api/session').json()['csrf']
  response=c.post('/api/settings/test',json={'llm':{'base_url':'https://example.org/v1','model':'model'}},headers={'X-Geo-CSRF':csrf})
  assert response.status_code==400 and '未返回测试文本' in response.text
