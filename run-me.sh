
#!/bin/bash

echo "Checking for Python installation..."
python3 --version > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "Python is not installed."
    echo "Checking for Homebrew installation..."
    brew -v > /dev/null 2>&1
    if [ $? -ne 0 ]; then
        echo "Homebrew is not installed. Attempting to install Homebrew..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" > /dev/null 2>&1
        if [ $? -ne 0 ]; then
            echo "Failed to install Homebrew. Please install Homebrew manually."
            exit 1
        fi
        echo "Homebrew installed successfully."
    fi
    echo "Installing Python via Homebrew..."
    brew install python3 > /dev/null 2>&1
    if [ $? -ne 0 ]; then
        echo "Failed to install Python. Please install Python manually."
        exit 1
    fi
    echo "Python installed successfully."
else
    echo "Python is already installed."
fi

echo "Installing required Python packages..."
pip3 install -r requirements.txt > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "Failed to install one or more Python packages. Check the requirements.txt file and try again."
    exit 1
fi
echo "All required Python packages are installed."

echo "Starting the application..."
python3 app.py
if [ $? -ne 0 ]; then
    echo "Application failed to start. Please check the application logs for more details."
    exit 1
fi
echo "Application is running."
