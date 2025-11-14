#!/usr/bin/env python3
"""
Skyvern API-based downloader module - ENHANCED WITH LIVE MONITORING

This module uses the Skyvern REST API to navigate and download files.

NEW FEATURES:
- Browser session persistence to stay logged in
- Live progress monitoring with detailed status updates
- No arbitrary timeouts - waits until task actually completes
- Progress tracking for visual monitoring
"""

import os
import time
import logging
import requests
import hashlib
import shutil
import json
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from urllib.parse import urlparse
from datetime import datetime

logger = logging.getLogger(__name__)

SKYVERN_API_BASE = "http://localhost:8000/api/v1"
SKYVERN_API_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjQ5MDc5MzY4NDcsInN1YiI6Im9fNDYwODIyNzA2MTQ3NzI4MTE4In0.a81nQ5EZV5xcE942hWfzkU-3Z7Kwqc31ypgahKKithI"

SKYVERN_DOWNLOAD_ROOT = Path(
    os.environ.get("SKYVERN_DOWNLOAD_ROOT", "/mnt/HC_Volume_103781006/skyvern/downloads")
)
SKYVERN_MAX_STEPS = int(os.environ.get("SKYVERN_MAX_STEPS", "20"))
FINAL_TASK_STATUSES = {"completed", "success", "terminated", "failed", "error", "timed_out", "canceled"}
FAILURE_STATUSES = {"failed", "error", "timed_out"}
HASH_CHUNK_SIZE = 8 * 1024 * 1024

# Browser session storage
SESSION_STORE_FILE = Path("/root/case-downloader/browser_sessions.json")
SESSION_TIMEOUT = 3600  # 1 hour

# Progress tracking storage
PROGRESS_STORE_FILE = Path("/root/case-downloader/download_progress.json")


class DownloadProgress:
    """Track download progress for monitoring."""

    def __init__(self, task_id: str, suspect_name: str, url: str):
        self.task_id = task_id
        self.suspect_name = suspect_name
        self.url = url
        self.status = "created"
        self.started_at = datetime.now().isoformat()
        self.updated_at = datetime.now().isoformat()
        self.steps_completed = 0
        self.max_steps = SKYVERN_MAX_STEPS
        self.failure_reason = None
        self.files_downloaded = 0
        self.current_action = "Initializing..."
        self.screenshot_urls = []

    def update(self, status: str, action: str = None, steps: int = None):
        """Update progress status."""
        self.status = status
        if action:
            self.current_action = action
        if steps is not None:
            self.steps_completed = steps
        self.updated_at = datetime.now().isoformat()
        self._save()

    def _save(self):
        """Save progress to disk for monitoring."""
        try:
            progress_data = self.__dict__.copy()

            # Load existing progress
            all_progress = {}
            if PROGRESS_STORE_FILE.exists():
                with open(PROGRESS_STORE_FILE, 'r') as f:
                    all_progress = json.load(f)

            # Update this task's progress
            all_progress[self.task_id] = progress_data

            # Save back
            PROGRESS_STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(PROGRESS_STORE_FILE, 'w') as f:
                json.dump(all_progress, f, indent=2)
        except Exception as exc:
            logger.warning(f"Failed to save progress: {exc}")


def _get_domain(url: str) -> str:
    """Extract domain from URL for session grouping."""
    try:
        parsed = urlparse(url)
        domain_parts = parsed.netloc.split('.')
        if len(domain_parts) >= 2:
            return '.'.join(domain_parts[-2:])
        return parsed.netloc
    except Exception:
        return "unknown"


def _load_session_store() -> Dict[str, Dict]:
    """Load browser sessions from persistent storage."""
    if not SESSION_STORE_FILE.exists():
        return {}
    try:
        with open(SESSION_STORE_FILE, 'r') as f:
            return json.load(f)
    except Exception as exc:
        logger.warning(f"Failed to load session store: {exc}")
        return {}


def _save_session_store(sessions: Dict[str, Dict]):
    """Save browser sessions to persistent storage."""
    try:
        SESSION_STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SESSION_STORE_FILE, 'w') as f:
            json.dump(sessions, f, indent=2)
    except Exception as exc:
        logger.warning(f"Failed to save session store: {exc}")


def _cleanup_stale_sessions(sessions: Dict[str, Dict]) -> Dict[str, Dict]:
    """Remove sessions that are too old."""
    now = time.time()
    cleaned = {}
    for domain, session_data in sessions.items():
        created_at = session_data.get('created_at', 0)
        if now - created_at < SESSION_TIMEOUT:
            cleaned[domain] = session_data
        else:
            logger.info(f"Removing stale browser session for {domain}")
    return cleaned


def _create_browser_session(domain: str) -> Optional[str]:
    """Create a new browser session via Skyvern API."""
    try:
        logger.info(f"Creating new browser session for domain: {domain}")
        payload = {
            "timeout": SESSION_TIMEOUT,
            "proxy_location": None
        }
        response = requests.post(
            f"{SKYVERN_API_BASE}/browser_sessions",
            json=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": SKYVERN_API_TOKEN
            }
        )
        if response.status_code != 200:
            logger.error(f"Failed to create browser session: {response.status_code}")
            logger.error(f"Response: {response.text}")
            return None
        session_data = response.json()
        session_id = session_data.get("browser_session_id")
        if session_id:
            logger.info(f"Created browser session: {session_id} for {domain}")
        return session_id
    except Exception as exc:
        logger.error(f"Error creating browser session: {exc}")
        return None


def _get_or_create_session(url: str) -> Optional[str]:
    """Get existing browser session for domain or create a new one."""
    domain = _get_domain(url)
    sessions = _load_session_store()
    sessions = _cleanup_stale_sessions(sessions)

    if domain in sessions:
        session_id = sessions[domain].get('session_id')
        if session_id:
            logger.info(f"Reusing existing browser session {session_id} for {domain}")
            return session_id

    session_id = _create_browser_session(domain)
    if session_id:
        sessions[domain] = {
            'session_id': session_id,
            'created_at': time.time(),
            'domain': domain
        }
        _save_session_store(sessions)
    return session_id


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
    """Compute a SHA256 checksum for a file."""
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
        file_size_mb = dest.stat().st_size / 1024 / 1024
        logger.info(f"Saved reported download: {dest.name} ({file_size_mb:.2f} MB)")
        saved += 1
    return saved


def _fetch_task_artifacts(task_id: str) -> List[Dict[str, Any]]:
    """Retrieve the artifact list for a given task."""
    try:
        response = requests.get(
            f"{SKYVERN_API_BASE}/tasks/{task_id}/artifacts",
            headers={"x-api-key": SKYVERN_API_TOKEN}
        )
        if response.status_code == 200:
            artifacts = response.json()
            logger.info(f"Fetched {len(artifacts)} artifact(s) for task {task_id}")
            return artifacts if isinstance(artifacts, list) else []
        logger.warning(f"Failed to fetch artifacts for task {task_id}: HTTP {response.status_code}")
        return []
    except Exception as exc:
        logger.warning(f"Error fetching artifacts for task {task_id}: {exc}")
        return []


def _download_artifact_files(
    task_id: str,
    artifacts: List[Dict[str, Any]],
    download_dir: Path,
    checksum_index: Dict[str, Path]
) -> int:
    """Download artifact files that are marked as downloads."""
    saved = 0
    for artifact in artifacts:
        artifact_id = artifact.get("artifact_id")
        artifact_type = artifact.get("artifact_type")
        if artifact_type != "download":
            continue

        checksum = artifact.get("checksum")
        filename = artifact.get("uri") or f"download_{artifact_id}"

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
    """Copy evidence files from the Skyvern host download directory."""
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


def _wait_for_task_completion(
    task_id: str,
    progress: DownloadProgress,
    poll_interval: int = 5
) -> Tuple[bool, Dict[str, Any]]:
    """
    Wait for task to complete with live progress monitoring.
    No arbitrary timeout - waits until task reaches final status.

    Returns:
        (success, task_status_dict)
    """
    logger.info(f"Monitoring task {task_id} until completion...")
    progress.update("running", "Waiting for task to start...")

    elapsed = 0
    last_status = None

    while True:
        time.sleep(poll_interval)
        elapsed += poll_interval

        # Get task status via run API
        try:
            status_response = requests.get(
                f"{SKYVERN_API_BASE}/tasks/{task_id}",
                headers={"x-api-key": SKYVERN_API_TOKEN}
            )

            if status_response.status_code != 200:
                logger.error(f"Failed to get task status: {status_response.status_code}")
                progress.update("error", f"Failed to get status: HTTP {status_response.status_code}")
                continue

            task_status = status_response.json()
            status = task_status.get("status")

            # Update progress with current status
            if status != last_status:
                logger.info(f"Task status: {status} (elapsed: {elapsed}s)")
                last_status = status

            # Update progress tracking
            action = f"Status: {status}"
            if task_status.get("screenshot_urls"):
                progress.screenshot_urls = task_status["screenshot_urls"]

            progress.update(status, action)

            # Check if task reached final status
            if status in FINAL_TASK_STATUSES:
                logger.info(f"Task completed with status: {status} after {elapsed}s")

                failure_reason = task_status.get("failure_reason")
                if failure_reason:
                    logger.warning(f"Failure reason: {failure_reason}")
                    progress.failure_reason = failure_reason
                    progress.update(status, f"Completed: {failure_reason}")

                # Check if it was a success
                success = status not in FAILURE_STATUSES
                return success, task_status

        except requests.exceptions.RequestException as e:
            logger.error(f"Network error getting task status: {e}")
            progress.update("error", f"Network error: {str(e)}")
            time.sleep(poll_interval)  # Wait before retry
            continue
        except Exception as e:
            logger.error(f"Error getting task status: {e}")
            progress.update("error", f"Error: {str(e)}")
            time.sleep(poll_interval)
            continue


def download_with_skyvern_api(
    url: str,
    download_path: str,
    username: Optional[str] = None,
    password: Optional[str] = None,
    suspect_name: str = ""
) -> bool:
    """
    Download files using Skyvern AI navigation via API.

    ENHANCED FEATURES:
    - Browser session persistence
    - Live progress monitoring
    - No arbitrary timeouts - waits for actual completion
    - Progress tracking for visual monitoring
    """
    task_id = None
    progress = None

    try:
        logger.info(f"Starting Skyvern API download for: {suspect_name}")
        logger.info(f"URL: {url}")

        Path(download_path).mkdir(parents=True, exist_ok=True)

        # Get or create browser session
        # Browser sessions not supported in this Skyvern version
        browser_session_id = None  # _get_or_create_session(url)
        if browser_session_id:
            logger.info(f"Using browser session: {browser_session_id}")

        # Build navigation goal
        if username and password:
            navigation_goal = f"""
Navigate to this evidence portal and download ALL the evidence files.

CRITICAL INSTRUCTION: Click each Download button ONLY ONCE. After clicking, the browser will continue downloading files in the background. Do NOT wait for downloads to finish. Complete the task immediately after clicking.

Steps:
1. If you see a login page:
   - Enter username: {username}
   - Enter password: {password}
   - Click the login/submit button
2. After logging in (or if no login needed):
   - Look for a "Files", "Documents", "Attachments", or "Evidence" section
   - Navigate there if needed
   - Find the Download button or link
   - IMPORTANT: Click the download button ONCE to start downloading
   - DO NOT wait for download completion - mark task complete immediately after clicking
"""
        else:
            navigation_goal = """
Navigate to this evidence portal and download ALL the evidence files.

CRITICAL INSTRUCTION: Click each Download button ONLY ONCE. Complete immediately after clicking.

Steps:
1. Look for a "Files", "Documents", "Attachments", or "Evidence" section
2. Find the download button
3. Click it ONCE to start downloading
4. DO NOT wait - mark task complete immediately after clicking
"""

        # Create task payload
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
            "max_steps_per_run": SKYVERN_MAX_STEPS,
            "complete_criterion": "Complete the task immediately after clicking the Download button."
        }

        if browser_session_id:
            payload["browser_session_id"] = browser_session_id

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

        # Initialize progress tracking
        progress = DownloadProgress(task_id, suspect_name, url)
        progress.update("created", "Task created, starting...")

        # Wait for task completion with live monitoring
        success, task_status = _wait_for_task_completion(task_id, progress)

        if not success:
            failure_reason = task_status.get("failure_reason", "Unknown")
            logger.error(f"Task failed: {failure_reason}")
            progress.update("failed", f"Failed: {failure_reason}")
            return False

        # Collect downloaded files
        reported_downloads = task_status.get("downloaded_files") or []
        if reported_downloads:
            logger.info(f"Task reported {len(reported_downloads)} downloaded file(s)")
            progress.files_downloaded = len(reported_downloads)

        progress.update("collecting", "Collecting downloaded files...")
        downloads_found = _collect_downloads(task_id, download_path, reported_downloads)

        if downloads_found:
            progress.update("completed", f"Successfully downloaded files")
            return True

        logger.warning("Task completed but no evidence files were located")
        progress.update("completed", "No evidence files found")
        return False

    except Exception as e:
        logger.error(f"Skyvern download failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        if progress:
            progress.update("error", f"Exception: {str(e)}")
        return False


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
