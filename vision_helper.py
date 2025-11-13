"""
AI Vision Helper for intelligent web navigation
Uses Claude with vision to analyze pages and decide what to click
"""
import os
import base64
from anthropic import Anthropic
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

class VisionNavigator:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv('ANTHROPIC_API_KEY')
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not found in environment")
        self.client = Anthropic(api_key=self.api_key)

    def analyze_page_for_downloads(self, screenshot_path: str, context: str = "") -> dict:
        """
        Analyze a screenshot to find download links or navigation to downloads

        Returns:
        {
            'action': 'click' | 'extract' | 'navigate' | 'done' | 'error',
            'target': 'CSS selector or description',
            'reasoning': 'Why this action',
            'download_links': ['url1', 'url2'] if action is 'extract'
        }
        """
        try:
            # Read and encode screenshot
            with open(screenshot_path, 'rb') as f:
                image_data = base64.standard_b64encode(f.read()).decode('utf-8')

            prompt = f"""You are analyzing a webpage screenshot to help download files.

Context: {context if context else 'Looking for downloadable files or documents'}

Your task:
1. Look at the page and identify if there are:
   - Direct download links/buttons for files
   - Navigation tabs/buttons to access files (like "Documents", "Files", "Attachments", "Media")
   - A list of files that can be downloaded
   - Pagination to see more files

IMPORTANT: If you see a login page, that means login may still be processing. Look for ANY navigation
elements that might lead to files (Documents, Attachments, Files, etc) and return 'click' to try them.

2. Decide the BEST next action (in priority order):
   - If you see a DOWNLOAD BUTTON (like "Download", "Download All", etc), return 'click' to click it and trigger the download
   - If you see navigation to a documents section (Documents, Attachments, Files tabs), return 'click' with what to click
   - If you see a list of individual file download links (multiple links to different files), return 'extract' with the pattern
   - If you see a "Next" button for pagination, return 'navigate'
   - If you see a login page BUT there are visible navigation elements, return 'click' for those elements
   - ONLY return 'done' if you are on a page with NO navigation options and NO download links visible
   - If the page shows an error or access denied, return 'error'

   IMPORTANT: Prefer 'click' for download BUTTONS over 'extract'. Only use 'extract' for lists of file links, not for download trigger buttons

3. Provide a CSS selector or clear description of what to click/extract

Return your response in this EXACT JSON format:
{{
    "action": "click|extract|navigate|done|error",
    "target": "CSS selector or description",
    "reasoning": "Brief explanation of what you see and why this action"
}}

Be specific with selectors. For example:
- "button:has-text('Documents')" for a Documents button
- "a[href*='download']" for download links
- ".file-item a" for file download links in a list"""

            response = self.client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_data
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }]
            )

            # Parse Claude's response
            response_text = response.content[0].text.strip()
            logger.info(f"Claude vision response: {response_text}")

            # Try to parse as JSON
            import json
            try:
                # Extract JSON from response (might have markdown code blocks)
                if '```json' in response_text:
                    response_text = response_text.split('```json')[1].split('```')[0].strip()
                elif '```' in response_text:
                    response_text = response_text.split('```')[1].split('```')[0].strip()

                result = json.loads(response_text)
                return result
            except json.JSONDecodeError:
                # Try to extract key information even if not valid JSON
                logger.warning(f"Could not parse as JSON, extracting info from: {response_text}")

                # Simple fallback parsing
                action = 'error'
                if 'click' in response_text.lower():
                    action = 'click'
                elif 'extract' in response_text.lower():
                    action = 'extract'
                elif 'navigate' in response_text.lower():
                    action = 'navigate'
                elif 'done' in response_text.lower():
                    action = 'done'

                return {
                    'action': action,
                    'target': response_text,
                    'reasoning': 'Fallback parsing - see target for full response'
                }

        except Exception as e:
            logger.error(f"Error in vision analysis: {e}")
            import traceback
            traceback.print_exc()
            return {
                'action': 'error',
                'target': '',
                'reasoning': f'Vision analysis error: {str(e)}'
            }
