import json
import os
import time, sys, csv
from dotenv import load_dotenv
from library.transaction_builder import get_token_address, send_tele_message, trade_token as execute_trade
from loguru import logger
import asyncio
from datetime import datetime
import shutil
from prettytable import PrettyTable

# Get the base directory (one level up from the current directory)
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

# Load environment variables
load_dotenv()

# Load vars from ENV
error_conditions = set(os.getenv('SKIP_ERROR_CONDITIONS', 'insufficient input amount,transfer_from_failed').replace(" ", "").lower().split(','))
debug_mode = os.getenv('DEBUG_MODE') == 'True'

# Load trade settings for multiple wallets
def load_trade_settings():
    with open(os.getenv('WALLET_SETTINGS'), 'r') as file:
        return json.load(file)

trade_settings = load_trade_settings()

# NOTIFICATION ENV SETTINGS LOAD 
notification_targets = os.getenv('WHATSAPP_TARGETS').split(',')
twilio_account_sid = os.getenv('TWILIO_ACCOUNT_SID')
twilio_auth_token = os.getenv('TWILIO_AUTH_TOKEN')
desired_coin_list = os.getenv('DESIRED_COIN_FILE')
available_coin_list = os.getenv('AVAILABLE_COIN_FILE')
shit_coin_list = os.getenv('SHIT_COIN_FILE')
token_state = os.getenv('TOKEN_STATE_FILE')

available_coins = None


# Initialize CSV file for logging trade actions
csv_folder = os.getenv('CSV_FOLDER')
os.makedirs(csv_folder, exist_ok=True)
csv_file_name = f"trade_actions_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
csv_file = open(os.path.join(csv_folder, csv_file_name), 'w', newline='')
csv_writer = csv.writer(csv_file)
# Initialize a CSV file for always updated log
csv_latest_file_name = "trade_actions_log_latest.csv"
csv_latest_file = open(os.path.join(csv_folder, csv_latest_file_name), 'w', newline='')
csv_latest_writer = csv.writer(csv_latest_file)

def load_json_file(file_path):
    with open(file_path, 'r') as file:
        return json.load(file)

def filter_market_data(binance_coins):
    coin_lists = load_json_file(available_coin_list)
    shit_coin_lists = set(load_json_file(shit_coin_list))
    filtered_coins = {coin_id: coin_info['symbol'].lower() for coin_id, coin_info in coin_lists.items() if coin_info['symbol'].lower() in binance_coins and coin_id not in shit_coin_lists}
    return filtered_coins

def save_token_state(data, wallet_name):
    wallet_specific_token_state = token_state.replace('token_state.json', f'token_state_{wallet_name}.json')
    with open(wallet_specific_token_state, 'w') as file:
        json.dump({"0": data}, file, indent=4)

def load_token_state(wallet_name):
    wallet_specific_token_state = token_state.replace('token_state.json', f'token_state_{wallet_name}.json')
    if not os.path.exists(wallet_specific_token_state):
        shutil.copy(token_state, wallet_specific_token_state)
    with open(wallet_specific_token_state, 'r') as file:
        data = json.load(file)
        return data["0"]

def modify_market_file_data(market_file, coin_id, real_price):
    with open(market_file, 'r+') as file:
        data = json.load(file)
        if "0" in data and coin_id in data["0"]:
            if len(data["0"][coin_id]) > 2:
                data["0"][coin_id][-1] = real_price
            else:
                data["0"][coin_id].append(real_price)
            file.seek(0)
            json.dump(data, file, indent=4)
            file.truncate()
        logger.info(f"Updated market file {market_file} with real price for {coin_id}")

def get_symbol_from_id(coin_id, filtered_coins=None):
    global available_coins
    if filtered_coins is not None:
        symbol = filtered_coins.get(coin_id, {})
        if symbol:
            return symbol

    if available_coins is None:
        available_coins = load_json_file(available_coin_list)
    # Directly access the symbol if coin_id is present in available_coins
    symbol = available_coins.get(coin_id, {}).get('symbol')
    if symbol:
        return symbol
    # Check if the coin_id matches any id in the available_coins
    return next((coin['symbol'] for coin in available_coins.values() if coin.get('id') == coin_id), 'N/A')

async def determine_token_amount(wallet_settings, token_price, buy_amount):
    slippage = float(wallet_settings['SLIPPAGE'])
    real_buy_amount = buy_amount * ((100 - slippage) / 100)
    return float(real_buy_amount/token_price)

async def determine_token_sell_amount(wallet_settings, token_price, token_holding_amount):
    slippage = float(wallet_settings['SLIPPAGE'])
    real_sell_amount = token_holding_amount * ((100 - slippage) / 100)
    return float(float(real_sell_amount)*float(token_price))

async def update_wallet_balance(wallet_settings, current_price):
    current_holding = wallet_settings.get('current_holdings', {})
    current_balance = 0
    for coin_id, holding_info in current_holding.items():
        holding_price = float(holding_info[0])
        holding_usd_amount = float(holding_info[2]) if len(holding_info) > 2 else 0
        holding_token_amount = float(holding_info[3]) if len(holding_info) > 3 else 0
        current_token_price = current_price.get(coin_id, [0, 0])[0]
        token_usd_amount = await determine_token_sell_amount(wallet_settings, current_token_price, holding_token_amount)
        current_balance += token_usd_amount
    wallet_settings['CURRENT_BALANCE'] = wallet_settings['AVAILABLE_BALANCE'] + current_balance
    return wallet_settings


@logger.catch
async def analyze_coin(coin_id, wallet_settings, wallet_id, latest_data, comparison_data, filtered_coins, token_state_data, wins_losses_lists, latest_file, tolerance, processed_coins, unprocessed_coins):
    wins, losses, win_list, loss_list, buy_list = wins_losses_lists
    coin_data = latest_data.get(coin_id, [0, 0])
    coin_volume = float(coin_data[1])
    current_price = float(coin_data[0])
    token_price = current_price if len(coin_data) == 2 else float(coin_data[2])
    coin_symbol = get_symbol_from_id(coin_id, filtered_coins)

    # Early exit for low volume, invalid price, or significant price discrepancy
    if (coin_volume < float(wallet_settings['MINIMUM_VOLUME']) or 
        token_price <= 0.0 or 
        coin_symbol == 'N/A' or 
        (current_price > 0 and (token_price / current_price > 10 or current_price / token_price > 10))):
        unprocessed_coins.add(coin_id)
        return
    
    trade_status = {"status": False, "message": "Failed to execute trade", "real_price": token_price}
    if coin_id in wallet_settings['current_holdings']:
        holding_info = wallet_settings['current_holdings'][coin_id]
        holding_price = float(holding_info[0])
        holding_usd_amount = float(holding_info[2]) if len(holding_info) > 2 else 0
        holding_token_amount = float(holding_info[3]) if len(holding_info) > 3 else 0
        price_ratio = token_price / holding_price if holding_price != 0 else 0
        sell_target_reached = round(price_ratio, len(str(wallet_settings['SELL_TARGET']).split('.')[1])) >= float(wallet_settings['SELL_TARGET'])
        stop_loss_target_reached = round(price_ratio, len(str(wallet_settings['STOP_LOSS_TARGET']).split('.')[1])) <= float(wallet_settings['STOP_LOSS_TARGET'])
        if debug_mode:
            logger.debug(f"[DEBUG] Comparing coin {coin_id} [DEBUG]\n\tCurrent price: {current_price:.18f}\n\tReal price: {token_price:.18f}\n\tHolding price: {holding_price:.18f}. \n\tPrice ratio: {price_ratio:.3f}. \n\tVolume: {coin_volume}. \n\tBuy: False \n\tSell: {sell_target_reached} \n\tStop Loss: {stop_loss_target_reached}")
        action = 'sell' if sell_target_reached else 'stop_loss' if stop_loss_target_reached else 'hold'
        token_usd_amount = await determine_token_sell_amount(wallet_settings, token_price, holding_token_amount)
        csv_writer.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), wallet_id, coin_symbol.upper(), coin_volume, f"{holding_price:.18f}", f"{current_price:.18f}", f"{token_price:.18f}", f"{price_ratio:.3f}", action, f"{token_usd_amount - holding_usd_amount:.2f}" if action != 'buy' and action != 'no_action' else "-"])
        csv_latest_writer.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), wallet_id, coin_symbol.upper(), coin_volume, f"{holding_price:.18f}", f"{current_price:.18f}", f"{token_price:.18f}", f"{price_ratio:.3f}", action, f"{token_usd_amount - holding_usd_amount:.2f}" if action != 'buy' and action != 'no_action' else "-"])
        processed_coins.add(coin_id)
        if sell_target_reached or stop_loss_target_reached:
            should_execute = False
            if wallet_settings.get('SIMULATION') == "True":
                should_execute = True
            elif action == 'sell' and current_price >= (token_price * (1 - tolerance)):
                should_execute = True
            elif action == 'stop_loss' and current_price <= (token_price * (1 + tolerance)):
                should_execute = True
            if should_execute:
                try:
                    if not wallet_settings.get('SIMULATION') == "True":
                        trade_status = await execute_trade(get_token_address(coin_symbol.upper()), wallet_settings, 0, False, float(wallet_settings['SLIPPAGE']), expected_price=current_price)
                    holding_duration = (int(latest_file) - int(holding_info[1])) // 1000000
                    trade_list = win_list if action == 'sell' else loss_list
                    if trade_status["status"] or wallet_settings.get('SIMULATION') == "True":
                        real_price = trade_status.get("real_price", 0)
                        token_price = real_price if real_price != 0 else token_price
                        token_usd_amount = await determine_token_sell_amount(wallet_settings, token_price, holding_token_amount)
                        trade_list.append((holding_duration, coin_symbol.upper(), int(holding_info[1]), "{:.18f}".format(holding_price), int(latest_file), "{:.18f}".format(token_price), "{:.18f}".format(token_usd_amount), holding_usd_amount))
                        token_state_data[coin_id] = [str(current_price), str(coin_volume), str(token_price)]  # Update specific token state on trade event
                        if action == 'sell':
                            wins += 1
                            wallet_settings['USED_BALANCE'] -= holding_usd_amount
                            wallet_settings['AVAILABLE_BALANCE'] += token_usd_amount
                        else:
                            losses += 1
                        wallet_settings['current_holdings'].pop(coin_id)
                        modify_market_file_data(f"{os.getenv('DATA_DIRECTORY')}/{latest_file}", coin_id, token_price)
                    if not trade_status["status"] and not wallet_settings.get('SIMULATION', "False") == "True":
                        if any(error_condition in trade_status['message'].replace(" ", "").lower() for error_condition in error_conditions):
                            logger.error(f"Error executing {action} for coin {coin_id}: {trade_status['message']}")
                            wallet_settings['current_holdings'].pop(coin_id)
                    if debug_mode:
                        logger.debug(f"[DEBUG] Action {action} executed for coin {coin_id}. \n\tWins: {wins}, Losses: {losses}.")
                except Exception as e:
                    logger.error(f"Error executing {action} for coin {coin_id}: {e}")
    else: 
        if float(wallet_settings.get("AVAILABLE_BALANCE")) < float(wallet_settings.get("MINIMUM_BUY")):
            unprocessed_coins.add(coin_id)
            return
        comparison_data_coin = comparison_data.get(coin_id, [0, 0])
        if comparison_data_coin == [0, 0]:
            token_state_data[coin_id] = [str(current_price), str(coin_volume), str(token_price)]  # Update token state data with new coin information
        elif coin_id in filtered_coins or any(coin_id == coin_data['id'] for coin_data in available_coins.values() if 'id' in coin_data):
            processed_coins.add(coin_id)
            comparison_price = float(comparison_data_coin[0])
            if current_price == 0 or comparison_price == 0:
                unprocessed_coins.add(coin_id)
                return
            price_ratio = token_price / comparison_price
            buy_target_reached = round(price_ratio, len(str(wallet_settings['BUY_TARGET']).split('.')[1])) <= float(wallet_settings['BUY_TARGET'])
            if debug_mode:
                logger.debug(f"[DEBUG] Comparing coin {coin_id} [DEBUG]\n\tCurrent price: {current_price:.18f}\n\tReal price: {token_price:.18f}\n\tComparison price: {comparison_price:.18f}. \n\tPrice ratio: {price_ratio:.3f}. \n\tVolume: {coin_volume}. \n\tBuy: {buy_target_reached} \n\tSell: False \n\tStop Loss: False")
            action = 'buy' if buy_target_reached else 'no_action'
            csv_writer.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), wallet_id, coin_symbol.upper(), coin_volume, f"{comparison_price:.18f}", f"{current_price:.18f}", f"{token_price:.18f}", f"{price_ratio:.3f}", action, "-"])
            csv_latest_writer.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), wallet_id, coin_symbol.upper(), coin_volume, f"{comparison_price:.18f}", f"{current_price:.18f}", f"{token_price:.18f}", f"{price_ratio:.3f}", action, "-"])
            if buy_target_reached and wallet_settings['AVAILABLE_BALANCE'] >= float(wallet_settings['MINIMUM_BUY']):
                if debug_mode:
                    logger.debug(f"[DEBUG] Buy target reached for coin {coin_id}. Try to buy...")
                try:
                    if wallet_settings.get('SIMULATION') == "True" or (token_price * (1 - tolerance)) > 0:
                        buy_amount = max(min(float(wallet_settings['MAXIMUM_BUY']), coin_volume / float(wallet_settings['MAXIMUM_BUY'])), float(wallet_settings['MINIMUM_BUY']))
                        if not wallet_settings.get('SIMULATION') == "True":
                            trade_status = await execute_trade(get_token_address(coin_symbol.upper()), wallet_settings, buy_amount, True, float(wallet_settings['SLIPPAGE']), expected_price=current_price)
                        if wallet_settings.get('SIMULATION') == "True" or trade_status["status"]:
                            real_price = trade_status.get("real_price", 0)
                            token_price = real_price if real_price != 0 else token_price
                            token_amount = await determine_token_amount(wallet_settings, token_price, buy_amount)
                            wallet_settings['current_holdings'][coin_id] = ("{:.18f}".format(token_price), int(latest_file), buy_amount, token_amount)
                            buy_list.append((coin_symbol.upper(), "{:.18f}".format(token_price), buy_amount, token_amount))
                            modify_market_file_data(f"{os.getenv('DATA_DIRECTORY')}/{latest_file}", coin_id, token_price)
                            token_state_data[coin_id] = [str(token_price), str(coin_volume), str(token_price)]  # Update token state data with current coin information
                            wallet_settings['AVAILABLE_BALANCE'] -= buy_amount
                            wallet_settings['USED_BALANCE'] += buy_amount
                        if debug_mode:
                            logger.debug(f"[DEBUG] Buy action prepared for coin {coin_id}. \n\tCurrent price: {current_price}, \n\tToken price: {token_price}, \n\tVolume considered for buy: {min(wallet_settings['MAXIMUM_BUY'], coin_volume / wallet_settings['MAXIMUM_BUY'])}.")
                except Exception as e:
                    logger.error(f"Error preparing buy for coin {coin_id}: {e}")

@logger.catch
async def analyze_market_conditions(wallet_settings, wallet_id, filtered_coins, data_folder):
    tolerance = float(wallet_settings.get('PRICE_DIFF_TOLERANCE', '0'))
    market_data_files = sorted(os.listdir(data_folder))
    if float(wallet_settings.get("AVAILABLE_BALANCE")) < float(wallet_settings.get("MINIMUM_BUY")):
        logger.warning(f"No available balance in wallet {wallet_id}.\n Buy actions will not happens, please add more funds to your wallet.")
    if len(market_data_files) < 10:
        logger.warning(f"Not enough market data files for analysis in wallet {wallet_id}.")
        return 0, 0, [], [], [], wallet_settings
    
    trade_mode = wallet_settings.get('TRADE_MODE', 'TimeFrame')
    comparison_file_index = -int(wallet_settings.get('TIMEFRAME', 1))
    comparison_file = f"{data_folder}/{market_data_files[comparison_file_index]}" if trade_mode == 'TimeFrame' else token_state
    latest_file = market_data_files[-1]
    latest_data = load_json_file(f"{data_folder}/{latest_file}")["0"]
    comparison_data = load_json_file(comparison_file)["0"] if comparison_file != token_state else load_token_state(wallet_id)
    wins, losses, win_list, loss_list, buy_list = 0, 0, [], [], []
    token_state_data = comparison_data
    coin_ids = set(latest_data.keys()) | set(wallet_settings['current_holdings'].keys())

    processed_coins = set()
    unprocessed_coins = set()
    wins_losses_lists = [wins, losses, win_list, loss_list, buy_list]
    
    logger.info(f"Analyzing {len(coin_ids)} coins based on recent and comparable data.")
    wallet_settings = await update_wallet_balance(wallet_settings, latest_data)
    tasks = [analyze_coin(coin_id, wallet_settings, wallet_id, latest_data, comparison_data, filtered_coins, token_state_data, wins_losses_lists, latest_file, tolerance, processed_coins, unprocessed_coins) for coin_id in coin_ids]
    await asyncio.gather(*tasks)

    wins, losses, win_list, loss_list, buy_list = wins_losses_lists
    # Update the token state data file with the latest analysis results
    save_token_state(token_state_data, wallet_id)
    logger.info(f"Analysis complete on wallet {wallet_id}. Processed Coins: {len(processed_coins)}, Unprocessed Coins: {len(unprocessed_coins)}")
    
    return wins, losses, win_list, loss_list, buy_list, wallet_settings

@logger.catch
async def notify_trades(win_list, loss_list, buy_list, notification_targets, twilio_account_sid, twilio_auth_token, wallet_id):
    tasks = []
    delay_between_messages = 60  # Delay in seconds, adjust as needed based on rate limit specifics

    async def schedule_message(trade, action):
        try:
            price_change_percentage = 0
            if action != "Buy":
                profit_gained = float(trade[6]) - float(trade[7])
                price_change_percentage = ((float(trade[6]) / float(trade[7]) - 1.0) * 100) if float(trade[7]) != 0 else 0
            if action == "Buy":
                message_content = f"🚀 <b>BUY ALERT</b> 🚀\n<b>Coin:</b> {trade[0].upper()} on <b>Wallet:</b> {wallet_id}\n<b>Price:</b> {format(float(trade[1]), '.18f')} USD\n<b>Amount:</b> ${format(trade[2], '.2f')}\n<b>Expected Tokens:</b> {format(trade[3], '.5f')} {trade[0].upper()}"
            else:
                change_direction = 'increase' if profit_gained >= 0 else 'decrease'
                message_content = f"🔔 <b>{action.upper()} ALERT</b> 🔔\n<b>Coin:</b> {trade[1].upper()} on <b>Wallet:</b> {wallet_id}\n<b>Price:</b> {format(float(trade[5]), '.18f')} USD\n<b>Change:</b> {change_direction} of {format(price_change_percentage, '.2f')}%\n<b>USD Received:</b> {format(float(trade[6]), '.5f')} USD\n<b>Profit:</b> ${format(profit_gained, '.5f')}"
                days, remainder = divmod(trade[0], 86400)
                hours, remainder = divmod(remainder, 3600)
                minutes, seconds = divmod(remainder, 60)
                message_content += f"\n<b>Holding Duration:</b> {days} days, {hours} hours, {minutes} minutes, and {seconds} seconds"
            await asyncio.sleep(delay_between_messages)  # Delay to prevent rate limit issues
            await send_tele_message(message_content, True)
        except Exception as e:
            logger.error(f"Error in wallet {wallet_id}: {e}")

    tasks.extend([asyncio.create_task(schedule_message(trade, action)) for action, trade_list in [("Sell", win_list), ("Stop Loss", loss_list), ("Buy", buy_list)] for trade in trade_list])

    # Await all scheduled tasks to complete
    await asyncio.gather(*tasks)

@logger.catch
async def process_wallet(wallet_id, wallet_settings):
    global available_coins
    try:
        # Load desired and available coins from configuration files
        desired_coins = load_json_file(desired_coin_list)
        available_coins = load_json_file(available_coin_list)
        
        # Extract symbols and normalize to lowercase
        desired_coin_symbols = {coin.lower() for coin in desired_coins if coin}
        available_coin_symbols = {coin['symbol'].lower() for coin in available_coins.values() if 'symbol' in coin and coin['symbol'] and 'id' in coin}
        
        # Combine symbols from both sets to form a comprehensive list
        binance_coins = list(desired_coin_symbols | available_coin_symbols)
        
        # Filter out unwanted coins based on market data
        filtered_coins = filter_market_data(binance_coins)
        
        # Log the number of coins processed
        logger.info(f"Notifier, Market Coin Data for {wallet_id}: {len(filtered_coins)} coins")
        
        # Analyze market conditions and update wallet settings
        wins, losses, win_list, loss_list, buy_list, wallet_settings = await analyze_market_conditions(wallet_settings, wallet_id, filtered_coins, os.getenv('DATA_DIRECTORY'))
        
        # Persist updated wallet settings to file
        with open(os.getenv('WALLET_SETTINGS'), "r+") as f:
            data = json.load(f)
            data[wallet_id] = wallet_settings
            f.seek(0)
            json.dump(data, f, indent=4)
            f.truncate()
        
        # Notify trades asynchronously to improve performance
        await notify_trades(win_list, loss_list, buy_list, notification_targets, twilio_account_sid, twilio_auth_token, wallet_id)
    except Exception as e:
        logger.error(f"Error processing wallet {wallet_id}: {e}")


if __name__ == "__main__":
    if not trade_settings:
        logger.error("No trade settings found. Please check your WALLET_SETTINGS configuration.")
        sys.exit(1)
    else:
        try:
            csv_writer.writerow(['Time', 'Wallet', 'Symbol', 'Volume', 'Comparison Price', 'Current Price', 'Real Price', 'Price Ratio', 'Action', 'Profits/Losses'])
            csv_latest_writer.writerow(['Time', 'Wallet', 'Symbol', 'Volume', 'Comparison Price', 'Current Price', 'Real Price', 'Price Ratio', 'Action', 'Profits/Losses'])
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            tasks = [process_wallet(wallet_id, wallet_settings) for wallet_id, wallet_settings in trade_settings.items() if wallet_settings.get('enabled') == "True"]
            loop.run_until_complete(asyncio.gather(*tasks))
            # Close the CSV files after all tasks are completed
            csv_file.close()
            csv_latest_file.close()
            # Summarize the round in a table
            with open(os.path.join(csv_folder, csv_file_name), 'r') as file:
                reader = csv.DictReader(file)
                wallet_summary = {}
                for row in reader:
                    wallet_id = row['Wallet']
                    if wallet_id not in wallet_summary:
                        wallet_summary[wallet_id] = {'Processed Coins': 0, 'Buy Count': 0, 'Sell Count': 0, 'Hold Count': 0, 'Sell PNL': 0, 'Hold PNL': 0, 'Total PNL': 0}
                    
                    if row['Action'] != 'no_action':
                        wallet_summary[wallet_id]['Processed Coins'] += 1
                    if row['Action'] == 'buy':
                        wallet_summary[wallet_id]['Buy Count'] += 1
                    elif row['Action'] == 'sell' or row['Action'] == 'stop_loss':
                        wallet_summary[wallet_id]['Sell Count'] += 1
                    elif row['Action'] == 'hold':
                        wallet_summary[wallet_id]['Hold Count'] += 1
                    
                    if row['Profits/Losses'] != "-":
                        pnl = float(row['Profits/Losses'])
                        if row['Action'] == 'sell':
                            wallet_summary[wallet_id]['Sell PNL'] += pnl
                        elif row['Action'] == 'hold':
                            wallet_summary[wallet_id]['Hold PNL'] += pnl
                        wallet_summary[wallet_id]['Total PNL'] += pnl

                # Creating a beautiful table for the summary for each wallet
                table = PrettyTable()
                wallet_ids = list(wallet_summary.keys())
                table.field_names = ["Metric"] + [f"{wallet_id.upper()}" for wallet_id in wallet_ids]
                
                processed_coins = ["Processed Coins"] + [summary['Processed Coins'] for summary in wallet_summary.values()]
                buy_counts = ["Buy Count"] + [summary['Buy Count'] for summary in wallet_summary.values()]
                sell_counts = ["Sell Count"] + [summary['Sell Count'] for summary in wallet_summary.values()]
                hold_counts = ["Hold Count"] + [summary['Hold Count'] for summary in wallet_summary.values()]
                sell_pnls = ["Sell PNL"] + [f"{summary['Sell PNL']:.2f} USD" for summary in wallet_summary.values()]
                hold_pnls = ["Hold PNL"] + [f"{summary['Hold PNL']:.2f} USD" for summary in wallet_summary.values()]
                total_pnls = ["Total PNL"] + [f"{summary['Total PNL']:.2f} USD" for summary in wallet_summary.values()]
                
                table.add_row(processed_coins)
                table.add_row(buy_counts)
                table.add_row(sell_counts)
                table.add_row(hold_counts)
                table.add_row(sell_pnls)
                table.add_row(hold_pnls)
                table.add_row(total_pnls)
                
                print("Round Summary for All Wallets:")
                print(table)
        except Exception as e:
            logger.error(f"Unexpected error encountered: {e}")
            sys.exit(1)

