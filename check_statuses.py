#!/usr/bin/env python3
import os
from dotenv import load_dotenv
from notion_client import Client

load_dotenv()

api_key = os.getenv("NOTION_API_KEY")
db_id = os.getenv("NOTION_DATABASE_ID")

client = Client(auth=api_key)

print("Checking Download Status values...")

response = client.databases.query(
    database_id=db_id,
    page_size=100
)

status_counts = {}
pages_with_links = []

for page in response.get("results", []):
    props = page.get("properties", {})
    
    status_prop = props.get("Download Status", {})
    if status_prop.get("type") == "select":
        status_value = status_prop.get("select")
        if status_value:
            status_name = status_value.get("name")
        else:
            status_name = "(empty)"
    else:
        status_name = "(no field)"
    
    status_counts[status_name] = status_counts.get(status_name, 0) + 1
    
    link_prop = props.get("Download Link", {})
    has_link = link_prop.get("url") is not None
    
    if status_name not in ["(empty)", "(no field)"] and has_link:
        title = ""
        for prop_name, prop_value in props.items():
            if prop_value.get("type") == "title":
                title_array = prop_value.get("title", [])
                if title_array:
                    title = title_array[0].get("plain_text", "")
                break
        
        pages_with_links.append({
            "status": status_name,
            "title": title,
            "link": link_prop.get("url")
        })

print("\nStatus counts:")
for status, count in sorted(status_counts.items(), key=lambda x: x[1], reverse=True):
    print(f"  {status}: {count}")

print(f"\nPages with status AND link: {len(pages_with_links)}")
for p in pages_with_links[:10]:
    print(f"\n  Status: {p[\"status\"]}")
    print(f"  Title: {p[\"title\"][:50]}")
