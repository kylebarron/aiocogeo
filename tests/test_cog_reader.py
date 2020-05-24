import math

import mercantile
import numpy as np
import pytest
import rasterio
from rasterio.warp import transform_bounds
from rasterio.windows import Window
from rio_tiler.io import cogeo
from rio_tiler import utils as rio_tiler_utils
from shapely.geometry import Polygon

from async_cog_reader.ifd import IFD
from async_cog_reader.tag import Tag
from async_cog_reader.errors import InvalidTiffError

from .conftest import TEST_DATA


@pytest.mark.asyncio
@pytest.mark.parametrize("infile", TEST_DATA)
async def test_cog_metadata(infile, create_cog_reader):
    async with create_cog_reader(infile) as cog:
        with rasterio.open(infile) as ds:
            rio_profile = ds.profile
            cog_profile = cog.profile

            # Don't compare nodata, its not supported yet
            cog_profile.pop("nodata", None)
            rio_profile.pop("nodata", None)

            # Don't compare photometric, rasterio seems to not always report color interp
            cog_profile.pop("photometric", None)
            rio_profile.pop("photometric", None)

            assert rio_profile == cog_profile
            assert ds.overviews(1) == cog.overviews


@pytest.mark.asyncio
@pytest.mark.parametrize("infile", TEST_DATA)
async def test_cog_metadata_overviews(infile, create_cog_reader):
    async with create_cog_reader(infile) as cog:
        for idx, ifd in enumerate(cog.ifds):
            width = ifd.ImageWidth.value
            height = ifd.ImageHeight.value
            try:
                # Test decimation of 2
                next_ifd = cog.ifds[idx + 1]
                next_width = next_ifd.ImageWidth.value
                next_height = next_ifd.ImageHeight.value
                assert pytest.approx(width / next_width, 5) == 2.0
                assert pytest.approx(height / next_height, 5) == 2.0

                # Test number of tiles
                tile_count = ifd.tile_count[0] * ifd.tile_count[1]
                next_tile_count = next_ifd.tile_count[0] * next_ifd.tile_count[1]
                assert (
                    pytest.approx(
                        (
                            max(tile_count, next_tile_count)
                            / min(tile_count, next_tile_count)
                        ),
                        3,
                    )
                    == 4.0
                )
            except IndexError:
                pass


@pytest.mark.asyncio
@pytest.mark.parametrize("infile", TEST_DATA)
async def test_cog_read_internal_tile(infile, create_cog_reader):
    async with create_cog_reader(infile) as cog:
        # Read top left tile at native resolution
        tile = await cog.get_tile(0, 0, 0)
        ifd = cog.ifds[0]

        # Make sure tile is the right size
        assert tile.shape == (
            ifd.TileHeight.value,
            ifd.TileWidth.value,
            ifd.SamplesPerPixel.value,
        )

        # Rearrange numpy array to match rasterio
        tile = np.rollaxis(tile, 2, 0)

        with rasterio.open(infile) as src:
            rio_tile = src.read(
                window=Window(0, 0, ifd.TileWidth.value, ifd.TileHeight.value)
            )
            assert rio_tile.shape == tile.shape
            assert np.allclose(tile, rio_tile, rtol=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("infile", TEST_DATA[:-1])
async def test_cog_read(infile, create_cog_reader):
    async with create_cog_reader(infile) as cog:
        zoom = math.floor(math.log2((2 * math.pi * 6378137 / 256) / cog.geotransform().a))
        centroid = Polygon.from_bounds(*transform_bounds(cog.epsg, "EPSG:4326", *cog.bounds)).centroid
        tile = mercantile.tile(centroid.x, centroid.y, zoom)

        tile_native_bounds = transform_bounds("EPSG:4326", cog.epsg, *mercantile.bounds(tile))

        arr = await cog.read(tile_native_bounds, (256, 256, 3))
        tile_arr, mask = cogeo.tile(infile, tile.x, tile.y, tile.z, tilesize=256, resampling_method="bilinear")

        assert np.allclose(np.rollaxis(arr, 2, 0), tile_arr, rtol=10)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "width,height", [(500, 500), (1000, 1000), (5000, 5000), (10000, 10000)]
)
async def test_cog_get_overview_level(create_cog_reader, width, height):
    async with create_cog_reader(TEST_DATA[0]) as cog:
        ovr = cog._get_overview_level(cog.bounds, width, height)

        with rasterio.open(TEST_DATA[0]) as src:
            expected_ovr = rio_tiler_utils.get_overview_level(
                src, src.bounds, height, width
            )
            # Our index for source data is 0 while rio tiler uses -1
            expected_ovr = 0 if expected_ovr == -1 else expected_ovr
            assert ovr == expected_ovr


@pytest.mark.asyncio
@pytest.mark.parametrize("infile", [TEST_DATA[0]])
async def test_cog_metadata_iter(infile, create_cog_reader):
    async with create_cog_reader(infile) as cog:
        for ifd in cog:
            assert isinstance(ifd, IFD)
            for tag in ifd:
                assert isinstance(tag, Tag)


@pytest.mark.asyncio
async def test_cog_not_a_tiff(create_cog_reader):
    infile = "https://async-cog-reader-test-data.s3.amazonaws.com/not_a_tiff.png"
    with pytest.raises(InvalidTiffError):
        async with create_cog_reader(infile) as cog:
            ...
