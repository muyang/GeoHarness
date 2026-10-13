"""Native workflow preview metadata can label a band instead of indexing it."""
from io import BytesIO
import numpy as np
import pytest
import rasterio
from PIL import Image
from rasterio.transform import from_bounds
from geo_harness.raster_preview import preview_band, render_tile
from geonexus.registration import RegistrationError

@pytest.mark.parametrize('preview,expected', [
    ({}, 1), ({'band': '归一化光谱指数 NDVI'}, 1),
    ({'band': 2}, 2), ({'band': 2.0}, 2),
    ({'band': 'population', 'band_index': 3}, 3),
])
def test_preview_numeric_index_and_legacy_label(preview, expected):
    assert preview_band(preview) == expected

@pytest.mark.parametrize('band', [True, 0, -1, 1.5, float('nan'), float('inf'), 'NDVI'])
def test_invalid_explicit_band_index_is_not_silently_changed(band):
    with pytest.raises(RegistrationError):
        preview_band({'band_index': band})

def test_real_geotiff_legacy_label_renders_valid_pixels_and_transparent_nodata(tmp_path):
    path = tmp_path / 'ndvi.tif'
    values = np.array([[0.2, 0.4], [0.6, -9999]], dtype='float32')
    with rasterio.open(path, 'w', driver='GTiff', width=2, height=2, count=1,
                       dtype='float32', crs='EPSG:4326', nodata=-9999,
                       transform=from_bounds(0, 0, 10, 10, 2, 2)) as dst:
        dst.write(values, 1)
    raw = render_tile(path, preview_band({'band': '归一化光谱指数 NDVI'}), [0, 1], 5, 16, 15)
    image = Image.open(BytesIO(raw))
    alpha = np.asarray(image)[:, :, 3]
    assert image.size == (256, 256) and image.mode == 'RGBA'
    assert (alpha == 255).sum() > 1000 and (alpha == 0).sum() > 1000
    with pytest.raises(RegistrationError):
        render_tile(path, 2, [0, 1], 5, 16, 15)
