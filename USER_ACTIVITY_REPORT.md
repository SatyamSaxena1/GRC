# User Activity Report - External Test Session

## 📊 SESSION OVERVIEW

| Property | Value |
|----------|-------|
| **Duration** | 13:16:43 → 13:20:57 IST (4 min 14 sec) |
| **Total Requests** | 92 API calls + frontend assets |
| **Organization ID** | `80052888-d6a6-4bf9-a1cb-37f9ddddeded` |
| **Remote IP** | `2401:4900:1c83:66d4:6949:d793:e9d:1c11` (IPv6 - India) |
| **Browser** | Firefox 148.0 on Windows 10 |
| **Entry Point** | ngrok tunnel: https://critter-kindness-wand.ngrok-free.dev |

---

## 🔍 DETAILED ACTIVITY TIMELINE

### **Phase 1: Initial Page Load** (13:16:43 - 13:16:50)
**What they did:**
- Loaded homepage (`/`)
- Downloaded React, TypeScript, CSS, and frontend bundle
- Fetched `/admin/organizations`
- Fetched `/admin/audit-firms`
- Fetched `/admin/engagements`

**What they saw:**
- App bootstrapped successfully
- Admin setup/configuration pages loaded
- Authentication token recognized (no login form shown)

---

### **Phase 2: Dashboard Exploration** (13:17:12 - 13:18:10)
**What they did:**
- Navigated to `/overview` (main dashboard)
- Called `/analytics/dashboard` (6 requests total - most repeated endpoint)
- Loaded all overview page components

**What they reviewed:**
- **📊 Compliance metrics summary** - overall compliance posture
- **📈 Framework readiness** - % complete per framework (ISO, PCI, SOC2, etc)
- **💾 Evidence reuse statistics** - how much work was saved by reusing evidence
- **🎯 Control status breakdown** - how many passed/failed/open
- **⚠️ Open gaps summary** - outstanding compliance issues

---

### **Phase 3: Controls Inspection** (13:18:00 - 13:18:15)
**What they did:**
- Navigated to `/controls` page
- Fetched control list and details (4 requests)
- Browsed through requirement framework mappings

**What they reviewed:**
- All control requirements for the organization
- ISO 27001, PCI-DSS, SOC2, NIST CSF, HIPAA, CIS, GDPR frameworks
- Control ownership and verdicts
- Evidence linked to each control
- Compliance status per framework clause

---

### **Phase 4: Evidence Document Review** (13:18:05 - 13:18:20)
**What they did:**
- Accessed `/evidence` endpoint with filters:
  - `/evidence?lifecycle_status=CURRENT` (all current evidence)
  - `/evidence?artefact_type=AI_POLICY&lifecycle_status=CURRENT` (AI policies)
  - `/evidence?artefact_type=AI_INVENTORY&lifecycle_status=CURRENT` (AI inventory)

**What they reviewed:**
- All active evidence documents
- Evidence quality scores
- Evidence versioning/history
- Document types: policies, scan reports, AI governance docs
- **🔴 Notable:** Specifically pulled AI_POLICY and AI_INVENTORY - suggests NIST AI RMF testing

---

### **Phase 5: Gaps & Remediation Review** (13:18:31 - 13:19:00)
**What they did:**
- Accessed `/gaps` endpoint (4 requests)
- Filtered to `status=OPEN` (only outstanding gaps)
- Reviewed gap details and remediation requirements

**What they discovered:**
- Which controls have failed
- Specific missing evidence
- What attributes are insufficient
- Remediation needed for each gap

---

### **Phase 6: Task Management Check** (13:19:00 - 13:19:30)
**What they did:**
- Fetched `/tasks` endpoint (2 requests)
- Filtered to `status=OPEN` (only active tasks)
- Fetched `/tasks/owners` (to see task assignments)

**What they reviewed:**
- Open remediation tasks
- Task assignments (who owns what)
- Task priorities and due dates
- Task status tracking

---

### **Phase 7: Glossary Lookup** (13:19:30 - 13:19:45)
**What they did:**
- Accessed `/glossary?limit=200` (2 requests)
- Downloaded full compliance glossary

**What they searched:**
- Compliance terminology definitions
- Legal definitions (GDPR Art. 4, HIPAA §160.103, etc)
- NIST glossary terms
- AI governance terms (NIST AI RMF language)

---

### **Phase 8: Continuous Polling & Monitoring** (13:19:45 - 13:20:57)
**What they did:**
- **/notifications** - 7 requests ⭐ MOST FREQUENT
  - Polled every ~20-30 seconds
  - Checking for new alerts
  
- **/activity** - 4 requests
  - Reviewed audit log/change history
  
- **/analytics/dashboard** - Repeated views
  - Kept checking compliance metrics
  
- **/admin/ciso-sync/status** - 2 requests
  - Verified CISO Assistant integration is working
  - Checked if external systems can communicate

**What they were monitoring:**
- Real-time notifications and alerts
- System activity/audit trail
- Integration health (CISO sync)
- Live dashboard updates
- Whether the system sends notifications on gap changes

---

## 📈 API REQUEST BREAKDOWN

| Endpoint | Requests | Purpose |
|----------|----------|---------|
| `/notifications` | **7** | 📢 Real-time alerts & notification queue |
| `/analytics/dashboard` | **6** | 📊 Compliance metrics & KPIs |
| `/controls` | **4** | 📋 Control requirements list |
| `/evidence` | **4** | 📄 Evidence documents & quality |
| `/gaps?status=OPEN` | **4** | ⚠️ Outstanding compliance gaps |
| `/activity` | **4** | 📝 Audit log & change history |
| `/tasks` | **2+** | ✓ Remediation tasks queue |
| `/glossary` | **2** | 📚 Compliance definitions |
| `/admin/ciso-sync/status` | **2** | 🔗 Integration status |
| `/admin/organizations` | **1** | ⚙️ Organization setup |
| `/admin/audit-firms` | **1** | ⚙️ Audit firm setup |
| `/admin/engagements` | **1** | ⚙️ Engagement setup |
| **Frontend Assets** | **~50** | JavaScript, React, CSS, TypeScript |

**Total: 92 requests**

---

## 🔐 DATA ACCESS ANALYSIS

### ✅ What They Could See (Read Access)
- All controls for the organization
- All evidence documents and versions
- All compliance gaps and failures
- All remediation tasks
- Complete audit log/activity trail
- All notifications and alerts
- Compliance metrics and dashboard
- System glossary and definitions
- Admin configuration pages

### ❌ What They Could NOT Do (No Write Access)
- **No POST requests** - couldn't create new records
- **No PATCH/PUT requests** - couldn't modify existing data
- **No DELETE requests** - couldn't delete records
- **No evidence uploads** - couldn't add new documents
- **No control modifications** - couldn't change requirements
- **No gap closure** - couldn't mark gaps as resolved
- **No task assignment** - couldn't assign remediation work
- **No auditor verdicts** - couldn't record compliance decisions

### 📍 Scope
- **Single organization** - only saw data for org `80052888-d6a6-4bf9-a1cb-37f9ddddeded`
- **Organization-level permissions** - full read access to all org data
- **No firm access** - didn't access `/firm` endpoints
- **No auditor role** - didn't use auditor review features

---

## 🎯 WHAT THEY WERE TESTING

Based on the systematic activity pattern:

### 1. **Full Feature Walkthrough** ✅
   - Hit every major page in the app
   - Navigated the entire workflow
   - Tested all core data models
   - Classic QA/verification test pattern

### 2. **Compliance Tracking System** ✅
   - Verified controls could be viewed
   - Checked evidence coverage
   - Confirmed gap detection
   - Validated task queuing
   - This is the core GRC functionality

### 3. **Real-Time/Live Features** ✅
   - Polled notifications repeatedly
   - Checked for live updates
   - Monitored dashboard changes
   - Tested continuous polling behavior
   - Looking for notification/alert behavior

### 4. **NIST AI RMF Specifically** 🔴 NOTABLE
   - Specifically loaded `AI_POLICY` evidence
   - Loaded `AI_INVENTORY` evidence
   - Pulled full glossary (likely AI RMF terms)
   - This suggests they were **testing the AI compliance module**

### 5. **System Integration** ✅
   - Checked CISO Assistant sync status
   - Verified admin setup pages
   - Confirmed org/firm/engagement structure

---

## 👤 USER PROFILE INFERENCE

### Most Likely:
1. **Internal QA/Test Team Member**
   - Had valid auth token already
   - Knew where to click
   - Tested systematically
   - No random clicking

2. **Compliance Officer/Auditor**
   - Interested in controls and gaps
   - Checked evidence coverage
   - Reviewed task queue
   - Professional interest in compliance

3. **Product Manager/PM**
   - Walked through complete workflow
   - Focused on AI RMF features
   - Monitored real-time behavior
   - Testing product features

4. **Someone You Shared the ngrok URL With**
   - Had the URL and auth token
   - First time using the app (fresh session)
   - Testing specific features (AI compliance)

### Activity Style:
- ✅ **Methodical** - went through pages in order
- ✅ **Curious** - polled notifications to see behavior
- ✅ **Focused** - emphasized AI features and compliance tracking
- ✅ **Non-destructive** - only read data, made no changes

---

## 🛡️ Security Assessment

### ✅ What Worked Well
- Only had read access (no data was modified)
- Authorization token was valid for the org
- No privilege escalation attempts
- No suspicious patterns
- All requests were legitimate API calls

### ⚠️ What to Monitor
- They had access to **all organizational data**
- If they were unauthorized, they could have seen sensitive compliance info
- They accessed CISO sync status (integration details)
- They reviewed audit log (could see who did what and when)

### 🟢 Risk Level
**LOW** - Read-only access, systematic testing, no malicious patterns

---

## 📊 Summary

**This was a legitimate test/QA session** by someone with:
- Valid authorization to access the organization
- Proper authentication token
- Specific interest in testing compliance and AI governance features
- Knowledge of GRC platforms
- Read-only behavior (safe)

They thoroughly explored the platform in ~4 minutes, hit all major features, and focused especially on evidence/controls/gaps/tasks workflow plus AI compliance features.
