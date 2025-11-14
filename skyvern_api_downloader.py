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
import hashlib
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

SKYVERN_API_BASE = "http://localhost:8000/api/v1"
SKYVERN_API_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjQ5MDc5MzY4NDcsInN1YiI6Im9fNDYwODIyNzA2MTQ3NzI4MTE4In0.a81nQ5EZV5xcE942hWfzkU-3Z7Kwqc31ypgahKKithI"

SKYVERN_DOWNLOAD_ROOT = Path(
    os.environ.get("SKYVERN_DOWNLOAD_ROOT", "/mnt/HC_Volume_103781006/skyvern/downloads")
)
SKYVERN_MAX_STEPS = int(os.environ.get("SKYVERN_MAX_STEPS", "60"))
FINAL_TASK_STATUSES = {"completed", "success", "terminated", "failed", "error"}
FAILURE_STATUSES = {"failed", "error"}
HASH_CHUNK_SIZE = 8 * 1024 * 1024


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


def _hash_file(file_path: Path) -> Optional[str]:
    """Compute a SHA256 checksum for a file without loading it entirely into memory."""
    try:
        digest = hashlib.sha256()
        with file_path.open("rb") as handle:
            while True:
                chunk = handle.read(HASH_CHUNK_SIZE)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()
    except OSError as exc:
        logger.warning(f"Unable to hash {file_path}: {exc}")
        return None


def _build_checksum_index(download_dir: Path) -> Dict[str, Path]:
    """Index existing evidence files by checksum and drop duplicates."""
    download_dir.mkdir(parents=True, exist_ok=True)
    checksum_index: Dict[str, Path] = {}
    files = [f for f in download_dir.iterdir() if f.is_file() and is_evidence_file(f.name)]

    for file_path in files:
        checksum = _hash_file(file_path)
        if not checksum:
            continue

        if checksum in checksum_index:
            logger.info(f"Removing duplicate evidence file already present: {file_path.name}")
            try:
                file_path.unlink()
            except OSError as exc:
                logger.warning(f"Unable to remove duplicate {file_path.name}: {exc}")
            continue

        checksum_index[checksum] = file_path

    return checksum_index


def _copy_reported_downloads(
    reported_downloads: List[Dict[str, Any]],
    download_dir: Path,
    checksum_index: Dict[str, Path]
) -> int:
    """Persist files referenced in the task status response."""
    saved = 0

    for record in reported_downloads or []:
        checksum = record.get("checksum")
        filename = record.get("filename") or record.get("name")
        source_path = record.get("filesystem_path") or record.get("local_path") or record.get("path")

        if checksum and checksum in checksum_index:
            logger.info(f"Skipping duplicate reported download {filename} (checksum {checksum})")
            continue

        if not source_path:
            logger.debug("Reported download missing local path; skipping")
            continue

        src = Path(source_path)
        if not src.exists():
            logger.debug(f"Reported download path does not exist: {source_path}")
            continue

        target_name = filename or src.name
        dest = download_dir / target_name

        if src.resolve() == dest.resolve():
            logger.debug(f"Reported download already present at destination: {dest}")
        else:
            try:
                shutil.copy2(src, dest)
            except OSError as exc:
                logger.warning(f"Failed to copy reported download {target_name}: {exc}")
                continue

        checksum = checksum or _hash_file(dest)
        if checksum and checksum in checksum_index:
            logger.info(f"Removing duplicate reported download {dest.name} (checksum {checksum})")
            try:
                dest.unlink()
            except OSError as exc:
                logger.warning(f"Unable to remove duplicate {dest.name}: {exc}")
            continue

        if checksum:
            checksum_index[checksum] = dest
        saved += 1

    return saved


def _fetch_task_artifacts(task_id: str) -> List[Dict[str, Any]]:
    """Retrieve artifact metadata for a task."""
    try:
        response = requests.get(
            f"{SKYVERN_API_BASE}/tasks/{task_id}/artifacts",
            headers={"x-api-key": SKYVERN_API_TOKEN}
        )
        if response.status_code == 200:
            return response.json()
        logger.warning(f"Failed to fetch artifacts for {task_id}: HTTP {response.status_code}")
    except requests.exceptions.RequestException as exc:
        logger.error(f"Artifact fetch failed for {task_id}: {exc}")

    return []


def _download_artifact_files(
    task_id: str,
    artifacts: List[Dict[str, Any]],
    download_dir: Path,
    checksum_index: Dict[str, Path]
) -> int:
    """Download artifact files for a task while deduplicating by checksum."""
    saved = 0

    for artifact in artifacts:
        if artifact.get("artifact_type") != "download":
            continue

        artifact_id = artifact.get("artifact_id")
        checksum = artifact.get("checksum")
        filename = artifact.get("uri", f"download_{artifact_id}")

        if checksum and checksum in checksum_index:
            logger.info(f"Skipping duplicate artifact {filename} (checksum {checksum})")
            continue

        file_response = requests.get(
            f"{SKYVERN_API_BASE}/artifacts/{artifact_id}/download",
            stream=True,
            headers={"x-api-key": SKYVERN_API_TOKEN}
        )

        if file_response.status_code != 200:
            logger.warning(f"Failed to download artifact {artifact_id} for task {task_id}")
            continue

        dest = download_dir / Path(filename).name

        with open(dest, 'wb') as handle:
            for chunk in file_response.iter_content(chunk_size=8192):
                handle.write(chunk)

        if not is_evidence_file(dest.name):
            logger.info(f"Skipping Skyvern artifact file: {dest.name}")
            try:
                dest.unlink()
            except OSError:
                pass
            continue

        checksum = checksum or _hash_file(dest)
        if checksum and checksum in checksum_index:
            logger.info(f"Removing duplicate artifact download {dest.name} (checksum {checksum})")
            try:
                dest.unlink()
            except OSError as exc:
                logger.warning(f"Unable to remove duplicate artifact {dest.name}: {exc}")
            continue

        if checksum:
            checksum_index[checksum] = dest

        file_size_mb = dest.stat().st_size / 1024 / 1024
        logger.info(f"Downloaded artifact: {dest.name} ({file_size_mb:.2f} MB)")
        saved += 1

    return saved


def _copy_from_task_mount(
    task_id: str,
    download_dir: Path,
    checksum_index: Dict[str, Path]
) -> int:
    """Copy evidence files from the Skyvern host download directory into the case directory."""
    task_directory = SKYVERN_DOWNLOAD_ROOT / task_id
    if not task_directory.exists():
        logger.debug(f"Skyvern download directory not found for task {task_id}: {task_directory}")
        return 0

    saved = 0
    for file_path in task_directory.iterdir():
        if not file_path.is_file() or not is_evidence_file(file_path.name):
            continue

        checksum = _hash_file(file_path)
        if checksum and checksum in checksum_index:
            logger.info(f"Skipping duplicate file from Skyvern volume: {file_path.name}")
            continue

        dest = download_dir / file_path.name
        if file_path.resolve() == dest.resolve():
            logger.debug(f"File already exists in destination: {dest}")
        else:
            try:
                shutil.copy2(file_path, dest)
            except OSError as exc:
                logger.warning(f"Failed to copy {file_path.name} from Skyvern volume: {exc}")
                continue

        checksum = checksum or _hash_file(dest)
        if checksum and checksum in checksum_index:
            logger.info(f"Removing duplicate copied file {dest.name} (checksum {checksum})")
            try:
                dest.unlink()
            except OSError as exc:
                logger.warning(f"Unable to remove duplicate copied file {dest.name}: {exc}")
            continue

        if checksum:
            checksum_index[checksum] = dest
        saved += 1

    return saved


def _collect_downloads(
    task_id: str,
    download_path: str,
    reported_downloads: Optional[List[Dict[str, Any]]]
) -> bool:
    """Aggregate downloads from all possible locations for a task."""
    download_dir = Path(download_path)
    checksum_index = _build_checksum_index(download_dir)

    artifacts = _fetch_task_artifacts(task_id)
    saved_from_report = _copy_reported_downloads(reported_downloads or [], download_dir, checksum_index)
    saved_from_artifacts = _download_artifact_files(task_id, artifacts, download_dir, checksum_index)
    saved_from_mount = _copy_from_task_mount(task_id, download_dir, checksum_index)

    evidence_files = [f for f in download_dir.iterdir() if f.is_file() and is_evidence_file(f.name)]
    total_new = saved_from_report + saved_from_artifacts + saved_from_mount

    if evidence_files:
        logger.info(
            "Skyvern collected %d evidence file(s) (%d new) in %s",
            len(evidence_files),
            total_new,
            download_dir
        )
        return True

    logger.warning("Evidence files still not found after aggregating all sources")
    return False


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
3. Trigger each download only once. Do not repeatedly click the same button after it starts.
4. As soon as downloads are running (progress/download indicator visible), stop interacting with the page and end the task so the files can finish downloading.
"""
        else:
            navigation_goal = """
Navigate to this evidence portal and download ALL the evidence files.

Steps:
1. Look for a "Files", "Documents", "Attachments", or "Evidence" section and navigate there if needed
2. Find the download button or link (labeled "Download", "Download All", "Download Files", "Export", or similar)
3. IMPORTANT: Click it to actually download the files (not just view them)
4. Trigger each download only once unless it clearly fails.
5. As soon as downloads begin, stop navigating and end the task so the browser can finish downloading everything in the background.
"""

        # Create navigation payload with increased max_steps for complex portals
        payload = {
            "url": url,
            "navigation_goal": navigation_goal.strip(),
            "data_extraction_goal": None,
            "navigation_payload": {
                "max_steps_per_run": SKYVERN_MAX_STEPS,
                "terminate_after_download": True
            },
            "extracted_information_schema": None,
            "webhook_callback_url": None,
            "totp_verification_url": None,
            "totp_identifier": None,
            "error_code_mapping": None,
            "max_steps_per_run": SKYVERN_MAX_STEPS
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
        logger.info("Waiting 15 seconds before polling to avoid rate limits...")
        time.sleep(15)
        logger.info(f"Resuming polling for task {task_id}")

        # Poll for task completion
        max_wait_time = 3600  # 1 hour
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

            if status in FINAL_TASK_STATUSES:
                logger.info(f"Skyvern task finished with status: {status}")

                failure_reason = task_status.get("failure_reason")
                if failure_reason:
                    logger.warning(f"Skyvern reported reason: {failure_reason}")
                    reason_lower = failure_reason.lower()
                    if any(keyword in reason_lower for keyword in ["login", "session", "credential"]):
                        logger.warning("Skyvern likely hit an authentication wall (session expired or login page)")

                reported_downloads = task_status.get("downloaded_files") or []
                if reported_downloads:
                    logger.info(f"Task reported {len(reported_downloads)} downloaded file(s)")

                downloads_found = _collect_downloads(task_id, download_path, reported_downloads)
                if downloads_found:
                    return True

                if status in FAILURE_STATUSES:
                    failure_reason = failure_reason or "Unknown"
                    logger.error(f"Skyvern task failed without evidence files: {failure_reason}")
                    return False

                logger.warning("Skyvern task completed but no evidence files were located")
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
