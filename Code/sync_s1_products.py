from utils import create_connection, read_config
import requests
import time
from datetime import datetime, timedelta

keys = ['uuid', 'identifier', 'filename', 'beginposition', 'endposition', 'orbitnumber',  
        'orbitdirection', 'footprint']

def read_polygon(polygon_path):
    """Opens the txt file containing the AOI polygon and returns it"""
    with open(polygon_path) as f:
        polygon = f.read()
    
    return polygon

def get_page(res):
    """Get one page of results from OpenSearch"""

    # Opensearch information fields
    os_fields = ['str', 'date', 'int']
    product_list = []

    product_json = res['feed']['entry']
    
    # If only one product is returned
    if isinstance(product_json, dict):
        product_json = [product_json]

    for product in product_json:
        prod = {}
        
        for field in os_fields:
            for info in product[field]:
                for key in keys:
                    if key == info['name']:
                        prod[key] = info['content']
                        break

        prod['info_link'] = product['link'][1]['href']
        prod['dl_link'] = product['link'][0]['href']

        product_list.append(prod)
    
    return product_list
            
def get_products(session, os_url):
    """Returns all found products. 
    Returns None if no products are found"""

    page = 0
    product_page = []
    product_list = []

    while len(product_page) == 100 or page == 0:
        r = session.get(os_url)

        try:
            r.raise_for_status()
            res = r.json()

            # Check for 0 results
            if 'entry' not in res['feed']:
                return

            product_page = get_page(res)
            product_list.extend(product_page)

            # Get 'next' link            
            for link in res['feed']['link']:
                if link['rel'] == 'next':
                    os_url = link['href']
            
            page += 1

        except requests.exceptions.HTTPError as e:
            raise e
        
        time.sleep(0.5)

    return product_list

if __name__ == '__main__':

    # Load config
    config = read_config('config.ini')

    con = create_connection(config['Path']['Database'])
    cur = con.cursor()

    # Get datetime of the most recently synced product
    table_name = config['Database']['Table']
    sql = 'SELECT beginposition FROM {} ORDER BY beginposition DESC LIMIT 1'.format(table_name)
    last_product = cur.execute(sql).fetchall()

    if len(last_product) != 0:
        # Due to the datetime being inclusive in opensearch, we add one second
        # to avoid getting the last product in the results
        last_product = datetime.strptime(last_product[0][0], "%Y-%m-%dT%H:%M:%S.%fZ") + timedelta(seconds=1)
        last_product = last_product.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        # If no products exist in the DB, get the start sync date
        last_product = config['Scihub']['Date_From']

    # Read variables from config
    base_url = config['Scihub']['Url']
    date_to = config['Scihub']['Date_To']

    # Read simplified polygon file
    file_api = "{}_api.txt".format(config['Preprocess']['SHP'][:-4])
    polygon = read_polygon(file_api)

    print(f"Starting sync from {last_product} TO {date_to}")

    # Build the OpenSearch query
    os_url = f"""{base_url}search?q=\
beginposition:[{last_product} TO {date_to}] AND endposition:[{last_product} TO {date_to}] AND \
platformname:Sentinel-1 AND producttype:GRD AND \
footprint:"Intersects({polygon})"\
&start=0&rows=100&orderby=beginposition desc&format=json"""

    session = requests.Session()
    session.auth = (config['Scihub']['Username'], config['Scihub']['Password'])

    products = get_products(session, os_url)

    if products:
        print("Products to sync: ", len(products))

        # Get list of existing products
        products_exist = list(prd[0] for prd in cur.execute('SELECT id FROM {}'.format(table_name)).fetchall())

        beginposition = ""

        for product in products:
            # Skip products having the same beginposition
            if beginposition == product['beginposition']:
                continue
            beginposition = product['beginposition']

            # Insert product in database
            if product['uuid'] not in products_exist:
                cur.execute('INSERT INTO {} values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'.format(table_name), (
                    product['uuid'], product['identifier'], product['filename'], product['beginposition'], product['endposition'], 
                    product['orbitnumber'], product['orbitdirection'], product['footprint'], product['info_link'], product['dl_link'], 
                    "", 0, 0, 0, 0
                ))

        con.commit()

        # Print the most recent synced product
        last_product = cur.execute('SELECT beginposition FROM {} ORDER BY beginposition DESC LIMIT 1'.format(table_name)).fetchall()
        print("Last product synced: ", last_product[0][0])
    else:
        print("No products to sync")

    con.close()

