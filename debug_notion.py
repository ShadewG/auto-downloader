#!/usr/bin/env python3
"""
Debug script to inspect Notion database structure and find available cases
"""
import os
import json
from dotenv import load_dotenv
from notion_client import Client

def main():
    load_dotenv()
    
    api_key = os.getenv('NOTION_API_KEY')
    db_id = os.getenv('NOTION_DATABASE_ID')
    
    client = Client(auth=api_key)
    
    print("Notion Database Inspection")
    print("="*60)
    
    # Get database schema
    print("\n1. Fetching database schema...")
    try:
        db = client.databases.retrieve(database_id=db_id)
        properties = db.get('properties', {})
        
        print(f"\nFound {len(properties)} properties:")
        for prop_name, prop_data in properties.items():
            prop_type = prop_data.get('type')
            print(f"  - {prop_name}: {prop_type}")
    except Exception as e:
        print(f"Error fetching database: {e}")
        return
    
    # Query first 5 pages without filters
    print("\n2. Fetching first 5 pages (no filter)...")
    try:
        response = client.databases.query(
            database_id=db_id,
            page_size=5
        )
        
        pages = response.get('results', [])
        print(f"\nFound {len(pages)} pages")
        
        for i, page in enumerate(pages, 1):
            props = page.get('properties', {})
            print(f"\nPage {i}:")
            
            # Print Download Status if exists
            if 'Download Status' in props:
                status = props['Download Status']
                if status.get('type') == 'select':
                    status_value = status.get('select')
                    if status_value:
                        print(f"  Download Status: {status_value.get('name')}")
                    else:
                        print(f"  Download Status: (empty)")
            
            # Print Download Link if exists  
            if 'Download Link' in props:
                link = props['Download Link']
                if link.get('type') == 'url':
                    print(f"  Download Link: {link.get('url')}")
            
            # Print title
            for prop_name, prop_value in props.items():
                if prop_value.get('type') == 'title':
                    title = prop_value.get('title', [])
                    if title:
                        print(f"  Title: {title[0].get('plain_text', '')}")
                    break
    
    except Exception as e:
        print(f"Error querying pages: {e}")
    
    # Try filtering for Ready for Download
    print("\n3. Trying to filter for 'Ready for Download'...")
    try:
        response = client.databases.query(
            database_id=db_id,
            filter={
                "property": "Download Status",
                "select": {
                    "equals": "Ready for Download"
                }
            },
            page_size=5
        )
        
        pages = response.get('results', [])
        print(f"Found {len(pages)} pages with 'Ready for Download' status")
        
    except Exception as e:
        print(f"Error with filter: {e}")

if __name__ == '__main__':
    main()
