import pytest

import numpy as np
import rasterio
from rasterio.windows import Window
from rio_tiler import utils as rio_tiler_utils

from async_cog_reader.ifd import IFD
from async_cog_reader.tag import Tag
from async_cog_reader.constants import COMPRESSIONS, INTERLEAVE
from async_cog_reader.errors import InvalidTiffError

from .conftest import TEST_DATA

@pytest.mark.asyncio
@pytest.mark.parametrize("infile", TEST_DATA)
async def test_cog_metadata(infile, create_cog_reader):
    async with create_cog_reader(infile) as cog:
        first_ifd = cog.ifds[0]

        with rasterio.open(infile) as ds:
            profile = ds.profile
            assert profile['width'] == first_ifd.ImageWidth.value
            assert profile['height'] == first_ifd.ImageHeight.value
            assert profile['transform'] == cog.geotransform()
            assert profile['blockxsize'] == first_ifd.TileWidth.value
            assert profile['blockysize'] == first_ifd.TileHeight.value
            assert profile['compress'] == COMPRESSIONS[first_ifd.Compression.value]
            assert profile['interleave'] == INTERLEAVE[first_ifd.PlanarConfiguration.value]
            assert profile['crs'].to_epsg() == cog.epsg
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
                next_ifd = cog.ifds[idx+1]
                next_width = next_ifd.ImageWidth.value
                next_height = next_ifd.ImageHeight.value
                assert pytest.approx(width / next_width, 5) == 2.0
                assert pytest.approx(height / next_height, 5) == 2.0

                # Test number of tiles
                tile_count = ifd.tile_count[0] * ifd.tile_count[1]
                next_tile_count = next_ifd.tile_count[0] * next_ifd.tile_count[1]
                assert pytest.approx((max(tile_count, next_tile_count) / min(tile_count, next_tile_count)), 3) == 4.0
            except IndexError:
                pass


@pytest.mark.asyncio
@pytest.mark.parametrize("infile", TEST_DATA)
async def test_cog_read_tile(infile, create_cog_reader):
    async with create_cog_reader(infile) as cog:
        # Read top left tile at native resolution
        tile = await cog.get_tile(0,0,0)
        ifd = cog.ifds[0]

        # Make sure tile is the right size
        assert tile.shape == (ifd.TileHeight.value, ifd.TileWidth.value, ifd.SamplesPerPixel.value)

        # Rearrange numpy array to match rasterio
        tile = np.rollaxis(tile, 2, 0)

        with rasterio.open(infile) as src:
            rio_tile = src.read(window=Window(0, 0, ifd.TileWidth.value, ifd.TileHeight.value))
            assert rio_tile.shape == tile.shape
            assert np.allclose(tile, rio_tile, rtol=1)

@pytest.mark.asyncio
@pytest.mark.parametrize("width,height",[(500,500),(1000,1000),(5000,5000),(10000,10000)])
async def test_cog_get_overview_level(create_cog_reader, width, height):
    async with create_cog_reader(TEST_DATA[0]) as cog:
        ovr = cog._get_overview_level(cog.bounds, width, height)

        with rasterio.open(TEST_DATA[0]) as src:
            expected_ovr = rio_tiler_utils.get_overview_level(
                src,
                src.bounds,
                height,
                width
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
