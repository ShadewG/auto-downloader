#!/usr/bin/env python3
"""
Auto Upload Monitor - Monitors completed Skyvern workflows and auto-uploads files
Runs alongside main.py to catch manual workflow runs and auto-upload their files
"""

import os
import sys
import time
import json
import glob
import shutil
import requests
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

from dropbox_uploader import upload_to_dropbox
from notion_api import NotionCaseClient as NotionAPI

# Load environment variables
load_dotenv()

# Configuration
SKYVERN_API_BASE = "http://5.161.210.79:8000/api/v1"
SKYVERN_API_TOKEN = os.getenv('SKYVERN_API_KEY', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjQ5MDc5MzY4NDcsInN1YiI6Im9fNDYwODIyNzA2MTQ3NzI4MTE4In0.a81nQ5EZV5xcE942hWfzkU-3Z7Kwqc31ypgahKKithI')
DOWNLOAD_BASE_PATH = "/mnt/HC_Volume_103781006/skyvern/downloads"
FINAL_BASE_PATH = "/mnt/HC_Volume_103781006/evidence_files"
PROCESSED_WORKFLOWS_FILE = "/tmp/processed_workflows.json"
POLL_INTERVAL = 60  # Check every 60 seconds

# Notion configuration
NOTION_API_KEY = os.getenv('NOTION_API_KEY')
NOTION_DATABASE_ID = os.getenv('NOTION_DATABASE_ID')
notion = NotionAPI(NOTION_API_KEY, NOTION_DATABASE_ID) if NOTION_API_KEY else None


def load_processed_workflows():
    """Load set of already processed workflow run IDs"""
    if os.path.exists(PROCESSED_WORKFLOWS_FILE):
        with open(PROCESSED_WORKFLOWS_FILE, 'r') as f:
            return set(json.load(f))
    return set()


def save_processed_workflow(workflow_run_id):
    """Mark a workflow as processed"""
    processed = load_processed_workflows()
    processed.add(workflow_run_id)
    with open(PROCESSED_WORKFLOWS_FILE, 'w') as f:
        json.dump(list(processed), f)


def get_completed_workflows():
    """Get recently completed workflows from Skyvern"""
    headers = {
        "Content-Type": "application/json",
        "x-api-key": SKYVERN_API_TOKEN
    }

    try:
        # Get recent workflow runs (last 100)
        print("Querying Skyvern API for completed workflows (this may take a while)...")
        response = requests.get(
            f"{SKYVERN_API_BASE}/workflows/runs?page=1&page_size=100",
            headers=headers,
            timeout=None  # No timeout - wait as long as needed
        )

        if response.status_code != 200:
            print(f"❌ Failed to get workflows: {response.status_code}")
            return []

        runs = response.json()

        # Filter for completed runs
        completed = [
            run for run in runs
            if run.get('status') == 'completed'
        ]

        return completed

    except Exception as e:
        print(f"❌ Error getting workflows: {e}")
        return []


def process_workflow_downloads(workflow_run_id, suspect_name=None):
    """
    Process downloads from a completed workflow
    Uploads directly from downloads directory and deletes after successful upload

    Args:
        workflow_run_id: The workflow run ID
        suspect_name: Optional suspect name (if None, uses workflow_run_id)

    Returns:
        tuple: (success: bool, file_count: int)
    """
    print(f"\n{'='*80}")
    print(f"PROCESSING WORKFLOW DOWNLOADS: {workflow_run_id}")
    print(f"{'='*80}")

    # Check if files exist
    source_dir = os.path.join(DOWNLOAD_BASE_PATH, workflow_run_id)

    if not os.path.exists(source_dir):
        print(f"⚠️  No download directory found: {source_dir}")
        return False, 0

    # Get all files
    all_files = glob.glob(os.path.join(source_dir, '*'))
    files = [f for f in all_files if os.path.isfile(f)]

    if not files:
        print(f"⚠️  No files found in {source_dir}")
        return False, 0

    print(f"Found {len(files)} file(s) to process")
    print(f"⚠️  DISK SPACE OPTIMIZATION: Upload direct from downloads, delete after upload")

    # Use suspect name or workflow ID
    folder_name = suspect_name or workflow_run_id

    # Process each file
    success_count = 0
    for i, file_path in enumerate(files, 1):
        filename = os.path.basename(file_path)
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)

        print(f"\n[{i}/{len(files)}] {filename} ({file_size_mb:.1f} MB)")

        try:
            # Upload directly from downloads directory
            if upload_to_dropbox(folder_name, file_path):
                success_count += 1
                print(f"  ✅ Uploaded to Dropbox")

                # Delete file after successful upload to free space
                try:
                    os.remove(file_path)
                    print(f"  ✅ Deleted local file (freed {file_size_mb:.1f} MB)")
                except Exception as e:
                    print(f"  ⚠️  Could not delete file: {e}")
            else:
                print(f"  ❌ Failed to upload to Dropbox")

        except Exception as e:
            print(f"  ❌ Error: {e}")

    print(f"\nSuccessfully processed: {success_count}/{len(files)} files")

    # Try to remove empty directory
    try:
        if not os.listdir(source_dir):
            os.rmdir(source_dir)
            print(f"✅ Removed empty directory: {source_dir}")
    except Exception as e:
        print(f"⚠️  Could not remove directory: {e}")

    return success_count > 0, success_count


def main():
    """Main monitoring loop"""

    print(f"\n{'#'*80}")
    print(f"AUTO UPLOAD MONITOR - Monitoring completed Skyvern workflows")
    print(f"{'#'*80}")
    print(f"Poll Interval: {POLL_INTERVAL} seconds")
    print(f"Download Path: {DOWNLOAD_BASE_PATH}")
    print(f"Final Path: {FINAL_BASE_PATH}")
    print(f"{'#'*80}\n")

    processed = load_processed_workflows()
    print(f"Already processed {len(processed)} workflow(s)")

    while True:
        try:
            print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Checking for completed workflows...")

            # Get completed workflows
            completed_workflows = get_completed_workflows()

            # Filter out already processed ones
            new_workflows = [
                w for w in completed_workflows
                if w.get('workflow_run_id') not in processed
            ]

            if new_workflows:
                print(f"Found {len(new_workflows)} new completed workflow(s)")

                for workflow in new_workflows:
                    workflow_run_id = workflow.get('workflow_run_id')

                    try:
                        # Process downloads
                        success, file_count = process_workflow_downloads(workflow_run_id)

                        if success:
                            print(f"✅ Processed {file_count} file(s) from {workflow_run_id}")

                        # Mark as processed
                        save_processed_workflow(workflow_run_id)
                        processed.add(workflow_run_id)

                    except Exception as e:
                        print(f"❌ Error processing {workflow_run_id}: {e}")
                        import traceback
                        traceback.print_exc()
            else:
                print(f"No new completed workflows")

            # Wait before next poll
            print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Waiting {POLL_INTERVAL} seconds...")
            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            print(f"\n\nMonitor stopped by user")
            break
        except Exception as e:
            print(f"❌ Error in main loop: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
