#!/usr/bin/env python3
"""
LLM-based credential parser using Claude API
Handles ANY format of credentials automatically
"""
import os
import json
import logging
import anthropic
from typing import Dict, Optional

logger = logging.getLogger(__name__)


def parse_credentials_with_llm(
    credential_text: str,
    anthropic_api_key: Optional[str] = None
) -> Dict[str, any]:
    """
    Use Claude to intelligently parse credentials from any format.

    Args:
        credential_text: Raw text from Notion's "Login Credentials" field
        anthropic_api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)

    Returns:
        Dict with keys: username, password, download_links (list)
        Example: {
            "username": "autumn@matcher.com",
            "password": "Insanity10M!",
            "download_links": []
        }
    """
    if not credential_text or not credential_text.strip():
        logger.warning("Empty credential text provided")
        return {"username": "", "password": "", "download_links": []}

    # Get API key
    api_key = anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("No Anthropic API key provided")
        return {"username": "", "password": "", "download_links": []}

    try:
        client = anthropic.Anthropic(api_key=api_key)

        # Create prompt for Claude
        prompt = f"""You are a credential parser. Extract the username, password, and any download URLs from the following text.

The text may contain:
- Username and password in various formats (newline-separated, colon-separated, slash-separated, space-separated, etc.)
- Download URLs (http/https links)
- Extra notes or instructions

TEXT TO PARSE:
{credential_text}

Return ONLY a JSON object with this exact structure (no markdown, no explanation):
{{
  "username": "extracted_username",
  "password": "extracted_password",
  "download_links": ["url1", "url2"]
}}

Rules:
- If username is an email, extract the full email address
- If password contains special characters, preserve them exactly
- If there are multiple URLs, include all of them in download_links array
- If no username/password/links found, use empty string or empty array
- Return valid JSON only, no other text"""

        # Call Claude API with Haiku for fast/cheap parsing
        response = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=500,
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )

        # Extract the response text
        response_text = response.content[0].text.strip()

        # Remove markdown code blocks if present
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            response_text = "\n".join(lines[1:-1] if len(lines) > 2 else lines)
            response_text = response_text.replace("```json", "").replace("```", "").strip()

        # Parse JSON response
        parsed = json.loads(response_text)

        # Validate structure
        result = {
            "username": str(parsed.get("username", "")).strip(),
            "password": str(parsed.get("password", "")).strip(),
            "download_links": parsed.get("download_links", [])
        }

        logger.info(f"LLM parsed credentials - Username: {result['username']}, Has password: {bool(result['password'])}, Links: {len(result['download_links'])}")

        return result

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Claude response as JSON: {e}")
        logger.error(f"Response was: {response_text}")
        return {"username": "", "password": "", "download_links": []}

    except Exception as e:
        logger.error(f"LLM credential parsing failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {"username": "", "password": "", "download_links": []}


# Test function
if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    # Test cases
    test_cases = [
        "autumn@matcher.com / Insanity10M!",
        "username: testuser\npassword: TestPass123!",
        "john.doe@example.com\nMySecret99",
        "user:pass123",
        """Username: alice@company.com
Password: Complex!Pass#2024
Download: https://portal.example.com/files/12345""",
    ]

    print("=" * 80)
    print("LLM CREDENTIAL PARSER TEST")
    print("=" * 80)
    print()

    for i, test_text in enumerate(test_cases, 1):
        print(f"Test {i}:")
        print(f"Input: {repr(test_text)}")

        result = parse_credentials_with_llm(test_text)

        print(f"Output:")
        print(f"  Username: {result['username']}")
        print(f"  Password: {result['password']}")
        print(f"  Download Links: {result['download_links']}")
        print()
