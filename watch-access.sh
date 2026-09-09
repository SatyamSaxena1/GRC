#!/bin/bash
# Real-time access log viewer

echo "🔍 Monitoring GRC Access Log"
echo "Press Ctrl+C to stop"
echo ""

if [ ! -f "access.log" ]; then
    echo "⏳ Waiting for access.log to be created..."
fi

tail -f access.log 2>/dev/null | while read line; do
    # Color-code by HTTP method
    if [[ "$line" == *"GET"* ]]; then
        echo -e "\033[36m$line\033[0m"  # Cyan for GET
    elif [[ "$line" == *"POST"* ]]; then
        echo -e "\033[32m$line\033[0m"  # Green for POST
    elif [[ "$line" == *"PATCH"* ]]; then
        echo -e "\033[33m$line\033[0m"  # Yellow for PATCH
    else
        echo "$line"
    fi
done
