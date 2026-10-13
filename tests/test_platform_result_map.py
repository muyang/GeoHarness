import asyncio
import hashlib
import json

import httpx
import pytest
from geonexus.registration import RegistrationError
from geo_harness.app import create_app
from geo_harness.core import Products, read_json
from geo_harness.fixtures import MAP_ID, seed_market
from geo_harness.resource_nodes import ResourceNodes
from geo_harness.results import Results
from test_gateway import KEY, signed

CALL='a'*32
GEO={'type':'FeatureCollection','features':[{'type':'Feature','geometry':{'type':'Point','coordinates':[114.3,30.6]},'properties':{'name':'真实测试点'}}]}

def run(coro):return asyncio.run(coro)

def setup(tmp_path, output=None, denial=False):
 products=Products(tmp_path);seed_market(products.market);products.install(MAP_ID,['viewer:network','workspace:artifacts'])
 seen=[];data={'id':CALL,'status':'succeeded','card_ref':'sample.data','node_ref':'node-1','result':{'outputs':output or {'preview':GEO,'artifacts':[],'provenance':{'provider':'Source'}}},'provenance':{'catalog_sha256':'b'*64}}
 def handler(request):
  seen.append((request.method,request.url.path,request.headers.get('Authorization')))
  if request.url.path=='/api/v1/node-executions/'+CALL:return httpx.Response(404 if denial else 200,json=data)
  if request.url.path.startswith('/api/v1/geocards/'):return httpx.Response(200,json={'geocard':{'name':'数据研究结果'}})
  if '/artifacts/' in request.url.path:return httpx.Response(200,content=b'data')
  raise AssertionError(request.url)
 nodes=ResourceNodes(tmp_path,products,transport=httpx.MockTransport(handler));nodes.credential('platform',{'token':'member-only-token'})
 return Results(tmp_path,products,nodes),seen,data


def test_import_is_read_only_idempotent_and_rechecks_ownership(tmp_path):
 results,seen,_=setup(tmp_path)
 first=run(results.import_platform_execution(CALL));second=run(results.import_platform_execution(CALL))
 assert first['id']==second['id'] and len(results.list())==1
 assert all(method=='GET' for method,_,_ in seen)
 assert len([x for x in seen if x[1].startswith('/api/v1/node-executions/')])==2
 assert first['name']=='数据研究结果' and first['origin']=='platform-execution'
 assert results.products.installed.get('sample.data') is None
 mapped=run(results.map(first['id'],'http://testserver/api/workbench/runtime'))
 project=read_json(results.root/first['id']/'map.geolibre.json')
 assert mapped['bounds']==[114.3,30.6,114.3,30.6] and project['layers'][0]['geojson']==GEO


@pytest.mark.parametrize('identity',['../private','https://example.org/result','f'*31,None])
def test_import_requires_a_platform_execution_id(tmp_path,identity):
 results,seen,_=setup(tmp_path)
 with pytest.raises(RegistrationError):run(results.import_platform_execution(identity))
 assert not seen


def test_foreign_or_deleted_call_never_becomes_a_private_map(tmp_path):
 results,_,_=setup(tmp_path,denial=True)
 with pytest.raises(RegistrationError):run(results.import_platform_execution(CALL))
 assert not results.list()


@pytest.mark.parametrize('output',[{'task_state':'submitted','preview':GEO},{'statistics':[{'mean':1}]},{'preview':{'type':'FeatureCollection','features':[]}}])
def test_pending_and_nonspatial_results_do_not_claim_a_map(tmp_path,output):
 results,_,_=setup(tmp_path,output)
 with pytest.raises(RegistrationError):run(results.import_platform_execution(CALL))
 assert not results.list()


def test_artifact_uses_platform_owner_gateway_not_node_token_and_checks_hash(tmp_path):
 artifact={'name':'result.tif','href':'/results/'+'c'*32+'/result.tif','bytes':4,'sha256':hashlib.sha256(b'data').hexdigest(),'access_token':'private-node-artifact-token'}
 results,seen,_=setup(tmp_path,{'artifacts':[artifact]})
 record=run(results.import_platform_execution(CALL))
 assert 'access_token' not in json.dumps(record)
 assert 'private-node-artifact-token' not in (results.root/record['id']/'result.json').read_text()
 path=run(results.artifact(record['id'],'result.tif'));assert path.read_bytes()==b'data'
 assert seen[-1]==('GET','/api/v1/node-executions/'+CALL+'/artifacts/result.tif','Bearer member-only-token')
 path.write_bytes(b'tampered')
 with pytest.raises(RegistrationError,match='校验失败'):run(results.artifact(record['id'],'result.tif'))


def test_cached_import_still_obeys_platform_owner_denial(tmp_path):
 results,_,_=setup(tmp_path);run(results.import_platform_execution(CALL))
 results.nodes.transport=httpx.MockTransport(lambda req:httpx.Response(404,json={'detail':'not found'}))
 with pytest.raises(RegistrationError):run(results.import_platform_execution(CALL))


def test_viewer_route_requires_scoped_identity_and_returns_same_origin_entry(tmp_path,monkeypatch):
 monkeypatch.setenv('GEONEXUS_HARNESS_GATEWAY_KEY',KEY);app=create_app(tmp_path)
 def response(request):
  if request.url.path.startswith('/api/v1/geocards/'):return httpx.Response(200,json={'geocard':{'name':'图层'}})
  return httpx.Response(200,json={'id':CALL,'status':'succeeded','card_ref':'sample.data','node_ref':'node','result':{'outputs':{'preview':GEO,'artifacts':[]}}})
 async def check():
  async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as client:
   session=await client.get('/api/session',headers=signed('/api/session'));body=session.json()
   child=next(iter(app.state.children.values()));child.state.resource_nodes.transport=httpx.MockTransport(response)
   path='/api/workbench/platform-results/map';headers={**signed(path,method='POST'),'X-Geo-CSRF':body['csrf'],'Origin':'http://127.0.0.1:9305'}
   denied=await client.post(path,headers=signed(path,method='POST'),json={'execution_id':CALL,'enable_viewer':True});assert denied.status_code==403
   good=await client.post(path,headers=headers,json={'execution_id':CALL,'enable_viewer':True});assert good.status_code==200,good.text
   value=good.json();assert value['layers']==1 and value['execution_id']==CALL
   assert value['viewer_entry'].startswith('http://127.0.0.1:9305/api/workbench/runtime/viewer/')
   assert 'member-a-private' not in good.text
   assert child.state.products.installed[MAP_ID]['enabled']
 asyncio.run(check())


def test_platform_raster_uses_native_tiles_and_real_pixel_colors(tmp_path):
 import io, numpy as np, rasterio
 from rasterio.transform import from_bounds
 from PIL import Image
 from geo_harness.raster_preview import render_tile
 path=tmp_path/'fixture.tif'
 with rasterio.open(path,'w',driver='GTiff',width=2,height=2,count=1,dtype='float32',crs='EPSG:4326',transform=from_bounds(-180,-85,180,85,2,2),nodata=-9999) as src:
  src.write(np.array([[0,100],[-9999,50]],dtype='float32'),1)
 image=np.array(Image.open(io.BytesIO(render_tile(path,1,[0,100],0,0,0))))
 assert image.shape==(256,256,4)
 assert (image[64,64,:3]==[68,1,84]).all() and image[64,64,3]==255
 assert (image[64,192,:3]==[253,231,37]).all()
 assert image[192,64,3]==0 and image[192,192,3]==255
 artifact={'name':'result.tif','href':'/results/'+'c'*32+'/result.tif','bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
 results,_,data=setup(tmp_path/'workspace',{'artifacts':[artifact],'raster_preview':{'band':1,'stretch':[0,100]}})
 def handler(req):
  if '/artifacts/' in req.url.path:return httpx.Response(200,content=path.read_bytes())
  if '/geocards/' in req.url.path:return httpx.Response(200,json={'geocard':{'name':'真实栅格'}})
  return httpx.Response(200,json=data)
 results.nodes.transport=httpx.MockTransport(handler)
 record=run(results.import_platform_execution(CALL));run(results.map(record['id'],'http://testserver/api/workbench/runtime'))
 layer=read_json(results.root/record['id']/'map.geolibre.json')['layers'][0]
 assert layer['type']=='xyz' and '/tiles/result.tif/{z}/{x}/{y}.png' in layer['source']['tiles'][0]
 assert layer['source']['bounds']==[-180,-85,180,85] and layer['source']['maxzoom']==18


@pytest.mark.parametrize('coords', [(-1,0,0),(19,0,0),(0,1,0),(2,-1,0)])
def test_display_tiles_reject_invalid_coordinates(tmp_path,coords):
 from geo_harness.raster_preview import render_tile
 with pytest.raises(RegistrationError):render_tile(tmp_path/'no-file.tif',1,None,*coords)
