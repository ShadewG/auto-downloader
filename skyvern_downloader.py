#!/usr/bin/env python3
"""
Skyvern-based downloader module

This module provides a Skyvern alternative to the Playwright approach.
Skyvern uses AI to understand and interact with web UIs more dynamically.
"""

import os
import asyncio
import logging
from pathlib import Path
from typing import Optional, List

logger = logging.getLogger(__name__)


async def download_with_skyvern(
    url: str,
    download_path: str,
    username: Optional[str] = None,
    password: Optional[str] = None,
    suspect_name: str = ""
) -> bool:
    """
    Download files using Skyvern AI navigation

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
        from skyvern import AsyncSkyvern
        from skyvern.forge.sdk.api.llm.models import LLMProvider

        logger.info(f"Starting Skyvern download for: {suspect_name}")
        logger.info(f"URL: {url}")

        # Create download directory
        Path(download_path).mkdir(parents=True, exist_ok=True)

        # Build the task prompt
        if username and password:
            task_prompt = f"""
Navigate to this page and download the evidence files.

If you see a login page:
1. Enter username: {username}
2. Enter password: {password}
3. Click the login/submit button

After logging in (or if no login is needed):
1. Look for a "Files", "Documents", or "Attachments" section and navigate there if needed
2. Find the download button or link (could be labeled "Download", "Download All", or similar)
3. Click it to download the files
4. Wait for downloads to complete

The page may redirect automatically to the files section.
"""
        else:
            task_prompt = """
Navigate to this page and download the evidence files.

Steps:
1. Look for a "Files", "Documents", or "Attachments" section and navigate there if needed
2. Find the download button or link (could be labeled "Download", "Download All", or similar)
3. Click it to download the files
4. Wait for downloads to complete

The page may redirect automatically to the files section.
"""

        logger.info(f"Skyvern task prompt: {task_prompt[:200]}...")

        # Initialize Skyvern
        # Use Anthropic Claude if API key is available
        api_key = os.getenv('ANTHROPIC_API_KEY')
        if api_key:
            logger.info("Using Anthropic Claude for Skyvern")
            skyvern = AsyncSkyvern(
                llm_provider=LLMProvider.ANTHROPIC,
                llm_api_key=api_key
            )
        else:
            logger.warning("No ANTHROPIC_API_KEY found, using default LLM")
            skyvern = AsyncSkyvern()

        # Run the task
        logger.info("Executing Skyvern task...")
        task = await skyvern.run_task(
            url=url,
            prompt=task_prompt,
            download_dir=download_path
        )

        logger.info(f"Skyvern task completed with status: {task.status}")

        # Check if task succeeded
        if task.status == "completed" or task.status == "success":
            # Check for downloaded files
            files = list(Path(download_path).glob("*"))
            if files:
                logger.info(f"Successfully downloaded {len(files)} file(s) with Skyvern:")
                for f in files:
                    size_mb = f.stat().st_size / 1024 / 1024
                    logger.info(f"  - {f.name} ({size_mb:.2f} MB)")
                return True
            else:
                logger.warning("Skyvern task completed but no files found")
                return False
        else:
            failure_reason = getattr(task, 'failure_reason', 'Unknown')
            logger.error(f"Skyvern task failed: {failure_reason}")
            return False

    except ImportError as e:
        logger.error(f"Skyvern not installed: {e}")
        logger.error("Install with: pip install skyvern")
        return False

    except Exception as e:
        logger.error(f"Skyvern download failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


async def test_skyvern_james_rinehart():
    """
    Test Skyvern with the James Rinehart case
    """
    url = "http://url5374.evidencelibrary.com/ls/click?upn=u001.1DmiTs-2BP7119MjX8j-2FWa7k-2FImRc1ptqmNNLQ0vvxQvwGXF5h9C84oCIEcDMbiJOOM1dFY1ZKtcXYby5O0Muu2mYFHCugv5HiGCR3-2BvXAxZ5aOLAinVzursotXRwqVzFSTC0l_QFGgicBhV6w8RCVzLzEsTzQcjkg8TOaakJfQ2R8mv9SYNKV2bCQWjpr9oHpP9a6CpyL6drUkNuaYq-2BkUmfmWWdd4Od8aY0ZnxkyWOHDbzy2B3Q4Jn-2BISBzfpuhCKHYFVtwsNJtz8y6HeXAjD1TjqOV2EqYCQXBrxxIKvC5urBwcsmyrBivYW-2FULfgB1IPBTUAWGp1bmW6zsudigFhrcg-2B6e9CnddTTfiORF2Aes3S-2BQ-3D"

    download_dir = "/tmp/skyvern_downloads/james_rinehart"

    print("=" * 80)
    print("SKYVERN TEST: James Rinehart Jr.")
    print("=" * 80)
    print()

    success = await download_with_skyvern(
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

    # Run test
    result = asyncio.run(test_skyvern_james_rinehart())
    exit(0 if result else 1)
