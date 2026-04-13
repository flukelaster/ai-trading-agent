# Windows VPS Setup Guide — MT5 Bridge

## 1. Get a Windows VPS
- Vultr Windows Server 2022, 2vCPU / 4GB RAM (~$24/month)
- Or any Windows VPS provider

## 2. RDP to VPS

## 3. Install Python 3.11+
- Download from python.org
- Check "Add to PATH" during install

## 4. Install MetaTrader 5
- Download from your broker
- Login with demo account first
- Ensure MT5 is running and logged in

## 5. Deploy MT5 Bridge
```powershell
git clone <your-repo-url>
cd ai-trading-agent/mt5_bridge
pip install -r requirements.txt
copy .env.example .env
# Edit .env with MT5 credentials and BRIDGE_API_KEY
```

## 6. Run MT5 Bridge
```powershell
# Direct run:
uvicorn main:app --host 0.0.0.0 --port 8001

# With watchdog (recommended):
python watchdog.py
```

## 7. Open Firewall
```powershell
netsh advfirewall firewall add rule name="MT5 Bridge" dir=in action=allow protocol=TCP localport=8001
```

## 8. Test
```bash
curl http://YOUR_VPS_IP:8001/health
```

## 9. Auto-start on Boot (Optional)
Use NSSM to register as Windows service:
```powershell
nssm install MT5Bridge "C:\Python311\python.exe" "C:\ai-trading-agent\mt5_bridge\watchdog.py"
nssm start MT5Bridge
```
