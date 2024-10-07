import os
import time
import json
from datetime import datetime
from dotenv import load_dotenv
from datetime import timedelta
import subprocess
import sched
import signal
import pandas as pd
from prettytable import PrettyTable
import requests

load_dotenv()
cnt = 0
last_run_day = "0"
scheduler = sched.scheduler(time.time, time.sleep)

def signal_handler(signum, frame):
    print("Program stopped due to CTRL+C")
    combine_and_clean_data()
    exit(0)

signal.signal(signal.SIGINT, signal_handler)

def send_telegram_message(message):
    telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    send_url = f"https://api.telegram.org/bot{telegram_token}/sendMessage?chat_id={chat_id}&parse_mode=Markdown&text={message}"
    requests.get(send_url)

def combine_and_clean_data():
    csv_data_folder = os.getenv('CSV_FOLDER', 'csv_data')
    all_csv_files = os.listdir(csv_data_folder)
    date_pattern = "trade_actions_log_"
    today_date_str = datetime.now().strftime("%Y%m%d")
    yesterday_date_str = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    
    # Extract unique dates from file names
    unique_dates = {f.split('_')[3] for f in all_csv_files if f.startswith(date_pattern) and len(f.split('_')) > 2 and f.endswith('.csv') and 'combined' not in f}
    for date_str in unique_dates:
        if not date_str.isdigit():
            print(f"Skipping non-numeric date string: {date_str}")
            continue
        if date_str == today_date_str:
            print(f"Skipping today's date: {date_str} to avoid redundancy")
            continue
        print(f"Combining and cleaning data for {date_str}")
        
        # Combine CSV files for each unique date
        csv_files = [f for f in all_csv_files if f.startswith(f"{date_pattern}{date_str}") and f.endswith('.csv')]
        if not csv_files:
            print(f"No CSV files found for {date_str}.")
            continue
        
        # Attempt to combine CSV files, handle case where no data is available to concatenate
        try:
            data_frames = [pd.read_csv(os.path.join(csv_data_folder, f)) for f in csv_files]
            if not data_frames:
                print(f"No data found in CSV files for {date_str}.")
                continue
            
            # Filter out records where action is 'no_action'
            filtered_data_frames = [df[df['Action'] != 'no_action'] for df in data_frames]
            
            combined_df = pd.concat(filtered_data_frames)
            combined_file_path = os.path.join(csv_data_folder, f"{date_pattern}{date_str}_combined.csv")
            combined_df.to_csv(combined_file_path, index=False)
            
            # Delete the individual files
            for f in csv_files:
                if 'combined' not in f:
                    os.remove(os.path.join(csv_data_folder, f))
            
            print(f"Combined data into {combined_file_path} and cleaned up individual files.")
            
            # Send summary to Telegram if the date is yesterday
            if date_str == yesterday_date_str:
                # Create a summary table with wallet differentiation
                summary_table = PrettyTable()
                wallet_ids = [wallet_id for wallet_id in combined_df['Wallet'].unique() if pd.notna(wallet_id)]
                if not wallet_ids:
                    wallet_ids = ['All Wallets']  # Default to 'All Wallets' if no specific wallet is detected

                summary_table.field_names = ["Metric"] + [f"{str(wallet_id).capitalize()}" for wallet_id in wallet_ids]
                
                # Count of transactions per wallet
                transactions_count_per_wallet = [len(combined_df[combined_df['Wallet'] == wallet_id]) for wallet_id in wallet_ids] if wallet_ids != ['All Wallets'] else [len(combined_df)]
                
                # Calculate Total PNL per wallet excluding rows with '-' as Profits/Losses
                total_pnl_per_wallet = []
                for wallet_id in wallet_ids:
                    if wallet_id == 'All Wallets':
                        wallet_df = combined_df[combined_df['Profits/Losses'] != '-']
                    else:
                        wallet_df = combined_df[(combined_df['Wallet'] == wallet_id) & (combined_df['Profits/Losses'] != '-')]
                    wallet_df['Profits/Losses'] = wallet_df['Profits/Losses'].replace('-', '0').astype(float)
                    total_pnl = wallet_df['Profits/Losses'].sum()
                    total_pnl_per_wallet.append(total_pnl)
                
                # Additional details for more insight per wallet
                action_types = ['buy', 'sell', 'hold']
                action_counts = {action: [] for action in action_types}
                action_pnls = {action: [] for action in action_types}
                
                for wallet_id in wallet_ids:
                    for action in action_types:
                        if wallet_id == 'All Wallets':
                            action_df = combined_df[(combined_df['Action'] == action) & (combined_df['Profits/Losses'] != '-')]
                        else:
                            action_df = combined_df[(combined_df['Wallet'] == wallet_id) & (combined_df['Action'] == action) & (combined_df['Profits/Losses'] != '-')]
                        if action == 'hold':
                            # Count only unique coin symbols for 'hold' action
                            unique_coins_count = action_df['Symbol'].nunique()
                            action_counts[action].append(unique_coins_count)
                            # Sum PNL only for unique coin symbols in 'hold' action
                            unique_coins_pnl = action_df.groupby('Symbol')['Profits/Losses'].sum().astype(float).sum()
                            action_pnls[action].append(unique_coins_pnl)
                        else:
                            action_counts[action].append(len(action_df))
                            action_pnls[action].append(action_df['Profits/Losses'].astype(float).sum())

                for action in action_types:
                    summary_table.add_row([f"{action.capitalize()} Count"] + action_counts[action])
                summary_table.add_row(["Transactions Count"] + transactions_count_per_wallet)
                for action in action_types:
                    if action != 'buy':
                        summary_table.add_row([f"{action.capitalize()} PNL"] + [f"{pnl:.2f} USD" for pnl in action_pnls[action]])

                summary_table.add_row(["Total PNL"] + [f"{pnl:.2f} USD" for pnl in total_pnl_per_wallet])
                
                summary_table.align = "l"
                pretty_date_str = datetime.strptime(date_str, '%Y%m%d').strftime('%B %d, %Y')
                summary_message = f"📊 Detailed summary for **{pretty_date_str}** 📊:\n```{summary_table.get_string()}```"
                print(summary_message)
                send_telegram_message(summary_message)
                
        except ValueError as e:
            print(f"Error combining CSV files for {date_str}: {e}")

def initialize_token_state():
    token_state_path = os.getenv('TOKEN_STATE_FILE', 'configs/token_state.json')
    data_directory = os.getenv('DATA_DIRECTORY', 'newerdata')
    try:
        # Find the most recent file in the data directory
        files = [os.path.join(data_directory, f) for f in os.listdir(data_directory) if os.path.isfile(os.path.join(data_directory, f))]
        if not files:
            print(f"No files found in the directory: {data_directory}.")
            return
        most_recent_file = max(files, key=os.path.getctime)
        print(f"Most recent file found: {most_recent_file}")
        
        # Read the most recent data
        with open(most_recent_file, 'r') as src:
            recent_data = json.load(src).get("0", {})
        
        # Check and update the token state file
        if os.path.exists(token_state_path):
            with open(token_state_path, 'r+') as dst:
                existing_data = json.load(dst).get("0", {})
                updated_data = {coin: recent_data.get(coin, existing_data.get(coin)) for coin in set(recent_data) | set(existing_data)}
                
                dst.seek(0)
                json.dump({"0": updated_data}, dst, indent=4)
                dst.truncate()
                
            print(f"Token state updated with recent data from: {most_recent_file}")
        else:
            with open(token_state_path, 'w') as dst:
                json.dump({"0": recent_data}, dst, indent=4)
            print(f"Token state file created and initialized with data from: {most_recent_file}")
    except Exception as e:
        print(f"Error initializing token state: {e}")
        
def run_tasks():
    global cnt
    cnt += 1
    print(f"Starting iteration number: {cnt}")
    start_time = time.time()
    
    # Run combine_and_clean_data only on the first iteration of each day
    current_day = datetime.now().strftime('%Y-%m-%d')
    global last_run_day
    if cnt == 1 or (last_run_day != current_day):
        combine_and_clean_data()
        last_run_day = current_day
    
    try:
        # Use subprocess to handle external script execution
        subprocess.run(["python3", "fetcher.py"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error running fetcher.py: {e}")
    
    if cnt == 1:
        try:
            initialize_token_state()
        except Exception as e:
            print(f"Error initializing token state: {e}")

    try:
        subprocess.run(["python3", "trader.py"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error running trader.py: {e}")

    end_time = time.time()
    elapsed_time = end_time - start_time
    print(f"Time spent on iteration {cnt}: {elapsed_time:.2f} seconds")
    # Schedule the next run regardless of errors
    scheduler.enter(60, 1, run_tasks)

def schedule_tasks():
    scheduler.enter(0, 1, run_tasks)
    scheduler.run()

if __name__ == "__main__":
    try:
        schedule_tasks()
    except (KeyboardInterrupt, SystemExit):
        print("Scheduler stopped on program exit")
        combine_and_clean_data()
