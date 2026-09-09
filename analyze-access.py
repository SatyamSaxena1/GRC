#!/usr/bin/env python3
"""
Quick analyzer for access patterns - shows what data is being accessed and when
"""
import os
from collections import defaultdict
from datetime import datetime

def analyze_access_log():
    """Analyze access.log and show key patterns"""
    
    if not os.path.exists("access.log"):
        print("❌ No access.log found yet. Waiting for first request...")
        return
    
    orgs = defaultdict(lambda: {'count': 0, 'endpoints': defaultdict(int), 'first': None, 'last': None})
    
    with open("access.log", "r") as f:
        lines = f.readlines()
    
    print(f"\n{'='*100}")
    print(f"ACCESS LOG ANALYSIS - Last {len(lines)} requests")
    print(f"{'='*100}\n")
    
    for line in lines:
        if '|' not in line:
            continue
        
        parts = line.split('|')
        if len(parts) < 5:
            continue
        
        try:
            timestamp = parts[0].strip()
            method = parts[1].strip()
            path = parts[2].strip()
            status = parts[3].strip()
            auth_part = parts[4].strip() if len(parts) > 4 else ""
            
            # Extract auth and org
            auth_info = auth_part.split(':', 1)[1] if ':' in auth_part else 'N/A'
            org_id = auth_info[:8] + '...' if len(auth_info) > 8 else auth_info
            
            org = orgs[org_id]
            org['count'] += 1
            
            # Extract endpoint category
            if '/control' in path:
                endpoint = 'Controls'
            elif '/evidence' in path:
                endpoint = 'Evidence'
            elif '/gap' in path:
                endpoint = 'Gaps'
            elif '/task' in path:
                endpoint = 'Tasks'
            elif '/notification' in path:
                endpoint = 'Notifications'
            elif '/analytics' in path or '/dashboard' in path:
                endpoint = 'Analytics'
            elif '/activity' in path:
                endpoint = 'Activity'
            elif '/admin' in path:
                endpoint = 'Admin'
            else:
                endpoint = 'Other'
            
            org['endpoints'][endpoint] += 1
            
            if org['first'] is None:
                org['first'] = timestamp
            org['last'] = timestamp
            
        except:
            pass
    
    # Print summary
    for org_id, data in sorted(orgs.items(), key=lambda x: x[1]['count'], reverse=True):
        print(f"📊 Organization: {org_id}")
        print(f"   Total Requests: {data['count']}")
        print(f"   First Access:   {data['first']}")
        print(f"   Last Access:    {data['last']}")
        print(f"   Data Accessed:")
        
        for endpoint, count in sorted(data['endpoints'].items(), key=lambda x: x[1], reverse=True):
            bar = "█" * (count // 2) if count > 0 else ""
            print(f"      {endpoint:.<20} {count:>3} requests {bar}")
        print()
    
    print(f"{'='*100}")
    print(f"Total unique organizations: {len(orgs)}")
    print(f"Total requests logged: {len(lines)}")
    print(f"{'='*100}\n")

if __name__ == '__main__':
    analyze_access_log()
