#!/usr/bin/env python3
"""
Unified Evidence File Downloader (Workflow-Only Mode + Google Drive Support)

Single-process architecture:
- Polls Notion for "Ready For Download" cases
- Detects Google Drive links and downloads them directly using gdown
- Launches Skyvern V2 workflows for other links
- Downloads artifacts directly to suspect-named folders
- Uploads to Dropbox inline
- Updates Notion with final status

ARCHITECTURE FIX:
- Checks for ACTIVE Skyvern workflows instead of relying on Notion status
- Prevents stale "Downloading" statuses from blocking the queue
"""

import os
import shutil
import glob
import sys
import time
import requests
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from requests.exceptions import RequestException
from urllib.parse import urlparse, parse_qs

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

from notion_api import NotionCaseClient

# Load environment variables
load_dotenv()

# Configuration from environment
NOTION_API_KEY = os.getenv('NOTION_API_KEY')
NOTION_DATABASE_ID = os.getenv('NOTION_DATABASE_ID')
SKYVERN_API_BASE = os.getenv('SKYVERN_API_BASE', 'http://5.161.210.79:8000/api/v1')
SKYVERN_API_KEY = os.getenv('SKYVERN_API_KEY', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjQ5MDc5MzY4NDcsInN1YiI6Im9fNDYwODIyNzA2MTQ3NzI4MTE4In0.a81nQ5EZV5xcE942hWfzkU-3Z7Kwqc31ypgahKKithI')
SKYVERN_WORKFLOW_ID = os.getenv('SKYVERN_WORKFLOW_ID') or os.getenv('SKYVERN_WORKFLOW_V2_ID', 'wpid_462565939888912052')
DOWNLOAD_BASE_PATH = os.getenv('DOWNLOAD_BASE_PATH', '/mnt/HC_Volume_103781006/evidence_files')
SKYVERN_DOWNLOADS_PATH = '/mnt/HC_Volume_103781006/skyvern/downloads'
POLL_INTERVAL = int(os.getenv('POLL_INTERVAL', '60'))
SKYVERN_TIMEOUT = int(os.getenv('SKYVERN_TIMEOUT', str(4 * 3600)))  # 4 hours default
SKYVERN_POLL_INTERVAL = int(os.getenv('SKYVERN_POLL_INTERVAL', '30'))
SKYVERN_PROXY_LOCATION = os.getenv('SKYVERN_PROXY_LOCATION', 'RESIDENTIAL')

# Dropbox configuration
DROPBOX_APP_KEY = os.getenv('DROPBOX_APP_KEY')
DROPBOX_APP_SECRET = os.getenv('DROPBOX_APP_SECRET')
DROPBOX_MEMBER_ID = os.getenv('DROPBOX_MEMBER_ID')
DROPBOX_BASE_FOLDER = os.getenv('DROPBOX_BASE_FOLDER', '')

# Initialize Notion client
notion = NotionCaseClient(NOTION_API_KEY, NOTION_DATABASE_ID)


def get_dropbox_token():
    """Get Dropbox access token using refresh token flow"""
    import dropbox
    from dropbox import DropboxOAuth2FlowNoRedirect

    # Check if we have a cached token
    token_file = os.path.join(os.path.dirname(__file__), '.dropbox_token')

    if os.path.exists(token_file):
        with open(token_file, 'r') as f:
            return f.read().strip()

    # Need to get a new token - this requires manual authorization once
    auth_flow = DropboxOAuth2FlowNoRedirect(DROPBOX_APP_KEY, DROPBOX_APP_SECRET)
    authorize_url = auth_flow.start()

    print(f"\n⚠️ Dropbox authorization required:")
    print(f"1. Visit: {authorize_url}")
    print(f"2. Click 'Allow'")
    print(f"3. Copy the authorization code")

    auth_code = input("Enter the authorization code: ").strip()
    oauth_result = auth_flow.finish(auth_code)

    # Save token for future use
    with open(token_file, 'w') as f:
        f.write(oauth_result.access_token)

    return oauth_result.access_token


def upload_to_dropbox_inline(suspect_name, local_file_path):
    """
    Upload a file to Dropbox directly using streaming to avoid memory issues
    Returns: Dropbox URL if successful, None otherwise
    """
    try:
        import dropbox

        # Get access token
        access_token = get_dropbox_token()

        # Create Dropbox client
        dbx = dropbox.Dropbox(
            access_token,
            headers={"Dropbox-API-Select-User": DROPBOX_MEMBER_ID}
        ) if DROPBOX_MEMBER_ID else dropbox.Dropbox(access_token)

        # Construct remote path
        filename = os.path.basename(local_file_path)
        remote_folder = f"{DROPBOX_BASE_FOLDER}/{suspect_name}".strip('/')
        remote_path = f"/{remote_folder}/{filename}"

        # Get file size without loading into memory
        file_size = os.path.getsize(local_file_path)

        # 150MB threshold for chunked upload
        chunk_size = 4 * 1024 * 1024  # 4MB chunks

        if file_size > 150 * 1024 * 1024:
            print(f"   Uploading large file ({file_size / (1024*1024):.1f} MB) in chunks...")

            # Stream the file in chunks without loading it all into memory
            with open(local_file_path, 'rb') as f:
                # Start upload session with first chunk
                first_chunk = f.read(chunk_size)
                upload_session_start_result = dbx.files_upload_session_start(first_chunk)
                cursor = dropbox.files.UploadSessionCursor(
                    session_id=upload_session_start_result.session_id,
                    offset=len(first_chunk)
                )

                # Upload remaining chunks
                bytes_uploaded = cursor.offset
                while bytes_uploaded < file_size:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break

                    bytes_remaining = file_size - bytes_uploaded

                    if bytes_remaining <= len(chunk):
                        # Last chunk - finish the upload
                        commit = dropbox.files.CommitInfo(
                            path=remote_path,
                            mode=dropbox.files.WriteMode.overwrite
                        )
                        dbx.files_upload_session_finish(chunk, cursor, commit)
                        bytes_uploaded += len(chunk)
                        print(f"   Progress: {bytes_uploaded / (1024*1024):.1f} MB / {file_size / (1024*1024):.1f} MB (100%)")
                        break
                    else:
                        # Append chunk to session
                        dbx.files_upload_session_append_v2(chunk, cursor)
                        bytes_uploaded += len(chunk)
                        cursor.offset = bytes_uploaded

                        # Show progress every 100MB
                        if bytes_uploaded % (100 * 1024 * 1024) < chunk_size:
                            progress_pct = (bytes_uploaded / file_size) * 100
                            print(f"   Progress: {bytes_uploaded / (1024*1024):.1f} MB / {file_size / (1024*1024):.1f} MB ({progress_pct:.1f}%)")
        else:
            # Small file - read and upload directly
            with open(local_file_path, 'rb') as f:
                file_data = f.read()

            dbx.files_upload(
                file_data,
                remote_path,
                mode=dropbox.files.WriteMode.overwrite
            )
            print(f"   Uploaded {file_size / (1024*1024):.1f} MB")

        # Create shared link
        try:
            shared_link = dbx.sharing_create_shared_link(remote_path)
            dropbox_url = shared_link.url.replace('?dl=0', '?dl=1')
        except Exception:
            # Link may already exist
            links = dbx.sharing_list_shared_links(path=remote_path).links
            if links:
                dropbox_url = links[0].url.replace('?dl=0', '?dl=1')
            else:
                dropbox_url = None

        print(f"   ✅ Uploaded to Dropbox: {remote_path}")
        return dropbox_url

    except Exception as e:
        print(f"   ❌ Dropbox upload failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def parse_credentials(login_text):
    """Parse login credentials from various formats"""
    if not login_text:
        return None, None

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
            username = line
        elif not password and not any(x in lower_line for x in ['email', 'username']):
            password = line

    return username, password


def is_google_drive_url(url):
    """Check if URL is a Google Drive link"""
    return 'drive.google.com' in url or 'docs.google.com' in url


def is_workflow_active(workflow_run_id):
    """
    Check if a Skyvern workflow is still active
    Returns: True if workflow is running/queued, False otherwise
    """
    if not workflow_run_id:
        return False, None

    try:
        headers = {"x-api-key": SKYVERN_API_KEY}
        response = requests.get(
            f"{SKYVERN_API_BASE}/workflow_runs/{workflow_run_id}",
            headers=headers,
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            status = data.get('status', '')
            # Consider workflow active if it's running, queued, or created
            return status in ['running', 'queued', 'created']
        elif response.status_code == 404:
            # Workflow not found - definitely not active
            return False, "No files downloaded from Google Drive"
        else:
            print(f"⚠️ Warning: Failed to check workflow status (HTTP {response.status_code})")
            # If we can't verify, assume it's not active to avoid blocking
            return False, "Could not extract Google Drive folder/file ID"
    except Exception as e:
        print(f"⚠️ Warning: Error checking workflow status: {e}")
        # If we can't verify, assume it's not active to avoid blocking
        return False


def clear_stale_downloading_statuses():
    """
    Clear cases stuck in 'Downloading' status with no active workflow
    This is a safety mechanism to prevent queue blocking
    """
    try:
        print("\n🔍 Checking for stale 'Downloading' statuses...")

        # Get all cases with "Downloading" status
        response = notion.client.databases.query(
            database_id=NOTION_DATABASE_ID,
            filter={
                "property": "Download Status",
                "select": {
                    "equals": "Downloading"
                }
            }
        )

        cases = response.get("results", [])

        if not cases:
            print("   ✅ No cases with 'Downloading' status")
            return 0

        cleared_count = 0

        for case in cases:
            case_data = notion._extract_case_data(case)
            if not case_data:
                continue

            page_id = case_data['page_id']
            suspect_name = case_data['suspect_name']
            workflow_run_id = case_data.get('workflow_run_id')

            # Check if workflow is actually active
            if workflow_run_id and is_workflow_active(workflow_run_id):
                print(f"   ✅ {suspect_name}: Workflow {workflow_run_id} is active")
                continue

            # Workflow is not active - clear the stale status
            print(f"   🔧 {suspect_name}: Clearing stale 'Downloading' status (workflow: {workflow_run_id or 'None'})")

            # Reset to "Ready For Download" so it can be retried
            notion.update_case_status(page_id, "Ready For Download")

            # Clear workflow ID if present
            if workflow_run_id:
                notion.update_workflow_run_id(page_id, None)

            cleared_count += 1

        if cleared_count > 0:
            print(f"   ✅ Cleared {cleared_count} stale 'Downloading' status(es)")

        return cleared_count

    except Exception as e:
        print(f"❌ Error clearing stale statuses: {e}")
        return 0


def download_google_drive(url, suspect_name, page_id):
    """
    Download from Google Drive using gdown

    Returns:
        tuple: (success: bool, failure_reason: str or None)
    """
    print(f"\n{'='*80}")
    print(f"GOOGLE DRIVE DOWNLOAD")
    print(f"{'='*80}")
    print(f"Suspect: {suspect_name}")
    print(f"URL: {url}")

    try:
        import gdown

        # Create local directory for this suspect
        local_dir = os.path.join(DOWNLOAD_BASE_PATH, suspect_name)
        os.makedirs(local_dir, exist_ok=True)

        # Update status to Downloading
        notion.update_case_status(page_id, status="Downloading")

        # Extract folder or file ID from URL
        folder_id = None
        file_id = None

        if '/folders/' in url:
            folder_id = url.split('/folders/')[1].split('?')[0]
        elif '/file/d/' in url:
            file_id = url.split('/file/d/')[1].split('/')[0]
        elif 'id=' in url:
            parsed = parse_qs(urlparse(url).query)
            id_val = parsed.get('id', [None])[0]
            folder_id = id_val

        if folder_id:
            print(f"📁 Google Drive folder ID: {folder_id}")
            folder_url = f"https://drive.google.com/drive/folders/{folder_id}"

            gdown.download_folder(folder_url, output=local_dir, quiet=False, use_cookies=False)

            downloaded_files = [f for f in os.listdir(local_dir) if os.path.isfile(os.path.join(local_dir, f))]

            if downloaded_files:
                print(f"✅ Downloaded {len(downloaded_files)} file(s) from Google Drive folder")

                # Upload files to Dropbox inline
                success_count = 0
                for filename in downloaded_files:
                    filepath = os.path.join(local_dir, filename)
                    file_size_mb = os.path.getsize(filepath) / (1024*1024)
                    print(f"   Uploading {filename} ({file_size_mb:.1f} MB)...")

                    dropbox_url = upload_to_dropbox_inline(suspect_name, filepath)
                    if dropbox_url:
                        success_count += 1

                if success_count > 0:
                    # Update Notion to "Downloaded" status
                    success = notion.update_case_status(page_id, status="Downloaded")
                    if not success:
                        print(f"⚠️ WARNING: Files uploaded but Notion status update failed!")
                    print(f"✅ Successfully processed {success_count}/{len(downloaded_files)} files")
                    return True, None
                else:
                    print(f"❌ Failed to upload files to Dropbox")
                    return False, "Failed to upload to Dropbox"
            else:
                print(f"❌ No files downloaded from Google Drive folder")
                return False, "Failed to upload to Dropbox"

        elif file_id:
            print(f"📄 Google Drive file ID: {file_id}")
            file_url = f"https://drive.google.com/uc?id={file_id}"

            output_file = os.path.join(local_dir, f"{suspect_name}_gdrive_file")
            gdown.download(file_url, output_file, quiet=False)

            if os.path.exists(output_file):
                file_size_mb = os.path.getsize(output_file) / (1024*1024)
                print(f"✅ Downloaded file from Google Drive ({file_size_mb:.1f} MB)")

                # Upload to Dropbox
                dropbox_url = upload_to_dropbox_inline(suspect_name, output_file)
                if dropbox_url:
                    # Update Notion to "Downloaded" status
                    success = notion.update_case_status(page_id, status="Downloaded")
                    if not success:
                        print(f"⚠️ WARNING: File uploaded but Notion status update failed!")
                    print(f"✅ Successfully processed file")
                    return True, None
                else:
                    print(f"❌ Failed to upload file to Dropbox")
                    return False
            else:
                print(f"❌ File not downloaded from Google Drive")
                return False
        else:
            print(f"❌ Could not extract Google Drive folder/file ID from URL")
            return False

    except Exception as e:
        print(f"❌ Google Drive download failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def download_with_skyvern_workflow(url, username, password, suspect_name, page_id):
    """
    Download using Skyvern V2 workflow

    Returns:
        bool: True if successful, False otherwise
    """
    print(f"\n{'='*80}")
    print(f"SKYVERN WORKFLOW DOWNLOAD")
    print(f"{'='*80}")
    print(f"Suspect: {suspect_name}")
    print(f"URL: {url}")
    print(f"Timeout: {SKYVERN_TIMEOUT/3600:.1f} hours")

    headers = {
        "Content-Type": "application/json",
        "x-api-key": SKYVERN_API_KEY
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
        "proxy_location": SKYVERN_PROXY_LOCATION
    }

    workflow_run_id = None

    try:
        # Start workflow
        response = requests.post(
            f"{SKYVERN_API_BASE}/workflows/{SKYVERN_WORKFLOW_ID}/run",
            headers=headers,
            json=payload,
            timeout=120
        )

        if response.status_code != 200:
            print(f"❌ Failed to start workflow: {response.status_code}")
            print(f"   Response: {response.text[:200]}")
            return False

        run_data = response.json()
        workflow_run_id = run_data.get('workflow_run_id')

        if not workflow_run_id:
            print("❌ Workflow response missing workflow_run_id")
            return False

        print(f"✅ Workflow started: {workflow_run_id}")

        # Update Notion with workflow ID and set status to Downloading
        notion.update_workflow_run_id(page_id, workflow_run_id)
        notion.update_case_status(page_id, status="Downloading")

        print(f"   Monitor: {SKYVERN_API_BASE.replace('/api/v1', '')}/workflows/run/{workflow_run_id}")

        # Poll for completion
        start_time = time.time()
        retry_count = 0  # Track consecutive API timeouts
        max_retries = 5  # Max consecutive timeouts before giving up


        while True:
            current_time = time.time()
            elapsed = current_time - start_time

            if elapsed > SKYVERN_TIMEOUT:
                print(f"⏱️ Timeout after {SKYVERN_TIMEOUT/3600:.1f} hours")

                # Cancel workflow
                try:
                    requests.post(
                        f"{SKYVERN_API_BASE}/workflows/runs/{workflow_run_id}/cancel",
                        headers=headers,
                        timeout=60
                    )
                    print(f"   Cancelled workflow: {workflow_run_id}")
                except Exception as e:
                    print(f"   Warning: Failed to cancel workflow: {e}")

                return False

            # Check workflow status
            try:
                status_response = requests.get(
                    f"{SKYVERN_API_BASE}/workflows/runs/{workflow_run_id}",
                    headers=headers,
                    timeout=120
                )
                status_response.raise_for_status()
                status_data = status_response.json()
                retry_count = 0  # Reset on success
            except requests.exceptions.Timeout:
                retry_count += 1
                print(f"⚠️ API timeout checking status (attempt {retry_count}/{max_retries})")

                if retry_count >= max_retries:
                    print(f"❌ Failed to get workflow status after {max_retries} attempts - giving up")
                    failure_reason = f"Failed to check workflow status after {max_retries} timeout attempts"
                    return False, failure_reason

                time.sleep(SKYVERN_POLL_INTERVAL * retry_count)  # Exponential backoff
                continue
            except Exception as e:
                print(f"❌ Error checking status: {e}")
                time.sleep(SKYVERN_POLL_INTERVAL)
                continue

            workflow_status = status_data.get('status')

            print(f"   Status: {workflow_status} (elapsed: {int(elapsed/60)}min)")

            if workflow_status in ['completed', 'failed', 'terminated', 'canceled']:
                break

            time.sleep(SKYVERN_POLL_INTERVAL)

        # Check final status
        failure_reason = None
        if workflow_status == 'completed':
            # Look for downloaded files in Skyvern downloads directory
            skyvern_download_dir = os.path.join(SKYVERN_DOWNLOADS_PATH, workflow_run_id)

            if os.path.exists(skyvern_download_dir):
                # Get all files from the directory
                all_files = glob.glob(os.path.join(skyvern_download_dir, '*'))
                downloaded_files = [f for f in all_files if os.path.isfile(f)]

                if downloaded_files:
                    print(f"✅ Found {len(downloaded_files)} file(s) in {skyvern_download_dir}")

                    # Create local directory for this suspect
                    local_dir = os.path.join(DOWNLOAD_BASE_PATH, suspect_name)
                    os.makedirs(local_dir, exist_ok=True)

                    # Copy files and upload to Dropbox inline
                    success_count = 0
                    dropbox_urls = []

                    for file_path in downloaded_files:
                        filename = os.path.basename(file_path)
                        dest_path = os.path.join(local_dir, filename)

                        try:
                            # Copy file to suspect-named folder
                            shutil.copy2(file_path, dest_path)
                            file_size_mb = os.path.getsize(file_path) / (1024*1024)
                            print(f"   Copied: {filename} ({file_size_mb:.1f} MB)")

                            # Upload to Dropbox immediately
                            dropbox_url = upload_to_dropbox_inline(suspect_name, dest_path)
                            if dropbox_url:
                                success_count += 1
                                dropbox_urls.append(dropbox_url)
                        except Exception as e:
                            print(f"   ❌ Failed to process {filename}: {e}")

                    if success_count > 0:
                        # Update Notion to "Downloaded" status
                        status_success = notion.update_case_status(page_id, status="Downloaded")
                        if not status_success:
                            print(f"⚠️ WARNING: Files uploaded but Notion status update FAILED!")
                            print(f"⚠️ This will leave the case stuck in 'Downloading' - manual intervention needed")

                        # Clear workflow ID since we're done
                        notion.update_workflow_run_id(page_id, None)

                        print(f"✅ Successfully processed {success_count}/{len(downloaded_files)} files")

                        # CLEANUP: Delete Skyvern download directory after successful upload
                        try:
                            shutil.rmtree(skyvern_download_dir)
                            print(f"🗑️  Cleaned up Skyvern downloads: {skyvern_download_dir}")
                        except Exception as e:
                            print(f"⚠️  Warning: Failed to cleanup {skyvern_download_dir}: {e}")

                        return True, None
                    else:
                        print(f"❌ Failed to process any files")
                        return False
                else:
                    print(f"⚠️ Workflow completed but directory is empty: {skyvern_download_dir}")
                    return False
            else:
                print(f"⚠️ Download directory not found: {skyvern_download_dir}")
                return False
        else:
            print(f"❌ Workflow failed with status: {workflow_status}")
            
            # Extract failure reason from workflow
            try:
                failure_message = status_data.get('failure_reason') or status_data.get('error_message')
                if failure_message:
                    failure_reason = f"Workflow {workflow_status}: {failure_message}"
                else:
                    failure_reason = f"Workflow {workflow_status}"
            except Exception as e:
                failure_reason = f"Workflow {workflow_status}"
                print(f"   Warning: Could not extract failure reason: {e}")
            
            return False, failure_reason

    except Exception as e:
        print(f"❌ Error in Skyvern workflow: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # Always clear workflow ID when done (success or failure)
        if workflow_run_id:
            notion.update_workflow_run_id(page_id, None)


def process_case(case):
    """Process a single case - detect Google Drive or use Skyvern workflow"""

    suspect_name = case.get('suspect_name', 'Unknown')
    download_links = case.get("download_links", [])
    download_link = download_links[0] if download_links else ""
    login_text = case.get("login_credentials", "")
    page_id = case.get('page_id')

    print(f"\n{'#'*80}")
    print(f"PROCESSING: {suspect_name}")
    print(f"{'#'*80}")
    print(f"Download Link: {download_link}")
    print(f"Page ID: {page_id}")

    # Parse credentials
    username, password = parse_credentials(login_text)

    if username and password:
        print(f"Credentials: {username} / {'*' * len(password)}")
    else:
        print(f"Credentials: None")

    # Check if it's a Google Drive URL
    if is_google_drive_url(download_link):
        print(f"🔍 Detected Google Drive URL - using gdown")
        success = download_google_drive(
            url=download_link,
            suspect_name=suspect_name,
            page_id=page_id
        )
    else:
        print(f"🔍 Regular URL - using Skyvern workflow")
        success = download_with_skyvern_workflow(
            url=download_link,
            username=username,
            password=password,
            suspect_name=suspect_name,
            page_id=page_id
        )

    if success:
        print(f"\n✅ Case processed successfully")
    else:
        # Mark as failed
        failed_success = notion.update_case_status(page_id, status="Failed")
        if failed_success:
            print(f"\n❌ Case failed - marked as Failed in Notion")
        else:
            print(f"\n❌ Case failed - AND status update to 'Failed' also failed!")


def count_active_downloads():
    """
    Count how many downloads are actually active
    This checks both Notion status AND Skyvern workflow status
    Returns: Number of truly active downloads
    """
    try:
        # Get all cases with "Downloading" status
        response = notion.client.databases.query(
            database_id=NOTION_DATABASE_ID,
            filter={
                "property": "Download Status",
                "select": {
                    "equals": "Downloading"
                }
            }
        )

        cases = response.get("results", [])

        if not cases:
            return 0

        active_count = 0

        for case in cases:
            case_data = notion._extract_case_data(case)
            if not case_data:
                continue

            workflow_run_id = case_data.get('workflow_run_id')

            # Check if workflow is actually active
            if workflow_run_id and is_workflow_active(workflow_run_id):
                active_count += 1

        return active_count

    except Exception as e:
        print(f"❌ Error counting active downloads: {e}")
        # If we can't verify, return 0 to avoid blocking
        return 0


def main():
    """Main downloader loop - workflow-only mode with Google Drive support"""

    print(f"\n{'#'*80}")
    print(f"UNIFIED EVIDENCE FILE DOWNLOADER")
    print(f"{'#'*80}")
    print(f"Architecture:")
    print(f"  - Polls Notion every {POLL_INTERVAL}s")
    print(f"  - Google Drive links: Direct gdown download")
    print(f"  - Other links: Skyvern workflows")
    print(f"  - Downloads to suspect-named folders")
    print(f"  - Uploads to Dropbox inline")
    print(f"  - CHECKS ACTIVE WORKFLOWS (not just Notion status)")
    print(f"  - Clears stale 'Downloading' statuses automatically")
    print(f"  - ALWAYS KEEPS 1 DOWNLOAD RUNNING")
    print(f"")
    print(f"Skyvern API: {SKYVERN_API_BASE}")
    print(f"Workflow ID: {SKYVERN_WORKFLOW_ID}")
    print(f"Download Path: {DOWNLOAD_BASE_PATH}")
    print(f"{'#'*80}\n")

    while True:
        try:
            # ARCHITECTURE FIX: Clear any stale "Downloading" statuses first
            cleared = clear_stale_downloading_statuses()

            if cleared > 0:
                print(f"🔧 Cleared {cleared} stale status(es) - queue should be unblocked now")

            # ARCHITECTURE FIX: Count ACTIVE downloads (not just Notion status)
            active_downloads = count_active_downloads()

            if active_downloads > 0:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {active_downloads} active download(s) running, waiting...")
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Waiting {POLL_INTERVAL} seconds...")
                time.sleep(POLL_INTERVAL)
                continue

            # Get one case ready for download
            cases = notion.get_cases_ready_for_download(limit=1)

            if not cases:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] No cases ready for download")
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Waiting {POLL_INTERVAL} seconds...")
                time.sleep(POLL_INTERVAL)
                continue

            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Found 1 case ready for download")

            try:
                process_case(cases[0])
            except Exception as e:
                print(f"❌ Error processing case: {e}")
                import traceback
                traceback.print_exc()

            # IMMEDIATELY continue to check for next case
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Checking for next case immediately...")
            continue

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
