# GRC Access Monitoring - Real-Time User Activity

## 🚀 Setup Complete

Enhanced access logging and real-time monitoring is now enabled.

### What's Running:

1. **Enhanced Backend Logging** ✅
   - Every request logs auth token, IP, path, and timestamp
   - Logs written to: `access.log` (local file)
   - Also logs to console with `[INFO] request method=...`

2. **Real-Time Monitors** ✅
   - `monitor.py` - ngrok tunnel activity tracker
   - `dashboard-monitor.py` - Access dashboard with org/user breakdown
   - Both run in background continuously

3. **Log Files**
   - `access.log` - Raw access log (all requests with auth/IP/path)
   - `backend.log` - Backend stderr/stdout
   - `ngrok.log` - ngrok tunnel events

### How to View Activity:

#### Option 1: Real-Time Dashboard (Recommended)
```bash
python3 /d/GRC/dashboard-monitor.py
```
Shows:
- By-organization request summary
- Last access time per org
- What data each org is accessing
- Auto-refreshes every 3 seconds

#### Option 2: Access Log (Raw)
```bash
tail -f access.log
```
Shows every request with format:
```
2026-09-09T13:20:57 | GET    | /notifications                                 | Status: 200 | Auth: org:80052888...  | IP: 2401:4900:1c83:66d4:6949:d793:e9d:1c11
```

#### Option 3: Color-Coded Log Viewer
```bash
./watch-access.sh
```
Same as access log but with color coding:
- Cyan = GET requests
- Green = POST requests  
- Yellow = PATCH requests

#### Option 4: Backend Console
```bash
tail -f backend.log
```
Shows FastAPI logs with request details.

### What to Watch For:

👀 **Key Data Access Patterns:**
- `/controls` - Viewing control requirements
- `/evidence` - Uploading/viewing evidence
- `/gaps` - Checking compliance gaps
- `/tasks` - Managing remediation tasks
- `/analytics/dashboard` - Viewing compliance metrics
- `/activity` - Checking audit trail
- `/admin/*` - Administrative functions (setup, assignments)

🔐 **Auth Header Meanings:**
- `org:XXXXXXXX-...` = Organization user accessing their own data
- `auditor:XXXXXXXX-...` = Audit firm auditor (has access to client data)
- `firm:XXXXXXXX-...` = Audit firm admin
- `user:XXXXXXXX-...` = Regular user

⚠️ **IP Address to Watch:**
- Remote: `2401:4900:1c83:66d4:6949:d793:e9d:1c11`
- This is the IPv6 address accessing via ngrok

### Current Session:

**Organization ID:** `80052888-d6a6-4bf9-a1cb-37f9ddddeded`
**Remote IP:** `2401:4900:1c83:66d4:6949:d793:e9d:1c11`
**Browser:** Firefox 148.0 on Windows 10
**Session Start:** 2026-09-09 13:16:43 IST

### Security Notes:

1. ⚠️ Auth tokens are logged - treat `access.log` as confidential
2. 🔒 All API endpoints require valid authorization header
3. 🌐 ngrok creates a public tunnel - anyone with the URL can access
4. 📊 Real-time monitoring helps catch unauthorized access

### Database Query (Advanced):

To see who accessed what data, query the audit trail:
```bash
curl -H "Authorization: org:YOUR_ORG_ID" http://localhost:8000/activity
```

---

**Stop monitoring:** Press Ctrl+C in any monitoring window
**View logs later:** `tail -n 1000 access.log` for last 1000 requests
