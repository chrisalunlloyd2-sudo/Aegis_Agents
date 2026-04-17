@echo off
title AEGIS-DIMON System Launcher
color 0A

REM Check for administrator privileges
net session >nul 2>&1
if %errorLevel% == 0 (
    echo [ADMIN] Running with administrator privileges
) else (
    echo [ADMIN] Requesting administrator privileges...
    echo [INFO] Please approve the UAC prompt to continue
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo ================================================================================
echo              /$$$$$$  /$$$$$$$$  /$$$$$$  /$$$$$$  /$$$$$$
echo             /$$__  $$^| $$_____/ /$$__  $$^|_  $$_/ /$$__  $$
echo            ^| $$  \ $$^| $$      ^| $$  \__/  ^| $$  ^| $$  \__/
echo            ^| $$$$$$$$^| $$$$$   ^| $$ /$$$$  ^| $$  ^|  $$$$$$
echo            ^| $$__  $$^| $$__/   ^| $$^|_  $$  ^| $$   \____  $$
echo            ^| $$  ^| $$^| $$      ^| $$  \ $$  ^| $$   /$$  \ $$
echo            ^| $$  ^| $$^| $$$$$$$$^|  $$$$$$/ /$$$$$$^|  $$$$$$/
echo            ^|__/  ^|__/^|________/ \______/ ^|______/ \______/
echo                    THE CANADIAN ULTRA MANIFOLD
echo ================================================================================
echo.
echo [SYSTEM] Initializing AEGIS-DIMON Hybrid AI System...
echo [SYSTEM] Local Model: Gemma 2B ^| Cloud Backup: Gemini Pro
echo [SYSTEM] Running with ELEVATED PRIVILEGES for Ollama
echo.

REM Kill any existing processes
echo [CLEANUP] Stopping old processes...
taskkill /F /IM cloudflared.exe 2>nul
taskkill /F /IM python.exe /FI "WINDOWTITLE eq AEGIS*" 2>nul
taskkill /F /IM ollama.exe 2>nul
timeout /t 2 /nobreak >nul

REM Change to project directory
cd /d C:\Users\viper\Aegis_Agents

REM Start Ollama with administrator privileges (already have them)
echo [CHECK] Starting Ollama service with admin privileges...
start "" "C:\Users\viper\AppData\Local\Programs\Ollama\ollama.exe" serve
timeout /t 5 /nobreak >nul

REM Verify Ollama is running
tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I /N "ollama.exe">NUL
if "%ERRORLEVEL%"=="1" (
    echo [ERROR] Failed to start Ollama. Please check installation.
    pause
    exit /b 1
) else (
    echo [OK] Ollama is running with elevated privileges
)

REM Check if gemma2:2b model is available
echo [CHECK] Verifying Gemma 2B model...
ollama list | findstr "gemma2:2b" >nul
if errorlevel 1 (
    echo [WARNING] Gemma 2B model not found. Pulling model...
    echo [INFO] This may take a few minutes...
    ollama pull gemma2:2b
) else (
    echo [OK] Gemma 2B model available
)

echo.
echo ================================================================================
echo [LAUNCH] Starting AEGIS Components...
echo ================================================================================
echo.

REM Start FastAPI Backend
echo [1/2] Starting FastAPI Backend Server...
start "AEGIS FastAPI Backend" python -m uvicorn gemini_bridge_api_fast:app --host 0.0.0.0 --port 5005 --reload

REM Wait for server to start
echo [INFO] Waiting for server initialization...
timeout /t 5 /nobreak >nul

REM Start Cloudflare Tunnel and capture output to log
echo [2/2] Creating Cloudflare Tunnel ^(generating new public URL^)...
start "Cloudflare Tunnel" /MIN C:\Users\viper\cloudflared.exe tunnel --url http://localhost:5005

REM Wait for tunnel to establish
echo [INFO] Waiting for tunnel to establish...
timeout /t 15 /nobreak >nul

REM Extract Cloudflare URL using PowerShell
echo [INFO] Extracting Cloudflare URL...
powershell -Command "$log = Get-Content C:\Users\viper\tunnel.log -Tail 50 | Select-String 'https://.*\.trycloudflare\.com'; if ($log) { $url = $log.Matches[0].Value; Write-Output $url; $url | Out-File -FilePath \"$env:USERPROFILE\OneDrive\CLOUDFLARE.txt\" -Encoding ASCII; $url | Out-File -FilePath \"$env:USERPROFILE\Desktop\CLOUDFLARE_URL.txt\" -Encoding ASCII }" > temp_url.txt

REM Read the extracted URL
set /p CLOUDFLARE_URL=<temp_url.txt
del temp_url.txt

echo.
echo ================================================================================
echo [SUCCESS] AEGIS-DIMON System is now ONLINE!
echo ================================================================================
echo.
echo [PUBLIC URL - SAVED TO ONEDRIVE]
echo %CLOUDFLARE_URL%
echo.
echo [LOCAL ACCESS]
echo http://localhost:5005
echo.
echo [INFO] URL saved to: %USERPROFILE%\OneDrive\CLOUDFLARE.txt
echo [INFO] URL also saved to: %USERPROFILE%\Desktop\CLOUDFLARE_URL.txt
echo [INFO] Timescale Memory System active (v2.0)
echo [INFO] Gemma 2B ready for local inference
echo.
echo [CONTROLS]
echo - Keep this window open to maintain the system
echo - Press Ctrl+C to shutdown all components
echo.
echo ================================================================================
echo [STATUS] Kernel Mode: AUTO ^| RAG: ACTIVE ^| VRAM: OPTIMIZED
echo ================================================================================
echo.

REM Open Cloudflare URL in browser (only if URL was extracted)
if defined CLOUDFLARE_URL (
    if not "%CLOUDFLARE_URL%"=="" (
        echo [INFO] Opening Cloudflare URL in browser...
        start "" "%CLOUDFLARE_URL%"
    ) else (
        echo [WARNING] URL not extracted. Check Desktop\CLOUDFLARE_URL.txt manually
    )
) else (
    echo [WARNING] URL variable not set. Check Desktop\CLOUDFLARE_URL.txt manually
)

REM Keep window open
pause

@REM Made with Bob
