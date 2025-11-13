"""
Smart LLM-based parser for extracting download information from Notion fields
Uses Claude Haiku for fast, intelligent parsing of any format
"""
import os
import json
import logging
from typing import Dict, Optional
from anthropic import Anthropic

logger = logging.getLogger(__name__)

class SmartParser:
    """Uses LLM to intelligently parse download information from Notion fields"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv('ANTHROPIC_API_KEY')
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not found in environment")
        self.client = Anthropic(api_key=self.api_key)

    def parse_download_info(self, raw_text: str) -> Dict[str, str]:
        """
        Parse download information from raw Notion field text

        Args:
            raw_text: Raw text from Notion download fields (could be login, link, etc.)

        Returns:
            Dict with keys: username, password, download_link
        """
        if not raw_text or not raw_text.strip():
            logger.warning("Empty text provided to parser")
            return {'username': '', 'password': '', 'download_link': ''}

        prompt = f"""Extract the following information from this text and respond ONLY with valid JSON:

Text:
{raw_text}

Extract:
- username or email (if present)
- password (if present)
- download_link or URL (if present)

Respond with ONLY this JSON format, no other text:
{{
  "username": "extracted username/email or empty string",
  "password": "extracted password or empty string",
  "download_link": "extracted URL or empty string"
}}

Rules:
- If information is not present, use empty string ""
- Extract only the actual values, no labels
- For newline-separated credentials, line 1 is username, line 2 is password
- For colon-separated like "user:pass", split on colon
- Look for email patterns like name@domain.com
- Look for URLs starting with http:// or https://
"""

        try:
            logger.info("Calling Claude Haiku to parse credentials...")

            response = self.client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=200,
                temperature=0,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            result_text = response.content[0].text.strip()
            logger.debug(f"LLM response: {result_text}")

            # Parse JSON response
            result = json.loads(result_text)

            logger.info(f"Parsed - Username: {result.get('username', '')[:20]}..., "
                       f"Has password: {bool(result.get('password'))}, "
                       f"Has link: {bool(result.get('download_link'))}")

            return {
                'username': result.get('username', ''),
                'password': result.get('password', ''),
                'download_link': result.get('download_link', '')
            }

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM JSON response: {e}")
            logger.error(f"Response was: {result_text}")
            # Fallback to simple parsing
            return self._fallback_parse(raw_text)

        except Exception as e:
            logger.error(f"LLM parsing failed: {e}")
            # Fallback to simple parsing
            return self._fallback_parse(raw_text)

    def _fallback_parse(self, text: str) -> Dict[str, str]:
        """Simple fallback parser if LLM fails"""
        logger.warning("Using fallback parser")

        lines = text.strip().split('\n')
        if len(lines) >= 2:
            # Assume newline-separated: email on line 1, password on line 2
            return {
                'username': lines[0].strip(),
                'password': lines[1].strip(),
                'download_link': ''
            }
        elif ':' in text and '\n' not in text:
            # Colon-separated
            parts = text.split(':', 1)
            return {
                'username': parts[0].strip(),
                'password': parts[1].strip() if len(parts) > 1 else '',
                'download_link': ''
            }
        else:
            # Just username
            return {
                'username': text.strip(),
                'password': '',
                'download_link': ''
            }
