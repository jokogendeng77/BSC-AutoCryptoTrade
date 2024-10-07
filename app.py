import json
import subprocess
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QWidget, QScrollArea, QLineEdit, QTableWidget, QTableWidgetItem, QInputDialog, QHeaderView, QComboBox, QApplication, QDialog
import psutil


def generate_wallet_credentials():
    from web3 import Web3
    # Generate a new wallet address and private key using web3
    w3 = Web3()
    account = w3.eth.account.create()
    wallet_address = account.address
    private_key = account._private_key.hex()
    return wallet_address, private_key

def load_settings():
    with open('app_dir/wallet_settings.json', 'r') as file:
        return json.load(file)

def save_settings(settings):
    with open('app_dir/wallet_settings.json', 'w') as file:
        json.dump(settings, file, indent=4)

def update_settings(wallet, new_status, status_label, toggle_button):
    settings = load_settings()
    previous_status = settings[wallet]['enabled'] == "True"
    print(f"Updating settings for {wallet} to {not previous_status}")
    settings[wallet]['enabled'] = str(not previous_status)
    save_settings(settings)
    QMessageBox.information(None, "Update Successful", f"Settings for {wallet} have been updated to {'enabled' if settings[wallet]['enabled'] else 'disabled'}.")
    status_label.setText(f"<b>{wallet.upper()} IS <font color={'green' if settings[wallet]['enabled'] else 'red'}>{'ENABLED' if settings[wallet]['enabled'] else 'DISABLED'}</font></b>")
    toggle_button.setText(f"{'Disable' if settings[wallet]['enabled'] else 'Enable'} Wallet")
    toggle_button.setStyleSheet(f"background-color: {'red' if settings[wallet]['enabled'] else 'blue'}; color: white; font-size: 12pt;")
    return settings[wallet]['enabled']

def update_wallet_config(wallet, config_key, new_value, config_label):
    settings = load_settings()
    settings[wallet][config_key] = new_value
    save_settings(settings)
    QMessageBox.information(None, "Configuration Updated", f"Configuration {config_key} for {wallet} has been updated.")
    config_label.setText(f"{config_key}: {new_value}")
    
def load_wallet_template():
    with open('configs/wallet_template.json', 'r') as file:
        return json.load(file)['template']

def add_wallet(wallet_name, config_windows):
    settings = load_settings()
    if wallet_name in settings:
        QMessageBox.warning(None, "Warning", "Wallet already exists.")
        return
    wallet_template = load_wallet_template()
    # Generate a new wallet address and private key
    wallet_address, private_key = generate_wallet_credentials()
    wallet_template['wallet_address'] = wallet_address
    wallet_template['private_key'] = private_key
    settings[wallet_name] = wallet_template
    save_settings(settings)
    QMessageBox.information(None, "Success", "Wallet added successfully with a new address and private key.")
    refresh_wallet_list(config_windows)  # Refresh the wallet list UI

def delete_wallet(wallet_name, config_windows):
    settings = load_settings()
    if wallet_name in settings:
        del settings[wallet_name]
        save_settings(settings)
        QMessageBox.information(None, "Success", "Wallet deleted successfully.")
        refresh_wallet_list(config_windows)  # Refresh the wallet list UI
    else:
        QMessageBox.warning(None, "Warning", "Wallet does not exist.")

def start_stop_application(app_button):
    global app_process
    if 'app_process' in globals() and app_process.poll() is None:
        try:
            parent = psutil.Process(app_process.pid)
            children = parent.children(recursive=True)
            for child in children:
                child.terminate()
            parent.terminate()
            gone, still_alive = psutil.wait_procs(children + [parent], timeout=10, callback=None)
            for p in still_alive:
                p.kill()
            app_button.setText("Start Application")
            QMessageBox.information(None, "Success", "Application stopped successfully.")
        except psutil.NoSuchProcess:
            QMessageBox.information(None, "Info", "Process already terminated.")
        except Exception as e:
            QMessageBox.critical(None, "Error", f"Failed to stop the application: {str(e)}")
    else:
        try:
            app_process = subprocess.Popen(['python', 'main.py'], cwd='app_dir')
            app_button.setText("Stop Application")
            app_button.setStyleSheet("background-color: red; color: white; font-size: 12pt; font-weight: bold;")
            QMessageBox.information(None, "Success", "Application started successfully.")
        except Exception as e:
            QMessageBox.critical(None, "Error", f"Failed to start the application: {str(e)}")

def create_ui():
    global app, root, config_windows  # Make these global to access them outside this function
    app = QtWidgets.QApplication([])
    default_font = QtGui.QFont("Arial", 10)
    app.setFont(default_font)
    root = QWidget()
    config_windows = {}
    root.setWindowTitle("Wallet Settings UI")
    root.resize(800, 600)
    root.setStyleSheet("background-color: #263238; padding: 10px;")  # Material design background color

    layout = QVBoxLayout(root)

    header_label = QLabel("Auto Crypto Bot UI", root)
    header_label.setStyleSheet("font-size: 20pt; font-weight: bold; color: #ECEFF1; margin-bottom: 20px;")  # Material design text color
    layout.addWidget(header_label, alignment=QtCore.Qt.AlignCenter)

    # Call to refresh the wallet list
    refresh_wallet_list(config_windows)

    button_container = QWidget(root)
    button_layout = QHBoxLayout(button_container)
    button_layout.setContentsMargins(10, 10, 10, 10)  # Adjusted margins for better spacing
    button_layout.setSpacing(20)  # Increased spacing between buttons
    layout.addWidget(button_container, alignment=QtCore.Qt.AlignCenter)
    
    add_wallet_button = QPushButton("Add Wallet", button_container)
    add_wallet_button.setStyleSheet("background-color: #2196F3; color: white; font-size: 14pt; padding: 10px;")  # Material design button color
    add_wallet_button.clicked.connect(lambda: add_wallet(QInputDialog.getText(None, "Add Wallet", "Enter wallet name:")[0], config_windows))
    button_layout.addWidget(add_wallet_button)

    app_button = QPushButton("Start Application", button_container)
    app_button.setStyleSheet("background-color: #4CAF50; color: white; font-size: 14pt; padding: 10px;")  # Material design button color
    app_button.clicked.connect(lambda: start_stop_application(app_button))
    button_layout.addWidget(app_button)

    # Additional buttons for showing coin lists
    show_available_coins_button = QPushButton("Show Available Coins", button_container)
    show_available_coins_button.setStyleSheet("background-color: #FF9800; color: white; font-size: 14pt; padding: 10px;")  # Material design button color
    show_available_coins_button.clicked.connect(lambda: show_coin_list('configs/available_coin_list.json', 'Available Coins', config_windows))
    button_layout.addWidget(show_available_coins_button)

    show_desired_coins_button = QPushButton("Show Desired Coins", button_container)
    show_desired_coins_button.setStyleSheet("background-color: #3F51B5; color: white; font-size: 14pt; padding: 10px;")  # Material design button color
    show_desired_coins_button.clicked.connect(lambda: show_coin_list('configs/desired_coin_list.json', 'Desired Coins', config_windows))
    button_layout.addWidget(show_desired_coins_button)

    root.show()
    app.exec_()


def refresh_wallet_list(config_windows):
    global scrollable_frame, scroll_layout, scroll_area  # Make these global to modify them in add/delete wallet functions
    if 'scroll_area' in globals():
        root.layout().removeWidget(scroll_area)
        scroll_area.deleteLater()  # Remove the old scroll area

    scroll_area = QScrollArea(root)
    scroll_area.setWidgetResizable(True)
    scroll_area.setStyleSheet("border: none;")  # Material UI style: no border for scroll area
    scrollable_frame = QWidget()
    scroll_area.setWidget(scrollable_frame)
    scroll_layout = QVBoxLayout(scrollable_frame)
    scroll_layout.setContentsMargins(0, 0, 0, 0)
    scroll_layout.setSpacing(10)

    settings = load_settings()
    for wallet, details in settings.items():
        create_wallet_widget(wallet, details, config_windows)

    # Add the scroll area to the main layout before the button container
    root.layout().insertWidget(1, scroll_area)  # Insert at position 1 to place it after the header label

def create_wallet_widget(wallet, details, config_windows):
    enabled_status = details['enabled'] == "True"
    status_label = QLabel(f"<b>{wallet.upper()} IS <font color={'#4CAF50' if enabled_status else '#F44336'}>{'ENABLED' if enabled_status else 'DISABLED'}</font></b>", scrollable_frame)
    status_label.setAlignment(QtCore.Qt.AlignCenter)
    status_label.setStyleSheet("color: white; font-size: 14pt; margin-bottom: 5px; background-color: #263238; padding: 10px;")
    scroll_layout.addWidget(status_label)

    button_frame = QWidget(scrollable_frame)
    button_frame.setStyleSheet("background-color: #37474F; padding: 10px;")
    button_layout = QHBoxLayout(button_frame)
    button_layout.setContentsMargins(0, 0, 0, 0)
    button_layout.setSpacing(10)
    scroll_layout.addWidget(button_frame)

    toggle_button = QPushButton(f"{'Disable' if enabled_status else 'Enable'} Wallet", button_frame)
    toggle_button.setStyleSheet(f"background-color: {'#F44336' if enabled_status else '#2196F3'}; color: white; font-size: 12pt; padding: 10px;")
    button_layout.addWidget(toggle_button)

    open_config_button = QPushButton("Open Configurations", button_frame)
    open_config_button.setStyleSheet("background-color: #FF9800; color: white; font-size: 12pt; padding: 10px;")
    button_layout.addWidget(open_config_button)
    
    delete_wallet_button = QPushButton("Delete Wallet", button_frame)
    delete_wallet_button.setStyleSheet("background-color: #F44336; color: white; font-size: 12pt; padding: 10px;")
    delete_wallet_button.clicked.connect(lambda: delete_wallet(wallet, config_windows))
    button_layout.addWidget(delete_wallet_button)

    def toggle_status(w=wallet, s=not enabled_status, sl=status_label, tb=toggle_button):
        s = update_settings(w, s, sl, tb)
        if s:
            show_config(w, root, config_windows)
        else:
            hide_config(w, root, config_windows)

    toggle_button.clicked.connect(lambda _, w=wallet, s=enabled_status, sl=status_label, tb=toggle_button: toggle_status(w, s, sl, tb))
    open_config_button.clicked.connect(lambda _, w=wallet: show_config(w, root, config_windows))


# Global dictionary to hold references to coin windows

def show_coin_list(file_path, title, open_coin_windows):
    # Create and configure the loading dialog
    loading_dialog = QDialog(None)
    loading_dialog.setWindowTitle("Loading")
    loading_label = QLabel("Loading coins, please wait...", loading_dialog)
    loading_layout = QVBoxLayout(loading_dialog)
    loading_layout.addWidget(loading_label)
    loading_dialog.setWindowModality(Qt.ApplicationModal)  # Block interaction with other windows
    loading_dialog.show()
    QApplication.processEvents()  # Update UI to show the dialog

    try:
        with open(file_path, 'r') as file:
            data = json.load(file)
        coin_window = QWidget()
        coin_window.setWindowTitle(title)
        coin_window.resize(800, 600)
        coin_window.setWindowFlags(Qt.WindowStaysOnTopHint)  # Ensure the window stays on top
        coin_window.setStyleSheet("""
            background-color: #121212; 
            padding: 10px; 
            color: white;
            font-family: 'Roboto', sans-serif;
        """)
        layout = QVBoxLayout(coin_window)

        header_label = QLabel(title)
        header_label.setStyleSheet("font-size: 20pt; font-weight: bold; color: white;")
        layout.addWidget(header_label)

        table = QTableWidget()
        layout.addWidget(table)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.MultiSelection)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.horizontalHeader().setStyleSheet("background-color: #333333; min-height: 40px;")
        table.horizontalHeader().setStretchLastSection(True)
        table.setStyleSheet("""
            QTableWidget {
                background-color: #1e1e1e;
                color: white;
                gridline-color: #444;
            }
            QHeaderView::section {
                background-color: #333333;
                padding: 10px;
                border: 1px solid #444;
                color: white;
                font-size: 10pt;
            }
            QLineEdit {
                min-height: 30px;
                background-color: #333333;
                color: white;
                border: 1px solid #444;
            }
        """)

        if isinstance(data, list):
            table.setColumnCount(1)  # Reduced column count since we're not using checkboxes
            table.setHorizontalHeaderLabels(["Symbol"])
            table.setRowCount(len(data))
            for index, symbol in enumerate(data):
                item = QTableWidgetItem(symbol)
                item.setTextAlignment(Qt.AlignCenter)  # Center the text
                table.setItem(index, 0, item)
        elif isinstance(data, dict):
            table.setColumnCount(4)  # Adjusted for dictionary data
            table.setHorizontalHeaderLabels(["Id", "Name", "Symbol", "Contract Address"])
            table.setRowCount(len(data))
            for index, (symbol, details) in enumerate(data.items()):
                if details is not None:
                    table.setItem(index, 0, QTableWidgetItem(details.get('id', 'N/A')))
                    # Remove emojis from the name to avoid errors with opentype support
                    name = details.get('name', 'N/A')
                    clean_name = ''.join(char for char in name if char.isalnum() or char.isspace()) if name is not None else 'N/A'
                    table.setItem(index, 1, QTableWidgetItem(clean_name))
                    table.setItem(index, 2, QTableWidgetItem(details.get('symbol', 'N/A')))
                    table.setItem(index, 3, QTableWidgetItem(details.get('contract_address', 'N/A')))

        table.resizeColumnsToContents()
        table.resizeRowsToContents()
        table.horizontalScrollBar().setStyleSheet("QScrollBar {height:12px; background-color: #333333;}")
        table.verticalScrollBar().setStyleSheet("QScrollBar {width:12px; background-color: #333333;}")

        add_button = QPushButton("Add New Record", coin_window)
        add_button.setStyleSheet("background-color: #1976D2; color: white; font-size: 12pt; min-height: 30px;")
        add_button.clicked.connect(lambda: add_item(file_path, table))
        layout.addWidget(add_button)

        delete_button = QPushButton("Delete Selected", coin_window)
        delete_button.setStyleSheet("background-color: #D32F2F; color: white; font-size: 12pt; min-height: 30px;")
        delete_button.clicked.connect(lambda: remove_selected_items(file_path, table))
        layout.addWidget(delete_button)

        coin_window.setLayout(layout)
        coin_window.show()

        # Store the window reference to prevent it from being garbage collected
        open_coin_windows[title] = coin_window
    except Exception as e:
        QMessageBox.critical(None, "Error", f"Failed to load coin list: {str(e)}")
    finally:
        loading_dialog.accept()  # Close the loading dialog once loading is complete

def handle_action(file_path, table, row, column):
    if column == 1:  # Actions column
        action = table.cellWidget(row, column).text()
        if action == "Remove":
            remove_item(file_path, table, row)
        elif action == "Edit":
            edit_item(file_path, table, row)
        elif action == "Add":
            add_item(file_path, table)

def remove_item(file_path, table, row):
    symbol = table.item(row, 0).text()
    with open(file_path, 'r') as file:
        data = json.load(file)
    if isinstance(data, list):
        data.remove(symbol)
    elif isinstance(data, dict):
        del data[symbol]
    with open(file_path, 'w') as file:
        json.dump(data, file, indent=4)
    table.removeRow(row)


def edit_item(file_path, table, row):
    symbol = table.item(row, 0).text()
    with open(file_path, 'r') as file:
        data = json.load(file)
    if isinstance(data, dict) and symbol in data:
        new_address, ok = QInputDialog.getText(table, "Input", "Enter new contract address:")
        if ok and new_address:
            data[symbol]['contract_address'] = new_address
            table.item(row, 1).setText(new_address)
            with open(file_path, 'w') as file:
                json.dump(data, file, indent=4)
                
def add_item(file_path, table):
    symbol, ok_symbol = QInputDialog.getText(table, "Input", "Enter symbol:")
    if ok_symbol:
        address, ok_address = QInputDialog.getText(table, "Input", "Enter contract address:")
        if ok_address:
            with open(file_path, 'r') as file:
                data = json.load(file)
            if isinstance(data, list):
                data.append(symbol)
            elif isinstance(data, dict):
                data[symbol] = {'contract_address': address}
            with open(file_path, 'w') as file:
                json.dump(data, file, indent=4)
            row_count = table.rowCount()
            table.setRowCount(row_count + 1)
            table.setItem(row_count, 0, QTableWidgetItem(symbol))
            table.setItem(row_count, 1, QTableWidgetItem(address))
            action_item = QTableWidgetItem("Edit" if isinstance(data, dict) else "Remove")
            action_item.setFlags(action_item.flags() & ~QtCore.Qt.ItemIsEditable)
            table.setItem(row_count, 2, action_item)
            
def remove_selected_items(file_path, table):
    selected_rows = table.selectedRanges()
    rows_to_delete = [range.topRow() for range in selected_rows]
    with open(file_path, 'r') as file:
        data = json.load(file)
    if isinstance(data, list):
        data = [data[i] for i in range(len(data)) if i not in rows_to_delete]
    elif isinstance(data, dict):
        keys_to_delete = [list(data.keys())[i] for i in rows_to_delete]
        for key in keys_to_delete:
            del data[key]
    with open(file_path, 'w') as file:
        json.dump(data, file, indent=4)
    for row in sorted(rows_to_delete, reverse=True):
        table.removeRow(row)

def show_config(wallet, root, config_windows):
    settings = load_settings()
    details = settings[wallet]
    if wallet not in config_windows:
        config_window = QWidget()
        config_window.setWindowTitle(f"Configuration for {wallet}")
        config_window.setFixedSize(570, 600)
        config_window.setStyleSheet("background-color: #0d1117; padding: 10px;")
        config_windows[wallet] = config_window
    else:
        config_window = config_windows[wallet]
        config_window.setFixedSize(570, 600)

    main_layout = QVBoxLayout(config_window)
    main_layout.setContentsMargins(10, 10, 10, 10)
    main_layout.setSpacing(10)

    scroll_area = QScrollArea(config_window)
    scroll_area.setWidgetResizable(True)
    scroll_area.setStyleSheet("background-color: #0d1117;")
    main_layout.addWidget(scroll_area)

    canvas = QWidget()
    canvas_layout = QVBoxLayout(canvas)
    canvas_layout.setContentsMargins(10, 10, 10, 10)
    canvas_layout.setSpacing(20)
    scroll_area.setWidget(canvas)

    entries = {}
    for key, value in details.items():
        if key != 'enabled':
            entry_frame = QWidget(canvas)
            entry_layout = QVBoxLayout(entry_frame)
            entry_layout.setContentsMargins(0, 0, 0, 0)
            entry_layout.setSpacing(5)
            canvas_layout.addWidget(entry_frame)

            human_readable_key = " ".join(word.capitalize() for word in key.split('_'))
            config_label = QLabel(f"{human_readable_key}:", entry_frame)
            config_label.setStyleSheet("color: white; font-size: 12pt; font-weight: bold;")
            entry_layout.addWidget(config_label)
            if key.lower() == 'trade_mode':
                config_entry = QComboBox(entry_frame)
                config_entry.addItems(["TimeFrame", "Event"])
                config_entry.setCurrentText(value)
                config_entry.setStyleSheet("""
                    QComboBox {
                        color: white;
                        font-size: 12pt;
                        border: 1px solid white;
                        padding: 5px;
                        background-color: #1e1e1e;
                    }
                    QComboBox::drop-down {
                        border: none;
                    }
                    QComboBox QAbstractItemView {
                        background-color: #1e1e1e;
                        color: white;
                        selection-background-color: #3a3a3a;
                    }
                """)
            else:
                config_entry = QLineEdit(str(value), entry_frame)
                config_entry.setReadOnly(key in ['current_holdings', 'FEE'])
                config_entry.setStyleSheet("color: white; font-size: 12pt;")
            entry_layout.addWidget(config_entry)
            entries[key] = config_entry

    button_container = QWidget(config_window)
    button_layout = QHBoxLayout(button_container)
    button_layout.setContentsMargins(0, 0, 0, 0)
    button_layout.setSpacing(10)
    main_layout.addWidget(button_container)

    update_button = QPushButton("Update All", button_container)
    update_button.setStyleSheet("background-color: blue; color: white; font-size: 12pt;")
    update_button.clicked.connect(lambda: update_all_configs(wallet, entries, config_windows))
    button_layout.addWidget(update_button)

    reset_button = QPushButton("Reset Current Holdings", button_container)
    reset_button.setStyleSheet("background-color: red; color: white; font-size: 12pt;")
    reset_button.clicked.connect(lambda: reset_current_holdings(wallet, entries))
    button_layout.addWidget(reset_button)

    config_window.show()

def update_all_configs(wallet, entries, config_windows):
    settings = load_settings()
    for key, entry_widget in entries.items():
        new_value = entry_widget.currentText() if isinstance(entry_widget, QComboBox) else entry_widget.text()
        settings[wallet][key] = new_value
    save_settings(settings)
    QMessageBox.information(None, "Configuration Updated", f"All configurations for {wallet} have been updated.")
    for key, entry_widget in entries.items():
        if isinstance(entry_widget, QLineEdit):
            entry_widget.setText(settings[wallet][key])
    config_windows[wallet].raise_()

def reset_current_holdings(wallet, entries):
    settings = load_settings()
    settings[wallet]['current_holdings'] = {}
    save_settings(settings)
    entries['current_holdings'].setText("{}")
    QMessageBox.information(None, "Holdings Reset", "Current holdings have been reset to 0.")

def hide_config(wallet, root, config_windows):
    if wallet in config_windows:
        config_windows[wallet].hide()

if __name__ == "__main__":
    create_ui()
