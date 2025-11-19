import os
from notion_client import Client
from typing import List, Dict, Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

NOTION_LOCK_PROPERTY = os.getenv("NOTION_LOCK_PROPERTY", "Downloader Lock")
NOTION_WORKFLOW_ID_PROPERTY = os.getenv("NOTION_WORKFLOW_ID_PROPERTY", "Workflow Run ID")
CASE_NOTES_FIELDS = [
    field.strip() for field in os.getenv(
        "NOTION_CASE_NOTES_FIELDS",
        "Case Notes,Notes"
    ).split(",") if field.strip()
]

class NotionCaseClient:
    def __init__(self, api_key: str, database_id: str):
        self.client = Client(auth=api_key)
        self.database_id = database_id
    
    def get_cases_ready_for_download(self, limit: int = 1) -> List[Dict]:
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
            
            # Extract notes from configurable fields
            case_notes = ""
            for field in CASE_NOTES_FIELDS:
                case_notes = self._get_text_property(properties, field)
                if case_notes:
                    break

            workflow_run_id = None
            if NOTION_WORKFLOW_ID_PROPERTY:
                workflow_run_id = self._get_text_property(properties, NOTION_WORKFLOW_ID_PROPERTY)

            lock_owner = None
            if NOTION_LOCK_PROPERTY:
                lock_owner = self._get_text_property(properties, NOTION_LOCK_PROPERTY)

            return {
                'page_id': page_id,
                'suspect_name': suspect_name or 'Unknown',
                'download_links': download_links,
                'login_credentials': login_credentials,
                'title': self._get_title(page),
                'notes': case_notes or '',
                'workflow_run_id': workflow_run_id,
                'lock_owner': lock_owner
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
                return ''.join([rt.get('plain_text', '') for rt in rich_text])
        return None
    
    def _rich_text_payload(self, value: Optional[str]) -> Dict:
        """Build Notion rich_text payload for updates"""
        if value:
            return {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {"content": value[:2000]}
                    }
                ]
            }
        return {"rich_text": []}

    def _update_properties(self, page_id: str, properties: Dict) -> bool:
        """Helper to update arbitrary properties while handling errors"""
        try:
            self.client.pages.update(
                page_id=page_id,
                properties=properties
            )
            return True
        except Exception as e:
            logger.error(f"Error updating properties {list(properties.keys())}: {e}")
            return False

    def update_case_status(self, page_id: str, status: str) -> bool:
        """Update the Download Status of a case"""
        success = self._update_properties(
            page_id,
            {
                "Download Status": {
                    "select": {
                        "name": status
                    }
                }
            }
        )
        if success:
            logger.info(f"Updated case status to: {status}")
        return success

    def claim_case_for_download(self, page_id: str, worker_id: str) -> bool:
        """Mark a case as Downloading and attach lock owner in a single update"""
        properties: Dict = {
            "Download Status": {
                "select": {
                    "name": "Downloading"
                }
            }
        }
        if NOTION_LOCK_PROPERTY:
            properties[NOTION_LOCK_PROPERTY] = self._rich_text_payload(worker_id)
        success = self._update_properties(page_id, properties)
        if not success and NOTION_LOCK_PROPERTY:
            # Retry without lock field so status can still advance
            logger.warning("Lock property update failed; retrying without lock field.")
            fallback_properties = {
                "Download Status": properties["Download Status"]
            }
            success = self._update_properties(page_id, fallback_properties)
        if success:
            logger.info(f"Case {page_id} claimed by {worker_id}")
        return success

    def release_case_lock(self, page_id: str) -> bool:
        """Clear the worker lock field so other workers can claim the case"""
        if not NOTION_LOCK_PROPERTY:
            return True
        success = self._update_properties(
            page_id,
            {
                NOTION_LOCK_PROPERTY: self._rich_text_payload(None)
            }
        )
        if not success:
            logger.warning("Failed to clear lock property; continuing")
        return True

    def update_workflow_run_id(self, page_id: str, workflow_run_id: Optional[str]) -> bool:
        """Store or clear the workflow run id associated with this case"""
        if not NOTION_WORKFLOW_ID_PROPERTY:
            return True
        success = self._update_properties(
            page_id,
            {
                NOTION_WORKFLOW_ID_PROPERTY: self._rich_text_payload(workflow_run_id)
            }
        )
        if not success:
            logger.warning("Failed to update workflow run id; continuing")
        return success

    def update_case_status_and_workflow(self, page_id: str, status: str, workflow_run_id: Optional[str]) -> bool:
        """Convenience helper to update status and workflow metadata together"""
        properties = {
            "Download Status": {
                "select": {
                    "name": status
                }
            }
        }
        if NOTION_WORKFLOW_ID_PROPERTY:
            properties[NOTION_WORKFLOW_ID_PROPERTY] = self._rich_text_payload(workflow_run_id)
        success = self._update_properties(page_id, properties)
        if not success and NOTION_WORKFLOW_ID_PROPERTY:
            logger.warning("Workflow run id update failed; retrying with status only.")
            success = self._update_properties(
                page_id,
                {
                    "Download Status": {
                        "select": {
                            "name": status
                        }
                    }
                }
            )
        return success

    def count_cases_with_status(self, status: str) -> int:
        """Count the number of cases currently set to a given Download Status"""
        try:
            start_cursor = None
            total = 0
            while True:
                response = self.client.databases.query(
                    database_id=self.database_id,
                    filter={
                        "property": "Download Status",
                        "select": {
                            "equals": status
                        }
                    },
                    start_cursor=start_cursor
                )
                total += len(response.get("results", []))
                if response.get("has_more"):
                    start_cursor = response.get("next_cursor")
                else:
                    break
            return total
        except Exception as e:
            logger.error(f"Error counting cases with status {status}: {e}")
            return 0
    
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
    def update_failure_reason(self, page_id: str, reason: str) -> bool:
        """Update the Failure Reason property when a download fails"""
        success = self._update_properties(
            page_id,
            {
                "Failure Reason": self._rich_text_payload(reason)
            }
        )
        if success:
            logger.info(f"Updated failure reason: {reason[0:100]}...")
        return success
