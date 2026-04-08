# setup_watchdog_task.ps1 — Create Windows Task Scheduler task for MT5 Bridge watchdog
# Run as Administrator on Contabo VPS

$BridgeDir = "C:\mt5_bridge"
$PythonExe = "C:\mt5_bridge\venv\Scripts\python.exe"
$WatchdogScript = "C:\mt5_bridge\watchdog.py"
$TaskName = "MT5BridgeWatchdog"

# Create watchdog.py if it doesn't exist
$WatchdogContent = @'
"""
Watchdog — monitors MT5 Bridge process and restarts if it crashes.
"""
import subprocess
import time
import requests
import logging

logging.basicConfig(
    filename=r"C:\mt5_bridge\watchdog.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

BRIDGE_URL = "http://127.0.0.1:8001/health"
BRIDGE_CMD = [r"C:\mt5_bridge\venv\Scripts\python.exe", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
BRIDGE_CWD = r"C:\mt5_bridge"
CHECK_INTERVAL = 30  # seconds
MAX_RESTARTS = 10
RESTART_COOLDOWN = 60  # seconds between restart attempts

restart_count = 0
process = None


def is_healthy():
    try:
        r = requests.get(BRIDGE_URL, timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def start_bridge():
    global process
    logging.info("Starting MT5 Bridge...")
    process = subprocess.Popen(BRIDGE_CMD, cwd=BRIDGE_CWD)
    time.sleep(5)  # Wait for startup
    return process


if __name__ == "__main__":
    logging.info("Watchdog started")
    start_bridge()

    while True:
        time.sleep(CHECK_INTERVAL)

        if not is_healthy():
            restart_count += 1
            logging.warning(f"Bridge unhealthy (attempt {restart_count}/{MAX_RESTARTS})")

            if restart_count > MAX_RESTARTS:
                logging.error("Max restarts exceeded, stopping watchdog")
                break

            # Kill existing process
            if process and process.poll() is None:
                process.kill()
                process.wait()

            time.sleep(RESTART_COOLDOWN)
            start_bridge()
        else:
            restart_count = 0  # Reset on successful health check
'@

if (-not (Test-Path $WatchdogScript)) {
    Set-Content -Path $WatchdogScript -Value $WatchdogContent
    Write-Host "Created watchdog.py at $WatchdogScript"
}

# Remove existing task if it exists
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed existing task: $TaskName"
}

# Create scheduled task that runs at system startup
$action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument $WatchdogScript `
    -WorkingDirectory $BridgeDir

$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365)

$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Monitors MT5 Bridge and restarts if it crashes"

Write-Host "Task '$TaskName' created successfully"
Write-Host "The watchdog will start automatically on system boot"
Write-Host "To start now: Start-ScheduledTask -TaskName '$TaskName'"
