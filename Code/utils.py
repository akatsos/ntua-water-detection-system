import os
import sqlite3
import configparser

def create_connection(db_file):
    """Create a database connection to an SQLite database"""
    con = None
    try:
        con = sqlite3.connect(db_file)
    except sqlite3.Error as e:
        print(e)

    return con

def read_config(conf_path):
    """Read and parse the configuration file"""
    config = configparser.ConfigParser()
    config.read(conf_path)

    return config

def build_preprocessed_path(product, preprocessed_path):
    """Build the full path to the preprocessed folder"""

    sat = product['title'].split('_')[0]
    folder = product['title'].split('_')[4] + '_' + product['title'].split('_')[-1] + '/'
    
    full_preprocessed_path = os.path.join(preprocessed_path, sat, folder)

    return full_preprocessed_path