#!/usr/bin/env python3
"""Upload cases that have Auto Upload Failed status"""
import sys
sys.path.insert(0, '/root/case-downloader')

import os
from notion_api import NotionCaseClient
from dropbox_client import DropboxClient
from dotenv import load_dotenv
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# Initialize clients
notion_client = NotionCaseClient(
    os.getenv('NOTION_API_KEY'),
    os.getenv('NOTION_DATABASE_ID')
)

dropbox_client = DropboxClient(
    os.getenv('DROPBOX_APP_KEY'),
    os.getenv('DROPBOX_APP_SECRET'),
    os.getenv('DROPBOX_MEMBER_ID')
)

download_path = "/mnt/HC_Volume_103781006/downloads"

# Get cases that need uploading
response = notion_client.client.databases.query(
    database_id=notion_client.database_id,
    filter={
        'property': 'Download Status',
        'select': {'equals': 'Ready For Download'}
    },
    page_size=100
)

results = response.get('results', [])
logger.info(f'Found {len(results)} cases marked "Ready For Download"')

for page in results:
    props = page['properties']

    # Get suspect name
    suspect_field = props.get('Suspect', {})
    if suspect_field.get('type') == 'rich_text':
        rich_text = suspect_field.get('rich_text', [])
        case_name = rich_text[0].get('plain_text', 'Unknown') if rich_text else 'Unknown'
    elif suspect_field.get('type') == 'title':
        title_array = suspect_field.get('title', [])
        case_name = title_array[0].get('plain_text', 'Unknown') if title_array else 'Unknown'
    else:
        case_name = 'Unknown'

    # Check if folder exists locally
    # Try to find the folder with current date first
    from datetime import datetime
    date_str = datetime.now().strftime('%Y-%m-%d')

    possible_folders = [
        os.path.join(download_path, f"{case_name} {date_str}"),
        os.path.join(download_path, f"{case_name} 2025-11-11"),
        os.path.join(download_path, f"{case_name} 2025-11-10"),
    ]

    case_folder = None
    for folder in possible_folders:
        if os.path.exists(folder):
            case_folder = folder
            break

    if not case_folder:
        logger.warning(f"No local folder found for: {case_name}")
        continue

    logger.info(f"\n{'='*80}")
    logger.info(f"Uploading: {case_name}")
    logger.info(f"Local folder: {case_folder}")

    try:
        # Update status to Auto Uploading
        notion_client.update_case_status(page['id'], 'Auto Uploading')

        # Upload to Dropbox
        dropbox_folder = f"/Auto Foia/{os.path.basename(case_folder)}"
        logger.info(f"Uploading to Dropbox: {dropbox_folder}")

        dropbox_client.upload_folder(case_folder, dropbox_folder)
        logger.info(f"✓ Uploaded successfully")

        # Get Dropbox link
        dropbox_link = dropbox_client.get_shared_link(dropbox_folder)

        # Update Notion with link
        notion_client.add_dropbox_link(page['id'], dropbox_link)

        # Update status to Auto Uploaded
        notion_client.update_case_status(page['id'], 'Auto Uploaded')
        logger.info(f"✓ Updated Notion status to Auto Uploaded")

        # Clean up local files
        import shutil
        shutil.rmtree(case_folder)
        logger.info(f"✓ Cleaned up local files")

    except Exception as e:
        logger.error(f"✗ Failed to upload {case_name}: {e}")
        import traceback
        traceback.print_exc()

        # Update status to Auto Upload Failed
        notion_client.update_case_status(page['id'], 'Auto Upload Failed')

logger.info(f"\n{'='*80}")
logger.info("Upload process complete!")
