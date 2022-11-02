from utils import create_connection, read_config
import os
import sqlite3
import requests
import hashlib


def get_checksum(session, info_link):
    """Get checksum from OData"""
    r = session.get(info_link+'?$format=json')

    try:
        r.raise_for_status()
        res = r.json()

        checksum = res['d']['Checksum']['Value']
        return checksum

    except requests.exceptions.HTTPError as e:
        raise e

def compare_checksums(file_path, checksum):
    """Calculates the MD5 checksum of the downloaded product.
    Then compares it to the one reported on Scihub to check if the download is valid."""

    if os.path.isfile(file_path):
        with open(file_path, "rb") as f:
            file_hash = hashlib.md5()
            chunk = f.read(8192)
            while chunk:
                file_hash.update(chunk)
                chunk = f.read(8192)

        if file_hash.hexdigest() == checksum:
            return True

    return False

def download_product(session, filename, dl_link, dl_path, checksum):
    """Download product and compare checksum for verification"""

    filename = filename + '.zip'
    
    file_path = os.path.join(dl_path, filename)

    # Check if product has already been downloaded
    if compare_checksums(file_path, checksum):
        print(f'{filename} already downloaded')
        return True

    print(f'Downloading {filename}')
    # Download product
    with session.get(dl_link, stream=True) as r:
        print("Status: ", r.status_code, dl_link)

        if r.status_code == 403:
            print('Returned 403')
            raise KeyboardInterrupt

        if r.status_code != 500 or r.status_code != 202:
            with open(file_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192): 
                    f.write(chunk)
        else:
            return False


    # Check if product downloaded correctly
    if compare_checksums(file_path, checksum):
        print('Downloaded Correctly.')
        return True

    # If product failed to be downloaded correctly
    return False


if __name__ == '__main__':

    # Load config
    config = read_config('config.ini')

    dl_path = config['Path']['Download']

    # Create SQLite connection
    con = create_connection(config['Path']['Database'])
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # Get not downloaded products
    products_down = cur.execute('SELECT * FROM s1_products WHERE downloaded=0 ORDER BY beginposition DESC')
    products_down = [dict(row) for row in cur.fetchall()]

    # Create session
    session = requests.Session()
    session.auth = (config['Scihub']['Username'], config['Scihub']['Password'])
    session.headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36'}
    
    try: 
        if len(products_down) != 0:
            for product in products_down:

                checksum = product['checksum']
                # Get checksum if it doesn't exist
                if not checksum:
                    checksum = get_checksum(session, product['info_link'])

                    cur.execute('UPDATE s1_products SET checksum = ? WHERE id = ?', (checksum, product['id']))
                    con.commit()

                # Download product
                if download_product(session, product['title'], product['dl_link'], dl_path, checksum):
                    cur.execute('UPDATE s1_products SET downloaded = 1 WHERE id = ?', (product['id'],))
                    con.commit()
                # Check if checksum has been changed on scihub
                else:
                    checksum = get_checksum(session, product['info_link'])

                    cur.execute('UPDATE s1_products SET checksum = ? WHERE id = ?', (checksum, product['id']))
                    con.commit()
        else:
            print('No products to download')
    except KeyboardInterrupt:
        print('Exiting...')
    finally:
        con.close()