from utils import create_connection, read_config, build_preprocessed_path
from pyroSAR.snap import util
from pyroSAR.datacube_util import Product, Dataset
from pyroSAR.ancillary import find_datasets, groupby
import os
import sqlite3
from pathlib import Path
from osgeo import gdal
import fiona

def cut_preprocessed(proc_files, outdir_path, shp_path, shp_layer, temp_path):
    """Cuts preprocessed VV/VH files to the exact AOI"""

    # Get AOI Upper and Lower x,y
    aoi_shp = fiona.open(shp_path)
    ulx_aoi, lry_aoi, lrx_aoi, uly_aoi = aoi_shp.bounds
    
    # Cut preprocessed VV and VH
    for p_file in proc_files:
        file_path = Path(outdir_path) / p_file

        image_temp_out = Path(temp_path) / p_file

        # Open Image and get corners
        src = gdal.Open(str(file_path))
        ulx, xres, xskew, uly, yskew, yres  = src.GetGeoTransform()
        lrx = ulx + (src.RasterXSize * xres)
        lry = uly + (src.RasterYSize * yres)

        src = None

        # Calculate on which corners to cut
        ulx_crop = ulx if ulx > ulx_aoi else ulx_aoi
        uly_crop = uly if uly < uly_aoi else uly_aoi
        lrx_crop = lrx if lrx < lrx_aoi else lrx_aoi
        lry_crop = lry if lry > lry_aoi else lry_aoi

        print(f"Cutting on: {ulx_crop}, {uly_crop}, {lrx_crop}, {lry_crop}")
        ds = gdal.Warp(str(image_temp_out),
                    str(file_path),
                    outputBounds = (ulx_crop, uly_crop, lrx_crop, lry_crop),
                    format = 'GTiff',
                    multithread=True)


        # Delete original
        os.remove(str(file_path))

        ds = gdal.Warp(str(file_path),
                    str(image_temp_out),
                    cutlineDSName = shp_path,
                    cutlineLayer = shp_layer,
                    cropToCutline = False,
                    format = 'GTiff',
                    multithread=True)

        os.remove(str(image_temp_out))

    print('VH, VV files created correctly.')

    return True

def preprocess(infile_path, outdir_path, shp_path, shp_layer, temp_path, cut_images = False):
    """Preprocess S1 .zip file to VV/VH .tiff
    Cutting VV, VH images based on the provided .shp file can be Enabled/Disabled"""

    # Check if folder exists and if not create it
    Path(outdir_path).mkdir(parents=True, exist_ok=True)

    # Check if file has already been preprocessed
    proc_files = [s for s in os.listdir(outdir_path) if ".tif" in s]
    if len(proc_files):
        print('Already Preprocessed')
        return True

    # Preprocess
    # https://pyrosar.readthedocs.io/en/latest/pyroSAR.html
    wf_file = util.geocode(
        infile=infile_path, 
        outdir=outdir_path, 
        t_srs=4326, spacing=10, polarizations='all', 
        shapefile=shp_path,
        scaling='dB', 
        geocoding_type='Range-Doppler', 
        removeS1BorderNoise=True, 
        removeS1BorderNoiseMethod='pyroSAR', 
        removeS1ThermalNoise=True, 
        offset=None, allow_RES_OSV=False, 
        demName='SRTM 1Sec HGT', 
        externalDEMFile=None, 
        externalDEMNoDataValue=None, 
        externalDEMApplyEGM=True, 
        terrainFlattening=True, 
        basename_extensions=None, 
        test=False, 
        export_extra=None, groupsize=3, cleanup=True, 
        tmpdir=temp_path, 
        gpt_exceptions=None, gpt_args=None, returnWF=True, 
        nodataValueAtSea=False, 
        demResamplingMethod='BILINEAR_INTERPOLATION', 
        imgResamplingMethod='BILINEAR_INTERPOLATION', 
        alignToStandardGrid=False, standardGridOriginX=0, standardGridOriginY=0, 
        speckleFilter='Lee', 
        refarea='gamma0',
        clean_edges=True
    )

    # Check if preprocess was successful and
    # both .tif files exist
    proc_files = [s for s in os.listdir(outdir_path) if ".tif" in s]

    # If preprocess was succesful
    if len(proc_files) == 2:
        if cut_images:
            return cut_preprocessed(proc_files, outdir_path, shp_path, shp_layer, temp_path)
    else:
        # If WorkFlow file exists, delete it
        if len([s for s in os.listdir(outdir_path) if ".xml" in s]) > 0:
            for xml_file in os.listdir(outdir_path):
                wf_file_path = os.path.join(outdir_path, xml_file)
                if os.path.exists(wf_file_path):
                    os.remove(wf_file_path)
                    print(f'WF file deleted {wf_file_path}')
        
        return False
	
def dc_create_index_yml(outdir_path):
    """Create .yml files used by ODC to index the images"""

    # If index file exists, delete it to create a new one
    yml_file = [s for s in os.listdir(outdir_path) if ".yml" in s]
    if len(yml_file) > 0:
        os.remove(os.path.join(outdir_path, yml_file[0]))

    # Find pyroSAR files by metadata attributes
    scenes_s1 = find_datasets(outdir_path, sensor=('S1A', 'S1B'), acquisition_mode='IW')

    # Group the found files by their file basenames
    # Files with the same basename are considered to belong to the same dataset
    grouped = groupby(scenes_s1, 'outname_base')

    # Define the polarization units describing the data sets
    units = {'VV': 'backscatter VV', 'VH': 'backscatter VH'}

    # Create a new product
    with Product(name='S1_GRD',
                product_type='gamma0',
                description='Gamma Naught RTC backscatter') as prod:

        for dataset in grouped:
            with Dataset(dataset, units=units) as ds:

                # Add the dataset to the product
                prod.add(ds)

                try:
                    # Parse datacube indexing YMLs from product and data set metadata
                    prod.export_indexing_yml(ds, outdir_path)
                    print('Index files created.')
                except RuntimeError:
                    print('Indexing YML already exists')

    

if __name__ == '__main__':
    
    # Load Config
    config = read_config('config.ini')
    
    shp_path = config['Preprocess']['SHP']
    shp_layer = config['Preprocess']['Layer']
    dl_path = config['Path']['Download']
    prep_path =  config['Path']['Preprocess']
    temp_path = config['Path']['Temporary']

    # Create SQLite connection
    con = create_connection(config['Path']['Database'])
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # Get downloaded but not preprocessed products
    products_down = cur.execute('SELECT * FROM s1_products WHERE downloaded=1 AND preprocessed=0 ORDER BY beginposition DESC')
    products_down = [dict(row) for row in cur.fetchall()]
    
    try:
        # For every downloaded product preprocess to VV, VH images
        if products_down:
            for product in products_down:
                filename = product['title'] + '.zip'

                downloaded_path = os.path.join(dl_path, filename)
                preprocessed_path = build_preprocessed_path(product, prep_path)
            
                print(f'Preprocessing: ', filename)
                if preprocess(downloaded_path, preprocessed_path, shp_path, shp_layer, temp_path):

                    # Create yml for datacube index
                    dc_create_index_yml(preprocessed_path)

                    # Commit to DB
                    cur.execute('UPDATE s1_products SET preprocessed = 1 WHERE id = ?', (product['id'],))
                    con.commit()
        else:
            print('No products to preprocess')
    except KeyboardInterrupt:
        print('Exiting...')
    finally:
        con.close()
