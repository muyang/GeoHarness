"""Bounded display tiles from verified private rasters, never analytical outputs."""
from io import BytesIO
import math
from geonexus.registration import RegistrationError

def preview_band(preview):
    """Use explicit numeric indexes; legacy band labels describe the first band."""
    band = preview.get('band_index', preview.get('band', 1))
    if isinstance(band, str) and 'band_index' not in preview:
        return 1
    if type(band) is float and math.isfinite(band) and band.is_integer():
        band = int(band)
    if type(band) is not int or band < 1:
        raise RegistrationError('栅格预览波段编号无效。')
    return band

def render_tile(path, band, stretch, z, x, y):
    import numpy as np
    import rasterio
    from rasterio.transform import from_bounds
    from rasterio.warp import reproject, Resampling
    from PIL import Image
    if not 0 <= z <= 18 or not (0 <= x < 2**z and 0 <= y < 2**z):
        raise RegistrationError('无效地图瓦片坐标。')
    size=256; half=20037508.342789244; span=2*half/(2**z)
    transform=from_bounds(-half+x*span,half-(y+1)*span,-half+(x+1)*span,half-y*span,size,size)
    with rasterio.open(path) as src:
        if not src.crs or type(band) is not int or not 1 <= band <= src.count:
            raise RegistrationError('栅格缺少坐标参考系或有效波段。')
        # Compressed file bytes alone do not bound decoded memory.
        if src.width*src.height > 16_000_000:
            raise RegistrationError('该栅格超过轻量地图预览的像元限制，请下载或使用专业工具。')
        values=src.read(band,masked=True).astype('float32').filled(np.nan)
        valid=values[np.isfinite(values)]
        low,high=stretch if isinstance(stretch,list) and len(stretch)==2 and all(type(v) in {int,float} and math.isfinite(v) for v in stretch) and stretch[1]>stretch[0] else (np.percentile(valid,[2,98]) if valid.size else [0,1])
        target=np.full((size,size),np.nan,dtype='float32')
        reproject(values,target,src_transform=src.transform,src_crs=src.crs,src_nodata=np.nan,dst_transform=transform,dst_crs='EPSG:3857',dst_nodata=np.nan,resampling=Resampling.nearest,num_threads=1)
    alpha=np.isfinite(target)
    scaled=np.clip(np.nan_to_num((target-low)/max(float(high-low),1e-12)),0,1)
    palette=np.array([[68,1,84],[59,82,139],[33,145,140],[94,201,98],[253,231,37]])
    colors=np.stack([np.interp(scaled,np.linspace(0,1,5),palette[:,c]) for c in range(3)],axis=-1).astype('uint8')
    rgba=np.dstack((colors,alpha.astype('uint8')*255));out=BytesIO();Image.fromarray(rgba).save(out,format='PNG');return out.getvalue()
