/** Cesium 渲染器（3D 地球，内置）。
 *
 *  动态 import：不选 3D 就不付这份包体。静态资源（Workers/Assets/Widgets）由
 *  scripts/copy-cesium.mjs 拷到 public/cesium/，运行时经 CESIUM_BASE_URL 取。
 *  影像用 OSM，不依赖 Cesium ion 令牌 —— 开箱即看，不许把"要注册令牌"当默认路径。
 */
import { bboxOf } from './maplibre.js'

export const cesiumRenderer = {
  id: 'cesium',
  name: 'Cesium · 3D 地球',
  dims: '3d',

  async create(container, opts = {}) {
    if (!window.CESIUM_BASE_URL) window.CESIUM_BASE_URL = '/cesium/'
    const Cesium = await import('cesium')
    await import('cesium/Build/Cesium/Widgets/widgets.css')

    const viewer = new Cesium.Viewer(container, {
      baseLayerPicker: false,
      geocoder: false,
      homeButton: false,
      sceneModePicker: false,
      navigationHelpButton: false,
      animation: false,
      timeline: false,
      fullscreenButton: false,
      infoBox: true,
      selectionIndicator: true,
      imageryProvider: new Cesium.OpenStreetMapImageryProvider({
        url: 'https://tile.openstreetmap.org/'
      })
    })
    viewer.scene.globe.baseColor = Cesium.Color.fromCssColorString('#0B1220')
    viewer.camera.setView({
      destination: Cesium.Cartesian3.fromDegrees(
        opts.center?.[0] ?? 110, opts.center?.[1] ?? 30, opts.height ?? 20000000)
    })

    const sources = []
    return {
      kind: '3d',
      async renderGeoJSON(fc, { name = '', color = '#3CE6B0' } = {}) {
        const ds = await Cesium.GeoJsonDataSource.load(fc, {
          clampToGround: true,
          stroke: Cesium.Color.fromCssColorString(color),
          fill: Cesium.Color.fromCssColorString(color).withAlpha(0.25),
          markerColor: Cesium.Color.fromCssColorString(color)
        })
        ds.name = name || 'layer'
        viewer.dataSources.add(ds)
        sources.push(ds)
        const b = bboxOf(fc)
        if (b) this.fit(b)
        return { layerId: ds.name, name: ds.name, bbox: b }
      },
      fit(bbox) {
        viewer.camera.flyTo({
          destination: Cesium.Rectangle.fromDegrees(bbox[0], bbox[1], bbox[2], bbox[3]),
          duration: 0.8
        })
      },
      removeLayer(layerId) {
        const ds = viewer.dataSources.getByName(layerId)[0]
        if (ds) viewer.dataSources.remove(ds, true)
        const i = sources.indexOf(ds)
        if (i >= 0) sources.splice(i, 1)
      },
      clear() {
        for (const ds of sources) viewer.dataSources.remove(ds, true)
        sources.length = 0
      },
      destroy() {
        if (!viewer.isDestroyed()) viewer.destroy()
      }
    }
  }
}
