@echo off
setlocal enabledelayedexpansion

echo Checking for Python installation...
python3 --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo Python is not installed.
    echo Checking for Chocolatey installation...
    choco -v >nul 2>&1
    IF %ERRORLEVEL% NEQ 0 (
        echo Chocolatey is not installed. Attempting to install Chocolatey...
        @powershell -NoProfile -ExecutionPolicy Bypass -Command "iex ((New-Object System.Net.WebClient).DownloadString('https://chocolatey.org/install.ps1'))" >nul 2>&1
        IF !ERRORLEVEL! NEQ 0 (
            echo Failed to install Chocolatey. Please install Chocolatey manually.
            exit /b 1
        )
        echo Chocolatey installed successfully.
        SET "PATH=%PATH%;%ALLUSERSPROFILE%\\chocolatey\\bin"
    )
    echo Installing Python via Chocolatey...
    choco install python3 --yes >nul 2>&1
    IF !ERRORLEVEL! NEQ 0 (
        echo Failed to install Python. Please install Python manually.
        exit /b 1
    )
    echo Python installed successfully.
) ELSE (
    echo Python is already installed.
)

echo Installing required Python packages...
pip3 install -r requirements.txt >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo Failed to install one or more Python packages. Check the requirements.txt file and try again.
    exit /b 1
)
echo All required Python packages are installed.

echo Starting the application...
python3 app.py
IF %ERRORLEVEL% NEQ 0 (
    echo Application failed to start. Please check the application logs for more details.
    exit /b 1
)
echo Application is running.
endlocal
