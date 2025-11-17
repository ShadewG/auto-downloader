#!/usr/bin/env python3
"""
Enhanced Evidence File Downloader with Complete Fallback Chain

Architecture:
1. LLM Pre-filter - Evaluate case notes to skip non-downloadable cases
2. Local Skyvern (V2 workflow with file_download block) - 4 hour timeout
3. Cloud Skyvern Fallback - Uploads to S3, monitored by s3_monitor.py
4. Playwright Fallback - Direct browser automation
5. Mark as Failed - Update Notion status

Supports parallel execution for long-running downloads
"""

import os
import shutil
import glob
import sys
import time
import json
import requests
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

from notion_api import NotionCaseClient as NotionAPI
from dropbox_uploader import upload_to_dropbox
from llm_pre_filter import should_download_case

# Load environment variables
load_dotenv()

# Configuration
NOTION_API_KEY = os.getenv('NOTION_API_KEY')
NOTION_DATABASE_ID = os.getenv('NOTION_DATABASE_ID')
DOWNLOAD_BASE_PATH = os.getenv('DOWNLOAD_BASE_PATH', '/mnt/HC_Volume_103781006/evidence_files')
SKYVERN_DOWNLOADS_PATH = '/mnt/HC_Volume_103781006/skyvern/downloads'
POLL_INTERVAL = int(os.getenv('POLL_INTERVAL', '60'))

# Skyvern configuration
SKYVERN_API_BASE = "http://5.161.210.79:8000/api/v1"
SKYVERN_API_TOKEN = os.getenv('SKYVERN_API_KEY', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjQ5MDc5MzY4NDcsInN1YiI6Im9fNDYwODIyNzA2MTQ3NzI4MTE4In0.a81nQ5EZV5xcE942hWfzkU-3Z7Kwqc31ypgahKKithI')
SKYVERN_WORKFLOW_V2_ID = "wpid_461538336606218912"  # V2 workflow with file_download block
SKYVERN_TIMEOUT = 14400  # 4 hours in seconds

# Cloud Skyvern configuration
CLOUD_SKYVERN_API_BASE = "https://api.skyvern.com/v1"
CLOUD_SKYVERN_API_KEY = os.getenv('CLOUD_SKYVERN_API_KEY', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjQ5MDc3Mjc1MTgsInN1YiI6Im9fNDU5OTIzNjM1MjE0NTIzOTQ4In0.M4e1HPultXky47lUO6S3STWM6PHPPJ0S2a9va8VEUfo')
CLOUD_WORKFLOW_ID = "wpid_461522695995697924"

# Initialize Notion client
notion = NotionAPI(NOTION_API_KEY, NOTION_DATABASE_ID)


def parse_credentials(login_text):
    """Parse login credentials from various formats"""
    if not login_text:
        return None, None

    # Try to extract email and password
    lines = [line.strip() for line in login_text.split('\n') if line.strip()]

    username = None
    password = None

    for line in lines:
        lower_line = line.lower()
        if 'email:' in lower_line or 'username:' in lower_line:
            username = line.split(':', 1)[1].strip()
        elif 'password:' in lower_line:
            password = line.split(':', 1)[1].strip()
        elif '@' in line and not username:
            # Likely an email address
            username = line
        elif not password and not any(x in lower_line for x in ['email', 'username']):
            # Likely a password
            password = line

    return username, password


def download_with_local_skyvern(url, username, password, suspect_name, page_id):
    """
    Attempt download using local Skyvern with V2 workflow (file_download block)
    4-hour timeout allows for large downloads

    Returns:
        tuple: (success: bool, downloaded_files: list)
    """
    print(f"\n{'='*80}")
    print(f"STAGE 1: LOCAL SKYVERN (V2 Workflow)")
    print(f"{'='*80}")
    print(f"Suspect: {suspect_name}")
    print(f"URL: {url}")
    print(f"Timeout: {SKYVERN_TIMEOUT/3600} hours")

    headers = {
        "Content-Type": "application/json",
        "x-api-key": SKYVERN_API_TOKEN
    }

    # Format credentials
    if username and password:
        login = f"Email: {username}\nPassword: {password}"
    else:
        login = ""

    # Trigger workflow
    payload = {
        "data": {
            "URL": url,
            "login": login
        },
        "proxy_location": "RESIDENTIAL"
    }

    try:
        # Start workflow
        response = requests.post(
            f"{SKYVERN_API_BASE}/workflows/{SKYVERN_WORKFLOW_V2_ID}/run",
            headers=headers,
            json=payload,
            timeout=14400
        )

        if response.status_code != 200:
            print(f"❌ Failed to start workflow: {response.status_code}")
            print(f"   Response: {response.text[:200]}")
            return False, []

        run_data = response.json()
        workflow_run_id = run_data.get('workflow_run_id')

        print(f"✅ Workflow started: {workflow_run_id}")
        print(f"   Monitor: http://5.161.210.79:8080/workflows/run/{workflow_run_id}")

        # Update Notion with workflow ID
        notion.update_case_status(
            page_id,
            status="Downloading",
        )

        # Poll for completion (4-hour timeout)
        start_time = time.time()
        poll_interval = 30  # Check every 30 seconds

        while True:
            elapsed = time.time() - start_time

            if elapsed > SKYVERN_TIMEOUT:
                print(f"⏱️ Timeout after {SKYVERN_TIMEOUT/3600} hours")
                return False, []

            # Check workflow status
            status_response = requests.get(
                f"{SKYVERN_API_BASE}/workflows/runs/{workflow_run_id}",
                headers=headers,
                timeout=14400
            )

            if status_response.status_code != 200:
                print(f"❌ Error checking status: {status_response.status_code}")
                time.sleep(poll_interval)
                continue

            status_data = status_response.json()
            workflow_status = status_data.get('status')

            print(f"   Status: {workflow_status} (elapsed: {int(elapsed/60)}min)")

            if workflow_status in ['completed', 'failed', 'terminated', 'canceled']:
                break

            time.sleep(poll_interval)

        # Check final status
        if workflow_status == 'completed':
            # Check local Skyvern downloads directory for files
            skyvern_download_dir = os.path.join(SKYVERN_DOWNLOADS_PATH, workflow_run_id)
            
            if os.path.exists(skyvern_download_dir):
                # Get all files from the directory
                all_files = glob.glob(os.path.join(skyvern_download_dir, '*'))
                downloaded_files = [f for f in all_files if os.path.isfile(f)]
                
                if downloaded_files:
                    print(f"✅ SUCCESS! Found {len(downloaded_files)} file(s) in {skyvern_download_dir}")
                    
                    # Create local directory for this suspect
                    local_dir = os.path.join(DOWNLOAD_BASE_PATH, suspect_name)
                    os.makedirs(local_dir, exist_ok=True)
                    
                    # Copy files from Skyvern downloads to final location
                    success_count = 0
                    for file_path in downloaded_files:
                        filename = os.path.basename(file_path)
                        dest_path = os.path.join(local_dir, filename)
                        
                        try:
                            # Copy file
                            shutil.copy2(file_path, dest_path)
                            print(f"   Copied: {filename} ({os.path.getsize(file_path) / (1024*1024):.1f} MB)")
                            
                            # Upload to Dropbox
                            if upload_to_dropbox(suspect_name, dest_path):
                                success_count += 1
                        except Exception as e:
                            print(f"   ❌ Failed to copy {filename}: {e}")
                    
                    if success_count > 0:
                        notion.update_case_status(
                            page_id,
                            status="Downloaded",
                        )
                        print(f"✅ Successfully processed {success_count}/{len(downloaded_files)} files")
                        return True, downloaded_files
                    else:
                        print(f"❌ Failed to process any files")
                        return False, []
                else:
                    print(f"⚠️ Workflow completed but directory is empty: {skyvern_download_dir}")
                    return False, []
            else:
                print(f"⚠️ Download directory not found: {skyvern_download_dir}")
                return False, []
        else:
            print(f"❌ Workflow failed with status: {workflow_status}")
            return False, []

    except Exception as e:
        print(f"❌ Error in local Skyvern: {e}")
        return False, []


def download_with_cloud_skyvern(url, username, password, suspect_name, page_id):
    """
    Attempt download using Cloud Skyvern API
    Files uploaded to S3, processed by s3_monitor.py

    Returns:
        tuple: (success: bool, workflow_run_id: str or None)
    """
    print(f"\n{'='*80}")
    print(f"STAGE 2: CLOUD SKYVERN FALLBACK")
    print(f"{'='*80}")
    print(f"Suspect: {suspect_name}")
    print(f"Files will be uploaded to S3 bucket for monitoring")

    headers = {
        "Content-Type": "application/json",
        "x-api-key": CLOUD_SKYVERN_API_KEY
    }

    # Format credentials
    if username and password:
        login = f"Email: {username}\nPassword: {password}"
    else:
        login = ""

    payload = {
        "workflow_id": CLOUD_WORKFLOW_ID,
        "parameters": {
            "URL": url,
            "login": login
        },
        "proxy_location": "RESIDENTIAL_ISP",
        "run_with": "agent",
        "ai_fallback": True
    }

    try:
        response = requests.post(
            f"{CLOUD_SKYVERN_API_BASE}/run/workflows",
            headers=headers,
            json=payload,
            timeout=14400
        )

        if response.status_code == 200:
            result = response.json()
            workflow_run_id = result.get('workflow_run_id')

            print(f"✅ Cloud workflow triggered: {workflow_run_id}")
            print(f"   Files will be uploaded to S3")
            print(f"   S3 monitor will auto-download and upload to Dropbox")

            # Update Notion
            notion.update_case_status(
                page_id,
                status="Downloading",
            )

            return True, workflow_run_id
        else:
            print(f"❌ Cloud Skyvern API error: {response.status_code}")
            print(f"   Response: {response.text[:200]}")
            return False, None

    except Exception as e:
        print(f"❌ Error calling Cloud Skyvern: {e}")
        return False, None


def download_with_playwright(url, username, password, suspect_name, page_id):
    """
    Attempt download using Playwright direct automation

    Returns:
        bool: success status
    """
    print(f"\n{'='*80}")
    print(f"STAGE 3: PLAYWRIGHT FALLBACK")
    print(f"{'='*80}")
    print(f"Suspect: {suspect_name}")
    print(f"URL: {url}")

    try:
        # Import playwright downloader
        pass # from downloader_full import download_files

        local_dir = os.path.join(DOWNLOAD_BASE_PATH, suspect_name)
        os.makedirs(local_dir, exist_ok=True)

        # Attempt download
        files = download_files(url, local_dir, username, password)

        if files:
            print(f"✅ Playwright downloaded {len(files)} file(s)")

            # Upload to Dropbox
            success_count = 0
            for file_path in files:
                if upload_to_dropbox(suspect_name, file_path):
                    success_count += 1

            if success_count > 0:
                notion.update_case_status(
                    page_id,
                    status="Downloaded",
                )
                return True

        print(f"❌ Playwright download failed")
        return False

    except Exception as e:
        print(f"❌ Playwright error: {e}")
        return False


def mark_as_failed(suspect_name, url, reason, page_id):
    """Mark case as failed in Notion"""
    print(f"\n{'='*80}")
    print(f"STAGE 4: MARKING AS FAILED")
    print(f"{'='*80}")
    print(f"Suspect: {suspect_name}")
    print(f"Reason: {reason}")

    notion.update_case_status(
        page_id,
        status="Failed",
    )

    print(f"✅ Marked as Failed in Notion")


def process_case(case):
    """Process a single case through the complete fallback chain"""

    suspect_name = case.get('suspect_name', 'Unknown')
    download_links = case.get("download_links", [])
    download_link = download_links[0] if download_links else ""
    login_text = case.get("login_credentials", "")
    page_id = case.get('page_id')
    case_notes = case.get('notes', '')

    print(f"\n{'#'*80}")
    print(f"PROCESSING: {suspect_name}")
    print(f"{'#'*80}")
    print(f"Download Link: {download_link}")
    print(f"Page ID: {page_id}")

#    # STAGE 0: LLM Pre-filter
#    print(f"\n{'='*80}")
#    print(f"STAGE 0: LLM PRE-FILTER")
#    print(f"{'='*80}")
#
#    should_download, filter_reason = should_download_case(case_notes, suspect_name, download_link)
#
#    print(f"Decision: {'DOWNLOAD' if should_download else 'SKIP'}")
#    print(f"Reason: {filter_reason}")
#
#    if not should_download:
#        # Skip download, mark as not applicable
#        notion.update_case_status(
#            page_id,
#            status="Not Applicable",
#        )
#        print(f"✅ Marked as Not Applicable in Notion")
#        return
#
    # Parse credentials
    username, password = parse_credentials(login_text)

    if username and password:
        print(f"Credentials: {username} / {'*' * len(password)}")
    else:
        print(f"Credentials: None")

    # STAGE 1: Local Skyvern (V2 workflow with file_download block)
    success, files = download_with_local_skyvern(
        url=download_link,
        username=username,
        password=password,
        suspect_name=suspect_name,
        page_id=page_id
    )

    if success:
        print(f"\n✅ Case processed successfully via Local Skyvern")
        return

    # STAGE 2: Playwright Fallback
    success = download_with_playwright(
        url=download_link,
        username=username,
        password=password,
        suspect_name=suspect_name,
        page_id=page_id
    )

    if success:
        print(f"\n✅ Case processed successfully via Playwright")
        return

    # STAGE 3: All methods failed
    mark_as_failed(
        suspect_name=suspect_name,
        url=download_link,
        reason="Local Skyvern and Playwright all failed",
        page_id=page_id
    )

    print(f"\n❌ Case failed after all fallback attempts")


def main():
    """Main downloader loop"""

    print(f"\n{'#'*80}")
    print(f"ENHANCED EVIDENCE FILE DOWNLOADER V2")
    print(f"{'#'*80}")
    print(f"Architecture:")
    print(f"  Stage 0: LLM Pre-filter")
    print(f"  Stage 1: Local Skyvern (V2 workflow, 4hr timeout)")
    print(f"  Stage 2: Playwright fallback")
    print(f"  Stage 3: Mark as Failed")
    print(f"")
    print(f"Poll Interval: {POLL_INTERVAL} seconds")
    print(f"{'#'*80}\n")

    while True:
        try:
            # Get cases ready for download
            cases = notion.get_cases_ready_for_download()

            if not cases:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] No cases ready for download")
            else:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Found {len(cases)} case(s) ready for download")

                for case in cases:
                    try:
                        process_case(case)
                    except Exception as e:
                        print(f"❌ Error processing case: {e}")
                        import traceback
                        traceback.print_exc()

            # Wait before next poll
            print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Waiting {POLL_INTERVAL} seconds...")
            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            print(f"\n\nDownloader stopped by user")
            break
        except Exception as e:
            print(f"❌ Error in main loop: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
