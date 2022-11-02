from utils import read_config
from pathlib import Path
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String
import fiona
from shapely.geometry import shape
import subprocess

if __name__ == '__main__':

    config = read_config('config.ini')

    # Create SQLite Database
    if not Path(config['Path']['Database']).is_file():
    
        engine = create_engine('{}:///{}'.format(config['Database']['Engine'], config['Path']['Database']), echo = True)
        meta = MetaData()

        products = Table(
            '{}'.format(config['Database']['Table']), meta, 
            Column('id', String, primary_key = True), 
            Column('title', String), 
            Column('filename', String),
            Column('beginposition', String),
            Column('endposition', String),
            Column('orbitnumber', Integer),
            Column('orbitdirection', String),
            Column('footprint', String),
            Column('info_link', String),
            Column('dl_link', String),
            Column('checksum', String),
            Column('downloaded', Integer),
            Column('preprocessed', Integer),
            Column('indexed', Integer),
            Column('detected', Integer),
            sqlite_with_rowid=False
        )

        meta.create_all(engine)


    # Create folders
    app_folders = [
        config['Path']['Temporary'],
        config['Path']['Download'],
        config['Path']['Preprocess'],
        config['Path']['Results']
    ]

    for folder_path in app_folders:
        Path(folder_path).mkdir(parents=True, exist_ok=True)

    # Check if SHP file exists
    if Path(config['Preprocess']['SHP']).is_file():
        # Create simplified polygon for Scihub API call
        with fiona.open(config['Preprocess']['SHP']) as c:
            polygon = next(iter(c))['geometry']
            polygon_shapely = shape(polygon)

            polygon_simplified = str(polygon_shapely.simplify(0.08))

        file_api = "{}_api.txt".format(config['Preprocess']['SHP'][:-4])
        with open(file_api, 'w') as smpl_fl:
            smpl_fl.write(polygon_simplified)
    else:
        print('File {} does not exist.'.format(config['Preprocess']['SHP']))

    
    # Check if trained model exists
    if not Path(config['Predict']['Model']).is_file():
        print('File {} does not exist.'.format(config['Predict']['Model']))
    
    # Add product to datacube
    subprocess.call("{}bin/datacube product add {}".format(config['Path']['Venv'], config['Preprocess']['Product_File']), shell=True)