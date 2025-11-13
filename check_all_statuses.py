#!/usr/bin/env python3
"""
Check all case statuses in Notion
"""
import os
import requests
from dotenv import load_dotenv

load_dotenv()

NOTION_API_KEY = os.getenv('NOTION_API_KEY')
NOTION_DATABASE_ID = os.getenv('NOTION_DATABASE_ID')

headers = {
    'Authorization': f'Bearer {NOTION_API_KEY}',
    'Notion-Version': '2022-06-28',
    'Content-Type': 'application/json'
}

# Get all cases
payload = {
    'page_size': 20
}

response = requests.post(
    f'https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query',
    headers=headers,
    json=payload
)

results = response.json().get('results', [])
print(f'\nFound {len(results)} total cases')

# Count by status
status_counts = {}
for page in results:
    props = page['properties']
    status_prop = props.get('Status', {})
    if 'status' in status_prop:
        status = status_prop['status']['name']
    else:
        status = 'No status'

    status_counts[status] = status_counts.get(status, 0) + 1

print('\nCases by status:')
for status, count in sorted(status_counts.items(), key=lambda x: -x[1]):
    print(f'  {status}: {count}')

# Show a few examples from each status
print('\n\nSample cases:')
for page in results[:10]:
    props = page['properties']
    name = props.get('Suspect Name', {}).get('title', [{}])[0].get('plain_text', 'Unknown')
    status_prop = props.get('Status', {})
    if 'status' in status_prop:
        status = status_prop['status']['name']
    else:
        status = 'No status'

    print(f'  {name[:40]:<40} -> {status}')
