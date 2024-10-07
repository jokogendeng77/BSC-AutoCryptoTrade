import os
import json
from dotenv import load_dotenv
import numpy as np
from termcolor import colored
import datetime
import random  # Import for simulating network factors
from library.transaction_builder import estimate_gas_fee, check_coin_approval, calculate_slippage  # Importing functions from modified_trade.py
from loguru import logger
from tqdm import tqdm  # Import for progress bar
import argparse
import itertools


# Load environment variables
load_dotenv()

# Check if DEBUG_MODE is enabled
DEBUG_MODE = os.getenv('DEBUG_MODE', 'False') == 'True'

# Initialization
coin_mapping = {}
coin_counts = {}
desired_coin_list = os.getenv('DESIRED_COIN_FILE', 'desired_coin_list.json')
available_coin_list = os.getenv('AVAILABLE_COIN_FILE', 'available_coin_list.json')

def load_json_file(file_path):
    """Load and return JSON data from a file."""
    with open(file_path, 'r') as file:
        return json.load(file)

def filter_market_data(binance_coins):
    """Filter and return market data for coins present in binance_coins."""
    coin_list = load_json_file(available_coin_list)
    return {coin_id: coin_info['symbol'].lower() for coin_id, coin_info in coin_list.items() if coin_info['symbol'].lower() in binance_coins}

# Load wallet settings
wallet_settings = load_json_file(os.getenv('WALLET_SETTINGS', 'wallet_settings.json'))

# Filter market data for desired coins
coin_mapping = filter_market_data([coin.lower() for coin in load_json_file(desired_coin_list)])

token_state = {}

# Initialize trading statistics for each wallet
wallet_trading_stats = {wallet_id: {
    'wins': 0,
    'losses': 0,
    'current_holdings': {},
    'total_profit': 0,
    'money_spent': 0,
    'total_money_gained': 0,
    'total_money_lost': 0,
    'winning_trades': [],
    'losing_trades': [],
    'average_holding_duration': 0,
    'trade_count': 0,
    'total_trades_executed': 0,
    'total_holding_value': 0,
    'total_holding_trades': 0,
    'execution_failures': 0,
    'gas_fee_spent': 0,  # New field to track gas fees spent on trades
    'failed_approvals': 0,  # New field to track failed coin approvals
    'slippage_losses': 0,  # New field to track losses due to slippage
} for wallet_id, settings in wallet_settings.items()}

# Load and sort data files
data_directory = os.getenv('DATA_DIRECTORY', 'data')
data_files = sorted(os.listdir(data_directory))  # Sort data files from oldest to newest

def simulate_network_factor():
    """Simulate network congestion that might affect trade execution with improved accuracy."""
    # Simulate network congestion with a weighted choice for more realistic outcomes
    # Weights: 0 (no congestion) - 70%, 1 (mild congestion) - 20%, 2 (severe congestion) - 10%
    network_conditions = [0, 1, 2]
    congestion_weights = [0.7, 0.2, 0.1]
    network_status = random.choices(network_conditions, weights=congestion_weights, k=1)[0]
    
    # Handling the network status with improved logic
    if network_status == 2:
        # Severe congestion, higher chance of trade execution failure
        return random.choice([False, True])  # 50% chance of failure
    elif network_status == 1:
        # Mild congestion, slight chance of trade execution delay but proceeds
        return True  # Proceed with a slight delay
    else:
        # No congestion, trade execution proceeds normally
        return True

def simulate_real_network_usage(wallet_id, coin_id):
    """Simulate real network usage including gas fee estimation, coin approval, and slippage."""
    stats = wallet_trading_stats[wallet_id]
    gas_fee = estimate_gas_fee()
    stats['gas_fee_spent'] += gas_fee
    if not check_coin_approval(coin_id):
        stats['failed_approvals'] += 1
        return False  # Coin approval failed
    slippage_loss = calculate_slippage(coin_id)
    stats['slippage_losses'] += slippage_loss
    return True  # Coin approved and slippage calculated

def update_token_state(coin_id, price_info):
    """Update token state with current data."""
    global token_state
    token_state[coin_id] = price_info

def process_trade_actions(wallet_id, file_index, current_prices, previous_prices):
    """Process trade actions based on current and previous prices."""
    stats = wallet_trading_stats[wallet_id]
    settings = wallet_settings[wallet_id]
    available_coins = load_json_file(available_coin_list)
    trade_datetime = datetime.datetime.fromtimestamp(int(data_files[file_index]) / 1000000).strftime('%Y-%m-%d %H:%M:%S.%f')
    for coin_id, price_info in current_prices.items():
        dex_price = float(price_info[-1]) if len(price_info) > 2 and price_info[-1] != "N/A" and float(price_info[-1]) != 0 else 0
        if coin_id in stats['current_holdings']:
            holding_info = stats['current_holdings'][coin_id]
            if float(holding_info[0]) != 0:
                sell_ratio = dex_price / float(holding_info[0])
                simulated_sell_price = dex_price
                coin_name = available_coins[coin_id]['symbol']
                tokens_sold = holding_info[2] 
                network_ok = simulate_network_factor()  # Check if network congestion affects trade execution
                if not network_ok:
                    stats['execution_failures'] += 1
                    if DEBUG_MODE:
                        print(colored(f"Execution failed for {coin_id} due to network congestion at {trade_datetime}", "red"))
                    break  # Skip this trade due to network issues
                money_received = simulated_sell_price * tokens_sold * ((100 - settings['SLIPPAGE']) / 100) - settings['FEE']
                profit_or_loss = float(money_received) - float(holding_info[3])
                initial_value = float(holding_info[3])
                percentage_change = (money_received - initial_value) / initial_value * 100
                if sell_ratio >= settings['SELL_TARGET']:
                    stats['wins'] += profit_or_loss
                    stats['total_money_gained'] += money_received
                    if DEBUG_MODE:
                        print(colored(f"{wallet_id} : SELLING TOKENS {coin_name} at {trade_datetime}: \nCurrent Price - {holding_info[0]} \nDEX Price - {dex_price} \nMoney Received - {money_received} \nTokens Sold - {tokens_sold} \nPercentage Change - {percentage_change:.2f}% \nPrice Ratio - {sell_ratio:.2f} \nToken Volume - {float(price_info[1])}", "green"))
                    record_trade(wallet_id, True, file_index, coin_id, price_info, tokens_sold, money_received, percentage_change)
                    update_token_state(coin_id, price_info)
                elif sell_ratio <= settings['STOP_LOSS_TARGET']:
                    stats['losses'] += -profit_or_loss
                    stats['total_money_lost'] += money_received
                    if DEBUG_MODE:
                        print(colored(f"{wallet_id} : STOPLOSS TOKENS {coin_name} at {trade_datetime}: \nCurrent Price - {holding_info[0]} \nDEX Price - {dex_price} \nMoney Received - {money_received} \nTokens Sold - {tokens_sold} \nPercentage Change - {percentage_change:.2f}% \nPrice Ratio - {sell_ratio:.2f} \nToken Volume - {float(price_info[1])}", "red"))
                    record_trade(wallet_id, False, file_index, coin_id, price_info, tokens_sold, money_received, percentage_change)
                    update_token_state(coin_id, price_info)
        else:
            if should_buy(wallet_id, coin_id, price_info, previous_prices):
                simulated_buy_price = dex_price
                network_ok = simulate_network_factor()  # Check if network congestion affects trade execution
                if not network_ok:
                    stats['execution_failures'] += 1
                    if DEBUG_MODE:
                        print(colored(f"Execution failed for {coin_id} due to network congestion at {trade_datetime}", "red"))
                    break  # Skip this trade due to network issues
                try:
                    money_spent = max(min(float(settings['MAXIMUM_BUY']), float(price_info[1]) / simulated_buy_price), float(settings['MINIMUM_BUY']))
                    tokens_to_buy = (money_spent - settings['FEE']) / simulated_buy_price * ((100 - settings['SLIPPAGE']) / 100)
                except ZeroDivisionError:
                    tokens_to_buy = 0
                    money_spent = 0
                    break
                if DEBUG_MODE:
                    print(colored(f"{wallet_id} : BUYING TOKENS {available_coins[coin_id]['symbol']} at {trade_datetime}: \nCurrent Price - {format(float(price_info[0]), '.8f')} \nDEX Price - {format(float(simulated_buy_price), '.8f')} \nMoney Spent - {format(float(money_spent), '.2f')} \nTokens Bought - {format(float(tokens_to_buy), '.2f')}", "blue"))
                buy_coin(wallet_id, coin_id, file_index, price_info, tokens_to_buy, money_spent)
                stats['money_spent'] += money_spent
                update_token_state(coin_id, price_info)

def record_trade(wallet_id, is_win, file_index, coin_id, price_info, tokens, money, percentage_change):
    """Record a trade as win or loss, including tokens traded and money involved."""
    stats = wallet_trading_stats[wallet_id]
    trade_duration = int(data_files[file_index]) - stats['current_holdings'][coin_id][1]
    trade_info = (trade_duration, coin_mapping[coin_id], stats['current_holdings'][coin_id][1], stats['current_holdings'][coin_id][0], int(data_files[file_index]), price_info[-1], tokens, money, percentage_change)
    if is_win:
        stats['winning_trades'].append(trade_info)
    else:
        stats['losing_trades'].append(trade_info)
    stats['trade_count'] += 1
    stats['average_holding_duration'] += trade_duration / 1000000  # Corrected to average correctly
    stats['total_holding_value'] -= float(stats['current_holdings'][coin_id][2]) * float(stats['current_holdings'][coin_id][0])  # Subtract the value of the sold holding
    stats['current_holdings'].pop(coin_id)
    stats['total_trades_executed'] += 1
    stats['total_holding_trades'] -= 1

def should_buy(wallet_id, coin_id, price_info, previous_prices):
    """Check if the conditions meet to buy a coin."""
    settings = wallet_settings[wallet_id]
    if coin_id not in previous_prices:
        update_token_state(coin_id, price_info)
        return False
    
    current_price = float(price_info[-1]) if len(price_info) > 2 and price_info[-1] != 'N/A' and float(price_info[-1]) != 0 else 0
    previous_price = float(previous_prices[coin_id][-1]) if len(previous_prices[coin_id]) > 2 and previous_prices[coin_id][-1] != 'N/A' and float(previous_prices[coin_id][-1]) != 0 else 0
    
    if current_price == 0 or previous_price == 0:
        return False
    
    return coin_id in coin_mapping and previous_price != 0 and current_price / previous_price <= settings['BUY_TARGET'] and float(price_info[1]) > float(settings['MINIMUM_VOLUME'])

def buy_coin(wallet_id, coin_id, file_index, price_info, tokens_to_buy, money_spent):
    """Buy a coin and update current holdings, including tokens bought and money spent."""
    stats = wallet_trading_stats[wallet_id]
    stats['current_holdings'][coin_id] = (price_info[-1], int(data_files[file_index]), tokens_to_buy, money_spent)
    stats['total_holding_value'] += money_spent  # Add the value of the new holding
    stats['total_holding_trades'] += 1  # Increment the total holding trades count when a new coin is bought

# Process each file for trade actions for each wallet in parallel
@logger.catch
def load_prices(file_index, data_files, trade_mode, timeframe):
    global token_state

    def read_json_file(file_path):
        with open(file_path) as f:
            try:
                return json.load(f)["0"]
            except json.JSONDecodeError:
                f.seek(0)
                return json.loads(f.readline())["0"]

    current_prices = read_json_file(os.path.join(data_directory, data_files[file_index]))

    if trade_mode == "Event":
        if token_state:
            previous_prices = token_state
        else:
            previous_prices = read_json_file(os.path.join(data_directory, data_files[file_index]))
            token_state = previous_prices
    elif trade_mode == "TimeFrame":
        target_file_index = max(0, file_index - timeframe)  # Ensure non-negative index
        previous_prices = read_json_file(os.path.join(data_directory, data_files[target_file_index]))

    return current_prices, previous_prices

def process_wallet_trades(wallet_id, file_index, data_files):
    settings = wallet_settings[wallet_id]
    trade_mode = settings.get("TRADE_MODE", "Event")
    timeframe = int(settings.get("TIMEFRAME", 0))
    current_prices, previous_prices = load_prices(file_index, data_files, trade_mode, timeframe)
    process_trade_actions(wallet_id, file_index, current_prices, previous_prices)

# Display trade results for each wallet
def display_trade_results():
    for wallet_id, stats in wallet_trading_stats.items():
        if wallet_settings[wallet_id].get('SIMULATION', 'False') == "True":
            stats['total_trades_executed'] += stats['total_holding_trades']
            print(colored(f"=============================== {wallet_id.upper()} STATS =====================================", "white"))
            stats['total_profit'] += stats['wins'] - stats['losses']
            profit_percentage = (stats['total_profit'] / stats['money_spent']) * 100 if stats['money_spent'] != 0 else 0
            total_current_money = stats['money_spent'] + stats['total_profit'] - stats['total_holding_value']
            print(colored(f"Wallet: {wallet_id}, Profit gained: ${stats['total_profit']:.2f} ({profit_percentage:.2f}%)", "magenta"))
            print(colored(f"Wallet: {wallet_id}, Money spent: ${stats['money_spent']:.2f}", "yellow"))
            print(colored(f"Wallet: {wallet_id}, Total money gained: ${stats['total_money_gained']:.2f}", "green"))
            print(colored(f"Wallet: {wallet_id}, Total money lost: ${stats['total_money_lost']:.2f}", "red"))
            print(colored(f"Wallet: {wallet_id}, Total holding value: ${stats['total_holding_value']:.2f}", "blue"))
            print(colored(f"Wallet: {wallet_id}, Total current money (excluding holdings): ${total_current_money:.2f}", "blue"))
            print(colored(f"Wallet: {wallet_id}, Execution Failures due to Network: {stats['execution_failures']}", "red"))
            print(colored(f"Wallet: {wallet_id}, Gas Fee Spent: ${stats['gas_fee_spent']:.2f}", "yellow"))  # Display gas fees spent
            print(colored(f"Wallet: {wallet_id}, Failed Approvals: {stats['failed_approvals']}", "red"))  # Display failed approvals
            print(colored(f"Wallet: {wallet_id}, Slippage Losses: ${stats['slippage_losses']:.2f}", "red"))  # Display slippage losses
            if stats['trade_count'] != 0:
                average_time = stats['average_holding_duration'] / stats['trade_count']
            else:
                average_time = 0
            winning_percentage = (len(stats['winning_trades']) / stats['total_trades_executed'] * 100) if stats['total_trades_executed'] > 0 else 0
            losing_percentage = (len(stats['losing_trades']) / stats['total_trades_executed'] * 100) if stats['total_trades_executed'] > 0 else 0
            total_holding_trade_percentage = (stats['total_holding_trades'] / stats['total_trades_executed'] * 100) if stats['total_trades_executed'] > 0 else 0
            days, remainder = divmod(average_time, 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes, seconds = divmod(remainder, 60)
            print(colored(f"Wallet: {wallet_id}, Average Holding Time: {days} days, {hours} hours, {minutes} minutes, {seconds:.2f} seconds", "blue"))
            print(colored(f"Wallet: {wallet_id}, Number of trades: {stats['total_trades_executed']}", "yellow"))
            print(colored(f"Wallet: {wallet_id}, Total Holding Trades: {stats['total_holding_trades']}", "cyan"))
            print(colored(f"Wallet: {wallet_id}, Total Winning Trades: {len(stats['winning_trades'])}", "green"))
            print(colored(f"Wallet: {wallet_id}, Total Losing Trades: {len(stats['losing_trades'])}", "red"))
            print(colored(f"Wallet: {wallet_id}, Holding Percentage: {total_holding_trade_percentage:.2f}%", "cyan"))
            print(colored(f"Wallet: {wallet_id}, Winning Percentage: {winning_percentage:.2f}%", "green"))
            print(colored(f"Wallet: {wallet_id}, Losing Percentage: {losing_percentage:.2f}%", "red"))
            print(colored(f"=============================== {wallet_id.upper()} END =====================================", "white"))
            print("\n")

def normal_operation():
    print(colored("Total data files: {}".format(len(data_files)), "yellow"))
    print(colored("Choose a period to analyze:", "white"))
    print(colored("1. Yesterday", "white"))
    print(colored("2. Today", "white"))
    print(colored("3. Last Week", "white"))
    print(colored("4. 7 Days", "white"))
    print(colored("5. 1 Month", "white"))
    print(colored("6. All", "white"))
    print(colored("7. Custom", "white"))
    choice = input("Enter the number of the period you want to analyze: ")

    period_mapping = {
        "1": "Yesterday",
        "2": "Today",
        "3": "Last Week",
        "4": "7 Days",
        "5": "1 Month",
        "6": "All",
        "7": "Custom"
    }

    period_string = period_mapping.get(choice, "Invalid Choice")
    print(colored("=============================== ANALYSIS START =====================================", "white"))
    analyze_trades_by_period(period_string)
    display_trade_results()
    print(colored("=============================== ANALYSIS END =====================================", "white"))

def handle_custom_period():
    import datetime
    import pytz

    first_file_timestamp = int(data_files[0].split('/')[-1].split('.')[0])
    last_file_timestamp = int(data_files[-1].split('/')[-1].split('.')[0])
    try:
        first_file_date = datetime.datetime.fromtimestamp(first_file_timestamp / 1e6, tz=pytz.utc).strftime("%Y-%m-%d")
        last_file_date = datetime.datetime.fromtimestamp(last_file_timestamp / 1e6, tz=pytz.utc).strftime("%Y-%m-%d")
    except OSError as e:
        print(f"Error converting timestamp to date: {e}")
        first_file_date = "Unavailable"
        last_file_date = "Unavailable"
    print(f"Available date range is from {first_file_date} to {last_file_date}.")

    def find_file_index_by_date(target_date):
            for i, file_name in enumerate(data_files):
                file_timestamp = int(file_name.split('/')[-1].split('.')[0])  # Adjusted to handle file names with extensions
                file_date = datetime.datetime.fromtimestamp(file_timestamp, tz=pytz.utc)
                if file_date >= target_date:
                    return i
            return len(data_files)  # If no file is found, return the end index

    while True:
        start_date_str = input("Enter start date (YYYY-MM-DD): ")
        end_date_str = input("Enter end date (YYYY-MM-DD): ")
        start_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").replace(tzinfo=pytz.utc)
        end_date = datetime.datetime.strptime(end_date_str, "%Y-%m-%d").replace(tzinfo=pytz.utc)

        start_index = find_file_index_by_date(start_date)
        end_index = find_file_index_by_date(end_date)

        if start_index == len(data_files) or end_index == len(data_files):
            print(f"No data found for the selected date range. Available date range is from {first_file_date} to {last_file_date}. Please choose again.")
        else:
            break
    return start_index, end_index


def analyze_trades_by_period(period):
    start_index = 0
    end_index = len(data_files)
    
    if period == "Yesterday":
        start_index = len(data_files) - 1440  # 24 hours * 60 minutes
        end_index = len(data_files) - 1
    elif period == "Today":
        start_index = len(data_files) - 1
    elif period == "Last Week":
        start_index = len(data_files) - 10080  # 7 days * 24 hours * 60 minutes
    elif period == "7 Days":
        start_index = len(data_files) - 10080  # 7 days * 24 hours * 60 minutes
    elif period == "1 Month":
        start_index = len(data_files) - 43200  # 30 days * 24 hours * 60 minutes
    elif period == "All":
        start_index = 0
    elif period == "Custom":
        start_index, end_index = handle_custom_period()

    if DEBUG_MODE:
        process_trades(start_index, end_index)
    else:
        process_trades_with_progress(start_index, end_index)

def process_trades(start_index, end_index):
    for file_index in range(start_index, end_index):
        for wallet_id, settings in wallet_settings.items():
            if settings.get('SIMULATION', False):
                process_wallet_trades(wallet_id, file_index, data_files)

def process_trades_with_progress(start_index, end_index):
    for file_index in tqdm(range(start_index, end_index), desc="Analyzing Trades", bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]"):
        for wallet_id, settings in wallet_settings.items():
            if settings.get('SIMULATION', False):
                process_wallet_trades(wallet_id, file_index, data_files)

def optimize_settings():
    best_profit = -float('inf')
    best_settings = None

    # Define ranges for each parameter
    sell_target_range = np.arange(1.05, 1.21, 0.05)
    buy_target_range = np.arange(0.6, 1.01, 0.05)
    stop_loss_target_range = np.arange(0.8, 0.96, 0.05)
    minimum_volume_range = np.arange(500, 1000000, 500)

    total_combinations = len(sell_target_range) * len(buy_target_range) * len(stop_loss_target_range) * len(minimum_volume_range)
    current_combination = 0

    # Iterate over all combinations of settings
    for sell_target in sell_target_range:
        for buy_target in buy_target_range:
            for stop_loss_target in stop_loss_target_range:
                for minimum_volume in minimum_volume_range:
                    current_combination += 1
                    print(f"Testing combination {current_combination}/{total_combinations}: "
                          f"SELL_TARGET={sell_target}, BUY_TARGET={buy_target}, "
                          f"STOP_LOSS_TARGET={stop_loss_target}, MINIMUM_VOLUME={minimum_volume}")

                    # Apply settings to all wallets
                    for wallet_id in wallet_settings:
                        wallet_settings[wallet_id]['SELL_TARGET'] = sell_target
                        wallet_settings[wallet_id]['BUY_TARGET'] = buy_target
                        wallet_settings[wallet_id]['STOP_LOSS_TARGET'] = stop_loss_target
                        wallet_settings[wallet_id]['MINIMUM_VOLUME'] = minimum_volume

                    # Analyze trades with current settings
                    analyze_trades_by_period("All")
                    current_profit = sum(stats['total_profit'] for stats in wallet_trading_stats.values())

                    # Check if the current settings yield a better profit
                    if current_profit > best_profit:
                        best_profit = current_profit
                        best_settings = {
                            wallet_id: {
                                'SELL_TARGET': wallet_settings[wallet_id]['SELL_TARGET'],
                                'BUY_TARGET': wallet_settings[wallet_id]['BUY_TARGET'],
                                'STOP_LOSS_TARGET': wallet_settings[wallet_id]['STOP_LOSS_TARGET'],
                                'MINIMUM_VOLUME': wallet_settings[wallet_id]['MINIMUM_VOLUME']
                            } for wallet_id in wallet_settings
                        }

                    print(f"Current profit: {current_profit}, Best profit: {best_profit}")

    # Save the best settings to a file
    with open('optimized_settings.json', 'w') as file:
        json.dump(best_settings, file)
    print(f"Optimized settings saved with a profit of {best_profit}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--auto', action='store_true', help='Run analysis on all historical data automatically')
    args = parser.parse_args()

    if args.auto:
        optimize_settings()
    else:
        normal_operation()


