import asyncio
import requests
import time
import itertools
import sys
import json, os
from dotenv import load_dotenv
from library.transaction_builder import get_token_price_from_router, get_token_address, load_router_contract, get_token_price_from_router_2
import concurrent.futures
from loguru import logger  # Add this import

# Load environment variables
load_dotenv()


project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Configure loguru logger
config = {
    "handlers": [
        {"sink": sys.stderr, "format": "{time} | {level} : {message}", "colorize": True},
        {"sink": os.path.join(project_root, "log", "user", "bot_logs.log"), "rotation": "10 MB", "format": "{time} | {level} : \n{message}"},
        {"sink": os.path.join(project_root, "log", "technician", "bot_logs.log"), "rotation": "100 MB", "format": "{time} | {level} : \n{message}", "backtrace": True, "diagnose": True, "serialize": True}
    ],
}
logger.configure(**config)



# Load variable from ENV
desired_coin_file = os.getenv('DESIRED_COIN_FILE')
available_coin_file = os.getenv('AVAILABLE_COIN_FILE')
minimum_volume = float(os.getenv('MINIMUM_VOLUME'))
data_location = os.getenv('DATA_DIRECTORY')
coingecko_api_key = os.getenv('COINGECKO_API_KEY')
market_prices = {}

def load_json_file(file_path):
    with open(file_path, 'r') as file:
        return json.load(file)

# Load desired and available coins from JSON files
desired_coins_list = load_json_file(desired_coin_file)
available_coins_list = load_json_file(available_coin_file)

# Convert coin symbols to lowercase for comparison
desired_coins_symbols_lowercase = {coin.lower() for coin in desired_coins_list}
available_coins_symbols_lowercase = {coin['symbol'].lower() for coin in available_coins_list.values()}

# Identify Binance coins by finding the intersection of desired and available coins
binance_coins_intersection = desired_coins_symbols_lowercase & available_coins_symbols_lowercase
binance_smart_chain_coins = binance_coins_intersection.copy()

def get_headers():
    return {
        "accept": "application/json",
        os.getenv('COINGECKO_API_HEADER'): coingecko_api_key
    }

def fetch_bsc_coins(provider='coingecko'):
    import sqlite3
    global binance_smart_chain_coins
    
    bsc_coins_list = []
    updated_available_coins_data = {}
    if provider == 'birdeye':
        # Fetch data from the database
        conn = sqlite3.connect(os.getenv("TOKEN_PRICES_DB_PATH"))
        c = conn.cursor()
        c.execute("SELECT address, symbol, name FROM token_list WHERE v24hUSD IS NOT NULL AND v24hUSD != 'NULL'")
        bsc_coins_data = [{'id': row[0], 'symbol': row[1], 'name': row[2], 'contract_address': row[0]} for row in c.fetchall()]
        conn.close()
    else:
        # Fetch data from the CoinGecko API
        api_url = f"{os.getenv('COINGECKO_URL')}/api/v3/coins/list"
        params = {'include_platform': 'true'}
        api_response = requests.get(api_url, params=params, headers=get_headers())
        if api_response.status_code == 200:
            bsc_coins_data = api_response.json()
        else:
            logger.error(f"Failed to fetch data from CoinGecko: {api_response.status_code}")  # Changed
            return
        
        
    if provider == 'coingecko':
        bsc_coins_list = [coin['symbol'].lower() for coin in bsc_coins_data if 'binance-smart-chain' in coin.get('platforms', '')]
        updated_available_coins_data = {
            coin['id']: {
                'id': coin['id'],
                'symbol': coin['symbol'].lower(),
                'name': coin['name'],
                'contract_address': coin['platforms']['binance-smart-chain']
            } for coin in bsc_coins_data if 'binance-smart-chain' in coin.get('platforms', '')
        }
    else:
        bsc_coins_list = [coin.get('symbol', '').strip().lower() for coin in bsc_coins_data if coin.get('symbol')]
        updated_available_coins_data = {
            coin['id']: {
                'id': coin['id'],
                'symbol': coin.get('symbol', '').strip().lower(),
                'name': coin['name'],
                'contract_address': coin.get('contract_address', 'N/A')
            } for coin in bsc_coins_data if coin.get('symbol')
        }
    logger.info(f"{len(bsc_coins_list)} BSC coins found.")  # Changed
    binance_smart_chain_coins.update(bsc_coins_list)
    update_available_coins(available_coin_file, updated_available_coins_data)

def update_available_coins(file_path, coins_data):
    try:
        with open(file_path, 'r') as file:
            existing_data = json.load(file)
    except FileNotFoundError:
        existing_data = {}

    is_updated = False
    existing_symbols = {coin_info['symbol'].lower(): id for id, coin_info in existing_data.items()}

    # Append new data, avoiding duplicates
    for coin_id, coin_info in coins_data.items():
        symbol = coin_info.get('symbol', 'N/A').lower()
        if symbol in existing_symbols:
            # Update existing coin data
            existing_id = existing_symbols[symbol]
            existing_data[existing_id].update(coin_info)
            is_updated = True
        else:
            # Add new coin data
            existing_data[coin_id] = coin_info
            existing_symbols[symbol] = coin_id
            is_updated = True

    # Save updated data if changes were made
    if is_updated:
        with open(file_path, 'w') as file:
            json.dump(existing_data, file, indent=4)
        logger.info("Coin list updated.")  # Changed

def log_cmc_data(unique_id, data):
    formatted_id = str(unique_id).zfill(20)
    with open(f"{data_location}/{formatted_id}", "w") as file:
        file.write(data)

def fetch_blockchain_price(filtered_prices_data, coins_data):
    logger.info("Fetch From Blockchain started...")  # Changed
    router_contract = load_router_contract()
    # Using concurrent futures to speed up the processing of external function calls
    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        # Pre-fetch token addresses to avoid repeated calls within the executor
        coin_addresses = {coin_id: get_token_address(coin_id) for coin_id in filtered_prices_data}
        # Filter out coins with contract address "N/A"
        valid_coin_addresses = {coin_id: addr for coin_id, addr in coin_addresses.items() if addr != "N/A"}
        # Submit futures for valid addresses
        futures = {executor.submit(get_token_price_from_router, addr, router_contract=router_contract, is_buy=True): coin_id for coin_id, addr in valid_coin_addresses.items()}
        
        total_futures = len(futures)
        completed_futures = 0
        try:
            for future in concurrent.futures.as_completed(futures, timeout=30):  # Set a timeout to prevent hanging
                completed_futures += 1
                progress = (completed_futures / total_futures) * 100
                logger.info(f"\rProgress: [{int(progress)//2 * '#'}{int(50 - progress//2) * ' '}] {int(progress)}%")  # Changed

                coin_id = futures[future]
                data = filtered_prices_data[coin_id]
                price = "{:.18f}".format(float(data.get('usd', 0))).rstrip('0').rstrip('.')
                volume_24h = "{:.2f}".format(float(data.get('usd_24h_vol', 0)))
                symbol = data.get('symbol', 'N/A').lower()
                contract_address = coin_addresses[coin_id] or "N/A"
                real_price = "{:.18f}".format(float(future.result())).rstrip('0').rstrip('.') if future.result() else "0"
                market_prices[coin_id] = [price, volume_24h, real_price]
                coins_data[coin_id] = {"symbol": symbol, "contract_address": contract_address}
        except concurrent.futures.TimeoutError:
            logger.error("Timeout while fetching blockchain data. Your network is not stable or the node is too slow?")  # Changed
            executor.shutdown(wait=False)  # Immediately free up resources
            raise Exception("Operation timed out and was cancelled.")
        except Exception as e:
            logger.error(f"An error occurred: {e}")  # Changed
    return market_prices, coins_data


import time

async def batch_fetch_blockchain_price(filtered_prices_data, coins_data, provider='coingecko'):
    logger.info("Fetch From Blockchain started...")
    router_contract = load_router_contract()
    coin_addresses = {coin_id: get_token_address(coin_id) if provider == 'coingecko' else coin_id for coin_id in filtered_prices_data}
    
    valid_coin_addresses = {coin_id: addr for coin_id, addr in coin_addresses.items() if addr != "N/A"}
    
    addr_list = [addr for addr in coin_addresses.values() if addr and addr != "N/A"]
    
    data_token = await get_token_price_from_router_2(addr_list, router_contract)
    
    total_tokens = len(data_token)
    processed_tokens = 0
    start_time = time.time()
    
    for token_address, token_data in data_token.items():
        processed_tokens += 1
        
        coin_id = next((id for id, addr in valid_coin_addresses.items() if addr == token_address), None)
        if coin_id:
            data = filtered_prices_data[coin_id]
            price_usd = "{:.18f}".format(float(data.get('usd', 0) if provider == 'coingecko' else 0)).rstrip('0').rstrip('.')
            volume_24h = "{:.2f}".format(float(data.get('usd_24h_vol', 0) if provider == 'coingecko' else data.get('v24hUSD', 0))).rstrip('0').rstrip('.')
            symbol = data.get('symbol', 'N/A').lower()
            real_price = "{:.18f}".format(float(token_data[0])).rstrip('0').rstrip('.') if token_data[0] else "0"
            market_cap = "{:.2f}".format(float(token_data[1])).rstrip('0').rstrip('.') if token_data[1] else "0"
            market_prices[coin_id] = [price_usd, volume_24h, real_price, market_cap]
            coins_data[coin_id] = {"symbol": symbol, "contract_address": token_address}
        
        # Update progress
        progress = (processed_tokens / total_tokens) * 100
        elapsed_time = time.time() - start_time
        estimated_total_time = elapsed_time / (processed_tokens / total_tokens)
        remaining_time = estimated_total_time - elapsed_time
        
        progress_bar = f"[{'=' * int(progress // 2):{50}s}]"
        logger.info(f"\rProgress: {progress_bar} {progress:.1f}% | "
                    f"Processed: {processed_tokens}/{total_tokens} | "
                    f"Elapsed: {elapsed_time:.1f}s | "
                    f"ETA: {remaining_time:.1f}s")
    
    logger.info("\nFetch complete.")
    return market_prices, coins_data


async def fetch_birdeye():
    import os
    import sqlite3
    import time
    from library.birdeye_fetcher import fetch_and_save_token_list_async

    # Database path from environment variable
    db_path = os.getenv('TOKEN_PRICES_DB_PATH', 'token_prices.db')
    last_fetch_time_file = 'last_birdeye_fetch_time.txt'

    # Check the last fetch time
    if os.path.exists(last_fetch_time_file):
        try:    
            with open(last_fetch_time_file, 'r') as file:
                last_fetch_time = float(file.read().strip())
        except Exception as e:
            last_fetch_time = 0
    else:
        last_fetch_time = 0

    current_time = time.time()
    # Fetch new data if more than 30 minutes have passed since the last fetch
    if current_time - last_fetch_time > 1800:
        logger.info("Fetching Birdeye token data...")  # Changed
        tokens = await fetch_and_save_token_list_async()
        logger.info("Birdeye token data fetch complete.")  # Changed

        # Update the last fetch time
        with open(last_fetch_time_file, 'w') as file:
            file.write(str(current_time))

    else:
        logger.info("Loading Birdeye token data from database...")  # Changed
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT address, v24hUSD, symbol FROM token_list ORDER BY v24hUSD DESC')  # Sorting by v24hUSD in descending order
        tokens = [{'address': row[0], 'v24hUSD': float(row[1]), 'symbol': row[2]} for row in cursor.fetchall()]
        conn.close()
        logger.info("Data loaded from database.")  # Changed
        
    logger.info(f"Token Fetched: {len(tokens)}")  # Changed
    # Filter tokens based on volume
    if tokens:
        filtered_prices_data = {
            token['address']: token for token in tokens
            if token.get('v24hUSD') and float(token['v24hUSD']) > minimum_volume
        }
    else:
        filtered_prices_data = {}
    return filtered_prices_data
    
def fetch_api_price():
    global market_prices
    api_url = f"{os.getenv('COINGECKO_URL')}/api/v3/simple/price"
    all_coin_ids = [coin['id'] for coin in available_coins_list.values() if 'id' in coin]
    # Splitting all_coin_ids into chunks of 250 for batch processing
    chunks = [all_coin_ids[i:i + 250] for i in range(0, len(all_coin_ids), 250)]
    all_prices_data = []
    total_chunks = len(chunks)
    logger.info("Fetching market data...")  # Changed

    # Check if cached data is available and fresh (less than 30 minutes old)
    cache_file = 'cache/market_prices.json'
    if os.path.exists(cache_file):
        last_modified = os.path.getmtime(cache_file)
        if (time.time() - last_modified) / 60 < 30:
            with open(cache_file, 'r') as file:
                all_prices_data = json.load(file)
                logger.info("Loaded data from cache.")  # Changed
                # Show progress bar even when loading from cache
                for i in range(total_chunks):
                    progress = ((i + 1) / total_chunks) * 100
                    logger.info(f"\rProgress: [{int(progress)//2 * '#'}{int(50 - progress//2) * ' '}] {int(progress)}%")  # Changed
                logger.info("\nCache load complete.")  # Changed
                return {
                    coin_id: data for coin_data in all_prices_data for coin_id, data in coin_data.items()
                    if data.get('usd_24h_vol', 'N/A') != 'N/A' and float(data['usd_24h_vol']) > minimum_volume
                }

    # Fetching prices in parallel for each chunk using ThreadPoolExecutor
    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        futures = [executor.submit(fetch_prices_for_chunk, chunk, api_url) for chunk in chunks]
        for i, future in enumerate(concurrent.futures.as_completed(futures)):
            result = future.result()
            if result:
                all_prices_data.append(result)
            # Update progress bar
            progress = (i + 1) / total_chunks * 100
            logger.info(f"\rProgress: [{int(progress)//2 * '#'}{int(50 - progress//2) * ' '}] {int(progress)}%")  # Changed

    # Cache the fetched data
    os.makedirs(os.path.dirname(cache_file), exist_ok=True)
    with open(cache_file, 'w') as file:
        json.dump(all_prices_data, file)
        logger.info("\nData cached.")  # Changed

    filtered_prices_data = {
            coin_id: data for coin_data in all_prices_data for coin_id, data in coin_data.items()
            if data.get('usd_24h_vol', 'N/A') != 'N/A' and float(data['usd_24h_vol']) > minimum_volume
        }
    logger.info("\nFetch Market data from CoinGecko Success! \n")  # Changed
    return filtered_prices_data

async def fetch_market_data(provider='coingecko'):
    api_func = fetch_api_price if provider == 'coingecko' else fetch_birdeye
    filtered_prices_data = await api_func()
    coins_data = {}
    market_prices, coins_data = await batch_fetch_blockchain_price(filtered_prices_data, coins_data, provider=provider)

    logger.info(len(market_prices))  # Changed
    if len(market_prices) > 0:
        update_available_coins(available_coin_file, coins_data)
    else:
        logger.info("No new Market Data found.")  # Changed

def fetch_prices_for_chunk(chunk, api_url):
    params = {
        'ids': ','.join(chunk),
        'vs_currencies': 'usd',
        'include_market_cap': 'true',
        'include_24hr_vol': 'true',
        'include_24hr_change': 'true',
        'include_last_updated_at': 'true',
    }
    response = requests.get(api_url, params=params, headers=get_headers())
    if response.status_code == 200:
        return response.json()  # This line confirms that response.json() returns a Python dictionary
    elif response.status_code == 429:
        logger.warning("Sorry, you are being throttled.")  # Changed
        return None
    else:
        logger.error(f"Failed to fetch prices for chunk: {response.status_code}")  # Changed
        return None
    
if __name__ == "__main__":
    # fetch_birdeye()
    start_time = time.time()

    fetch_bsc_coins(provider='birdeye')
    asyncio.run(fetch_market_data(provider='birdeye'))

    logger.info(f"here\n{len(market_prices)}")  # Changed
    data_log = {"0": market_prices}
    log_cmc_data(int(time.time() * 1000000), json.dumps(data_log))

    end_time = time.time()
    logger.info(f"Total time spent on Fetching BSC Coins and Market Data: {end_time - start_time} seconds")  # Changed
