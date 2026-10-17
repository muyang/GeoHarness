"""Private result history and GeoLibre presentation; execution stays on GeoNodes."""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
import uuid
from datetime import datetime, timezone

import httpx
from geonexus.registration import RegistrationError

from .core import inside, read_json, write_private
from .fixtures import MAP_ID
from .resource_nodes import endpoint

MAX_ARTIFACT = 16 * 1024 * 1024
NAME = re.compile(r"[A-Za-z0-9_.-]{1,80}")


def payload(result):
    """Unwrap Platform / GeoMCP envelopes without interpreting scientific values."""
    value = result
    for _ in range(3):
        if not isinstance(value, dict):
            return {}
        if isinstance(value.get("outputs"), dict):
            return value["outputs"]
        if isinstance(value.get("result"), dict):
            value = value["result"]
        else:
            return value
    return value


def geographic_preview(value):
    preview = value.get("preview")
    if not preview and value.get("type") == "FeatureCollection":
        preview = value
    if not preview and isinstance(value.get("items"), list):
        # STAC search results: draw footprints, never embed signed asset URLs.
        preview = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": item.get("geometry"),
                    "properties": {"id": item.get("id"), **item.get("properties", {})},
                }
                for item in value["items"]
                if item.get("geometry")
            ],
        }
    if not isinstance(preview, dict) or preview.get("type") != "FeatureCollection":
        return None, None
    if preview.get("crs"):
        # RFC 7946 has no CRS member. Do not silently relabel projected coordinates.
        crs = preview["crs"]
        if "4326" not in str(crs) and "CRS84" not in str(crs):
            raise RegistrationError("矢量结果需要声明并转换为 WGS84 后才能在地图中显示。")
    points = []

    def visit(coords):
        if not isinstance(coords, list):
            return
        if len(coords) >= 2 and all(type(x) in {float, int} for x in coords[:2]):
            x, y = coords[:2]
            if (
                not math.isfinite(x)
                or not math.isfinite(y)
                or not -180 <= x <= 180
                or not -90 <= y <= 90
            ):
                raise RegistrationError("矢量坐标不是有效 WGS84 坐标，已停止地图转换。")
            points.append((x, y))
        else:
            for child in coords:
                visit(child)

    def geometry(g):
        if not isinstance(g, dict):
            return
        if g.get("type") == "GeometryCollection":
            for child in g.get("geometries", []):
                geometry(child)
        else:
            visit(g.get("coordinates"))

    for feature in preview.get("features", []):
        geometry(feature.get("geometry"))
    bounds = (
        [
            min(p[0] for p in points),
            min(p[1] for p in points),
            max(p[0] for p in points),
            max(p[1] for p in points),
        ]
        if points
        else None
    )
    return preview, bounds


class Results:
    def __init__(self, workspace, products, nodes):
        self.root = workspace / "resource-results"
        self.products, self.nodes = products, nodes
        self.locks = {}

    def record(self, identity):
        if not re.fullmatch(r"[a-f0-9]{32}", identity):
            raise RegistrationError("结果不存在。")
        value = read_json(self.root / identity / "record.json", None)
        if not value:
            raise RegistrationError("结果不存在。")
        return value

    def list(self, product_id=None):
        records = [read_json(p) for p in self.root.glob("*/record.json")]
        return sorted(
            (r for r in records if not product_id or r["product_id"] == product_id),
            key=lambda r: r["created_at"],
            reverse=True,
        )

    def save(self, product_id, tool, result):
        identity = uuid.uuid4().hex
        product = self.products.installed[product_id]
        manifest = self.products.verify(self.products.active_path(product_id))
        value = payload(result)
        artifacts = value.get("artifacts", [])
        artifacts = [
            a
            for a in artifacts
            if isinstance(a, dict)
            and NAME.fullmatch(a.get("name", ""))
            and a["name"] not in {".", ".."}
            and re.fullmatch(r"[a-f0-9]{64}", a.get("sha256", ""))
        ]
        record = {
            "id": identity,
            "product_id": product_id,
            "name": (
                read_json(inside(self.products.active_path(product_id), manifest["cards"][0])).get(
                    "name"
                )
                if manifest.get("cards")
                else manifest["name"]
            ),
            "tool": tool,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "digest": product["digest"],
            "version": product["version"],
            "node_run_id": value.get("run_id"),
            "status": result.get("status", value.get("status", "returned")),
            "synthetic": value.get("synthetic"),
            "summary": value.get("summary", {}),
            "provenance": value.get("provenance", {}),
            "limitations": value.get("limitations", []),
            "artifacts": artifacts,
            "cached": [],
            "map_available": bool(
                value.get("preview")
                or value.get("items")
                or value.get("type") == "FeatureCollection"
                or any(a["name"].endswith((".tif", ".tiff", ".geojson")) for a in artifacts)
            ),
        }
        folder = self.root / identity
        folder.mkdir(parents=True, mode=0o700)
        write_private(folder / "result.json", result)
        write_private(folder / "record.json", record)
        return record

    async def import_platform_execution(self, execution_id):
        """Reference an owned, completed Platform call; never execute the capability again."""
        if not isinstance(execution_id, str) or not re.fullmatch(r'[a-f0-9]{32}', execution_id):
            raise RegistrationError('运行编号格式不正确。')
        node = self.nodes.platform
        async with self.locks.setdefault(('platform-call', node['endpoint'], execution_id), asyncio.Lock()):
            result = await self.nodes.request(node, 'GET', '/api/v1/node-executions/' + execution_id, authenticated=True)
            if result.get('id') != execution_id or result.get('status') != 'succeeded':
                raise RegistrationError('此运行尚未完成，不能生成成果地图。')
            value = payload(result)
            if value.get('task_state') in {'submitted', 'running', 'queued'} or value.get('status') in {'submitted', 'running', 'queued'}:
                raise RegistrationError('节点计算尚未完成；请确认完成后查看成果地图。')
            # Recheck ownership through Platform on every import, even for a cached map.
            for record in self.list():
                if record.get('platform_execution_id') == execution_id and record.get('platform_endpoint') == node['endpoint']:
                    return record
            artifacts = [
                {k: a[k] for k in ('name', 'href', 'bytes', 'sha256', 'media_type') if k in a}
                for a in value.get('artifacts', []) if isinstance(a, dict)
                and NAME.fullmatch(a.get('name', '')) and a.get('name') not in {'.', '..'}
                and re.fullmatch(r'[a-f0-9]{64}', a.get('sha256', ''))
                and re.fullmatch(r'/results/[a-f0-9]{32}/[A-Za-z0-9_.-]{1,80}', a.get('href', ''))
            ]
            preview, bounds = geographic_preview(value)
            available = bool((preview and preview.get('features') and bounds) or any(a['name'].lower().endswith(('.tif', '.tiff', '.geojson')) for a in artifacts))
            if not available:
                raise RegistrationError('此结果没有可显示的空间数据；仍可查看表格和下载文件。')
            name = result.get('card_ref', 'Platform 数据结果')
            try:
                from urllib.parse import quote
                detail = await self.nodes.request(node, 'GET', '/api/v1/geocards/' + quote(name, safe='') + '?node_ref=' + quote(str(result.get('node_ref', '')), safe=''))
                name = detail.get('geocard', {}).get('name') or name
            except RegistrationError:
                pass  # Completed owned results remain readable if a public card was withdrawn.
            identity = uuid.uuid4().hex
            record = {'id': identity, 'product_id': result.get('card_ref'), 'name': name,
                'origin': 'platform-execution', 'platform_endpoint': node['endpoint'],
                'platform_execution_id': execution_id, 'node_ref': result.get('node_ref'),
                'created_at': datetime.now(timezone.utc).isoformat(),
                'digest': result.get('provenance', {}).get('catalog_sha256'), 'version': 'execution-snapshot',
                'node_run_id': value.get('run_id'), 'status': result['status'], 'synthetic': value.get('synthetic'),
                'summary': value.get('summary', {}), 'provenance': value.get('provenance', {}),
                'limitations': value.get('limitations', []), 'artifacts': artifacts, 'cached': [], 'map_available': True}
            folder = self.root / identity; folder.mkdir(parents=True, mode=0o700)
            def public(x):
                if isinstance(x, dict):
                    return {k: public(v) for k, v in x.items() if k.lower() not in {'access_token', 'session_token', 'api_key', 'authorization', 'password', 'secret', 'token'}}
                if isinstance(x, list):
                    return [public(v) for v in x]
                return x
            write_private(folder / 'result.json', public(result))
            write_private(folder / 'record.json', record)
            return record

    async def fetch_artifact(self, record, artifact):
        if record.get('origin') == 'platform-execution':
            node = self.nodes.platform
            if node['endpoint'] != record.get('platform_endpoint'):
                raise RegistrationError('此成果属于另一平台入口，请从原入口读取。')
        else:
            # Installed products continue to enforce their existing pinned binding.
            package = self.products.active_path(record['product_id'])
            if self.products.installed[record['product_id']]['digest'] != record['digest']:
                raise RegistrationError('产品版本已改变，不能补取旧节点产物。已保存结果仍可查看。')
            manifest = self.products.verify(package)
            binding = read_json(inside(package, manifest.get('binding', 'binding.json')), {})
            if binding.get('transport') in {'mcp', 'streamable-http'} and binding.get('artifact_endpoint'):
                node = {'id': 'artifact-channel', 'protocol': 'geomcp-http', 'endpoint': endpoint(binding['artifact_endpoint'])}
            elif binding.get('transport') == 'resource-node':
                node = self.nodes.node(binding['source_id'])
                if binding['endpoint'] != node['endpoint']:
                    raise RegistrationError('节点入口已改变，已停止读取产物。')
            else:
                raise RegistrationError('此 MCP 产品未声明受信任的产物下载通道。内联矢量结果仍可显示。')
        if not re.fullmatch(
            r"/results/[a-f0-9]{32}/[A-Za-z0-9_.-]{1,80}", artifact.get("href", "")
        ):
            raise RegistrationError("产物不是节点声明的结果路径。")
        size = artifact.get("bytes", MAX_ARTIFACT)
        if type(size) is not int or not 0 < size <= MAX_ARTIFACT:
            raise RegistrationError("地图产物超过 16 MiB，已停止读取。")
        result = read_json(self.root / record["id"] / "result.json")
        if node["protocol"] == "platform":
            if not re.fullmatch(r"[a-f0-9]{32}", result.get("id", "")):
                raise RegistrationError("缺少 Platform 调用记录。")
            path = f"/api/v1/node-executions/{result['id']}/artifacts/{artifact['name']}"
        elif node["protocol"] == "geomcp-http":
            path = artifact["href"]
        else:
            raise RegistrationError("标准 MCP 节点尚未声明 HTTP 产物入口；内联矢量结果可直接显示。")
        target = node["endpoint"] + path
        await self.nodes.check_address(target)
        headers = {"Accept-Encoding": "identity"}
        access_token = artifact.get('access_token')
        if access_token is not None and node['protocol'] != 'platform':
            if not isinstance(access_token, str) or not re.fullmatch(r'[a-f0-9]{32,128}', access_token):
                raise RegistrationError('节点产物访问凭据格式不正确。')
            headers['X-Artifact-Token'] = access_token
        key = self.nodes.credential_value(node["id"])
        if key:
            headers["Authorization" if node["protocol"] == "platform" else "X-API-Key"] = (
                "Bearer " if node["protocol"] == "platform" else ""
            ) + key
        try:
            async with (
                httpx.AsyncClient(
                    transport=self.nodes.transport,
                    trust_env=False,
                    follow_redirects=False,
                    timeout=30,
                ) as client,
                client.stream("GET", target, headers=headers) as response,
            ):
                response.raise_for_status()
                chunks, total = [], 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > size:
                        raise RegistrationError("节点产物超过声明大小。")
                    chunks.append(chunk)
                data = b"".join(chunks)
        except httpx.HTTPError as exc:
            raise RegistrationError("节点产物不可读取，请检查节点登录与下载权限。") from exc
        if ("bytes" in artifact and len(data) != size) or hashlib.sha256(
            data
        ).hexdigest() != artifact["sha256"]:
            raise RegistrationError("节点产物大小或 SHA256 与声明不一致，已停止显示。")
        return data

    async def artifact(self, identity, name):
        record = self.record(identity)
        artifact = next((a for a in record["artifacts"] if a["name"] == name), None)
        if not artifact:
            raise RegistrationError("产物未在结果中声明。")
        async with self.locks.setdefault((identity, name), asyncio.Lock()):
            path = self.root / identity / "artifacts" / name
            if not path.is_file():
                data = await self.fetch_artifact(record, artifact)
                path.parent.mkdir(exist_ok=True, mode=0o700)
                path.write_bytes(data)
                path.chmod(0o600)
            if hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
                raise RegistrationError("缓存产物校验失败。")
            return path

    def viewer(self):
        self.products.active_path(MAP_ID)
        if "workspace:artifacts" not in self.products.installed[MAP_ID]["permissions"]:
            raise RegistrationError("请先授权 GeoLibre 查看工作空间结果。")
        try:
            import geolibre
        except ImportError as exc:
            raise RegistrationError("请安装 GeoLibre 可视化依赖。") from exc
        return geolibre

    async def map(self, identity, base_url):
        geolibre = self.viewer()
        from geolibre import project as gp

        record = self.record(identity)
        value = payload(read_json(self.root / identity / "result.json"))
        preview, bounds = geographic_preview(value)
        project = gp.build_empty_project(name=record["name"] + " · 运行结果")
        if preview and preview["features"]:
            project["layers"].append(
                gp.geojson_layer(
                    record["name"],
                    preview,
                    fillColor="#268779",
                    fillOpacity=0.35,
                    lineColor="#176b5f",
                    lineWidth=2,
                    circleColor="#ef8c45",
                    circleRadius=6,
                )
            )
        rasters = [a for a in record["artifacts"] if a["name"].lower().endswith((".tif", ".tiff"))]
        for index, artifact in enumerate(rasters[:2]):
            path = await self.artifact(identity, artifact["name"])
            raster_preview = value.get("raster_preview", {})
            from .raster_preview import preview_band
            band = preview_band(raster_preview)
            stretch = raster_preview.get("stretch")
            display_rgb = False
            if (value.get('display_preview') or {}).get('role') == 'display-only':
                import rasterio
                with rasterio.open(path) as src:
                    display_rgb = src.count == 3
            project["layers"].append(
                gp.cog_layer(
                    artifact["name"] + " · " + (raster_preview.get("label", "真实栅格") if index == 0 else "中间成果"),
                    f"{base_url}/api/resource-results/{identity}/artifacts/{artifact['name']}",
                    bands=[1, 2, 3] if display_rgb else [band],
                    colormap=None if display_rgb else "viridis",
                    rescale=[stretch] if stretch else None,
                )
            )
            project["layers"][-1]['visible'] = index == 0
            # Derive view from the actual raster geotransform, not a presumed card bbox.
            try:
                import rasterio
                from rasterio.warp import transform_bounds

                with rasterio.open(path) as src:
                    if not src.crs:
                        raise RegistrationError("栅格缺少坐标参考系。")
                    if src.width*src.height > 16_000_000:
                        raise RegistrationError('该栅格超过轻量地图预览的像元限制，请下载或使用专业工具。')
                    bbox = list(transform_bounds(src.crs, "EPSG:4326", *src.bounds))
                bounds = (
                    bbox
                    if bounds is None
                    else [
                        min(bounds[0], bbox[0]),
                        min(bounds[1], bbox[1]),
                        max(bounds[2], bbox[2]),
                        max(bounds[3], bbox[3]),
                    ]
                )
            except ImportError as exc:
                raise RegistrationError("栅格地图需安装 rasterio 坐标读取依赖。") from exc
        if rasters:
            # Use native XYZ display tiles: the embedded COG overlay can load
            # successfully without drawing in GeoLibre's current web renderer.
            for index, artifact in enumerate(rasters[:2]):
                layer=project['layers'][len(project['layers'])-min(2,len(rasters))+index]
                tile=gp.tile_layer(layer['name'],f"{base_url}/api/resource-results/{identity}/tiles/{artifact['name']}/{{z}}/{{x}}/{{y}}.png", bounds=bounds)
                tile['source']['maxzoom']=18
                tile['visible']=index==0
                project['layers'][project['layers'].index(layer)]=tile
        if not project["layers"]:
            # QGIS / declarative MCP artifacts can also provide a verified GeoJSON.
            vector = next((a for a in record["artifacts"] if a["name"].lower().endswith(".geojson")), None)
            if vector:
                path = await self.artifact(identity, vector["name"])
                preview, bounds = geographic_preview(read_json(path))
                if preview and preview["features"]:
                    project["layers"].append(gp.geojson_layer(vector["name"], preview))
        if not project["layers"]:
            raise RegistrationError("此结果没有可显示的地理要素；可查看表格、完整结果和产物。")
        if bounds:
            project["mapView"].update(
                center=[(bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2],
                zoom=max(
                    1,
                    min(
                        15,
                        math.log2(180 / max(bounds[2] - bounds[0], bounds[3] - bounds[1], 0.003)),
                    ),
                ),
            )
        project["metadata"] = {
            "harnessResult": identity,
            "productDigest": record["digest"],
            "provenance": record["provenance"],
            "limitations": record["limitations"],
            "viewer": "opengeos/GeoLibre",
            "viewerVersion": geolibre.__version__,
        }
        write_private(self.root / identity / "map.geolibre.json", project)
        return {
            "project_url": f"{base_url}/api/resource-results/{identity}/project",
            "layers": len(project["layers"]),
            "bounds": bounds,
            "viewer": "GeoLibre",
            "viewer_version": geolibre.__version__,
        }
