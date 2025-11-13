#!/usr/bin/env python3
"""
Reset failed cases back to Auto Ready for testing
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

# Get failed cases
payload = {
    'filter': {
        'property': 'Status',
        'status': {'equals': 'Auto Download Failed'}
    },
    'page_size': 10
}

response = requests.post(
    f'https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query',
    headers=headers,
    json=payload
)

results = response.json().get('results', [])
print(f'\nFound {len(results)} failed cases:')

for i, page in enumerate(results[:5], 1):
    props = page['properties']
    name = props.get('Suspect Name', {}).get('title', [{}])[0].get('plain_text', 'Unknown')
    print(f'{i}. {name} (ID: {page["id"][:8]}...)')

# Reset first 3 cases to Auto Ready
print(f'\nResetting first 3 cases to Auto Ready...')

for i, page in enumerate(results[:3], 1):
    page_id = page['id']
    props = page['properties']
    name = props.get('Suspect Name', {}).get('title', [{}])[0].get('plain_text', 'Unknown')

    # Update status to Auto Ready
    update_payload = {
        'properties': {
            'Status': {
                'status': {'name': 'Auto Ready'}
            }
        }
    }

    update_response = requests.patch(
        f'https://api.notion.com/v1/pages/{page_id}',
        headers=headers,
        json=update_payload
    )

    if update_response.status_code == 200:
        print(f'✓ Reset {name} to Auto Ready')
    else:
        print(f'✗ Failed to reset {name}: {update_response.text}')

print('\nDone! Cases ready for testing.')
