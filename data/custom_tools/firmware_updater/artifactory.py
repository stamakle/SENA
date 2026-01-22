
# artifactory.py (Refactored)
"""
Firmware Search Utilities - Enhanced Version
Features:
- Configurable SSL verification
- Retry logic with exponential backoff
- Structured logging
- Cache management with size limit and cleanup
- Improved ranking using Levenshtein distance
"""

from __future__ import annotations
import json
import logging
import os
import time
import warnings
from heapq import heappush, heappop
from typing import List, Dict, Optional, Tuple, Union

import requests
from lxml import html
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Setup environment and configuration
warnings.filterwarnings('ignore', message='Unverified HTTPS request')
logger = logging.getLogger(__name__)

# Load .env
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))

# Configurable constants
CACHE_FILE = os.path.join(os.path.dirname(__file__), '.cache.json')
DATA_FILE = os.path.join(os.path.dirname(__file__), 'data.json')
CACHE_EXPIRY = int(os.getenv('CACHE_EXPIRY', '3600'))  # seconds
CACHE_MAX_ENTRIES = int(os.getenv('CACHE_MAX_ENTRIES', '100'))
VERIFY_SSL = os.getenv('VERIFY_SSL', 'false').lower() == 'true'
HTTP_TIMEOUT = (5, 30)

# Retry strategy for HTTP requests
retry_strategy = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"]
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session = requests.Session()
session.mount("https://", adapter)
session.mount("http://", adapter)

# ---------------- Ranking Algorithm ----------------
def levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        return levenshtein(b, a)
    if len(b) == 0:
        return len(a)
    previous_row = range(len(b) + 1)
    for i, ca in enumerate(a):
        current_row = [i + 1]
        for j, cb in enumerate(b):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (ca != cb)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]

def heuristic(name: str, query: str) -> int:
    # Negative score for max-heap behavior
    return -levenshtein(name.lower(), query.lower())

# ---------------- Cache Management ----------------
def get_cache() -> Dict:
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Error reading cache: %s", e)
        return {}

def update_cache(cache_key: str, results: List[str]) -> None:
    try:
        cache = get_cache()
        # Cleanup if cache exceeds max entries
        if len(cache) >= CACHE_MAX_ENTRIES:
            oldest_key = min(cache.items(), key=lambda x: x[1].get('timestamp', 0))[0]
            cache.pop(oldest_key, None)
        cache[cache_key] = {'timestamp': time.time(), 'results': results}
        tmp = CACHE_FILE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(cache, f)
        os.replace(tmp, CACHE_FILE)
    except Exception as e:
        logger.warning("Error updating cache: %s", e)

def generate_cache_key(query: str, type: Optional[str], extensions: List[str]) -> str:
    ext_string = '_'.join(sorted(extensions)) if extensions else 'none'
    type_string = type or 'none'
    return f"{query}_{type_string}_{ext_string}"

# ---------------- Search Logic ----------------
def _process_url(base: str, headers: Dict[str, str], querys: str, modes: str, extensions_tuple: Tuple[str, ...]) -> List[Tuple[int, str]]:
    results: List[Tuple[int, str]] = []
    try:
        with session.get(base, headers=headers, verify=VERIFY_SSL, timeout=HTTP_TIMEOUT) as r:
            if r.status_code != 200:
                return results
            tree = html.fromstring(r.content)
            matching_item = next((i.strip() for i in tree.xpath('//a/text()') if querys.lower() in i.lower()), '')
            if not matching_item:
                return results
            data_with_item = base + matching_item
            with session.get(data_with_item, headers=headers, verify=VERIFY_SSL, timeout=HTTP_TIMEOUT) as r2:
                if r2.status_code != 200:
                    return results
                tree_fw = html.fromstring(r2.content)
                for item in tree_fw.xpath('//a/text()'):
                    full_path = data_with_item + item
                    if (querys and modes in full_path.lower() and full_path.endswith(extensions_tuple)):
                        results.append((heuristic(item, querys), full_path))
    except Exception as e:
        logger.error("Error processing %s: %s", base, e)
    return results

def _perform_search(query: str, type: Optional[str], extensions: List[str], timeout: int) -> List[str]:
    try:
        with open(DATA_FILE, 'r') as file:
            fw_data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error("Error loading data.json: %s", e)
        return []

    api_key = os.getenv('api_key')
    api_url = os.getenv('api_url')
    if not api_key or not api_url:
        logger.error("API key or URL not found in environment variables")
        return []

    mode = '-generic-dev-virtual'
    headers = {"X-JFrog-Art-Api": api_key}

    bases = [
        f"{api_url}/{key}{mode}/{v}/"
        for dir in fw_data.get('repo', [])
        for day in fw_data.get('days', [])
        for key, value in dir.items()
        for k, v in day.items()
    ]

    modes = f"_fw_asic_{type}" if type else "_fw_asic"
    querys = ('XX' + query[4:8]) if len(query) >= 8 else query
    if not querys:
        logger.warning("Invalid query: %s", query)
        return []

    extensions_tuple = tuple(extensions)

    heap: List[Tuple[int, str]] = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_process_url, base, headers, querys, modes, extensions_tuple): base for base in bases}
        try:
            for fut in as_completed(futures, timeout=timeout):
                for item in fut.result():
                    heappush(heap, item)
        except Exception as e:
            logger.error("Timeout or error during search: %s", e)

    best_matches: List[str] = []
    while heap:
        best_matches.append(heappop(heap)[1])

    if best_matches:
        logger.info("Found %d firmware matches for %s", len(best_matches), query)
    else:
        logger.warning("No firmware found for %s", query)
    return best_matches

def search_firmware(query: str, type: Optional[str] = None, extensions: Optional[List[str]] = None, use_cache: bool = True, timeout: int = 10) -> List[str]:
    if not query:
        raise ValueError("Firmware query cannot be empty")
    query = query.upper()
    extensions = extensions or ['.ubi','.ubi.enc']
    cache_key = generate_cache_key(query, type, extensions)

    if use_cache:
        cache = get_cache()
        entry = cache.get(cache_key)
        if entry and (time.time() - entry.get('timestamp', 0) < CACHE_EXPIRY):
            logger.info("Cache hit for %s", cache_key)
            return entry.get('results', [])

    results = _perform_search(query, type, extensions, timeout)
    if results and use_cache:
        update_cache(cache_key, results)
    return results

searchfirmware = search_firmware

def get_firmware_by_query(query: str, type: Optional[str] = None, extension: Union[str, List[str]] = '.ubi, .ubi.enc') -> Optional[str]:
    if not query:
        logger.error("Empty firmware query provided")
        return None
    query = query.upper()
    exts = [extension] if isinstance(extension, str) else extension
    urls = search_firmware(query, type, exts)
    if not urls:
        return None
    return next((u for u in urls if query in u), urls[0])

def cleanup_firmware(filepath: str) -> bool:
    if not filepath or not os.path.exists(filepath):
        return False
    try:
        os.remove(filepath)
        logger.info("Removed temporary firmware file: %s", filepath)
        return True
    except Exception as e:
        logger.error("Error removing firmware file %s: %s", filepath, e)
        return False

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Firmware Search Utility')
    parser.add_argument('-v', '--version', type=str, required=True, help='Firmware version to search for (e.g., 007S)')
    parser.add_argument('-t', '--type', type=str, choices=['rel', 'dbg'], default=None, help='Firmware type')
    parser.add_argument('-e', '--extension', type=str, default='.ubi', help='File extension (default: .ubi)')
    parser.add_argument('--no-cache', action='store_true', help='Disable using cached search results')
    parser.add_argument('--verbose', '-V', action='count', default=0, help='Increase verbosity (-VV for debug)')
    args = parser.parse_args()

    level = logging.WARNING
    if args.verbose >= 2:
        level = logging.DEBUG
    elif args.verbose == 1:
        level = logging.INFO
    logging.basicConfig(level=level, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')

    urls = search_firmware(args.version, args.type, [args.extension], use_cache=not args.no_cache)
    if urls:
        logger.info("Firmware URLs found:")
        for u in urls:
            print(" -", u)
    else:
        logger.warning("No firmware URLs found matching the criteria.")
