import asyncio
import sqlite3
from web3 import Web3
from eth_account import Account
from multicall import Call, Multicall
from tqdm.asyncio import tqdm
from loguru import logger
import os
from transaction_builder import get_contract

# Constants
NETWORKS = {
    'bnb': 'https://neat-fragrant-forest.bsc.quiknode.pro/12871fa4bda0ec5948382487c64274903598d1ef/',
    # 'eth': 'https://mainnet.infura.io/v3/YOUR_INFURA_PROJECT_ID'
}
WALLET_COUNT = 3000  # Default number of wallets to generate if no keys are provided

# Database setup
conn = sqlite3.connect('wallets.db')
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS valid_wallets
             (network TEXT, address TEXT, private_key TEXT, seed_phrase TEXT, balance TEXT)''')
conn.commit()
web3 = None

def from_wei(value):
    return web3.from_wei(value, 'ether')

def get_private_keys():
    keys_input = input("Enter private keys separated by newlines (leave blank to generate new wallets): \n")
    if keys_input.strip():
        return keys_input.split('\n')
    else:
        return [Account.create()._private_key.hex() for _ in range(WALLET_COUNT)]

async def create_and_check_wallets(network_name, web3, private_keys):
    # Example Multicall contract address (replace with actual address for your network)
    bnb_address = '0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c'  # BNB address for example
    eth_address = '0x420000000000000000000000006'  # ETH address for example

    accounts = [Account.from_key(key.strip()) for key in private_keys]
    print(f"Accounts: {accounts[0].address}")

    # Prepare multicall
    multicall = get_contract(os.getenv("MULTICALL_ADDRESS"), filename='multicall_abi')

    # Create Call objects for getting balances using Multicall
    # calls = [Call(bnb_address if network_name == 'bnb' else eth_address, ['balanceOf(address)(uint256)', account.address], [(account.address, from_wei)]) for account in accounts]
    call_data = [get_contract(web3.to_checksum_address(bnb_address if network_name == 'bnb' else eth_address), filename='mock_abi').functions.balanceOf(account.address)._encode_transaction_data() for account in accounts]
    calls = [(web3.to_checksum_address(bnb_address if network_name == 'bnb' else eth_address), True, data) for data in call_data]
    # Execute multicall
    results = multicall.functions.aggregate3(calls).call()

    progress_bar = tqdm(total=len(accounts), desc=f"Scanning {network_name} wallets", unit="wallet")
    for account, result in zip(accounts, results):
        try:
            # Decode the output for each account
            from eth_abi import abi
            if result[1] != b'':
                balance = abi.decode(['uint256'], result[1])[0]
                logger.info(f"Wallet: {account.address} | Raw Balance: {balance} | Converted Balance: {from_wei(balance)}")
                if float(balance) > 0:
                    # Save to database
                    c.execute("INSERT INTO valid_wallets VALUES (?, ?, ?, ?, ?)",
                              (network_name, account.address, account.private_key, '', str(balance)))
                    conn.commit()
            else:
                logger.info(f"Wallet: {account.address} | No balance returned")
        except Exception as e:
            logger.error(f"Failed to decode output for wallet {account.address}: {e}")
        progress_bar.update(1)
    progress_bar.close()

async def main():
    global web3
    tasks = []
    for network_name, url in NETWORKS.items():
        web3 = Web3(Web3.HTTPProvider(url))
        private_keys = get_private_keys()
        task = asyncio.create_task(create_and_check_wallets(network_name, web3, private_keys))
        tasks.append(task)
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    try:
        while True:
            asyncio.run(main())
    except KeyboardInterrupt:
        print("Stopped by user.")
    finally:
        conn.close()