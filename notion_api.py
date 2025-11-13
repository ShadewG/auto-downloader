import os
from notion_client import Client
from datetime import datetime
from typing import List, Dict, Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class NotionCaseClient:
    def __init__(self, api_key: str, database_id: str):
        self.client = Client(auth=api_key)
        self.database_id = database_id
    
    def get_cases_ready_for_download(self, limit: int = 4) -> List[Dict]:
        """
        Query Notion database for cases with 'Download Status' not empty 
        and equals 'Ready for Download'
        """
        try:
            response = self.client.databases.query(
                database_id=self.database_id,
                filter={
                    "and": [
                        {
                            "property": "Download Status",
                            "select": {
                                "equals": "Ready For Download"
                            }
                        },
                        {
                            "property": "Download Link",
                            "url": {
                                "is_not_empty": True
                            }
                        }
                    ]
                },
                page_size=limit
            )
            
            cases = []
            for page in response.get('results', []):
                case_data = self._extract_case_data(page)
                if case_data:
                    cases.append(case_data)
            
            logger.info(f"Found {len(cases)} cases ready for download")
            return cases
        
        except Exception as e:
            logger.error(f"Error querying Notion: {e}")
            return []
    
    def _extract_case_data(self, page: Dict) -> Optional[Dict]:
        """Extract relevant data from a Notion page"""
        try:
            properties = page.get('properties', {})
            
            # Extract suspect name
            suspect_name = self._get_suspect_name(properties, page)
            
            # Extract download links from multiple fields
            download_links = self._get_download_links(properties)
            
            # Extract login credentials if available
            login_credentials = self._get_text_property(properties, 'Download Login')
            
            # Get page ID for updating status later
            page_id = page.get('id')
            
            if not download_links:
                logger.warning(f"No download links found for case: {suspect_name}")
                return None
            
            return {
                'page_id': page_id,
                'suspect_name': suspect_name or 'Unknown',
                'download_links': download_links,
                'login_credentials': login_credentials,
                'title': self._get_title(page)
            }
        
        except Exception as e:
            logger.error(f"Error extracting case data: {e}")
            return None
    
    def _get_suspect_name(self, properties: Dict, page: Dict) -> str:
        """Get suspect name from Suspect field or page title (first line only)"""
        # Try Suspect field first
        suspect_field = properties.get('Suspect', {})
        
        if suspect_field.get('type') == 'rich_text':
            rich_text = suspect_field.get('rich_text', [])
            if rich_text and len(rich_text) > 0:
                full_text = rich_text[0].get('plain_text', '')
                # Take only the first line to avoid extra info like reference numbers
                return full_text.split('\n')[0].strip()
        elif suspect_field.get('type') == 'title':
            title_array = suspect_field.get('title', [])
            if title_array and len(title_array) > 0:
                full_text = title_array[0].get('plain_text', '')
                return full_text.split('\n')[0].strip()
        
        # Fall back to page title
        return self._get_title(page)
    
    def _get_title(self, page: Dict) -> str:
        """Extract page title"""
        properties = page.get('properties', {})
        
        # Look for title property (usually 'Name' or 'Title')
        for prop_name, prop_value in properties.items():
            if prop_value.get('type') == 'title':
                title_array = prop_value.get('title', [])
                if title_array and len(title_array) > 0:
                    return title_array[0].get('plain_text', '')
        
        return 'Untitled'
    
    def _get_download_links(self, properties: Dict) -> List[str]:
        """Extract download links from multiple fields"""
        links = []
        
        # Check Download Link (1-3) which should be URL type
        for field_name in ['Download Link', 'Download Link (2)', 'Download Link (3)']:
            url = self._get_url_property(properties, field_name)
            if url:
                links.append(url)
        
        # Check Download Link (4) which is a text field with multiple links
        link_4_text = self._get_text_property(properties, 'Download Links (4)')
        if link_4_text:
            # Split by newlines or spaces to get multiple links
            additional_links = [l.strip() for l in link_4_text.split() if l.strip().startswith('http')]
            links.extend(additional_links)
        
        return links
    
    def _get_url_property(self, properties: Dict, field_name: str) -> Optional[str]:
        """Get URL from a URL-type property"""
        prop = properties.get(field_name, {})
        if prop.get('type') == 'url':
            return prop.get('url')
        return None
    
    def _get_text_property(self, properties: Dict, field_name: str) -> Optional[str]:
        """Get text from a rich_text property"""
        prop = properties.get(field_name, {})
        if prop.get('type') == 'rich_text':
            rich_text = prop.get('rich_text', [])
            if rich_text and len(rich_text) > 0:
                return rich_text[0].get('plain_text', '')
        return None
    
    def update_case_status(self, page_id: str, status: str) -> bool:
        """Update the Download Status of a case"""
        try:
            self.client.pages.update(
                page_id=page_id,
                properties={
                    "Download Status": {
                        "select": {
                            "name": status
                        }
                    }
                }
            )
            logger.info(f"Updated case status to: {status}")
            return True
        except Exception as e:
            logger.error(f"Error updating case status: {e}")
            return False
    
    def add_dropbox_link(self, page_id: str, dropbox_link: str) -> bool:
        """Add Dropbox link to the case"""
        try:
            self.client.pages.update(
                page_id=page_id,
                properties={
                    "Dropbox URL": {
                        "url": dropbox_link
                    }
                }
            )
            logger.info(f"Added Dropbox link to case")
            return True
        except Exception as e:
            logger.error(f"Error adding Dropbox link: {e}")
            return False
    
    def reset_stuck_uploading_cases(self) -> int:
        """Reset cases stuck in 'Uploading' status back to 'Ready For Download'"""
        try:
            # Find all cases with Uploading status
            response = self.client.databases.query(
                database_id=self.database_id,
                filter={
                    "property": "Download Status",
                    "select": {
                        "equals": "Uploading"
                    }
                },
                page_size=100
            )
            
            count = 0
            for page in response.get('results', []):
                # Check if they have a download link
                props = page['properties']
                link = self._get_url_property(props, 'Download Link')
                
                if link:  # Only reset if they have a download link
                    self.update_case_status(page['id'], 'Ready For Download')
                    count += 1
            
            logger.info(f"Reset {count} cases from Uploading to Ready For Download")
            return count
        except Exception as e:
            logger.error(f"Error resetting stuck cases: {e}")
            return 0
