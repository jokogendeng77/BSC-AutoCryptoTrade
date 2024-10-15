@echo off
setlocal enabledelayedexpansion

echo Checking for Python installation...
python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo Python is not installed.
    echo Checking for Chocolatey installation...
    where choco >nul 2>&1
    IF %ERRORLEVEL% NEQ 0 (
        echo Chocolatey is not installed. Attempting to install Chocolatey...
        @powershell -NoProfile -ExecutionPolicy Bypass -Command "[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))" && SET "PATH=%PATH%;%ALLUSERSPROFILE%\chocolatey\bin"
        IF !ERRORLEVEL! NEQ 0 (
            echo Failed to install Chocolatey. Please install Chocolatey manually.
            pause
            exit /b 1
        )
        echo Chocolatey installed successfully.
    )
    echo Installing Python via Chocolatey...
    choco install python --yes
    IF !ERRORLEVEL! NEQ 0 (
        echo Failed to install Python. Please install Python manually.
        pause
        exit /b 1
    )
    echo Python installed successfully.
    refreshenv
) ELSE (
    echo Python is already installed.
)

echo Checking for pip installation...
pip --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo pip is not installed. Attempting to install pip...
    python -m ensurepip --upgrade
    IF !ERRORLEVEL! NEQ 0 (
        echo Failed to install pip. Please install pip manually.
        pause
        exit /b 1
    )
    echo pip installed successfully.
)

echo Installing required Python packages...
pip install -r requirements.txt
IF %ERRORLEVEL% NEQ 0 (
    echo Failed to install one or more Python packages. Check the requirements.txt file and try again.
    pause
    exit /b 1
)
echo All required Python packages are installed.

echo Starting the application...
python app.py
IF %ERRORLEVEL% NEQ 0 (
    echo Application failed to start. Please check the application logs for more details.
    pause
    exit /b 1
)
echo Application is running.
pause
endlocal
