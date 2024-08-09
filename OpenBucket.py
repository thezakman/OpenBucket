#!/usr/bin/env python3

import re
import os
import sys
import random
import xml.etree.ElementTree as ElementTree
import requests
import urllib.parse
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

version = "1.9"

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

user_agents = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3",
    "Mozilla/5.0 (Windows NT 6.1; WOW64; rv:54.0) Gecko/20100101 Firefox/54.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/11.1 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 10_3_1 like Mac OS X) AppleWebKit/603.1.30 (KHTML, like Gecko) Version/10.0 Mobile/14E304 Safari/602.1",
    "Mozilla/5.0 (Linux; Android 7.0; Nexus 5X Build/NBD90W) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/62.0.3202.84 Mobile Safari/537.36",
]

def get_namespace(element):
    m = re.match(r'\{.*\}', element.tag)
    return m.group(0) if m else ''

def create_directory_structure(path):
    if not os.path.exists(path):
        try:
            os.makedirs(path)
        except FileExistsError:
            pass  # Handle race condition where directory was created between the exists check and makedirs

def is_blacklisted(key, blacklist):
    extension = key.split('.')[-1].lower()
    return extension in blacklist

def download_file(bucket_url, key, out_folder, blacklist):
    file_url = None
    try:
        if key.endswith('/') or is_blacklisted(key, blacklist):  # Skip directories or blacklisted files
            return

        adjusted_key = key.replace('//', '/double_slash/')
        file_path = os.path.join(out_folder, adjusted_key)
        directory = os.path.dirname(file_path)

        create_directory_structure(directory)

        file_url = bucket_url.rstrip('/') + '/' + adjusted_key.replace('/double_slash/', '//')
        print(f'[+] Downloading {file_url}')
        
        # Select a random User-Agent
        headers = {'User-Agent': random.choice(user_agents)}
        r = requests.get(file_url, headers=headers)

        if r.status_code == 200:
            with open(file_path, 'wb') as f:
                f.write(r.content)
        else:
            print(f'[!] Failed to download {file_url} ==> HTTP Status Code: {r.status_code}')
    except Exception as e:
        print(f'[!] Error downloading {file_url}: {e}')

def parse_xml(bucket_list_result, bucket_url, out_folder, blacklist):
    tree = ElementTree.parse(bucket_list_result)
    root = tree.getroot()
    namespace = get_namespace(root)

    # Define a ThreadPoolExecutor with a reasonable number of threads
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(download_file, bucket_url, content.find(f'{namespace}Key').text, out_folder, blacklist) 
                   for content in root.findall(f'{namespace}Contents') if '/' in content.find(f'{namespace}Key').text]

        for future in as_completed(futures):
            future.result()  # This will re-raise any exceptions caught

def retrieve_bucket_list_result(url, out_folder):
    print(f'[+] Downloading bucket list result from {url}')

    # Create out_folder
    create_directory_structure(out_folder)

    bucket_list_file = os.path.join(out_folder, 'content.xml')
    
    # Select a random User-Agent
    headers = {'User-Agent': random.choice(user_agents)}
    r = requests.get(url, headers=headers)

    if r.status_code == 200:
        with open(bucket_list_file, 'wb') as f:
            f.write(r.content)
        return bucket_list_file
    else:
        print(f'[!] Failed to download the bucket list. HTTP Status Code: {r.status_code}')
        return None

def main():
    blacklist = []
    if len(sys.argv) >= 2:
        bucket_url = sys.argv[1]
        parsed_url = urlparse(bucket_url)
        bucket_name = parsed_url.netloc  # Get the domain name to use

        out_folder = os.path.join(os.getcwd(), bucket_name)  # DomainName = Folder

        # Handle blacklist
        if '--blacklist' in sys.argv:
            blacklist_index = sys.argv.index('--blacklist')
            if blacklist_index + 1 < len(sys.argv):
                blacklist = sys.argv[blacklist_index + 1].split(',')

        bucket_list_file = retrieve_bucket_list_result(bucket_url, out_folder)
        if bucket_list_file:
            parse_xml(bucket_list_file, bucket_url, out_folder, blacklist)
    else:
        print('Usage: python download_bucket.py <bucket_url> [--blacklist jpg,png,gif]')

if __name__ == '__main__':
    banner()
    main()
