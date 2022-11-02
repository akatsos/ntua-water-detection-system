import os
import datacube
import sqlite3
from datetime import datetime
from pathlib import Path
from joblib import load
from utils import read_config, create_connection

import numpy as np
import xarray as xr
import rioxarray as rio
import rasterio
from rasterio.merge import merge
from skimage import morphology

import warnings
warnings.filterwarnings('ignore')

def get_img_min_max_xy(dc, prd, dt):
    """
    Get the minimum and maximum x, y values of an image
    """
    
    result = dc.find_datasets(product=prd, time=(dt, dt))[0]
    
    min_xy = result.metadata_doc['grid_spatial']['projection']['geo_ref_points']['ul']
    max_xy = result.metadata_doc['grid_spatial']['projection']['geo_ref_points']['lr']

    min_x, min_y = min_xy['x'], min_xy['y']
    max_x, max_y = max_xy['x'], max_xy['y']
    
    if min_y > max_y:
        temp_y = min_y
        min_y = max_y
        max_y = temp_y
    
    return min_x, min_y, max_x, max_y


def predict_water(pipeline, dc):
    """
    Predict water pixels in an image.
    """

    vh = dc['VH'].values.squeeze()
    vv = dc['VV'].values.squeeze()
  
    img_shape = vh.shape
    X = np.stack((vh.flatten(), vv.flatten()), axis=1)
    
    predictions = pipeline.predict(X)
    
    del X
    
    p = predictions.reshape((img_shape))
    
    return p


def create_gt_img(water, lat, lon, full_path):
    """
    Create tiff of predicted water pixels in a chunk
    """
    xar = xr.DataArray(water, coords={'y': lat, 'x': lon}, dims=['y', 'x'])
    xar.name = 'water'

    xar = xar.transpose('y', 'x')
    xar.rio.write_crs("epsg:4326", inplace=True)
    xar.rio.write_nodata(0, inplace=True)
    xar.rio.set_spatial_dims(x_dim="x", y_dim='y', inplace=True)

    xar.rio.to_raster(f"{full_path}.tif", compress='LZW', dtype='uint8')
    

def merge_images(full_path, name):
    """
    Merge all tiffs of chunks to form the final image
    """
    products = [full_path + "/" + product for product in os.listdir(full_path) if product.startswith(f'{name}_')]
    src_files_to_mosaic = []

    for fp in products:
        src = rasterio.open(fp)
        src_files_to_mosaic.append(src)

    mosaic, out_trans = merge(src_files_to_mosaic)

    out_meta = src.meta.copy()

    # Update the metadata
    out_meta.update({"driver": "GTiff",
                            "height": mosaic.shape[1],
                            "width": mosaic.shape[2],
                            "transform": out_trans,
                            "compress":"LZW", 
                            "dtype":"uint8"
                        })
    # Save path
    img_path = f'{full_path}/{name}.tif'
    with rasterio.open(img_path, "w", **out_meta) as dest:
        dest.write(mosaic)
    
    # Close temp files
    for src in src_files_to_mosaic:
        src.close()
        
    # Delete temp files
    for product in products:
        os.remove(product)


if __name__ == '__main__':
    dc = datacube.Datacube(app="predict_cut")

    # Load config
    config = read_config('config.ini')
    results_path = config['Path']['Results']

    product_name = config['Preprocess']['Product_Name']
    clf = load(config['Predict']['Model'])

    # Create SQLite connection
    con = create_connection(config['Path']['Database'])
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    products_indexed = cur.execute('SELECT * FROM s1_products WHERE indexed=1 AND detected=0 ORDER BY beginposition DESC')
    products_indexed = [dict(row) for row in cur.fetchall()]

    # Iterate through products/images that haven't been predicted yet
    if products_indexed:
        for product in products_indexed:
            product_title = product['title']
            print('Predicting water for: ', product_title)
            
            # Get datetime of product in the desired datacube format
            dt_strp = datetime.strptime(product['beginposition'], '%Y-%m-%dT%H:%S:%M.%fZ')
            dt_strf = dt_strp.strftime("%Y-%m-%dT%H:%S:%M")
            year = dt_strp.strftime("%Y")
            month = dt_strp.strftime("%m")

            # Create full path to predicted file and
            # check if folder exists and if not create it
            full_path = os.path.join(results_path, year, month)
            Path(full_path).mkdir(parents=True, exist_ok=True)

            # Get image minimum and maximum x, y
            min_x, min_y, max_x, max_y = get_img_min_max_xy(dc, product_name, dt_strf)

            # Break image in smaller chunks based on min and max y
            # to conserve on RAM usage
            # Every chunk is 0.5 degrees of Latitude about 55km - ~5500 image height
            res = int(max_y - min_y) if int(max_y - min_y) != 0 else 0.5 
        
            # Iterate for every chunk
            for i in range(0, int(res*20), 5):
                # Create full path to predicted file and
                # check if folder exists and if not create it
                file_path = os.path.join(full_path, f"{product_title}_{i}")

                # Calculate the desired chunk
                i_l = i/10
                min_y_l, max_y_l = min_y+i_l, min_y+i_l+0.5

                if max_y < max_y_l:
                    max_y_l = max_y
                    
                if min_y_l > max_y_l:
                    break

                # Load the desired chunk
                ds = dc.load(product=product_name,
                    time=(dt_strf, dt_strf),
                    y = (min_y_l, max_y_l),
                    x = (min_x, max_x),
                    resolution = (-0.00008983, 0.00008983),
                    resampling='nearest'
                )
                
                # Predict the selected chunk
                p_w = predict_water(clf, ds)

                # Object/Holes threshold
                p_w = xr.where(p_w == 1, True, False)
                
                # Remove holes/objects
                cleaned_w = morphology.remove_small_holes(p_w, area_threshold=int(config['Predict']['Holes_Threshold']))
                cleaned_w = morphology.remove_small_objects(cleaned_w, min_size=int(config['Predict']['Objects_Threshold']))
                
                del p_w

                # Get lat, long
                lat_w = ds['latitude'].values.squeeze()
                long_w = ds['longitude'].values.squeeze()

                # Create image
                cleaned_w = xr.where(cleaned_w == True, 1, 0)
                create_gt_img(cleaned_w, lat_w, long_w, file_path)

                del cleaned_w, lat_w, long_w
            
            # Merge all the tiffs created for one product
            merge_images(full_path, product_title)

            # Commit to DB
            cur.execute('UPDATE s1_products SET detected = 1 WHERE id = ?', (product['id'],))
            con.commit()

            print('Predicted :', product_title)
    else:
        print('No products to predict')
    
    con.close()