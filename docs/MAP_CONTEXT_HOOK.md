# 地图上下文钩子（Platform `/map-viewer.html` → GeoHarness）

服务端已就绪：`Workbench.sync` 接收 `active_tool`，`context()` 在无待确认动作时回退到它。
地图侧只需把**变化后**的状态上报到现有 `POST /api/workbench/sync`，无需新增端点。

## 契约

```json
{
  "revision": 42,
  "viewport": {"center": [115.0, 20.0], "zoom": 5.4, "bbox": [89.7, -10.05, 140.8, 50.2]},
  "layers": ["rfi-sites", "basemap"],
  "selection": {"kind": "features", "ids": ["site-0091"]},
  "active_tool": {"id": "terrain.slope", "state": "armed", "args": {"method": "horn"}}
}
```

- `layers` 只报**已加载图层的 id**（服务端与项目图层对齐，未知 id 会被忽略）。
- `active_tool.state` 取值 `idle | armed | running | done | error`；`armed` 表示等待用户确认。
- `revision` 由查看器维护，单调递增；服务端把它写进 `context().revision` 供模型判断新鲜度。

## 最小实现（放到查看器初始化处）

```js
const HARNESS = new URL(window.location.href).searchParams.get('harness') || ''; // 嵌入时的 GeoHarness 源
let revision = 0, timer = null;

async function csrf() {
  const r = await fetch(`${HARNESS}/api/session`, { credentials: 'include' });
  return (await r.json()).csrf;
}

function snapshot(map, activeTool) {
  revision += 1;
  return {
    revision,
    viewport: {
      center: map.getCenter().toArray(),
      zoom: map.getZoom(),
      bbox: bboxOf(map.getBounds())          // [west, south, east, north]
    },
    layers: loadedLayerIds(),                 // 与项目图层 id 对齐
    selection: currentSelection(),            // {kind, ids} 或 null
    active_tool: activeTool || { id: null, state: 'idle', args: {} }
  };
}

async function push(map, activeTool) {
  clearTimeout(timer);
  timer = setTimeout(async () => {
    try {
      await fetch(`${HARNESS}/api/workbench/sync`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', 'X-Geo-CSRF': await csrf() },
        body: JSON.stringify(snapshot(map, activeTool))
      });
    } catch (e) { /* 断网时保留下一次变化再推，服务端以 revision 判定新鲜度 */ }
  }, 300);                                     // 200–500ms 防抖
}

map.on('moveend', () => push(map, currentTool()));
map.on('zoomend', () => push(map, currentTool()));
map.on('styledata', () => push(map, currentTool()));
layerPanel.addEventListener('change', () => push(map, currentTool()));
toolPanel.addEventListener('change', () => push(map, currentTool()));
```

## 验收

1. 在 Platform `/cases` 打开 Durham（或任一地图），移动/缩放后 500ms 内 `GET /api/workbench/project` 的 `revision` 增加；
2. 打开“坡度分析”工具（armed）后，会话里让主智能体读 `map_context`，返回的 `active_tool.id` 为 `terrain.slope`、`state` 为 `armed`；
3. 让 Agent 请求 `layer.remove`：返回 400 + 原因（需 `_policy_confirm=true` 重试）；UI 点击删除不受影响。

## 说明

- Platform 侧属跨仓改动：只加这一个 `push(...)` 与三处事件监听，不改路由、不改鉴权。
- 若查看器与 GeoHarness 不同源，`credentials: 'include'` 需要网关放行 CORS 与 Cookie；嵌入式部署（同源 `/map-viewer.html`）无需额外配置。
