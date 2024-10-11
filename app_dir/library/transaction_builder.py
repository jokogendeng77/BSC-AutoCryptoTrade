import json
import requests
import os
from dotenv import load_dotenv
from web3 import Web3
from library.utils import core_performance_patcher, initialize_web3
import time, sys
from loguru import logger
import asyncio
import random
import aiohttp
from decimal import Decimal
# Configure loguru logger
# config = {
#     "handlers": [
#         {"sink": sys.stderr, "format": "{time} | {level} : <level>\n{message}</level>", "colorize": True},
#         {"sink": "log/user/multi_trade_logs.log", "rotation": "10 MB", "format": "{time} | {level} : \n{message}"},
#         {"sink": "log/technician/multi_trade_logs.log", "rotation": "100 MB", "format": "{time} | {level} : \n{message}", "backtrace": True, "diagnose": True, "serialize": True}
#     ],
# }
# logger.configure(**config)

# Load environment variables
load_dotenv()  # Specify the .env file to load

# Load settings environment
available_coin_file = os.getenv('AVAILABLE_COIN_FILE')
shit_coin_file = os.getenv('SHIT_COIN_FILE')
banned_error_conditions = os.getenv('BANNED_ERROR_CONDITIONS', '').replace(" ", "").lower().split(',')
bnb_price = None
debug_mode = os.getenv('DEBUG_MODE') == 'True'


# Initialize web3 using the function from utils.py
web3 = initialize_web3()

# Default fallback wallet address and private key
wallet_address = os.getenv('WALLET_ADDRESS')
private_key = os.getenv('PRIVATE_KEY')

# Abi file Location
abi_data_folder = os.getenv('ABI_DIRECTORY')

# COIN MARKETCAPAPI
cmc_api = os.getenv('CMC_API_KEY')

# PancakeSwap Router v2 details
router_address = os.getenv('ROUTER_ADDRESS')
router_contract = None

# Pancake Factory details
pancake_factory = os.getenv('PANCAKE_FACTORY_ADDRESS')
abi_file_path = os.path.join(os.path.dirname(__file__), abi_data_folder, 'pancakeswap_factory_abi.json')
with open(abi_file_path) as f:
    pancake_factory_abi = json.load(f)
factory_contract = web3.eth.contract(address=pancake_factory, abi=pancake_factory_abi)

# USDT BEP20 address
real_usdt_address = os.getenv('USDT_ADDRESS')
usdt_address = Web3.to_checksum_address(real_usdt_address)

# BNB BEP20 address
real_bnb_address = os.getenv('BNB_ADDRESS')
bnb_address = Web3.to_checksum_address(real_bnb_address)


# Cache Token Data dictionary
token_supply_cache = {}

# COIN LIST INITIALIZATION
coin_list = {}
with open(available_coin_file, 'r') as f:
  coin_list = json.load(f)

# Retry count for API calls
retry_count = 1

# USED IN SIMULATIONS
def estimate_gas_fee():
    try:
        # Estimate gas fee based on the current network conditions
        gas_price = web3.eth.gas_price
        estimated_gas = 21000  # Average gas limit for a standard transaction
        estimated_fee = gas_price * estimated_gas
        return estimated_fee
    except Exception as e:
        raise Exception(f"Failed to estimate gas fee: {str(e)}")

def check_coin_approval(coin_address, local_router_address=router_address):
    try:
        # Check if a coin is approved for trading by querying the allowance
        token_contract = web3.eth.contract(address=coin_address, abi=get_mock_abi())
        allowance = token_contract.functions.allowance(wallet_address, local_router_address).call()
        return allowance > 0
    except Exception as e:
        raise Exception(f"Failed to check coin approval: {str(e)}")
    
def calculate_slippage(coin_address, slippage_rate, timestamp):
    # Placeholder function for calculating slippage with random values
    # Original code is commented out for reference
    '''
    try:
        # Calculate slippage by comparing expected and actual transaction values
        # Retrieve the most recent transaction around the specified timestamp
        last_transaction = fetch_last_transaction(coin_address, timestamp)
        if not last_transaction or last_transaction['status'] == 'failed':
            raise Exception("Calculation error: Last transaction failed or not found")

        # Verify the token's liquidity
        liquidity = check_token_liquidity(coin_address)
        if liquidity <= 0:
            raise Exception("Calculation error: Token lacks liquidity")

        # Determine slippage from the most recent successful transaction
        expected_amount_out = last_transaction['amount_out']
        actual_amount_out = expected_amount_out * (1 - slippage_rate)
        slippage_amount = expected_amount_out - actual_amount_out
        return slippage_amount
    except Exception as e:
        raise Exception(f"Slippage calculation error: {str(e)}")
    '''
    # Generating a random slippage amount for demonstration purposes
    slippage_amount = random.uniform(0, slippage_rate * 100)  # Assuming slippage_rate is a percentage
    return slippage_amount
# END USED IN SIMULATIONS

def get_token_circulating_supply(token_address):
    current_time = time.time()
    cache_entry = token_supply_cache.get(token_address)

    # Check if the cache entry exists and is within the 2-minute validity window
    if cache_entry and (current_time - cache_entry['timestamp'] < 120):
        return cache_entry['data']

    # If not cached or cache is outdated, fetch new data
    api_key = os.getenv("BSCSCAN_API_KEY")
    api_url = f"https://api.bscscan.com/api?module=stats&action=tokenCsupply&contractaddress={token_address}&apikey={api_key}"
    response = requests.get(api_url)
    if response.status_code == 200:
        result = response.json()
        
        if result['status'] == '1':
            # Update the cache with new data and timestamp
            result = result['result']
            token_supply_cache[token_address] = {'data': result, 'timestamp': current_time}
            return result
        else:
            return None
    return None

def get_mock_abi():
    with open(os.path.join(os.path.dirname(__file__), abi_data_folder, 'mock_abi.json')) as f:
        return json.load(f)

# Function to get token symbol with space stripping
def get_token_symbol(token_address, cmc_id=None):
    token_address = token_address.lower()  # Normalize address
    symbol = next((coin['symbol'].strip() for coin in coin_list.values() if coin['contract_address'].lower() == token_address), None)
    if symbol:
        return symbol
    # Fetch from CoinGecko if not found locally, ensuring symbols are stripped of spaces
    headers = {'Accepts': 'application/json', os.getenv('COINGECKO_API_HEADER'): os.getenv('COINGECKO_API_KEY')}
    params = {'contract_addresses': token_address, 'vs_currencies': 'usd'}
    response = requests.get(f'{os.getenv("COINGECKO_URL")}/api/v3/simple/token_price/binance-smart-chain', headers=headers, params=params)
    if response.status_code == 200:
        data = response.json()
        if token_address in data:
            symbol = data[token_address]['symbol'].strip()  # Strip spaces from symbol
            # Update local coin list with stripped symbol
            coin_list[str(cmc_id)] = {'symbol': symbol, 'contract_address': token_address}
            with open(available_coin_file, 'w') as f:
                json.dump(coin_list, f, indent=2)
            return symbol
    return None

def get_token_address(token_symbol):
    token_symbol = token_symbol.upper()  # Normalize symbol
    address = next((coin['contract_address'] for key, coin in coin_list.items() if coin['symbol'].upper() == token_symbol or ('id' in coin and str(coin['id']).upper() == token_symbol) or key == token_symbol), None)
    if address and address.lower() != "n/a":
        return address
    return None

def save_untraded_coins(coin_address):
    # Load the available coin list
    with open(available_coin_file, 'r') as f:
        coin_list = json.load(f)
    # Search for the coin by address and get its symbol and ID
    coin_id, token_symbol = next(((id, coin['symbol']) for id, coin in coin_list.items() if coin['contract_address'] == coin_address), (None, None))
    
    if token_symbol and coin_id:
        logger.error(f"Token Price not found for {token_symbol}")
        new_entry = {coin_id: {"symbol": token_symbol, "contract_address": coin_address}}
        # Save the new entry to the untraded coins list
        try:
            with open(shit_coin_file, "r+") as file:
                try:
                    existing_data = json.load(file)
                except json.JSONDecodeError:  # Handle empty file
                    existing_data = {}
                existing_data.update(new_entry)
                file.seek(0)
                file.truncate()  # Clear the file before writing the updated data
                json.dump(existing_data, file, indent=2)
        except FileNotFoundError:
            with open(shit_coin_file, "w") as file:
                json.dump(new_entry, file, indent=2)
        # Remove the entry from the available coin list and save the updated list
        del coin_list[coin_id]
        with open(available_coin_file, 'w') as f:
            json.dump(coin_list, f, indent=2)
    else:
        logger.error(f"Coin with address {coin_address} not found in available coin list.")

def load_router_contract(filename="pancakeswap_router_abi"):
  router_contract = get_contract(
      router_address,
      filename=filename)  # Corrected ABI filename
  return router_contract

def determine_best_router(token_address, token_balance_before_swap, mode=True):
    global router_contract, router_address
    # Define potential routers and their ABIs including additional routers
    routers = {
        'PancakeSwap': {'address': os.getenv('PANCAKE_ROUTER_ADDRESS'), 'abi_file': 'pancakeswap_router_abi'},
        'BakerySwap': {'address': os.getenv('BAKERY_ROUTER_ADDRESS'), 'abi_file': 'bakeryswap_router_abi'},
        'ApeSwap': {'address': os.getenv('APESWAP_ROUTER_ADDRESS'), 'abi_file': 'apeswap_router_abi'},
        'Biswap': {'address': os.getenv('BISWAP_ROUTER_ADDRESS'), 'abi_file': 'biswap_router_abi'},
    }
    best_router = None
    best_price = float('inf') if mode else float('-inf')
    best_router_name = None
    # Check prices on each router
    comparison_table = []
    for name, router in routers.items():
        local_router_contract = get_contract(router['address'], filename=router['abi_file'])
        price = get_token_price_from_router(token_address, local_router_contract, name, token_balance_before_swap, is_buy=mode)
        comparison_table.append({'Router Name': name, 'Price': price})
        if price is not None and price != 0 and price != float('inf') and price != float('-inf'):
            if (mode and price < best_price) or (not mode and price > best_price):
                best_price = price
                best_router = router
                best_router_name = name
    if best_router:
        logger.info(f"Best router determined: {best_router_name} with {'Buy' if mode else 'Sell'} price: {best_price}")
        router_address = best_router['address']
        router_contract = get_contract(best_router['address'], filename=best_router['abi_file'])
        # Print the comparison table in a good table view
        print("\nComparison Table:")
        print("{:<15} {:<10}".format('Router Name', 'Price'))
        for item in comparison_table:
            print("{:<15} {:<10}".format(item['Router Name'], item['Price']))
        return best_router['address'], router_contract, best_router['abi_file']
    else:
        logger.error("Failed to determine the best router.")
        return None, None, None

def get_token_price_from_router(token_address, router_contract=router_contract, router_name="PancakeSwap", token_balance_before_swap=1, is_buy=True):
    global router_address
    # This function fetches the token price from a router by simulating a swap
    if router_contract is None:
        router_contract = load_router_contract()
    try:

        # Simulate a swap from the token to a stable coin to get the price
        amount_in = web3.to_wei(usdt_to_bnb(1), 'ether') if is_buy else token_balance_before_swap  # Simulate swap of 1 token (assuming 18 decimals)
        try:
            # Ensure the router supports the getAmountsOut function
            if hasattr(router_contract.functions, 'getAmountsOut'):
                if is_buy:
                    amounts_out = router_contract.functions.getAmountsOut(amount_in, [bnb_address, web3.to_checksum_address(token_address)]).call()
                else:
                    amounts_out = router_contract.functions.getAmountsOut(amount_in, [web3.to_checksum_address(token_address), bnb_address]).call()
                # print(amounts_out)
                price = web3.from_wei(amounts_out[-1], 'ether')
                # Get the price of token in USD
                token_price_in_usd = float(1 / price) if is_buy else price
                return token_price_in_usd
            else:
                # logger.error(f"{router_name} router does not support getAmountsOut function.")
                return 0
        except Exception as e:
            # logger.error(f"Failed to get price from {router_name} router for {token_address}: {e}")
            return 0
    except Exception as e:
        # logger.error(f"Failed to get price from {router_name} router for {token_address}: {e}")
        return 0

@logger.catch
async def get_token_price_from_router_2(token_addresses, router_contract=None, router_name="PancakeSwap", token_balance_before_swap=1, is_buy=True):
    global router_address
    # Ensure router_contract is loaded
    if router_contract is None:
        router_contract = load_router_contract()

    try:
        # Prepare multicall
        multicall = get_contract(os.getenv("MULTICALL_ADDRESS"), filename='multicall_router_abi')
        
        # Ensure token_addresses is a list even if a single string is provided
        if isinstance(token_addresses, str):
            token_addresses = [token_addresses]

        # Determine the amount to simulate with based on the path's starting token
        amount_in = web3.to_wei(usdt_to_bnb(1), 'ether') if is_buy else token_balance_before_swap
        paths = [[bnb_address, web3.to_checksum_address(token_address)] if is_buy else [web3.to_checksum_address(token_address), bnb_address] for token_address in token_addresses]
        
        # Increase chunk size to process more addresses in one go
        chunk_size = 3000  # Adjust based on network capacity and testing
        token_address_chunks = [token_addresses[i:i + chunk_size] for i in range(0, len(token_addresses), chunk_size)]
        prices = {}
        market_caps = {}

        async def fetch_prices_for_chunk(chunk):
            call_data = [router_contract.functions.getAmountsOut(amount_in, path)._encode_transaction_data() for path in paths if web3.to_checksum_address(path[1]) in chunk]
            calls = [(router_contract.address, True, data) for data in call_data]

            # Execute multicall for prices
            results = multicall.functions.aggregate3(calls).call()
            chunk_prices = {}
            # Execute multicall for total supplies
            total_supply_calls = [(get_contract(token).address, False, get_contract(token).functions.totalSupply()._encode_transaction_data()) for token in chunk]
            total_supply_results = multicall.functions.aggregate3(total_supply_calls).call()

            for i, output in enumerate(results):
                token_address = chunk[i]
                try:
                    # Decode the output for each token address
                    from eth_abi import abi
                    if output[1] != b'':
                        amounts_out = abi.decode(['uint256[]'], output[1])
                        if amounts_out:
                            price = amounts_out[0][-1]  # Get the last element which is the amount out
                            price = web3.from_wei(price, 'ether')
                            token_price_in_usd = float(Decimal('1.0') / Decimal(price)) if is_buy else float(price)
                            # Get total supply from multicall results
                            total_supply_output = total_supply_results[i]
                            total_supply = abi.decode(['uint256'], total_supply_output[1])[0] if total_supply_output[1] != b'' else 0
                            # Fetch circulating supply, replace if available
                            circulating_supply = get_token_circulating_supply(token_address)
                            supply_to_use = circulating_supply if circulating_supply else total_supply
                            market_cap = supply_to_use * token_price_in_usd
                        else:
                            token_price_in_usd = 0
                    else:
                        token_price_in_usd = 0
                    chunk_prices[token_address] = [token_price_in_usd, market_cap]
                except Exception as e:
                    # logger.error(f"Failed to decode output for token {token_address}: {e}")
                    chunk_prices[token_address] = [0, 0]
            return chunk_prices

        # Use tqdm and asyncio.gather to fetch prices for all chunks in parallel
        from tqdm.asyncio import tqdm
        price_tasks = [fetch_prices_for_chunk(chunk) for chunk in token_address_chunks]
        for result in tqdm(asyncio.as_completed(price_tasks), total=len(price_tasks), desc="Fetching prices"):
            prices_chunk = await result
            prices.update(prices_chunk)

        return prices
    except Exception as e:
        logger.error(f"Failed to get prices from {router_name} router for tokens: {e}")
        return {token_address: [None, None] for token_address in token_addresses}

def send_tele_message_sync(message, token=None, chat_id=None, parse_mode="HTML"):
    telegram_group_id = os.getenv("TELEGRAM_CHAT_ID") if chat_id is None else chat_id
    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN") if token is None else token
    telegram_url = f"https://api.telegram.org/bot{telegram_bot_token}/sendMessage"
    telegram_data = {"chat_id": telegram_group_id, "text": message, "parse_mode": parse_mode}
    response = requests.post(telegram_url, data=telegram_data)
    if response.status_code != 200:
        logger.error(f"Failed to send message: {response.text}")

async def send_tele_message_async(message, token=None, chat_id=None, parse_mode="HTML"):
    telegram_group_id = os.getenv("TELEGRAM_CHAT_ID") if chat_id is None else chat_id
    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN") if token is None else token
    telegram_url = f"https://api.telegram.org/bot{telegram_bot_token}/sendMessage"
    telegram_data = {"chat_id": telegram_group_id, "text": message, "parse_mode": parse_mode}
    connector = aiohttp.TCPConnector(ssl=False)  # Disable SSL verification
    async with aiohttp.ClientSession(connector=connector) as session:
        response = await session.post(telegram_url, data=telegram_data)
        if response.status != 200:
            text = await response.text()
            logger.error(f"Failed to send async message: {text}")

def send_tele_message(message, is_async=False, token=None, chat_id=None, parse_mode="HTML"):
    if debug_mode:
        logger.debug(message)
    if is_async:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            return asyncio.create_task(send_tele_message_async(message, token, chat_id, parse_mode))
        else:
            return asyncio.run(send_tele_message_async(message, token, chat_id, parse_mode))
    else:
        return send_tele_message_sync(message, token, chat_id, parse_mode)


def fetch_and_store_abi(address, abi_file_path):
    api_key = os.getenv("BSCSCAN_API_KEY")
    abi_endpoint = f"https://api.bscscan.com/api?module=contract&action=getabi&address={address}&apikey={api_key}"
    try:
        abi_response = requests.get(abi_endpoint, timeout=10)  # Set a timeout for the request
        if abi_response.status_code == 200:
            abi_response_json = json.loads(abi_response.text)
            if abi_response_json['status'] == '1':
                abi = json.loads(abi_response_json['result'])
                with open(abi_file_path, 'w') as abi_file:
                    json.dump(abi, abi_file)
                return abi
            else:
                abi = get_mock_abi()
                with open(abi_file_path, 'w') as abi_file:
                    json.dump(abi, abi_file)
                return abi
        logger.error(f"Failed to fetch ABI: {abi_response.text}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Request to fetch ABI failed: {e}")
    return get_mock_abi()

# Function to get the contract of a token
def get_contract(address, filename=''):
    mock_abi = get_mock_abi()
    if filename:
        abi_file_path = os.path.join(os.path.dirname(__file__), abi_data_folder, f'{filename}.json')
    else:
        abi_file_path = os.path.join(os.path.dirname(__file__), abi_data_folder, f'{get_token_symbol(address)}_{address}.json')
    
    try:
        if os.path.exists(abi_file_path):
            with open(abi_file_path, 'r') as abi_file:
                abi = json.load(abi_file)
        else:
            abi = fetch_and_store_abi(address, abi_file_path)
        
        contract = web3.eth.contract(address=Web3.to_checksum_address(address), abi=abi if abi else mock_abi)
        if not filename:
            contract.functions.balanceOf(wallet_address).call()  # Test the ABI by calling a function
    except Exception as e:
        logger.warning(f"Self Contract Error, Using Default Contract...")
        contract = web3.eth.contract(address=Web3.to_checksum_address(address), abi=mock_abi)
    
    return contract

# Function to approve token
def approve_token(token_contract,
                  spender_address,
                  amount,
                  wallet_address,
                  private_key,
                  slippage=0.5):
  if token_contract is None:
    logger.error("Token contract is not available. Cannot proceed with approval.")
    return False
  # Check current allowance
  current_allowance = token_contract.functions.allowance(
      wallet_address, spender_address).call()
  if current_allowance >= amount:
    logger.info("Token already approved for the required amount or higher.")
    return True
  nonce = web3.eth.get_transaction_count(wallet_address, 'pending')
  txn = token_contract.functions.approve(router_address,
                                         amount).build_transaction({
                                             'from': wallet_address,
                                             'nonce': nonce,
                                         })
  signed_txn = web3.eth.account.sign_transaction(txn, private_key=private_key)
  try:
    txn_hash = web3.eth.send_raw_transaction(signed_txn.rawTransaction)
    logger.info("Token Approval success!")
    receipt = web3.eth.wait_for_transaction_receipt(txn_hash, timeout=120)  # Reduced timeout for faster confirmation
    if receipt.status == 1:
        logger.info(f"Transaction approved. Transaction hash: {web3.to_hex(txn_hash)}")
        return True
    else:
        logger.error("Transaction failed with status code: " + str(receipt.status))
        # Retry the transaction in case of failure
        return approve_token(token_contract, spender_address, amount, wallet_address, private_key, slippage)
  except Exception as e:
    logger.error(f"Error occurred during token approval: {e}.")
    return False



# Function to get BNB price in USD
def get_bnb_price():
    global bnb_price
    primary_url = f"{os.getenv('COINGECKO_URL')}/api/v3/simple/price?ids=binancecoin&vs_currencies=usd"
    fallback_url = "https://api.binance.com/api/v3/ticker/price?symbol=BNBUSDT"
    primary_headers = {
        "accept": "application/json",
        os.getenv('COINGECKO_API_HEADER'): os.getenv('COINGECKO_API_KEY')
    }

    # Check if the price is cached and not expired
    if 'bnb_price' in globals() and bnb_price is not None and time.time() - bnb_price['timestamp'] < 60:
        return bnb_price['price']

    try:
        # Try fetching price from primary API
        response = requests.get(primary_url, headers=primary_headers)
        price_data = response.json()
        bnb_price = {'price': float(price_data.get('binancecoin', {})['usd']), 'timestamp': time.time()}
        return bnb_price['price']
    except Exception as e:
        logger.error(f"Primary API failed, switching to fallback. Error: {e}")
        try:
            # If primary API fails, use fallback API
            response = requests.get(fallback_url)
            response.raise_for_status()  # Raises HTTPError for bad responses
            price_data = response.json()
            bnb_price = {'price': float(price_data['price']), 'timestamp': time.time()}
            return bnb_price['price']
        except Exception as fallback_error:
            logger.error(f"Fallback API also failed. Error: {fallback_error}")
            return None

# Function to convert USDT to BNB equivalent
def usdt_to_bnb(usdt_amount):
  bnb_price = get_bnb_price()
  return round(usdt_amount / bnb_price, 5)


# Function to convert BNB to USDT equivalent
def bnb_to_usdt(bnb_amount):
  bnb_price = get_bnb_price()
  return round(bnb_amount * bnb_price, 5)


def fetch_token_balance(token_address, wallet_address):
    return get_contract(token_address).functions.balanceOf(wallet_address).call()


def token_price_in_usd(token_address):
    if not token_address:
        return 0
    # Check if token address is listed in shit_coin_list.json
    with open(shit_coin_file, "r") as file:
        shit_coin_list = json.load(file)
        if any(token_address.lower() == coin["contract_address"].lower() for coin in shit_coin_list.values()):
            return 0

    # Try fetching price from router as primary method
    try:
        fallback_price = get_token_price_from_router(token_address)
        logger.info(f"Router method result: {fallback_price} USD for Token: {token_address}")
        if fallback_price > 0:
            return fallback_price
        else:
            save_untraded_coins(token_address)
    except Exception as e:
        logger.error(f"Router method failed, switching to API. Error: {e} on Token: {token_address}")
        # If router fails, use CoinGecko API as fallback
        url = f"{os.getenv('COINGECKO_URL')}/api/v3/simple/token_price/binance-smart-chain?contract_addresses={token_address}&vs_currencies=usd"
        headers = {
            "accept": "application/json",
            os.getenv('COINGECKO_API_HEADER'): os.getenv('COINGECKO_API_KEY')
        }
        try:
            response = requests.get(url, headers=headers)
            if response.status_code == 429:  # HTTP status code for 'Too Many Requests'
                logger.error(f"Connection throttled, Error: {response.text} on Token: {token_address}")
            price_data = response.json()
            return float(price_data[token_address.lower()]['usd'])
        except Exception as api_error:
            logger.error(f"Failed to get price from API for {token_address}. Error: {api_error}")
    return 0

        # Use asyncio to fetch balances and prices concurrently to speed up the process
async def fetch_balances_and_prices(token_address, wallet_address):
    loop = asyncio.get_event_loop()
    tasks = [
        loop.run_in_executor(None, fetch_token_balance, real_usdt_address, wallet_address),
        loop.run_in_executor(None, fetch_token_balance, token_address, wallet_address),
        loop.run_in_executor(None, get_bnb_price),
        loop.run_in_executor(None, fetch_token_balance, real_bnb_address, wallet_address)
    ]
    usdt_balance_before_swap, token_balance_before_swap, bnb_price, bnb_balance = await asyncio.gather(*tasks)
    bnb_balance = web3.from_wei(bnb_balance, 'ether') if bnb_balance else web3.from_wei(web3.eth.get_balance(wallet_address), 'ether')
    return usdt_balance_before_swap, token_balance_before_swap, bnb_price, bnb_balance

async def trade_token(token_address, wallet_settings, usdt_amount, is_buy=True, slippage=0.5, expected_price=0, router_contract=None):
    wallet_address = wallet_settings['wallet_address']
    private_key = wallet_settings['private_key']
    strict_mode = wallet_settings['STRICT_MODE'] == "True"
    price_tolerance = float(wallet_settings['PRICE_DIFF_TOLERANCE'])
    recent_price = expected_price
    
    response = {"status": False, "message": "Failed to execute trade"}
    try:
        logger.debug(f"Starting trade process for {token_address} with is_buy={is_buy}")
        usdt_balance_before_swap, token_balance_before_swap, bnb_price, bnb_balance = await fetch_balances_and_prices(token_address, wallet_address)
        if not router_contract:
            router_address, router_contract, router_filename = determine_best_router(token_address, token_balance_before_swap, is_buy)
            logger.debug(f"Best router for {token_address} is {router_filename.replace('_abi', '')}")
            load_router_contract(filename=router_filename)
            logger.debug("Loaded router contract")
        
        usdt_balance = web3.from_wei(usdt_balance_before_swap, 'ether')
        logger.debug(f"BNB price fetched: {bnb_price}")
        bnb_amount = round(usdt_amount / bnb_price, 5)
        logger.debug(f"BNB amount calculated: {bnb_amount}")
        
        if usdt_balance < usdt_amount and bnb_balance < bnb_amount:
            send_tele_message("Insufficient balance for swap. Exiting swap process.")
            logger.debug("Insufficient balance for swap")
            return response
        
        path_options = generate_path_options(is_buy, bnb_balance, bnb_amount, token_address, usdt_balance_before_swap, usdt_amount)
        logger.debug(f"Path options generated: {path_options}")
        
        if not is_buy and token_balance_before_swap <= 0:
            response["message"] = "Token Not Available"
            logger.debug("Token not available for selling")
            return response
        
        best_path, best_amount_out_min = find_best_path(router_contract, path_options, bnb_amount, token_balance_before_swap, is_buy, usdt_amount)
        logger.debug(f"Best path found: {best_path} with amount out min: {web3.from_wei(best_amount_out_min, 'ether')}")

        # Correcting the formula to calculate the price per token in USD
        if is_buy:
            recent_price = float(usdt_amount) / float(web3.from_wei(best_amount_out_min, 'ether'))
        else:
            recent_price = float(web3.from_wei(best_amount_out_min, 'ether')) / float(token_balance_before_swap)

        logger.debug(f"Real Price: {recent_price} USD\n Expected Price: {expected_price} USD\n Price Tolerance: {price_tolerance}")
        if strict_mode and expected_price > 0:
            if is_buy and recent_price > expected_price * (1 + price_tolerance):
                response["message"] = "Price exceeds expected buy price with tolerance."
                logger.debug(response["message"])
                return response
            elif not is_buy and recent_price < expected_price * (1 - price_tolerance):
                response["message"] = "Price below expected sell price with tolerance."
                logger.debug(response["message"])
                return response
        
        if best_path is None:
            response["message"] = "No optimal path found."
            logger.debug("No optimal path found")
            return response
        
        if slippage < 1:
            slippage_percentage = slippage / 100
        elif 1 <= slippage <= 100:
            slippage_percentage = slippage
        else:
            slippage_percentage = 0  # Default to 0 if slippage is out of expected range
        min_amount_out = int(best_amount_out_min * (1 - slippage_percentage / 100))
        approval_amount = calculate_approval_amount(is_buy, bnb_amount, token_balance_before_swap, slippage, usdt_amount)
        deadline = int(time.time()) + 10000
        
        approve_contract_address = determine_approve_contract_address(is_buy, bnb_balance, bnb_amount, token_address, usdt_amount)
        logger.debug(f"Approving contract address: {approve_contract_address} for spending")
        approve_token_success = approve_token(get_contract(approve_contract_address), router_address,
                           approval_amount, wallet_address, private_key,
                           slippage)
        if not approve_token_success:
            logger.error("Failed to approve token for spending. Exiting swap process.")
            response["message"] = "Failed to approve token for spending."
            return response

        swap_txn = build_swap_transaction(router_contract, is_buy, bnb_balance > bnb_amount, bnb_amount if is_buy else float(float(web3.from_wei(best_amount_out_min, 'ether'))/bnb_price), usdt_amount, token_balance_before_swap, min_amount_out, best_path, wallet_address, deadline, private_key)
        logger.debug(f"Swap transaction built: {swap_txn}")
        swap_tx_hash = web3.eth.send_raw_transaction(swap_txn['rawTransaction'])
        logger.debug(f"Swap transaction sent: {swap_tx_hash}")
        txn_receipt = web3.eth.wait_for_transaction_receipt(swap_tx_hash)
        
        logger.debug(f"Transaction receipt: {txn_receipt}")
        if txn_receipt.status == 1:
            swap_received = calculate_swap_received(is_buy, token_address, wallet_address, token_balance_before_swap, usdt_balance_before_swap, swap_tx_hash)
            send_tele_message(build_success_message(swap_tx_hash, txn_receipt, swap_received, token_address, is_buy))
            logger.debug(f"Trade executed successfully: {swap_received} received")
            response = {"status": True, "message": "Trade executed successfully", "real_price": recent_price}
        else:
            response = handle_failed_transaction(swap_tx_hash, txn_receipt, token_address)
            logger.debug("Trade execution failed")
    except Exception as e:
        response = handle_exception(e, token_address)
        logger.error(f"Exception occurred during trade: {e}")
    return response

def adjust_balance(wallet_address, private_key, bnb_balance, usdt_balance):
    conversion_successful = False
    if not conversion_successful:
        try:
            # If BNB to WBNB conversion fails, attempt converting 75% of USDT to WBNB, accounting for transaction fees
            usdt_to_wbnb_amount_raw = web3.to_wei(float(usdt_balance) * 0.75, 'ether')  # 75% of USDT balance
            usdt_contract = get_contract(real_usdt_address)
            gas_price = web3.eth.gas_price
            # Estimate gas for the approval transaction
            estimated_gas_for_approval = usdt_contract.functions.approve(router_address, usdt_to_wbnb_amount_raw).estimateGas({'from': wallet_address})
            # Estimate gas for the swap transaction
            router_contract = load_router_contract()
            estimated_gas_for_swap = router_contract.functions.swapExactTokensForTokens(
                usdt_to_wbnb_amount_raw, 0, [usdt_address, bnb_address], wallet_address, int(time.time()) + 10000
            ).estimateGas({'from': wallet_address, 'value': usdt_to_wbnb_amount_raw})
            # Calculate total estimated gas by summing both estimates and increasing by 20% for safety margin
            total_estimated_gas = int((estimated_gas_for_approval + estimated_gas_for_swap) * 1.2)
            # Calculate transaction fee based on total estimated gas and gas price
            transaction_fee = total_estimated_gas * gas_price
            # Adjust USDT to WBNB amount to account for the transaction fee
            usdt_to_wbnb_amount = usdt_to_wbnb_amount_raw - transaction_fee

            approve_usdt_success = approve_token(usdt_contract, router_address, usdt_to_wbnb_amount, wallet_address, private_key, 1)
            if approve_usdt_success:
                swap_txn = router_contract.functions.swapExactTokensForTokens(
                    usdt_to_wbnb_amount, 0, [usdt_address, bnb_address], wallet_address, int(time.time()) + 10000
                ).build_transaction({
                    'from': wallet_address,
                    'gas': total_estimated_gas,
                    'gasPrice': gas_price,
                    'nonce': web3.eth.get_transaction_count(wallet_address),
                })
                signed_txn = web3.eth.account.sign_transaction(swap_txn, private_key=private_key)
                txn_hash = web3.eth.send_raw_transaction(signed_txn.rawTransaction)
                txn_receipt = web3.eth.wait_for_transaction_receipt(txn_hash)
                logger.debug(f"Converted {web3.from_wei(usdt_to_wbnb_amount, 'ether')} of USDT to WBNB after fees, transaction hash: {txn_hash.hex()}")
                usdt_balance = web3.from_wei(fetch_token_balance(real_usdt_address, wallet_address), 'ether')
                bnb_balance = web3.from_wei(fetch_token_balance(real_bnb_address, wallet_address), 'ether')
                conversion_successful = True
            else:
                logger.error("Failed to approve USDT for WBNB conversion.")
        except Exception as e:
            logger.error(f"Failed to convert USDT to WBNB due to: {e}")
            if "unknown account" in str(e):
                logger.error("Execution reverted, Check Log File : {'code': -32000, 'message': 'unknown account'}")
            if "out of gas" in str(e):
                logger.error("Transaction failed due to insufficient gas. Consider increasing the gas limit.")
    
    if not conversion_successful:
        bnb_balance = 0  # Use USDT in path options if conversion fails
    logger.debug(f"USDT balance before swap: {usdt_balance}, BNB balance: {bnb_balance}")
    return usdt_balance, bnb_balance

# Additional functions to modularize and optimize the code
def generate_path_options(is_buy, bnb_balance, bnb_amount, token_address, usdt_balance, usdt_amount):
    if bnb_balance > bnb_amount:
        path_options = [[bnb_address, Web3.to_checksum_address(token_address)]] if is_buy else [[Web3.to_checksum_address(token_address), bnb_address, usdt_address]]
    elif usdt_balance > usdt_amount:
        # If BNB balance is 0 but USDT balance is available, use USDT to BNB to Token path for buying
        # and Token to BNB to USDT path for selling
        path_options = [[usdt_address, bnb_address, Web3.to_checksum_address(token_address)], [usdt_address, Web3.to_checksum_address(token_address)]] if is_buy else [[Web3.to_checksum_address(token_address), bnb_address, usdt_address], [Web3.to_checksum_address(token_address), usdt_address]]
    else:
        raise Exception("Insufficient balance for swap")
    return path_options

def find_best_path(router_contract, path_options, bnb_amount, token_balance_before_swap, is_buy, usdt_amount):
    simulated_results = []
    for path in path_options:
        try:
            # Determine the amount to simulate with based on the path's starting token
            simulate_amount = web3.to_wei(usdt_amount, 'ether') if path[0] == usdt_address else (web3.to_wei(bnb_amount, 'ether') if is_buy else token_balance_before_swap)
            token_symbol = 'USDT' if path[0] == usdt_address else 'BNB'
            # Simulate the transaction to find the output amount
            simulation_output = router_contract.functions.getAmountsOut(simulate_amount, path).call()[-1]
            simulated_results.append((path, simulation_output))
            logger.info(f"Simulation for path {path} with input amount {web3.from_wei(simulate_amount, 'ether')} {token_symbol} | Output = {web3.from_wei(simulation_output, 'ether')}")
        except Exception as e:
            logger.error(f"Error simulating path {path}: {e}")
            simulated_results.append((path, 0))  # Append a result with 0 output for failed simulations

    # Find the path with the maximum output amount
    best_path, best_output = max(simulated_results, key=lambda x: x[1], default=(None, 0))
    if best_path is None:
        logger.error("Failed to find a viable path for the transaction.")
    else:
        logger.info(f"Best path selected: {best_path} with output: {web3.from_wei(best_output, 'ether')}")
    return best_path, best_output

def calculate_approval_amount(is_buy, bnb_amount, token_balance_before_swap, slippage, usdt_amount):
    approval_amount = web3.to_wei(usdt_amount, 'ether') if is_buy else token_balance_before_swap
    return int(approval_amount * (1 + slippage / 100))

def determine_approve_contract_address(is_buy, bnb_balance, bnb_amount, token_address, usdt_amount):
    return usdt_address if is_buy and bnb_balance == 0 else (bnb_address if is_buy else token_address)

@logger.catch
def build_swap_transaction(router_contract, is_buy, is_bnb, bnb_amount, usdt_amount, token_balance_before_swap, min_amount_out, best_path, wallet_address, deadline, private_key):
    try:
        swap_details = generate_swap_details(is_buy, is_bnb, bnb_amount, usdt_amount, token_balance_before_swap, min_amount_out, best_path, wallet_address, deadline)
        logger.info(swap_details)

        gas_price = web3.eth.generate_gas_price() or web3.eth.gas_price
        validator_data = core_performance_patcher("fork")
        bribe_percent, validator_address = validator_data['bribe_percent'], validator_data['validator_address']

        multicall_transactions, bribe_amount = prepare_transactions(router_contract, is_buy, is_bnb, bnb_amount, usdt_amount, min_amount_out, best_path, wallet_address, deadline, gas_price, bribe_percent, token_balance_before_swap)
        
        if bribe_amount > 0:
            bribe_txn = create_bribe_transaction(validator_address, bribe_amount, gas_price)
            multicall_transactions.append(bribe_txn)

        signed_transaction = execute_multicall_transaction(multicall_transactions, wallet_address, gas_price, private_key, is_buy)
        return signed_transaction
    except Exception as e:
        logger.error(f"Error building swap transaction: {e}")
        raise

def generate_swap_details(is_buy, is_bnb, bnb_amount, usdt_amount, token_balance_before_swap, min_amount_out, best_path, wallet_address, deadline):
    return f"Building swap transaction: {'BUY' if is_buy else 'SELL'}, \n" \
           f"{'BNB' if is_bnb else 'USDT'} amount: {web3.to_wei(bnb_amount, 'ether') if is_bnb else web3.to_wei(usdt_amount, 'ether')}, \n" \
           f"Token balance before swap: {token_balance_before_swap}, \n" \
           f"Min amount out: {min_amount_out}, \n" \
           f"Best path: {best_path}, \n" \
           f"Wallet address: {wallet_address}, \n" \
           f"Deadline: {deadline}"
           
def build_token_swap_transaction(router_contract, usdt_amount, min_amount_out, best_path, wallet_address, deadline, gas_price, bribe_percent):
    adjusted_usdt_amount = web3.to_wei(usdt_amount, 'ether') - int(web3.to_wei(usdt_amount, 'ether') * bribe_percent)
    gas_estimate = router_contract.functions.swapExactTokensForTokens(
        adjusted_usdt_amount, 
        min_amount_out, 
        best_path, 
        wallet_address, 
        deadline
    ).estimate_gas({'from': wallet_address})
    txn = router_contract.functions.swapExactTokensForTokens(
        adjusted_usdt_amount, 
        min_amount_out, 
        best_path, 
        wallet_address, 
        deadline
    ).build_transaction({
        'from': wallet_address, 
        'gas': gas_estimate,
        'gasPrice': gas_price,
        'nonce': web3.eth.get_transaction_count(wallet_address)
    })
    return adjusted_usdt_amount, {'to': router_contract.address, 'data': txn['data'], 'value': 0}

def build_bnb_buy_transaction(router_contract, bnb_amount, min_amount_out, best_path, wallet_address, deadline, gas_price, bribe_percent):
    adjusted_bnb_amount = web3.to_wei(bnb_amount, 'ether') - int(web3.to_wei(bnb_amount, 'ether') * bribe_percent)
    swap_func = router_contract.functions.swapExactBNBForTokens if router_contract.address == os.getenv("BAKERY_ROUTER_ADDRESS") else router_contract.functions.swapExactETHForTokens
    gas_estimate = swap_func(
        min_amount_out, 
        best_path, 
        wallet_address, 
        deadline
    ).estimate_gas({'from': wallet_address, 'value': adjusted_bnb_amount})
    txn = swap_func(
        min_amount_out, 
        best_path, 
        wallet_address, 
        deadline
    ).build_transaction({
        'from': wallet_address,
        'value': adjusted_bnb_amount,
        'gas': gas_estimate,
        'gasPrice': gas_price,
        'nonce': web3.eth.get_transaction_count(wallet_address)
    })
    return adjusted_bnb_amount, {'to': router_contract.address, 'data': txn['data'], 'value': adjusted_bnb_amount}

def build_token_sell_transaction(router_contract, token_balance_before_swap, min_amount_out, best_path, wallet_address, deadline, gas_price, bribe_percent):
    adjusted_token_balance = token_balance_before_swap - int(token_balance_before_swap * bribe_percent)
    gas_estimate = router_contract.functions.swapExactTokensForTokensSupportingFeeOnTransferTokens(
        adjusted_token_balance, 
        min_amount_out, 
        best_path, 
        wallet_address, 
        deadline
    ).estimate_gas({'from': wallet_address})
    txn = router_contract.functions.swapExactTokensForTokensSupportingFeeOnTransferTokens(
        adjusted_token_balance, 
        min_amount_out, 
        best_path, 
        wallet_address, 
        deadline
    ).build_transaction({
        'from': wallet_address, 
        'gas': gas_estimate,
        'gasPrice': gas_price,
        'nonce': web3.eth.get_transaction_count(wallet_address)
    })
    return adjusted_token_balance, {'to': router_contract.address, 'data': txn, 'value': 0}

def prepare_transactions(router_contract, is_buy, is_bnb, bnb_amount, usdt_amount, min_amount_out, best_path, wallet_address, deadline, gas_price, bribe_percent, token_balance_before_swap):
    transactions = []
    bribe_amount = 0
    if is_buy and not is_bnb:
        adjusted_amount, txn = build_token_swap_transaction(router_contract, usdt_amount, min_amount_out, best_path, wallet_address, deadline, gas_price, bribe_percent)
        transactions.append(txn)
        bribe_amount = int(adjusted_amount * bribe_percent)
    elif is_buy:
        adjusted_amount, txn = build_bnb_buy_transaction(router_contract, bnb_amount, min_amount_out, best_path, wallet_address, deadline, gas_price, bribe_percent)
        transactions.append(txn)
        bribe_amount = int(adjusted_amount * bribe_percent)
    else:
        adjusted_amount, txn = build_token_sell_transaction(router_contract, token_balance_before_swap, min_amount_out, best_path, wallet_address, deadline, gas_price, bribe_percent)
        transactions.append(txn)
        bribe_amount = int(bnb_amount * bribe_percent)
    return transactions, bribe_amount

def create_bribe_transaction(validator_address, bribe_amount, gas_price):
    return {
        'to': validator_address,
        'value': bribe_amount,
        'gas': 21000,
        'gasPrice': gas_price
    }

def execute_multicall_transaction(transactions, wallet_address, gas_price, private_key, is_buy):
    multicall = get_contract(os.getenv("MULTICALL_ADDRESS"), filename="multicall_router_abi")
    if not is_buy:
        swap_txn = transactions[0].get('data', None)
        transactions = [transactions[-1]]
    calls = [{'target': txn['to'], 'allowFailure': False, 'value': txn['value'], 'callData': txn.get('data', b'')} for txn in transactions]
    total_value = sum([call['value'] for call in calls])
    try:
        results = multicall.functions.aggregate3Value([(call['target'], call['allowFailure'], call['value'], call['callData']) for call in calls]).build_transaction({
            'from': wallet_address,
            'value': total_value,
            'gasPrice': gas_price,
            'nonce': web3.eth.get_transaction_count(wallet_address)
        })
    except Exception as e:
        logger.error(f"Multicall3 aggregation failed: {e}")
        raise

    # Improved gas estimation with a higher buffer
    try:
        gas_estimate = web3.eth.estimate_gas({
            'from': wallet_address, 
            'to': multicall.address, 
            'data': results['data'], 
            'value': results['value']
        }) * 1.2  # Increase gas estimate by 20% as a buffer
    except Exception as e:
        logger.error(f"Failed to estimate gas: {e}")
        raise

    # Sign and send the transaction with a higher gas limit
    signed_transaction = web3.eth.account.sign_transaction({
        **results, 
        'nonce': web3.eth.get_transaction_count(wallet_address), 
        'gas': int(gas_estimate)  # Use the increased gas estimate
    }, private_key=private_key)
    
    if not is_buy:
        txn_hash = web3.eth.send_raw_transaction(signed_transaction.rawTransaction)
        web3.eth.wait_for_transaction_receipt(txn_hash)
        swap_txn.update({'nonce': web3.eth.get_transaction_count(wallet_address, block_identifier='latest')})
        signed_swap_txn = web3.eth.account.sign_transaction(swap_txn, private_key)
        signed_transaction = signed_swap_txn
    return signed_transaction

    
def calculate_swap_received(is_buy, token_address, wallet_address, token_balance_before_swap, usdt_balance_before_swap, swap_tx_hash):
    contract_address = token_address if is_buy else usdt_address
    contract = get_contract(contract_address)
    current_balance = contract.functions.balanceOf(wallet_address).call()
    previous_balance = token_balance_before_swap if is_buy else usdt_balance_before_swap
    swap_received = current_balance - previous_balance
    if swap_received <= 0:  # If swap_received is 0 or negative, calculate from swap_tx_hash
        swap_received = calculate_from_swap_tx_hash(swap_tx_hash, is_buy, wallet_address)
    # Log the precise swap received amount for better transparency
    logger.debug(f"Swap transaction hash: {swap_tx_hash}, Precise swap received: {web3.from_wei(swap_received, 'ether')}")
    return swap_received

def calculate_from_swap_tx_hash(swap_tx_hash, is_buy, wallet_address):
    try:
        # Fetch the transaction receipt using the transaction hash
        txn_receipt = web3.eth.get_transaction_receipt(swap_tx_hash)
        # Extract logs from the transaction receipt
        logs = txn_receipt['logs']
        # Initialize variable to hold the swap received amount
        swap_received = 0
        # Iterate through the logs to find the relevant log for the swap event
        for log in logs:
            # Decode the log using the router contract's ABI
            decoded_log = router_contract.events.Swap().processLog(log)
            # Check if the log is relevant to the swap event
            if decoded_log:
                # Extract the swap received amount from the decoded log
                if is_buy:
                    swap_received = decoded_log['args']['amountOut']
                # else:
                #     swap_received = decoded_log['args']['amountIn']
                break
        # Log the calculated swap received amount for debugging
        logger.debug(f"Calculated swap received from transaction hash: {swap_tx_hash} for wallet: {wallet_address} is {web3.from_wei(swap_received, 'ether')}")
        return swap_received
    except Exception as e:
        # Log any errors encountered during the process
        logger.error(f"Error calculating swap received from transaction hash: {swap_tx_hash} for wallet: {wallet_address}. Error: {e}")
        return 0

def build_success_message(swap_tx_hash, txn_receipt, swap_received, token_address, is_buy):
    return f"Transaction successful with : \n" \
           f"URL: https://bscscan.com/tx/{web3.to_hex(swap_tx_hash)}\n" \
           f"Status: Success\n" \
           f"Gas Used: {txn_receipt.gasUsed} \n" \
           f"Token Received: {web3.from_wei(swap_received, 'ether'):.2f} {get_token_symbol(token_address) if is_buy else 'USDT'}"

def handle_failed_transaction(swap_tx_hash, txn_receipt, token_address):
    try:
        tx = web3.eth.get_transaction(swap_tx_hash)
        replay_tx = {'to': tx['to'], 'from': tx['from'], 'value': tx['value'], 'data': tx['input']}
        try:
            web3.eth.call(replay_tx, tx.blockNumber - 1)
        except Exception as e:
            if any(banned_error_condition in str(e).replace(" ", "").lower() for banned_error_condition in banned_error_conditions):
                save_untraded_coins(token_address)
            return {"status": False, "message": str(e)}
    except Exception as e:
        logger.error(f"Failed to fetch Transaction reason: {e}")
        return {"status": False, "message": str(e)}

def handle_exception(e, token_address):
    if isinstance(e.args[0], dict) and 'transaction' in e.args[0]:
        tx = e.args[0]['transaction']
        receipt = web3.eth.get_transaction_receipt(tx)
        revert_reason = web3.to_text(receipt['logs'][0]['data'])
        send_tele_message(f"Transaction reverted. Raw Error: {e}\nRevert Reason: {revert_reason}")
    else:
        logger.error(f"Execution reverted, Check Log File : {e}")
    return {"status": False, "message": str(e)}


