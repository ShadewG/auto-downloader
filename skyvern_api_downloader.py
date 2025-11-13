#!/usr/bin/env python3
"""
Skyvern API-based downloader module - FIXED VERSION

This module uses the Skyvern REST API to navigate and download files.
Skyvern runs as a Docker service and we interact with it via HTTP requests.

FIXED: Filter out Skyvern's own navigation screenshots (ai_nav_step_*.png)
"""

import os
import time
import logging
import requests
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

SKYVERN_API_BASE = "http://localhost:8000/api/v1"
SKYVERN_API_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjQ5MDc5MzY4NDcsInN1YiI6Im9fNDYwODIyNzA2MTQ3NzI4MTE4In0.a81nQ5EZV5xcE942hWfzkU-3Z7Kwqc31ypgahKKithI"


def _skyvern_artifact_reason(filename: str) -> Optional[str]:
    """Return a reason when filename is a known Skyvern-generated artifact."""
    name = filename.lower()

    if name.startswith("ai_nav_step_") and name.endswith(".png"):
        return "Skyvern navigation screenshot"

    if name.startswith("recording_") and name.endswith((".webm", ".mp4")):
        return "Skyvern session recording"

    if name.endswith("browser_console.log"):
        return "Browser console log"

    if name.endswith("browser_network.log"):
        return "Browser network log"

    if name.endswith("trace.zip") and "playwright" in name:
        return "Playwright trace archive"

    return None


def is_evidence_file(filename: str) -> bool:
    """Return True for evidence files; False for known Skyvern artifacts."""
    reason = _skyvern_artifact_reason(filename)
    if reason:
        logger.debug(f"Skipping {filename}: {reason}")
        return False

    return True


def download_with_skyvern_api(
    url: str,
    download_path: str,
    username: Optional[str] = None,
    password: Optional[str] = None,
    suspect_name: str = ""
) -> bool:
    """
    Download files using Skyvern AI navigation via API

    Args:
        url: URL to navigate to
        download_path: Local directory to save files
        username: Optional username for login
        password: Optional password for login
        suspect_name: Name of suspect for logging

    Returns:
        True if files were downloaded successfully, False otherwise
    """
    try:
        logger.info(f"Starting Skyvern API download for: {suspect_name}")
        logger.info(f"URL: {url}")

        # Create download directory
        Path(download_path).mkdir(parents=True, exist_ok=True)

        # Build the task prompt
        if username and password:
            navigation_goal = f"""
Navigate to this evidence portal and download ALL the evidence files.

Steps:
1. If you see a login page:
   - Enter username: {username}
   - Enter password: {password}
   - Click the login/submit button
2. After logging in (or if no login needed):
   - Look for a "Files", "Documents", "Attachments", or "Evidence" section
   - Navigate there if needed
   - Find the Download button or link (might say "Download", "Download All", "Download Files", "Export", etc.)
   - IMPORTANT: Click the download button to actually download the files
   - Wait for the browser's download to complete (check for download progress indicators)
3. Make sure files are actually downloading - not just viewing or listing them
"""
        else:
            navigation_goal = """
Navigate to this evidence portal and download ALL the evidence files.

Steps:
1. Look for a "Files", "Documents", "Attachments", or "Evidence" section and navigate there if needed
2. Find the download button or link (labeled "Download", "Download All", "Download Files", "Export", or similar)
3. IMPORTANT: Click it to actually download the files (not just view them)
4. Wait for the browser's download to complete (check for download progress indicators)
"""

        # Create navigation payload
        payload = {
            "url": url,
            "navigation_goal": navigation_goal.strip(),
            "data_extraction_goal": None,
            "navigation_payload": {},
            "extracted_information_schema": None,
            "webhook_callback_url": None,
            "totp_verification_url": None,
            "totp_identifier": None,
            "error_code_mapping": None
        }

        logger.info("Creating Skyvern task...")

        # Create task
        response = requests.post(
            f"{SKYVERN_API_BASE}/tasks",
            json=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": SKYVERN_API_TOKEN
            }
        )

        if response.status_code != 200:
            logger.error(f"Failed to create Skyvern task: {response.status_code}")
            logger.error(f"Response: {response.text}")
            return False

        task_data = response.json()
        task_id = task_data.get("task_id")

        if not task_id:
            logger.error("No task_id returned from Skyvern")
            return False

        logger.info(f"Skyvern task created: {task_id}")

        # Poll for task completion
        max_wait_time = 300  # 5 minutes
        poll_interval = 5  # 5 seconds
        elapsed = 0

        while elapsed < max_wait_time:
            time.sleep(poll_interval)
            elapsed += poll_interval

            # Get task status
            status_response = requests.get(
                f"{SKYVERN_API_BASE}/tasks/{task_id}",
                headers={"x-api-key": SKYVERN_API_TOKEN}
            )

            if status_response.status_code != 200:
                logger.error(f"Failed to get task status: {status_response.status_code}")
                continue

            task_status = status_response.json()
            status = task_status.get("status")

            logger.info(f"Skyvern task status: {status} ({elapsed}s elapsed)")

            if status in ["completed", "success", "terminated"]:
                logger.info(f"Skyvern task finished with status: {status}")

                failure_reason = task_status.get("failure_reason")
                if failure_reason:
                    logger.warning(f"Skyvern reported reason: {failure_reason}")
                    reason_lower = failure_reason.lower()
                    if any(keyword in reason_lower for keyword in ["login", "session", "credential"]):
                        logger.warning("Skyvern likely hit an authentication wall (session expired or login page)")

                # Check for downloaded artifacts
                # Skyvern stores artifacts in the configured artifact path
                # We need to check if any files were downloaded

                # Get task artifacts
                artifacts_response = requests.get(
                    f"{SKYVERN_API_BASE}/tasks/{task_id}/artifacts",
                    headers={"x-api-key": SKYVERN_API_TOKEN}
                )

                if artifacts_response.status_code == 200:
                    artifacts = artifacts_response.json()
                    logger.info(f"Task artifacts: {len(artifacts)} artifact(s)")

                    # Download artifacts to our download_path
                    downloaded_files = 0
                    for artifact in artifacts:
                        artifact_id = artifact.get("artifact_id")
                        artifact_type = artifact.get("artifact_type")

                        if artifact_type == "download":
                            # This is a downloaded file - get it
                            file_response = requests.get(
                                f"{SKYVERN_API_BASE}/artifacts/{artifact_id}/download",
                                stream=True,
                                headers={"x-api-key": SKYVERN_API_TOKEN}
                            )

                            if file_response.status_code == 200:
                                # Save the file
                                filename = artifact.get("uri", f"download_{artifact_id}")
                                filepath = Path(download_path) / Path(filename).name

                                # Check if this is an evidence file
                                if not is_evidence_file(filepath.name):
                                    logger.info(f"Skipping Skyvern artifact: {filepath.name}")
                                    continue

                                with open(filepath, 'wb') as f:
                                    for chunk in file_response.iter_content(chunk_size=8192):
                                        f.write(chunk)

                                file_size_mb = filepath.stat().st_size / 1024 / 1024
                                logger.info(f"Downloaded: {filepath.name} ({file_size_mb:.2f} MB)")
                                downloaded_files += 1

                    if downloaded_files > 0:
                        logger.info(f"Successfully downloaded {downloaded_files} evidence file(s) with Skyvern")
                        return True

                # Check if files exist in download directory (filter out screenshots)
                # (Skyvern might save directly to configured download path)
                all_files = list(Path(download_path).glob("*"))
                evidence_files = [f for f in all_files if f.is_file() and is_evidence_file(f.name)]

                if evidence_files:
                    logger.info(f"Successfully downloaded {len(evidence_files)} evidence file(s) with Skyvern:")
                    for f in evidence_files:
                        size_mb = f.stat().st_size / 1024 / 1024
                        logger.info(f"  - {f.name} ({size_mb:.2f} MB)")

                    # Clean up Skyvern screenshots
                    for f in all_files:
                        if f.is_file() and not is_evidence_file(f.name):
                            logger.info(f"Removing Skyvern artifact: {f.name}")
                            f.unlink()

                    return True

                # Check Skyvern's actual downloads directory (volume mounted)
                skyvern_download_dir = Path("/root/skyvern/downloads") / task_id
                if skyvern_download_dir.exists():
                    all_files = list(skyvern_download_dir.glob("*"))
                    evidence_files = [f for f in all_files if f.is_file() and is_evidence_file(f.name)]

                    if evidence_files:
                        logger.info(f"Successfully downloaded {len(evidence_files)} evidence file(s) with Skyvern:")
                        for f in evidence_files:
                            size_mb = f.stat().st_size / 1024 / 1024
                            logger.info(f"  - {f.name} ({size_mb:.2f} MB)")

                        # Copy evidence files to the requested download_path
                        Path(download_path).mkdir(parents=True, exist_ok=True)
                        for f in evidence_files:
                            dest = Path(download_path) / f.name
                            logger.info(f"Copying {f.name} to {download_path}")
                            import shutil
                            shutil.copy2(f, dest)

                        return True

                logger.warning("Skyvern task completed but no evidence files found (only artifacts)")
                failure_reason = task_status.get("failure_reason")
                if failure_reason:
                    logger.warning(f"Skyvern failure reason: {failure_reason}")
                logger.warning("Skyvern may have navigated the portal but didn't actually download files")
                return False

            elif status in ["failed", "error"]:
                failure_reason = task_status.get("failure_reason", "Unknown")
                logger.error(f"Skyvern task failed: {failure_reason}")
                return False

        logger.error(f"Skyvern task timed out after {max_wait_time} seconds")
        return False

    except requests.exceptions.RequestException as e:
        logger.error(f"Skyvern API request failed: {e}")
        return False

    except Exception as e:
        logger.error(f"Skyvern download failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


# Test function
async def test_skyvern_james_rinehart():
    """
    Test Skyvern with the James Rinehart case
    """
    url = "http://url5374.evidencelibrary.com/ls/click?upn=u001.1DmiTs-2BP7119MjX8j-2FWa7k-2FImRc1ptqmNNLQ0vvxQvwGXF5h9C84oCIEcDMbiJOOM1dFY1ZKtcXYby5O0Muu2mYFHCugv5HiGCR3-2BvXAxZ5aOLAinVzursotXRwqVzFSTC0l_QFGgicBhV6w8RCVzLzEsTzQcjkg8TOaakJfQ2R8mv9SYNKV2bCQWjpr9oHpP9a6CpyL6drUkNuaYq-2BkUmfmWWdd4Od8aY0ZnxkyWOHDbzy2B3Q4Jn-2BISBzfpuhCKHYFVtwsNJtz8y6HeXAjD1TjqOV2EqYCQXBrxxIKvC5urBwcsmyrBivYW-2FULfgB1IPBTUAWGp1bmW6zsudigFhrcg-2B6e9CnddTTfiORF2Aes3S-2BQ-3D"

    download_dir = "/tmp/skyvern_test_downloads/james_rinehart"

    print("=" * 80)
    print("SKYVERN API TEST: James Rinehart Jr.")
    print("=" * 80)
    print()

    success = download_with_skyvern_api(
        url=url,
        download_path=download_dir,
        suspect_name="James Rinehart Jr."
    )

    if success:
        print("\n✓ Skyvern successfully downloaded files!")
    else:
        print("\n✗ Skyvern failed to download files")

    return success


if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Run test (synchronous)
    import asyncio
    result = asyncio.run(test_skyvern_james_rinehart())
    exit(0 if result else 1)
