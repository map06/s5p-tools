import argparse
from os import makedirs
from os.path import exists
import warnings

from functools import partial
import geopandas
from shapely.geometry import mapping
from tqdm import tqdm
import rioxarray
from multiprocessing import Pool, cpu_count


def _export_raster(index, band_name, time_resolution, shapefile, ds):
    export_name = f"{EXPORT_DIR}/{band_name}/{time_resolution}__{ds.time.values[index].strftime('%Y-%m-%d')}.tif"
    if shapefile is not None:
        ds.isel(time=index).rio.clip(shapefile.geometry.apply(
            mapping), shapefile.crs).rio.to_raster(export_name)
    else:
        ds.isel(time=index).rio.to_raster(export_name)


def main(netcdf_file, time_resolution, shp, band_name, chunk_size, num_workers):

    tqdm.write("\n")
    if not exists(netcdf_file):
        tqdm.write(f"The file {netcdf_file} does not exist")
        exit(1)
    else:
        DS = rioxarray.open_rasterio(netcdf_file, chunks={'time': chunk_size})

    while True:
        try:
            band = DS[band_name]
            break
        except KeyError:
            tqdm.write("The band name does not exist. The following bands were found:")
            for variable in DS.data_vars.keys():
                tqdm.write(f'\t{variable}')
            band_name = input("Band name: ")

    ds = band.resample(time=time_resolution).mean(dim='time', skipna=None)

    if shp is not None:
        tqdm.write("Loading and simplifying shapefile...\n")

        # Compute the spatial resolution of the data
        delta_x, delta_y = abs(ds.x[1] - ds.x[0]), abs(ds.y[1] - ds.y[0])
        resolution = min(delta_x, delta_y).values.item(0) / 2

        # Load, reproject and simplify the geometries
        shapefile = geopandas.read_file(shp).to_crs("EPSG:4326")
        shapefile.geometry = shapefile.geometry.simplify(resolution)
    else:
        shapefile = None

    makedirs(f'{EXPORT_DIR}/{band_name}', exist_ok=True)
    num_time = len(ds.time)

    with Pool(processes=num_workers) as pool:
        list(tqdm(pool.imap_unordered(partial(_export_raster,
                                              band_name=band_name,
                                              time_resolution=time_resolution,
                                              shapefile=shapefile,
                                              ds=ds),
                                      range(num_time)), desc="Exporting", total=num_time))
        pool.close()
        pool.join()
    tqdm.write('\nDone\n')


if __name__ == "__main__":

    # Ignore warnings
    warnings.filterwarnings("ignore", category=RuntimeWarning)

    # CLI ARGUMENTS

    parser = argparse.ArgumentParser(
        description='Compress the processed netCDF file into multiple compressed files'
    )

    parser.add_argument(
        'netcdf', help='path to the processed netCDF file', type=str)

    parser.add_argument(
        'band', help='name of the band to export', type=str)

    parser.add_argument(
        '--time-resolution', help='resampling rate of the time dimension', type=str, default='1D')

    parser.add_argument(
        '--shp', help='path to the shapefile (.shp) for masking', type=str)

    # chunk-size:
    parser.add_argument('--chunk-size', help='dask chunk size along the time dimension',
                        type=int, default=200)

    # num-workers:
    parser.add_argument('--num-workers', help='number of workers spawned for compression',
                        type=int, default=cpu_count())

    args = parser.parse_args()

    # PATHS

    # export: directory for compressed files
    EXPORT_DIR = 'compressed'

    main(netcdf_file=args.netcdf,
         time_resolution=args.time_resolution,
         shp=args.shp,
         band_name=args.band,
         chunk_size=args.chunk_size,
         num_workers=args.num_workers)
