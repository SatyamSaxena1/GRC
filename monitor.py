#!/usr/bin/env python3
"""
Real-time access monitor for ngrok tunnel
Tracks user activity, requests, and data access
"""
import requests
import json
import time
from datetime import datetime
from collections import defaultdict

class AccessMonitor:
    def __init__(self):
        self.last_request_id = None
        self.activity_log = []
        self.unique_ips = set()
        self.endpoint_counts = defaultdict(int)
        
    def get_ngrok_requests(self):
        """Fetch latest requests from ngrok API"""
        try:
            response = requests.get('http://localhost:4040/api/requests/http')
            data = response.json()
            return data.get('requests', [])
        except Exception as e:
            print(f"Error fetching ngrok data: {e}")
            return []
    
    def extract_auth_info(self, request_headers):
        """Extract authorization and user info from headers"""
        auth = request_headers.get('Authorization', ['N/A'])[0] if request_headers.get('Authorization') else 'N/A'
        referer = request_headers.get('Referer', ['N/A'])[0] if request_headers.get('Referer') else 'N/A'
        return auth, referer
    
    def parse_request(self, req):
        """Parse and categorize a request"""
        uri = req.get('uri', '')
        method = req.get('request', {}).get('method', 'GET')
        remote_addr = req.get('remote_addr', 'unknown')
        headers = req.get('request', {}).get('headers', {})
        start_time = req.get('start', '')
        auth, referer = self.extract_auth_info(headers)
        
        # Categorize the request
        if '/api/' in uri or uri.startswith('/admin/') or uri.startswith('/analytics/'):
            request_type = 'API'
            category = self._categorize_endpoint(uri)
        elif uri.startswith('/src/') or uri.startswith('/node_modules/'):
            request_type = 'ASSET'
            category = 'Frontend'
        else:
            request_type = 'PAGE'
            category = self._categorize_endpoint(uri)
        
        return {
            'id': req.get('id', ''),
            'time': start_time,
            'method': method,
            'uri': uri,
            'type': request_type,
            'category': category,
            'ip': remote_addr,
            'auth': auth,
            'referer': referer,
            'duration_ms': req.get('duration', 0) / 1000
        }
    
    def _categorize_endpoint(self, uri):
        """Categorize endpoint by function"""
        if 'control' in uri:
            return 'Controls Management'
        elif 'evidence' in uri or 'artefact' in uri:
            return 'Evidence Handling'
        elif 'gap' in uri:
            return 'Gaps/Remediation'
        elif 'task' in uri:
            return 'Task Management'
        elif 'notification' in uri or 'activity' in uri:
            return 'Activity/Notifications'
        elif 'dashboard' in uri or 'analytics' in uri or 'readiness' in uri:
            return 'Analytics/Dashboard'
        elif 'admin' in uri or 'firm' in uri:
            return 'Admin/Firm'
        elif 'glossary' in uri:
            return 'Reference'
        else:
            return 'Other'
    
    def monitor_once(self):
        """Check for new activity once"""
        requests_data = self.get_ngrok_requests()
        new_requests = []
        
        for req in requests_data:
            req_id = req.get('id', '')
            if req_id == self.last_request_id:
                break
            parsed = self.parse_request(req)
            new_requests.append(parsed)
            self.unique_ips.add(parsed['ip'])
            self.endpoint_counts[parsed['category']] += 1
        
        if new_requests:
            self.last_request_id = requests_data[0].get('id') if requests_data else None
            
        return new_requests
    
    def print_summary(self):
        """Print current session summary"""
        print("\n" + "="*80)
        print(f"NGROK MONITOR SUMMARY - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*80)
        print(f"✓ Unique IPs accessing: {len(self.unique_ips)}")
        print(f"  {list(self.unique_ips)}\n")
        
        print("Activity by Category:")
        for category, count in sorted(self.endpoint_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"  {category:.<40} {count:>3} requests")
        
        print("="*80 + "\n")

def main():
    monitor = AccessMonitor()
    print("🔍 Starting GRC Access Monitor...")
    print("Tracking all requests via ngrok tunnel\n")
    
    request_buffer = []
    
    try:
        while True:
            new_reqs = monitor.monitor_once()
            
            for req in new_reqs:
                # Skip asset requests in display for clarity
                if req['type'] != 'ASSET':
                    request_buffer.append(req)
                    
                    # Print immediate notification
                    timestamp = req['time'].split('T')[1][:8] if 'T' in req['time'] else '??:??:??'
                    org_id = req['auth'].split(':')[1][:8] + '...' if ':' in req['auth'] else 'N/A'
                    
                    icon = '📊' if 'analytics' in req['uri'].lower() else \
                           '📋' if 'control' in req['uri'].lower() else \
                           '📄' if 'evidence' in req['uri'].lower() else \
                           '⚠️' if 'gap' in req['uri'].lower() else \
                           '✓' if 'task' in req['uri'].lower() else \
                           '📢' if 'notification' in req['uri'].lower() else \
                           '📊'
                    
                    print(f"[{timestamp}] {icon} {req['category']:.<30} | {req['method']:>4} {req['uri'][:40]:.<40} | Org: {org_id}")
            
            # Print summary every 20 API requests
            if len(request_buffer) % 20 == 0 and request_buffer:
                monitor.print_summary()
            
            time.sleep(2)  # Poll every 2 seconds
            
    except KeyboardInterrupt:
        print("\n\n⛔ Monitor stopped")
        monitor.print_summary()
        if request_buffer:
            print(f"\nCaptured {len(request_buffer)} API requests during this session")

if __name__ == '__main__':
    main()
