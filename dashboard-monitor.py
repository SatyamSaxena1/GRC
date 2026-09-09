#!/usr/bin/env python3
"""
GRC Access Dashboard - Real-time monitoring of user activity
Shows what data each user/organization is accessing and when
"""
import requests
import json
import time
from datetime import datetime
from collections import defaultdict
import os
import sys

class GRCDashboard:
    def __init__(self):
        self.orgs = defaultdict(lambda: {'requests': 0, 'last_seen': None, 'endpoints': defaultdict(int), 'ips': set()})
        self.total_requests = 0
        self.start_time = datetime.now()
        
    def get_ngrok_requests(self):
        """Fetch latest requests from ngrok"""
        try:
            response = requests.get('http://localhost:4040/api/requests/http', timeout=5)
            data = response.json()
            return data.get('requests', [])
        except:
            return []
    
    def get_access_logs(self):
        """Read local access.log file"""
        logs = []
        if os.path.exists("access.log"):
            try:
                with open("access.log", "r") as f:
                    logs = f.readlines()[-100:]  # Last 100 lines
            except:
                pass
        return logs
    
    def extract_org_id(self, auth_str):
        """Extract org ID from auth header"""
        if auth_str and ':' in auth_str:
            parts = auth_str.split(':')
            return f"{parts[0]}:{parts[1][:8]}..." if len(parts) > 1 else auth_str
        return auth_str
    
    def categorize_endpoint(self, uri):
        """Categorize API endpoint"""
        if '/control' in uri:
            return '📋 Controls'
        elif '/evidence' in uri:
            return '📄 Evidence'
        elif '/gap' in uri:
            return '⚠️ Gaps'
        elif '/task' in uri:
            return '✓ Tasks'
        elif '/notification' in uri:
            return '📢 Notifications'
        elif '/analytics' in uri or '/dashboard' in uri:
            return '📊 Analytics'
        elif '/activity' in uri:
            return '📝 Activity'
        elif '/admin' in uri or '/firm' in uri:
            return '⚙️ Admin'
        elif '/glossary' in uri:
            return '📚 Glossary'
        else:
            return '❓ Other'
    
    def update_from_logs(self):
        """Parse access.log and update dashboard"""
        logs = self.get_access_logs()
        
        for line in logs:
            if '|' not in line:
                continue
            
            try:
                parts = line.split('|')
                if len(parts) < 5:
                    continue
                
                timestamp = parts[0].strip()
                method = parts[1].strip()
                path = parts[2].strip()
                status = parts[3].strip()
                auth_part = parts[4].strip() if len(parts) > 4 else ""
                ip_part = parts[5].strip() if len(parts) > 5 else ""
                
                # Extract auth and org
                auth_info = auth_part.split(':', 1)[1] if ':' in auth_part else 'N/A'
                org_id = auth_info[:8] + '...' if len(auth_info) > 8 else auth_info
                
                ip = ip_part.split(':', 1)[1].strip() if ':' in ip_part else 'unknown'
                
                if org_id not in self.orgs:
                    self.orgs[org_id] = {'requests': 0, 'last_seen': None, 'endpoints': defaultdict(int), 'ips': set()}
                
                org = self.orgs[org_id]
                org['requests'] += 1
                org['last_seen'] = timestamp
                
                category = self.categorize_endpoint(path)
                org['endpoints'][category] += 1
                org['ips'].add(ip)
                
                self.total_requests += 1
            except Exception as e:
                pass
    
    def clear_screen(self):
        """Clear terminal"""
        os.system('clear' if os.name != 'nt' else 'cls')
    
    def print_dashboard(self):
        """Print formatted dashboard"""
        self.clear_screen()
        
        print("\n" + "="*100)
        print("🔍 GRC ACCESS DASHBOARD - Real-time User Activity Monitor".center(100))
        print("="*100)
        print(f"Started: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Current: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Total Requests: {self.total_requests} | Organizations: {len(self.orgs)}")
        print("-"*100)
        
        if not self.orgs:
            print("⏳ Waiting for requests...")
            return
        
        # Sort by request count
        sorted_orgs = sorted(self.orgs.items(), key=lambda x: x[1]['requests'], reverse=True)
        
        for org_id, data in sorted_orgs:
            print(f"\n📊 Organization: {org_id}")
            print(f"   Requests: {data['requests']:>4} | Last Seen: {data['last_seen']} | IPs: {', '.join(sorted(data['ips']))}")
            print(f"   Access by Category:")
            
            # Sort endpoints by access count
            endpoints = sorted(data['endpoints'].items(), key=lambda x: x[1], reverse=True)
            for category, count in endpoints:
                print(f"      {category:.<40} {count:>3} requests")
        
        print("\n" + "="*100)
        print("Press Ctrl+C to stop monitoring")
        print("="*100 + "\n")

def main():
    dashboard = GRCDashboard()
    
    print("🚀 Starting GRC Access Dashboard...")
    print("Reading access logs and monitoring real-time activity\n")
    
    try:
        while True:
            dashboard.update_from_logs()
            dashboard.print_dashboard()
            time.sleep(3)  # Refresh every 3 seconds
    except KeyboardInterrupt:
        print("\n\n⛔ Dashboard stopped")
        dashboard.print_dashboard()
        print("\nFinal Statistics:")
        print(f"Total requests captured: {dashboard.total_requests}")
        print(f"Organizations: {len(dashboard.orgs)}")
        print(f"Session duration: {datetime.now() - dashboard.start_time}")

if __name__ == '__main__':
    main()
