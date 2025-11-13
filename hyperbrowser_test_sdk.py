#!/usr/bin/env python3
"""
Test Hyperbrowser Claude Computer Use on a failed download case using SDK
"""
import os
from hyperbrowser import Hyperbrowser
from hyperbrowser.models.agents.claude_computer_use import StartClaudeComputerUseTaskParams
from hyperbrowser.models.session import CreateSessionParams
from dotenv import load_dotenv
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

HYPERBROWSER_API_KEY = "hb_8d5e35b3ed7f0df205acbfe96e71"

def test_extract_download_links(url: str, case_name: str):
    """
    Use Hyperbrowser Claude to extract all download links from a page
    """
    logger.info(f"Testing Hyperbrowser on: {case_name}")
    logger.info(f"URL: {url}")

    client = Hyperbrowser(api_key=HYPERBROWSER_API_KEY)

    # Task for Claude to extract download links
    task = f"""
    Go to this URL: {url}

    Find ALL download links for files (PDFs, videos, documents, media, etc.).

    For each download link you find:
    1. Get the EXACT direct download URL (not just the button - the actual href or download URL)
    2. Note what type of file it is (if visible)

    Return a list of all download URLs you found in this format:
    - URL 1: <exact_url>
    - URL 2: <exact_url>
    etc.

    If there are multiple pages (pagination), check all pages.

    Return ONLY the list of URLs, nothing else.
    """

    logger.info("Starting Hyperbrowser task...")

    try:
        params = StartClaudeComputerUseTaskParams(
            task=task,
            llm="claude-sonnet-4-5",
            max_steps=20,  # Plan limit is 25 max
            session_options=CreateSessionParams(accept_cookies=True)
        )

        result = client.agents.claude_computer_use.start_and_wait(params=params)

        if result.status == "completed":
            logger.info("✓ Task completed successfully!")
            logger.info(f"\nExtracted download links:\n{result.data.final_result}")

            # Also log steps taken
            if hasattr(result.data, 'steps'):
                logger.info(f"\nSteps taken: {len(result.data.steps)}")

            return result.data.final_result
        else:
            logger.error(f"Task failed: {result.error if hasattr(result, 'error') else 'Unknown error'}")
            return None

    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return None

def main():
    # Test case - Austin Green (evidence.com direct download)
    test_cases = [
        {
            "name": "Austin Green",
            "url": "https://monroesheriffmi.evidence.com/?class=Evidence&proc=PackagePublic&action=downloadpkg&package_id=973e1a9aef6e40dea83316a1fd515f67&token=%2FP%2FL%2FhaW27mReSzFvxtpDeVI91BT0TxHBsTor2ahgJ3fbZQI4d2VyzSSELgPNnX5t%2FFuvpgAJK2O%2BODTXWg9oC8RSrHV1AaNIspBAHNtK%2FUOwyjpmAqSR5wOANXW8iPVUTfhJwvBgcjhhy8zqGs3BmrsdVJDTVcyCevlhapoBXVbILywAYpFKpzilQkrH3dgJLpM4V73OqPZU2ajq8ePe2G1RK49JjLn6WuYDEp2BTyjvL2CAg%2BFhDYcxe%2F8OVyj&batch_id=5a42e55b90004100a3906a466bf40282&ver=2"
        },
    ]

    for test_case in test_cases:
        print("\n" + "="*60)
        result = test_extract_download_links(test_case["url"], test_case["name"])
        print("="*60 + "\n")

        if result:
            print(f"SUCCESS for {test_case['name']}")
            print(f"\nResult:\n{result}")
        else:
            print(f"FAILED for {test_case['name']}")

if __name__ == '__main__':
    main()
