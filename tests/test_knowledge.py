"""Installed knowledge product -> official MCP -> user-selected LLM boundary."""
import json
import os,socket,subprocess,sys,time
import httpx,pytest
from contextlib import contextmanager
from geo_harness.core import file_digest,write_private
from geo_harness.resource_nodes import digest

from fastapi.testclient import TestClient
from geokg.knowledge import verify_bundle
from geokg.products import export_product

from geo_harness.app import create_app


def setup_client(tmp_path, endpoint):
    manifest=export_product(tmp_path/'market/geokg')
    root=tmp_path/'market/geokg';binding=json.loads((root/'binding.json').read_text());binding['endpoint']=endpoint;write_private(root/'binding.json',binding)
    manifest['files']['binding.json']=file_digest(root/'binding.json');manifest['content_digest']=digest(manifest['files']);write_private(root/'manifest.json',manifest)
    app=create_app(tmp_path)
    client=TestClient(app)
    client.__enter__()
    client.get('/')
    state=client.get('/api/bootstrap').json()
    csrf={'X-Geo-CSRF':state['csrf']}
    permissions=next(p for p in state['catalog'] if p['id']=='org.geonexus.geokg')['permissions']
    response=client.post('/api/products/org.geonexus.geokg/install',json={'granted':permissions},headers=csrf)
    assert response.status_code==200,response.text
    return client,csrf



@pytest.fixture
def mcp_endpoint(tmp_path):
    # A genuine isolated MCP HTTP service; never assume the user's 8792 instance.
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    env=dict(os.environ)
    with open(tmp_path/'mcp.log','w') as log:
        process=subprocess.Popen([sys.executable,'-m','geokg.mcp_server','--transport','streamable-http','--port',str(port)],env=env,stdout=log,stderr=log)
        try:
            for _ in range(100):
                if process.poll() is not None:raise RuntimeError('Isolated MCP server exited')
                try:httpx.get(f'http://127.0.0.1:{port}/',timeout=.2,trust_env=False);break
                except httpx.RequestError:time.sleep(.1)
            else:raise RuntimeError('Isolated MCP server did not start')
            yield f'http://127.0.0.1:{port}/mcp'
        finally:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()

def test_installed_knowledge_real_http_mcp_and_disable(tmp_path,mcp_endpoint):
    client,csrf=setup_client(tmp_path,mcp_endpoint)
    try:
        result=client.post('/api/knowledge/query',json={'tool':'knowledge.search','arguments':{'query':'巴西'}},headers=csrf)
        assert result.status_code==200,result.text
        assert result.json()['results'][0]['id']=='country.BRA'
        citations=client.post('/api/knowledge/query',json={'tool':'knowledge.case_citations','arguments':{'case_id':'case.flightway-wetland'}},headers=csrf)
        assert citations.status_code==200 and verify_bundle(citations.json())
        rejected=client.post('/api/knowledge/query',json={'tool':'refresh','arguments':{}},headers=csrf)
        assert rejected.status_code==400
        client.post('/api/products/org.geonexus.geokg/disable',json={},headers=csrf)
        assert client.post('/api/knowledge/query',json={'arguments':{'query':'BRA'}},headers=csrf).status_code==400
    finally:
        client.__exit__(None,None,None)


def test_configured_llm_can_use_installed_public_knowledge(tmp_path,monkeypatch,mcp_endpoint):
    client,csrf=setup_client(tmp_path,mcp_endpoint)
    seen=[]
    async def completion(messages,tools=None):
        seen.append(messages)
        assert any(t['function']['name']=='knowledge_search' for t in tools)
        if len(seen)==1:
            return {'choices':[{'message':{'role':'assistant','content':None,'tool_calls':[{'id':'q1','type':'function','function':{'name':'knowledge_search','arguments':json.dumps({'query':'6.6.1'})}}]}}]}
        assert 'sdg.indicator.6.6.1' in messages[-1]['content']
        return {'choices':[{'message':{'role':'assistant','content':'已从固定快照找到 SDG 6.6.1。'}}]}
    monkeypatch.setattr(client.app.state.settings,'completion',completion)
    try:
        response=client.post('/api/chat',json={'message':'查找 6.6.1'},headers=csrf)
        assert response.status_code==200,response.text
        assert response.json()['events'][0]['tool']=='knowledge_search'
    finally:
        client.__exit__(None,None,None)
