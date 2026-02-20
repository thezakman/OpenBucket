#!/usr/bin/env python3.11

import re
import os
import sys
import random
import xml.etree.ElementTree as ElementTree
import requests
import urllib.parse
import argparse
import time
import logging
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
from colorama import init, Fore, Style

# Inicializar colorama para funcionamento correto no Windows
init(autoreset=True)

version = "2.1"
author = "TheZakMan"
def banner():
    banner = f'''                         
                                                           
{Fore.CYAN}- Hey, look! it's a                                        {Fore.GREEN}[VERSION {version}]
{Fore.YELLOW}────────────────────────────────────────────────────────────────────────
{Fore.CYAN} dP"Yb  88""Yb 888888 88b 88 88""Yb 88   88  dP""b8 88  dP 888888 888888 
{Fore.CYAN}dP //Yb 88__dP 88__   88Yb88 88__dP 88   88 dP   `" 88odP  88__     88   
{Fore.CYAN}Yb// dP 88"""  88""   88 Y88 88""Yb Y8   8P Yb      88"Yb  88""     88   
{Fore.CYAN} YbodP  88     888888 88  Y8 88oodP `YbodP'  YboodP 88  Yb 888888   88                                    
{Fore.YELLOW}────────────────────────────────────────────────────────────────────────                                                     
                                                      {Fore.GREEN}Let's download it!
    '''
    print(banner)

user_agents = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3",
    "Mozilla/5.0 (Windows NT 6.1; WOW64; rv:54.0) Gecko/20100101 Firefox/54.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/11.1 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 10_3_1 like Mac OS X) AppleWebKit/603.1.30 (KHTML, like Gecko) Version/10.0 Mobile/14E304 Safari/602.1",
    "Mozilla/5.0 (Linux; Android 7.0; Nexus 5X Build/NBD90W) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/62.0.3202.84 Mobile Safari/537.36",
]

# Configuração de logging
def setup_logging(log_file=None, verbose=False):
    log_level = logging.DEBUG if verbose else logging.INFO
    log_format = '%(asctime)s - %(levelname)s - %(message)s'
    logging.basicConfig(level=log_level, format=log_format)
    
    # Criar logger
    logger = logging.getLogger('OpenBucket')
    
    # Adicionar log para arquivo se especificado
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter(log_format))
        logger.addHandler(file_handler)
        
    return logger

def get_namespace(element):
    m = re.match(r'\{.*\}', element.tag)
    return m.group(0) if m else ''

def create_directory_structure(path):
    if not os.path.exists(path):
        try:
            os.makedirs(path)
            return True
        except FileExistsError:
            pass  # Handle race condition where directory was created between the exists check and makedirs
        except Exception as e:
            print(f"{Fore.RED}[!] Erro ao criar diretório {path}: {e}")
            return False
    return True

def is_blacklisted(key, blacklist):
    if not blacklist:
        return False
    extension = key.split('.')[-1].lower() if '.' in key else ''
    return extension in blacklist

def download_file(bucket_url, key, out_folder, blacklist, timeout=30, retry_count=3):
    file_url = None
    
    if key.endswith('/') or is_blacklisted(key, blacklist):  # Skip directories or blacklisted files
        return {"status": "skipped", "file": key, "reason": "directory or blacklisted"}

    try:
        adjusted_key = key.replace('//', '/double_slash/')
        file_path = os.path.join(out_folder, adjusted_key)
        directory = os.path.dirname(file_path)

        if not create_directory_structure(directory):
            return {"status": "failed", "file": key, "reason": "could not create directory"}

        file_url = bucket_url.rstrip('/') + '/' + adjusted_key.replace('/double_slash/', '//')
        
        # Tentativas com retry
        for attempt in range(retry_count):
            try:
                # Select a random User-Agent
                headers = {'User-Agent': random.choice(user_agents)}
                r = requests.get(file_url, headers=headers, timeout=timeout, stream=True)
                
                if r.status_code == 200:
                    with open(file_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=8192): 
                            if chunk:
                                f.write(chunk)
                    file_size = os.path.getsize(file_path)
                    return {"status": "success", "file": key, "size": file_size}
                elif attempt < retry_count - 1:
                    time.sleep(1)  # Aguardar antes de tentar novamente
                    continue
                else:
                    return {"status": "failed", "file": key, "reason": f"HTTP Status: {r.status_code}"}
                    
            except requests.exceptions.RequestException as e:
                if attempt < retry_count - 1:
                    time.sleep(1)
                    continue
                return {"status": "failed", "file": key, "reason": str(e)}
                
    except Exception as e:
        return {"status": "failed", "file": key, "reason": str(e)}

def parse_xml(bucket_list_result, bucket_url, out_folder, blacklist, max_workers=10, timeout=30):
    try:
        tree = ElementTree.parse(bucket_list_result)
        root = tree.getroot()
        namespace = get_namespace(root)
        
        contents = root.findall(f'{namespace}Contents')
        if not contents:
            print(f"{Fore.YELLOW}[!] Nenhum arquivo encontrado no bucket ou formato XML não reconhecido.")
            return {"downloaded": 0, "failed": 0, "skipped": 0}
            
        # Filtrar conteúdos relevantes
        files_to_download = []
        for content in contents:
            key_element = content.find(f'{namespace}Key')
            if key_element is not None:
                key = key_element.text
                if key and not (key.endswith('/') or is_blacklisted(key, blacklist)):
                    files_to_download.append(key)
        
        if not files_to_download:
            print(f"{Fore.YELLOW}[!] Nenhum arquivo para download após filtragem.")
            return {"downloaded": 0, "failed": 0, "skipped": 0}
        
        total_files = len(files_to_download)
        print(f"{Fore.GREEN}[+] Encontrados {total_files} arquivos para download.")
        
        results = {"downloaded": 0, "failed": 0, "skipped": 0, "total_size": 0}
        
        # Define a ThreadPoolExecutor with a configurable number of threads
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Criar um dicionário para mapear futures para keys para melhor reporting
            futures = {
                executor.submit(
                    download_file, bucket_url, key, out_folder, blacklist, timeout
                ): key for key in files_to_download
            }
            
            # Usar tqdm para mostrar barra de progresso
            with tqdm(total=len(futures), unit='file', desc='Baixando arquivos', 
                     bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]') as pbar:
                for future in as_completed(futures):
                    result = future.result()
                    if result["status"] == "success":
                        results["downloaded"] += 1
                        if "size" in result:
                            results["total_size"] += result["size"]
                        pbar.set_postfix(baixados=f"{results['downloaded']}/{total_files}")
                    elif result["status"] == "skipped":
                        results["skipped"] += 1
                    else:
                        results["failed"] += 1
                        print(f"{Fore.RED}[!] Falha ao baixar {result['file']}: {result['reason']}")
                    pbar.update(1)
        
        return results
    
    except Exception as e:
        print(f"{Fore.RED}[!] Erro ao processar o XML: {e}")
        return {"downloaded": 0, "failed": 0, "skipped": 0}

def retrieve_bucket_list_result(url, out_folder, timeout=30):
    print(f"{Fore.BLUE}[+] Baixando lista do bucket de {url}")

    # Create out_folder
    if not create_directory_structure(out_folder):
        return None

    bucket_list_file = os.path.join(out_folder, 'content.xml')
    
    try:
        # Select a random User-Agent
        headers = {'User-Agent': random.choice(user_agents)}
        r = requests.get(url, headers=headers, timeout=timeout)

        if r.status_code == 200:
            with open(bucket_list_file, 'wb') as f:
                f.write(r.content)
            print(f"{Fore.GREEN}[+] Lista do bucket baixada com sucesso.")
            return bucket_list_file
        else:
            print(f"{Fore.RED}[!] Falha ao baixar a lista do bucket. HTTP Status Code: {r.status_code}")
            return None
    except Exception as e:
        print(f"{Fore.RED}[!] Erro ao baixar a lista do bucket: {e}")
        return None

def format_size(size_bytes):
    """Formata tamanho em bytes para formato legível (KB, MB, GB)"""
    if size_bytes < 1024:
        return f"{size_bytes} bytes"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes/1024:.2f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes/(1024*1024):.2f} MB"
    else:
        return f"{size_bytes/(1024*1024*1024):.2f} GB"

def parse_arguments():
    parser = argparse.ArgumentParser(description='OpenBucket - Ferramenta para baixar conteúdo de buckets de armazenamento')
    parser.add_argument('bucket_url', help='URL do bucket para download')
    parser.add_argument('--blacklist', help='Lista de extensões para ignorar (separadas por vírgula)', default='')
    parser.add_argument('--threads', '-t', help='Número de threads para download paralelo', type=int, default=10)
    parser.add_argument('--output', '-o', help='Pasta de saída para os arquivos', default='')
    parser.add_argument('--timeout', help='Timeout para requests em segundos', type=int, default=30)
    parser.add_argument('--verbose', '-v', help='Modo verboso', action='store_true')
    parser.add_argument('--log', help='Arquivo para salvar logs')
    
    return parser.parse_args()

def main():
    args = parse_arguments()
    logger = setup_logging(args.log, args.verbose)
    
    bucket_url = args.bucket_url
    parsed_url = urlparse(bucket_url)
    bucket_name = parsed_url.netloc  # Get the domain name to use

    # Define output folder
    if args.output:
        out_folder = args.output
    else:
        # Inclui o caminho do bucket após o domínio para evitar conflitos
        bucket_path = parsed_url.path.strip('/')
        if bucket_path:
            out_folder = os.path.join(os.getcwd(), bucket_name, bucket_path)
        else:
            out_folder = os.path.join(os.getcwd(), bucket_name)
    
    print(f"{Fore.BLUE}[*] Bucket URL: {bucket_url}")
    print(f"{Fore.BLUE}[*] Pasta de saída: {out_folder}")
    
    # Handle blacklist
    blacklist = []
    if args.blacklist:
        blacklist = args.blacklist.split(',')
        print(f"{Fore.BLUE}[*] Extensões ignoradas: {', '.join(blacklist)}")

    start_time = time.time()
    bucket_list_file = retrieve_bucket_list_result(bucket_url, out_folder, args.timeout)
    
    if bucket_list_file:
        results = parse_xml(bucket_list_file, bucket_url, out_folder, blacklist, args.threads, args.timeout)
        
        end_time = time.time()
        duration = end_time - start_time
        
        # Mostrar resumo
        print("\n" + "="*60)
        print(f"{Fore.GREEN}[✓] Download concluído em {duration:.2f} segundos!")
        print(f"{Fore.GREEN}[✓] Arquivos baixados com sucesso: {results['downloaded']}")
        if "total_size" in results:
            print(f"{Fore.GREEN}[✓] Tamanho total baixado: {format_size(results['total_size'])}")
        if results["skipped"] > 0:
            print(f"{Fore.YELLOW}[!] Arquivos ignorados: {results['skipped']}")
        if results["failed"] > 0:
            print(f"{Fore.RED}[!] Arquivos com falha: {results['failed']}")
        print("="*60)
    else:
        print(f"{Fore.RED}[!] Não foi possível obter a lista de arquivos do bucket.")

if __name__ == '__main__':
    banner()
    main()
