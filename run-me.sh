#!/bin/bash

set -e

# Function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to handle errors
handle_error() {
    echo "Error: $1" >&2
    exit 1
}

# Function to install Python
install_python() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        if ! command_exists brew; then
            echo "Homebrew is not installed. Attempting to install Homebrew..."
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" || handle_error "Failed to install Homebrew. Please install Homebrew manually."
            echo "Homebrew installed successfully."
        fi
        echo "Installing Python via Homebrew..."
        brew install python3 || handle_error "Failed to install Python via Homebrew."
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        # Linux
        echo "Updating package lists..."
        sudo apt update || handle_error "Failed to update package lists."
        echo "Installing Python via apt..."
        sudo apt install -y python3 python3-pip || handle_error "Failed to install Python via apt."
    else
        handle_error "Unsupported operating system. Please install Python manually."
    fi
    echo "Python installed successfully."
}

# Function to install pip
install_pip() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        brew install pip3 || handle_error "Failed to install pip via Homebrew."
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        # Linux
        sudo apt install -y python3-pip || handle_error "Failed to install pip via apt."
    else
        handle_error "Unsupported operating system. Please install pip manually."
    fi
    echo "pip installed successfully."
}

# Main script execution
echo "Checking for Python installation..."
if ! command_exists python3; then
    echo "Python is not installed."
    install_python
else
    echo "Python is already installed."
fi

echo "Checking for pip installation..."
if ! command_exists pip3 && ! python3 -m pip --version >/dev/null 2>&1; then
    echo "pip is not installed. Attempting to install pip..."
    install_pip
else
    echo "pip is already installed."
fi

echo "Installing required Python packages..."
python3 -m pip install -r requirements.txt || handle_error "Failed to install one or more Python packages. Check the requirements.txt file and try again."
echo "All required Python packages are installed."

echo "Starting the application..."
python3 app.py || handle_error "Application failed to start. Please check the application logs for more details."
echo "Application is running."
