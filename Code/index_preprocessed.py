from utils import create_connection, read_config, build_preprocessed_path
import os, sys
import subprocess
import sqlite3


if __name__ == '__main__':
    config = read_config('config.ini')
    
    prep_path = config['Path']['Preprocess']
    venv_path = config['Path']['Venv']
    product_file_name = config['Preprocess']['Product_Name']


    # Create SQLite connection
    con = create_connection(config['Path']['Database'])
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # Get preprocessed but not indexed products
    products_down = cur.execute('SELECT * FROM s1_products WHERE preprocessed=1 AND indexed=0 ORDER BY beginposition DESC')
    products_down = [dict(row) for row in cur.fetchall()]

    try:
        if len(products_down) != 0:
            for product in products_down:
                product_name = product['title']
                print(f'Indexing: {product_name}')

                outdir_path = build_preprocessed_path(product, prep_path)

                try:
                    # Get full path to .yml index file
                    yml_file = os.path.join(outdir_path, [f for f in os.listdir(outdir_path) if f.endswith('.yml')][0])
                                    
                except IndexError:
                    print('No index file found (yml). Will try to preprocess again at next run.')
                    
                    # Update DB
                    cur.execute('UPDATE s1_products SET preprocessed = 0 WHERE id = ?', (product['id'],))
                    con.commit()
                    continue

                # Index file
                subprocess.call(f"{venv_path}bin/datacube dataset add {yml_file} -p {product_file_name}", shell=True)
                
                # Update DB
                cur.execute('UPDATE s1_products SET indexed = 1 WHERE id = ?', (product['id'],))
                con.commit()

                print(f'Indexed: {product_name}')
        else:
            print('No products to ingest')
    except KeyboardInterrupt:
            print('Exiting...')
    finally:
        con.close()