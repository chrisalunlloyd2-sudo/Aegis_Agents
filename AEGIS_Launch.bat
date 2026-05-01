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
echo [SYSTEM] Initializing AEGIS-DIMON Local Blueprint...
echo [SYSTEM] Primary Local Model: aegis-gemma2-abliterated:2b-q8 ^| Google paid path: DISABLED
echo [SYSTEM] Vector Memory: LOCAL Qdrant/SQLite
echo [SYSTEM] Running with ELEVATED PRIVILEGES for Ollama
echo.

REM Kill any existing processes
echo [CLEANUP] Stopping old processes...
taskkill /F /IM cloudflared.exe 2>nul
taskkill /F /IM python.exe /FI "WINDOWTITLE eq AEGIS*" 2>nul
taskkill /F /IM ollama.exe 2>nul
timeout /t 2 /nobreak >nul

REM Change to project directory
cd /d "%~dp0"

REM Default to the local-only blueprint: local model + local DB + local tools
if "%AEGIS_DEFAULT_MODE%"=="" set "AEGIS_DEFAULT_MODE=auto"
if "%AEGIS_LOCAL_ONLY%"=="" set "AEGIS_LOCAL_ONLY=1"
if "%AEGIS_LOCAL_PRIMARY_MODEL%"=="" set "AEGIS_LOCAL_PRIMARY_MODEL=gemma4:26b-a4b-it-q8_0"
if "%AEGIS_LOCAL_CODE_MODEL%"=="" set "AEGIS_LOCAL_CODE_MODEL=%AEGIS_LOCAL_PRIMARY_MODEL%"
if "%AEGIS_LOCAL_TOOL_MODEL%"=="" set "AEGIS_LOCAL_TOOL_MODEL=qwen2.5-coder:1.5b"
if "%AEGIS_LOCAL_TOOL_FALLBACK_MODEL%"=="" set "AEGIS_LOCAL_TOOL_FALLBACK_MODEL=%AEGIS_LOCAL_PRIMARY_MODEL%"
if "%AEGIS_PICOCLAW_MODEL%"=="" set "AEGIS_PICOCLAW_MODEL=%AEGIS_LOCAL_PRIMARY_MODEL%"
if "%AEGIS_PICOCLAW_PREFER_DIRECT%"=="" set "AEGIS_PICOCLAW_PREFER_DIRECT=1"
if "%AEGIS_BROWSER_USE_MODEL%"=="" set "AEGIS_BROWSER_USE_MODEL=%AEGIS_LOCAL_PRIMARY_MODEL%"
if "%AEGIS_ENABLE_GOOGLE_PAID%"=="" set "AEGIS_ENABLE_GOOGLE_PAID=0"
if "%AEGIS_DISABLE_CLOUD%"=="" set "AEGIS_DISABLE_CLOUD=1"
if "%AEGIS_FORCE_LOCAL_VECTOR%"=="" set "AEGIS_FORCE_LOCAL_VECTOR=1"
if "%AEGIS_CLOUD_VECTOR_DSN%"=="" set "AEGIS_CLOUD_VECTOR_DSN="
if "%AEGIS_INCLUDE_REASONING_NOTES%"=="" set "AEGIS_INCLUDE_REASONING_NOTES=0"
if "%AEGIS_OLLAMA_PRIMARY_KEEP_ALIVE%"=="" set "AEGIS_OLLAMA_PRIMARY_KEEP_ALIVE=20m"
if "%AEGIS_OLLAMA_TOOL_KEEP_ALIVE%"=="" set "AEGIS_OLLAMA_TOOL_KEEP_ALIVE=8m"
if "%AEGIS_OLLAMA_EMBED_KEEP_ALIVE%"=="" set "AEGIS_OLLAMA_EMBED_KEEP_ALIVE=4m"
if "%AEGIS_OLLAMA_CHAT_TIMEOUT_SECONDS%"=="" set "AEGIS_OLLAMA_CHAT_TIMEOUT_SECONDS=240"
if "%AEGIS_OLLAMA_FIRST_TOKEN_TIMEOUT_SECONDS%"=="" set "AEGIS_OLLAMA_FIRST_TOKEN_TIMEOUT_SECONDS=75"
if "%AEGIS_OLLAMA_NUM_CTX_SIMPLE%"=="" set "AEGIS_OLLAMA_NUM_CTX_SIMPLE=2048"
if "%AEGIS_OLLAMA_NUM_CTX_DEFAULT%"=="" set "AEGIS_OLLAMA_NUM_CTX_DEFAULT=8192"
if "%AEGIS_OLLAMA_NUM_CTX_LONG%"=="" set "AEGIS_OLLAMA_NUM_CTX_LONG=12288"
if "%AEGIS_WORKER_NUM_CTX%"=="" set "AEGIS_WORKER_NUM_CTX=1024"
if "%AEGIS_PROGRAM_LOOP_NUM_CTX%"=="" set "AEGIS_PROGRAM_LOOP_NUM_CTX=3072"
if "%AEGIS_ENGINE_NUM_CTX%"=="" set "AEGIS_ENGINE_NUM_CTX=8192"
if "%AEGIS_RESPONSE_BUDGET_SIMPLE%"=="" set "AEGIS_RESPONSE_BUDGET_SIMPLE=1536"
if "%AEGIS_RESPONSE_BUDGET_DEFAULT%"=="" set "AEGIS_RESPONSE_BUDGET_DEFAULT=4096"
if "%AEGIS_RESPONSE_BUDGET_DELIBERATE%"=="" set "AEGIS_RESPONSE_BUDGET_DELIBERATE=6144"
if "%AEGIS_RESPONSE_BUDGET_FULL%"=="" set "AEGIS_RESPONSE_BUDGET_FULL=8192"
if "%AEGIS_RESPONSE_BUDGET_MAX%"=="" set "AEGIS_RESPONSE_BUDGET_MAX=12000"
if "%AEGIS_INTEL_LAVA_ENABLED%"=="" set "AEGIS_INTEL_LAVA_ENABLED=0"
if "%AEGIS_INTEL_LAVA_BACKEND%"=="" set "AEGIS_INTEL_LAVA_BACKEND=cpu-simulation"
if "%AEGIS_INTEL_LAVA_WORKSPACE%"=="" set "AEGIS_INTEL_LAVA_WORKSPACE=%CD%\agentic_jobs\lava_neuromorphic"
if "%OLLAMA_KEEP_ALIVE%"=="" set "OLLAMA_KEEP_ALIVE=15m"
if "%OLLAMA_NUM_PARALLEL%"=="" set "OLLAMA_NUM_PARALLEL=2"
if "%OLLAMA_MAX_LOADED_MODELS%"=="" set "OLLAMA_MAX_LOADED_MODELS=3"
if "%OLLAMA_FLASH_ATTENTION%"=="" set "OLLAMA_FLASH_ATTENTION=1"
if "%OLLAMA_KV_CACHE_TYPE%"=="" set "OLLAMA_KV_CACHE_TYPE=q4_0"

REM Remote manifold lane defaults OFF in the local-only blueprint
if "%AEGIS_CLOUD_MANIFOLD_ENABLED%"=="" set "AEGIS_CLOUD_MANIFOLD_ENABLED=0"
if "%AEGIS_CLOUD_MANIFOLD_TRANSPORT%"=="" set "AEGIS_CLOUD_MANIFOLD_TRANSPORT=gcloud"
if "%AEGIS_CLOUD_MANIFOLD_INSTANCE%"=="" set "AEGIS_CLOUD_MANIFOLD_INSTANCE=ai-lean-node"
if "%AEGIS_CLOUD_MANIFOLD_ZONE%"=="" set "AEGIS_CLOUD_MANIFOLD_ZONE=us-west1-b"
if "%AEGIS_CLOUD_MANIFOLD_HOST%"=="" set "AEGIS_CLOUD_MANIFOLD_HOST="
if "%AEGIS_CLOUD_MANIFOLD_USER%"=="" set "AEGIS_CLOUD_MANIFOLD_USER=%USERNAME%"
if "%AEGIS_CLOUD_MANIFOLD_PORT%"=="" set "AEGIS_CLOUD_MANIFOLD_PORT=22"
if "%AEGIS_CLOUD_MANIFOLD_KEY_PATH%"=="" set "AEGIS_CLOUD_MANIFOLD_KEY_PATH=%USERPROFILE%\.ssh\google_compute_engine"
if "%AEGIS_CLOUD_MANIFOLD_PYTHON%"=="" set "AEGIS_CLOUD_MANIFOLD_PYTHON=python3"
if "%AEGIS_CLOUD_MANIFOLD_REMOTE_DIR%"=="" set "AEGIS_CLOUD_MANIFOLD_REMOTE_DIR=/home/%AEGIS_CLOUD_MANIFOLD_USER%/Aegis_Agents"
if "%AEGIS_CLOUD_MANIFOLD_TEMP_DIR%"=="" set "AEGIS_CLOUD_MANIFOLD_TEMP_DIR=/dev/shm/aegis"
if "%AEGIS_CLOUD_MANIFOLD_ALLOW_LOCAL_HANDS%"=="" set "AEGIS_CLOUD_MANIFOLD_ALLOW_LOCAL_HANDS=0"

REM Project ALICE lane defaults to the same local model unless explicitly re-enabled remotely
if "%AEGIS_ALICE_ENABLED%"=="" set "AEGIS_ALICE_ENABLED=0"
if "%AEGIS_ALICE_TRANSPORT%"=="" set "AEGIS_ALICE_TRANSPORT=%AEGIS_CLOUD_MANIFOLD_TRANSPORT%"
if "%AEGIS_ALICE_INSTANCE%"=="" set "AEGIS_ALICE_INSTANCE=%AEGIS_CLOUD_MANIFOLD_INSTANCE%"
if "%AEGIS_ALICE_ZONE%"=="" set "AEGIS_ALICE_ZONE=%AEGIS_CLOUD_MANIFOLD_ZONE%"
if "%AEGIS_ALICE_HOST%"=="" set "AEGIS_ALICE_HOST=%AEGIS_CLOUD_MANIFOLD_HOST%"
if "%AEGIS_ALICE_USER%"=="" set "AEGIS_ALICE_USER=%AEGIS_CLOUD_MANIFOLD_USER%"
if "%AEGIS_ALICE_PORT%"=="" set "AEGIS_ALICE_PORT=%AEGIS_CLOUD_MANIFOLD_PORT%"
if "%AEGIS_ALICE_KEY_PATH%"=="" set "AEGIS_ALICE_KEY_PATH=%AEGIS_CLOUD_MANIFOLD_KEY_PATH%"
if "%AEGIS_ALICE_PYTHON%"=="" set "AEGIS_ALICE_PYTHON=%AEGIS_CLOUD_MANIFOLD_PYTHON%"
if "%AEGIS_ALICE_REMOTE_DIR%"=="" set "AEGIS_ALICE_REMOTE_DIR=%AEGIS_CLOUD_MANIFOLD_REMOTE_DIR%"
if "%AEGIS_ALICE_TEMP_DIR%"=="" set "AEGIS_ALICE_TEMP_DIR=%AEGIS_CLOUD_MANIFOLD_TEMP_DIR%"
if "%AEGIS_ALICE_MODEL%"=="" set "AEGIS_ALICE_MODEL=%AEGIS_LOCAL_PRIMARY_MODEL%"

REM Secondary Xeon lane / swarm worker
if "%AEGIS_XEON_ENABLED%"=="" set "AEGIS_XEON_ENABLED=0"
if "%AEGIS_XEON_HOST%"=="" set "AEGIS_XEON_HOST="
if "%AEGIS_XEON_USER%"=="" set "AEGIS_XEON_USER=%USERNAME%"
if "%AEGIS_XEON_PORT%"=="" set "AEGIS_XEON_PORT=22"
if "%AEGIS_XEON_REMOTE_DIR%"=="" set "AEGIS_XEON_REMOTE_DIR=/home/%AEGIS_XEON_USER%"
if "%AEGIS_XEON_PYTHON%"=="" set "AEGIS_XEON_PYTHON=python3"
if "%AEGIS_XEON_TEMP_DIR%"=="" set "AEGIS_XEON_TEMP_DIR=/dev/shm/aegis"
if "%AEGIS_SSH_EXE%"=="" set "AEGIS_SSH_EXE=C:\Windows\System32\OpenSSH\ssh.exe"
if "%AEGIS_SCP_EXE%"=="" set "AEGIS_SCP_EXE=C:\Windows\System32\OpenSSH\scp.exe"
if "%AEGIS_XEON_KEY_PATH%"=="" set "AEGIS_XEON_KEY_PATH=%USERPROFILE%\.ssh\google_compute_engine"

REM Resolve Python explicitly so elevated launches do not depend on PATH aliases
set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

REM Allow port override when a stale listener is already using 5005
if "%AEGIS_PORT%"=="" set "AEGIS_PORT=5005"
echo [CONFIG] Backend port: %AEGIS_PORT%
echo [CONFIG] Python: %PYTHON_EXE%

REM Clear any stale FastAPI listener that survived a previous launch
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%AEGIS_PORT% .*LISTENING"') do (
    echo [CLEANUP] Stopping stale listener on port %AEGIS_PORT% ^(PID %%P^)
    taskkill /F /PID %%P >nul 2>&1
)

REM Start Ollama with administrator privileges (already have them)
echo [CHECK] Starting Ollama service with admin privileges...
if "%OLLAMA_EXE%"=="" set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
start "" "%OLLAMA_EXE%" serve
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

REM Check if the local blueprint model is available
echo [CHECK] Verifying primary local model...
ollama list | findstr /C:"%AEGIS_LOCAL_PRIMARY_MODEL%" >nul
if errorlevel 1 (
    echo [WARNING] Primary local model not found. Pulling model...
    echo [INFO] This may take a few minutes...
    ollama pull %AEGIS_LOCAL_PRIMARY_MODEL%
) else (
    echo [OK] Primary local model available
)

echo.
echo ================================================================================
echo [LAUNCH] Starting AEGIS Components...
echo ================================================================================
echo.

REM Start FastAPI Backend
echo [1/2] Starting FastAPI Backend Server...
start "AEGIS FastAPI Backend" "%PYTHON_EXE%" -m uvicorn gemini_bridge_api_fast:app --host 0.0.0.0 --port %AEGIS_PORT%

REM Wait for server to start
echo [INFO] Waiting for server initialization...
timeout /t 5 /nobreak >nul

REM Start Cloudflare Tunnel and capture output to log
echo [2/2] Creating Cloudflare Tunnel ^(generating new public URL^)...
if "%CLOUDFLARED_EXE%"=="" set "CLOUDFLARED_EXE=%USERPROFILE%\cloudflared.exe"
if "%AEGIS_TUNNEL_LOG%"=="" set "AEGIS_TUNNEL_LOG=%USERPROFILE%\tunnel.log"
if exist "%AEGIS_TUNNEL_LOG%" del /q "%AEGIS_TUNNEL_LOG%"
start "Cloudflare Tunnel" /MIN cmd /c ""%CLOUDFLARED_EXE%" tunnel --url http://localhost:%AEGIS_PORT% > "%AEGIS_TUNNEL_LOG%" 2>&1"

REM Wait for tunnel to establish
echo [INFO] Waiting for tunnel to establish...
timeout /t 15 /nobreak >nul

REM Extract Cloudflare URL using PowerShell
echo [INFO] Extracting Cloudflare URL...
powershell -Command "$log = Get-Content $env:AEGIS_TUNNEL_LOG -Tail 50 | Select-String 'https://.*\.trycloudflare\.com'; if ($log) { $url = $log.Matches[0].Value; Write-Output $url; $url | Out-File -FilePath \"$env:USERPROFILE\OneDrive\CLOUDFLARE.txt\" -Encoding ASCII; $url | Out-File -FilePath \"$env:USERPROFILE\Desktop\CLOUDFLARE_URL.txt\" -Encoding ASCII; $stamp = Get-Date -Format 'yyyy-MM-dd_HH:mm'; Add-Content -Path \"$env:USERPROFILE\OneDrive\AGENTS.txt\" -Value \"# CLOUD_URL $stamp $url\" }" > temp_url.txt

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
echo http://localhost:%AEGIS_PORT%
echo.
echo [INFO] URL saved to: %USERPROFILE%\OneDrive\CLOUDFLARE.txt
echo [INFO] URL appended to: %USERPROFILE%\OneDrive\AGENTS.txt
echo [INFO] URL also saved to: %USERPROFILE%\Desktop\CLOUDFLARE_URL.txt
echo [INFO] Timescale Memory System active (v2.0)
echo [INFO] Gemma 2B ready for local inference
echo.
echo [CONTROLS]
echo - Keep this window open to maintain the system
echo - Press Ctrl+C to shutdown all components
echo.
echo ================================================================================
echo [STATUS] Kernel Mode: AUTO MANIFOLD-FIRST ^| Xeon Swarm: READY WHEN CONFIGURED ^| Local Hands: ON DEMAND ^| Google Paid Path: OFF
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
