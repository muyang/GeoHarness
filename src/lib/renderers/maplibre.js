/** MapLibre 渲染器（2D，内置默认）。
 *
 *  底图 = OSM 栅格瓦片（联网时可见）+ 深色背景（离线也不白屏 —— 客户端不许
 *  因为拿不到瓦片就装死，业务图层照常画）。
 */
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'

const STYLE = {
  version: 8,
  glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
  sources: {
    osm: {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      attribution: '© OpenStreetMap contributors'
    }
  },
  layers: [
    { id: 'bg', type: 'background', paint: { 'background-color': '#0B1220' } },
    { id: 'osm', type: 'raster', source: 'osm', paint: { 'raster-opacity': 0.9 } }
  ]
}

export const maplibreRenderer = {
  id: 'maplibre',
  name: 'MapLibre · 2D',
  dims: '2d',

  async create(container, opts = {}) {
    const map = new maplibregl.Map({
      container,
      style: STYLE,
      center: opts.center || [110, 30],
      zoom: opts.zoom ?? 2,
      attributionControl: { compact: true }
    })
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), 'top-right')
    await new Promise((resolve) => map.once('load', resolve))

    let n = 0
    const mine = []

    return {
      kind: '2d',
      renderGeoJSON(fc, { name = '', color = '#3CE6B0' } = {}) {
        const sid = `gnx-${Date.now().toString(36)}-${++n}`
        map.addSource(sid, { type: 'geojson', data: fc })
        const layers = [
          [`${sid}-fill`, {
            id: `${sid}-fill`, type: 'fill', source: sid,
            filter: ['match', ['geometry-type'], ['Polygon', 'MultiPolygon'], true, false],
            paint: { 'fill-color': color, 'fill-opacity': 0.25 }
          }],
          [`${sid}-line`, {
            id: `${sid}-line`, type: 'line', source: sid,
            filter: ['match', ['geometry-type'], ['Polygon', 'MultiPolygon', 'LineString', 'MultiLineString'], true, false],
            paint: { 'line-color': color, 'line-width': 1.6 }
          }],
          [`${sid}-pt`, {
            id: `${sid}-pt`, type: 'circle', source: sid,
            filter: ['match', ['geometry-type'], ['Point', 'MultiPoint'], true, false],
            paint: {
              'circle-radius': 5, 'circle-color': color,
              'circle-stroke-color': '#0B1220', 'circle-stroke-width': 1
            }
          }]
        ]
        for (const [id, def] of layers) { map.addLayer(def); mine.push(id) }
        const b = bboxOf(fc)
        if (b) this.fit(b)
        return { layerId: sid, name: name || sid, bbox: b }
      },
      fit(bbox) {
        map.fitBounds([[bbox[0], bbox[1]], [bbox[2], bbox[3]]], { padding: 48, duration: 600 })
      },
      removeLayer(layerId) {
        for (const suf of ['-fill', '-line', '-pt']) {
          if (map.getLayer(layerId + suf)) map.removeLayer(layerId + suf)
        }
        const i = mine.indexOf(layerId)
        if (i >= 0) mine.splice(i, 1)
        if (map.getSource(layerId)) map.removeSource(layerId)
      },
      clear() {
        for (const id of mine) {
          if (map.getLayer(id)) map.removeLayer(id)
        }
        mine.length = 0
        for (const s of Object.keys(map.getStyle().sources)) {
          if (s.startsWith('gnx-')) map.removeSource(s)
        }
      },
      destroy() { map.remove() }
    }
  }
}

/** 从 FeatureCollection 粗算 bbox（渲染器自己算，调用方可以不传）。 */
export function bboxOf(fc) {
  let minX = Infinity; let minY = Infinity; let maxX = -Infinity; let maxY = -Infinity
  const walk = (c) => {
    if (typeof c[0] === 'number') {
      minX = Math.min(minX, c[0]); maxX = Math.max(maxX, c[0])
      minY = Math.min(minY, c[1]); maxY = Math.max(maxY, c[1])
      return
    }
    for (const sub of c) walk(sub)
  }
  const feats = fc?.type === 'FeatureCollection' ? fc.features : [fc]
  for (const f of feats || []) {
    if (f?.bbox?.length === 4) {
      minX = Math.min(minX, f.bbox[0], f.bbox[2]); maxX = Math.max(maxX, f.bbox[0], f.bbox[2])
      minY = Math.min(minY, f.bbox[1], f.bbox[3]); maxY = Math.max(maxY, f.bbox[1], f.bbox[3])
      continue
    }
    if (f?.geometry?.coordinates) walk(f.geometry.coordinates)
  }
  if (minX === Infinity) return null
  return [minX, minY, maxX, maxY]
}
