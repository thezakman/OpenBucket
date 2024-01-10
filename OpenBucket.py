#!/usr/bin/env python3

import re
import os
import sys
import re
import xml.etree.ElementTree as ElementTree
import requests
import urllib.parse
from urllib.parse import urlparse

version = "1.4"
# OpenBucket
# TheZakMan
# 10/01/2024

'''
                  ,.--'`````'--., 
                 (\'-.,_____,.-'/)
                  \\-.,_____,.-//
                  ;\\         //|
                  | \\_ ___ _// |
                  |  '-[___]-'  |
                  | .0penBucket |
                  `'-.,_____,.-''

                ░▀▀█▀▀░▀▀█▀░█▀▄▀█░░
                ░░ █ ░░▄█▄▄░█░▀░█░░

             C0d3d by TheZakMan with <3
'''

def banner():
    banner = f'''                         
                                                           
- Hey, look! it's a                                        [VERSION {version}]
────────────────────────────────────────────────────────────────────────
 dP"Yb  88""Yb 888888 88b 88 88""Yb 88   88  dP""b8 88  dP 888888 888888 
dP //Yb 88__dP 88__   88Yb88 88__dP 88   88 dP   `" 88odP  88__     88   
Yb// dP 88"""  88""   88 Y88 88""Yb Y8   8P Yb      88"Yb  88""     88   
 YbodP  88     888888 88  Y8 88oodP `YbodP'  YboodP 88  Yb 888888   88                                    
────────────────────────────────────────────────────────────────────────                                                     
                                                      Let's download it!
    '''
    print(banner)

def get_namespace(element):
    m = re.match(r'\{.*\}', element.tag)
    return m.group(0) if m else ''

def create_directory_structure(path):
    if not os.path.exists(path):
        os.makedirs(path)

def download_file(bucket_url, key, out_folder):
    file_path = os.path.join(out_folder, key)
    directory = os.path.dirname(file_path)

    # Cloning the structure 
    create_directory_structure(directory)

    # Download all the files!
    file_url = urllib.parse.urljoin(bucket_url, urllib.parse.quote(key))
    print(f'[+] Downloading {file_url}')
    r = requests.get(file_url)

    if r.status_code == 200:
        with open(file_path, 'wb') as f:
            f.write(r.content)
    else:
        print(f'[!] Failed to download {file_url}. HTTP Status Code: {r.status_code}')

def parse_xml(bucket_list_result, bucket_url, out_folder):
    tree = ElementTree.parse(bucket_list_result)
    root = tree.getroot()
    namespace = get_namespace(root)

    for content in root.findall(f'{namespace}Contents'):
        key = content.find(f'{namespace}Key').text
        if '/' in key:  # check if 'key' is a file in a subfolder
            download_file(bucket_url, key, out_folder)

def retrieve_bucket_list_result(url, out_folder):
    print(f'[+] Downloading bucket list result from {url}')

    # Create out_folder
    create_directory_structure(out_folder)

    bucket_list_file = os.path.join(out_folder, 'content.xml')
    r = requests.get(url)

    if r.status_code == 200:
        with open(bucket_list_file, 'wb') as f:
            f.write(r.content)
        return bucket_list_file
    else:
        print(f'[!] Failed to download the bucket list. HTTP Status Code: {r.status_code}')
        return None


def main():
    if len(sys.argv) >= 2:
        bucket_url = sys.argv[1]
        parsed_url = urlparse(bucket_url)
        bucket_name = parsed_url.netloc  # Get the domain name to use

        out_folder = os.path.join(os.getcwd(), bucket_name)  # DomainName = Folder

        bucket_list_file = retrieve_bucket_list_result(bucket_url, out_folder)
        if bucket_list_file:
            parse_xml(bucket_list_file, bucket_url, out_folder)
    else:
        print('Usage: python download_bucket.py <bucket_url>')

if __name__ == '__main__':
    banner()
    main()
