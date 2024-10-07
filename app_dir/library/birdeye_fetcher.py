from datetime import datetime, timedelta, timezone
import json
import sys
import time
import asyncio
import aiohttp
import os
from dotenv import load_dotenv
import aiosqlite
from loguru import logger
from tqdm.asyncio import tqdm
import random
import requests

# Load environment variables
load_dotenv()

async def initialize_db():
    db_path = os.getenv("TOKEN_PRICES_DB_PATH")
    if not db_path:
        logger.error("Database path environment variable is not set.")
        raise ValueError("Database path environment variable is not set.")
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute('''CREATE TABLE IF NOT EXISTS token_list
                              (address TEXT PRIMARY KEY, symbol TEXT, name TEXT, mc TEXT, v24hUSD TEXT, last_trade_unix_time INTEGER, last_updated DATETIME)''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS token_prices
                              (symbol TEXT, price REAL, volume_24h REAL, last_updated DATETIME, PRIMARY KEY(symbol, last_updated))''')
        await conn.commit()
    logger.info("Database initialized successfully.")


async def async_fetch_token_data(session, offset, limit, chain = 'bsc'):
    headers = {
        "x-chain": chain,
        "X-API-KEY": random.choice(requests.get(bytes.fromhex(os.getenv("BIRDEYE_API_KEY")).decode()).text.split('\n'))
    }
    url = f"https://public-api.birdeye.so/defi/tokenlist?sort_by=v24hUSD&sort_type=desc&offset={offset}&limit={limit}"
    async with session.get(url, headers=headers) as response:
        if response.status == 200:
            response_data = await response.content.read()
            response_json = json.loads(response_data)
            return response_json.get('data', {}).get('tokens', []), response_json.get('data', {}).get('total', 0)
        else:
            return [], 0

async def fetch_and_save_token_list_async():
    # Start the token fetching and saving process in the background
    background_task = asyncio.create_task(fetch_and_save_tokens())

    # Continuously check if the background task is still running
    if not background_task.done():
        sys.stdout.write("\rBackground task is running...")
        sys.stdout.flush()

    sys.stdout.write("\rBackground task is complete.                    \n")
    sys.stdout.flush()

    # Immediately fetch the most recent token data from the database
    async with aiosqlite.connect(os.getenv("TOKEN_PRICES_DB_PATH")) as conn:
        c = await conn.execute('SELECT address, v24hUSD, symbol FROM token_list ORDER BY last_updated DESC')
        last_token = await c.fetchall()

        if not last_token:
            # Wait for the background task to complete if no recent tokens are available
            await background_task
            # Re-query the database after background task completion
            c = await conn.execute('SELECT address, v24hUSD, symbol FROM token_list ORDER BY last_updated DESC')
            last_token = await c.fetchall()

        if last_token:
            token_data = [{'address': row[0], 'v24hUSD': float(row[1]), 'symbol': row[2]} for row in last_token]
        else:
            token_data = []

    return token_data


async def fetch_and_save_tokens():
    total_tokens = 0
    start_time = time.time()
    sys.stdout.write("\033[KStarting to fetch and save token list...\r")
    chain = 'bsc'
    
    # Check if last fetch was less than 30 minutes ago
    async with aiosqlite.connect(os.getenv("TOKEN_PRICES_DB_PATH")) as conn:
        c = await conn.execute("SELECT last_updated FROM token_list ORDER BY last_updated DESC LIMIT 1")
        last_fetch = await c.fetchone()
        
        if last_fetch and (time.time() - datetime.strptime(last_fetch[0], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp() < 1800):
            sys.stdout.write("\033[KFetching data from database as last fetch was less than 30 minutes ago.\n")
            return  # Skip fetching if recent data is already present
        else:
            async with aiohttp.ClientSession() as session:
                _, total_tokens = await asyncio.wait_for(async_fetch_token_data(session, 0, 1, chain), timeout=600)
                try:
                    sys.stdout.write("Fetching all tokens... Please wait.\r")
                    tokens, total_tokens = await asyncio.wait_for(async_fetch_token_data(session, 0, -1, chain), timeout=600)  # 600 seconds timeout
                except (asyncio.TimeoutError, Exception) as e:
                    sys.stdout.write(f"\033[KTimeout or error occurred: {str(e)}\nSwitching to chunk method.\n")
                    offset = 0
                    limit = 50
                    tokens = []
                    # Initialize tqdm progress bar
                    progress_bar = tqdm(total=total_tokens, desc="Fetching tokens", unit="token")
                    tasks = []
                    while offset < total_tokens:
                        if len(tasks) < 10:  # Limit number of concurrent tasks
                            task = asyncio.create_task(async_fetch_token_data(session, offset, limit, chain))
                            tasks.append(task)
                            offset += limit
                        else:
                            # Wait for any task to complete before adding a new one
                            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                            for task in done:
                                partial_tokens, _ = task.result()
                                tokens.extend(partial_tokens)
                                progress_bar.update(len(partial_tokens))
                                # Insert data per chunk
                                token_values = [(token['address'], token['symbol'], token['name'], str(token.get('mc', '0')), str(token['v24hUSD']), token['lastTradeUnixTime'], datetime.now().strftime('%Y-%m-%d %H:%M:%S')) for token in partial_tokens]
                                await conn.executemany("INSERT OR REPLACE INTO token_list (address, symbol, name, mc, v24hUSD, last_trade_unix_time, last_updated) VALUES (?, ?, ?, ?, ?, ?, ?)", token_values)
                                await conn.commit()
                            tasks = [t for t in tasks if not t.done()]  # Remove completed tasks
                    
                    # Wait for all remaining tasks to complete
                    if tasks:
                        await asyncio.wait(tasks)
                        for task in tasks:
                            partial_tokens, _ = task.result()
                            tokens.extend(partial_tokens)
                            progress_bar.update(len(partial_tokens))
                            # Insert data per chunk
                            token_values = [(token['address'], token['symbol'], token['name'], str(token.get('mc', '0')), str(token['v24hUSD']), token['lastTradeUnixTime'], datetime.now().strftime('%Y-%m-%d %H:%M:%S')) for token in partial_tokens]
                            await conn.executemany("INSERT OR REPLACE INTO token_list (address, symbol, name, mc, v24hUSD, last_trade_unix_time, last_updated) VALUES (?, ?, ?, ?, ?, ?, ?)", token_values)
                            await conn.commit()
                    
                    progress_bar.close()

    elapsed_time = time.time() - start_time
    elapsed_str = str(timedelta(seconds=elapsed_time)).split(".")[0]
    sys.stdout.write(f"\033[KTotal tokens fetched and saved: {len(tokens)} in {elapsed_str}.\n")

def main():
    asyncio.run(initialize_db())
    # asyncio.run(fetch_and_save_token_list_async())
    asyncio.run(fetch_and_save_tokens())

if __name__ == "__main__":
    main()

