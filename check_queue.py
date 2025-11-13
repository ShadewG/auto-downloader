import os
import sys
from notion_api import NotionCaseClient

client = NotionCaseClient(
    os.environ.get("NOTION_API_KEY"),
    os.environ.get("NOTION_DATABASE_ID")
)

response = client.client.databases.query(
    database_id=client.database_id,
    page_size=100
)

status_counts = {}
for page in response.get("results", []):
    props = page["properties"]
    status_prop = props.get("Download Status", {})
    if "select" in status_prop and status_prop["select"]:
        status = status_prop["select"]["name"]
    else:
        status = "No status"
    status_counts[status] = status_counts.get(status, 0) + 1

print("Current Queue Status:")
print("=" * 60)
for status, count in sorted(status_counts.items(), key=lambda x: -x[1]):
    print(f"{status:30} {count:>3} cases")
print("=" * 60)
print(f"Total: {sum(status_counts.values())} cases")

