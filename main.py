#!/usr/bin/env python3
import os
import sys
import time
import shutil
from datetime import datetime
from dotenv import load_dotenv
import logging

from notion_api import NotionCaseClient
from dropbox_client import DropboxClient
from downloader import FileDownloader

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class CaseDownloadOrchestrator:
    def __init__(self):
        # Load environment variables
        load_dotenv()
        
        self.notion_api_key = os.getenv('NOTION_API_KEY')
        self.notion_db_id = os.getenv('NOTION_DATABASE_ID')
        self.dropbox_app_key = os.getenv('DROPBOX_APP_KEY')
        self.dropbox_app_secret = os.getenv('DROPBOX_APP_SECRET')
        self.dropbox_member_id = os.getenv("DROPBOX_MEMBER_ID")
        self.download_path = os.getenv('DOWNLOAD_PATH', '/tmp/case_downloads')
        self.check_interval = int(os.getenv('CHECK_INTERVAL', 3600))
        self.test_mode = os.getenv('TEST_MODE', 'True').lower() == 'true'
        self.test_case_limit = int(os.getenv('TEST_CASE_LIMIT', 4))
        
        # Initialize clients
        self.notion = NotionCaseClient(self.notion_api_key, self.notion_db_id)
        self.dropbox = DropboxClient(self.dropbox_app_key, self.dropbox_app_secret, self.dropbox_member_id)
        self.downloader = FileDownloader(self.download_path)
    
    def process_case(self, case: dict) -> bool:
        """Process a single case: download files and upload to Dropbox"""
        page_id = case['page_id']
        suspect_name = case['suspect_name']
        download_links = case['download_links']
        login_creds = case['login_credentials']
        
        logger.info(f"Processing case: {suspect_name}")
        logger.info(f"Found {len(download_links)} download link(s)")
        
        # Update status to Downloading
        self.notion.update_case_status(page_id, "Auto Downloading")
        
        # Create case folder with suspect name and date
        date_str = datetime.now().strftime("%Y-%m-%d")
        case_folder_name = f"{suspect_name} {date_str}"
        
        # Sanitize folder name
        case_folder_name = self._sanitize_filename(case_folder_name)
        
        local_case_path = os.path.join(self.download_path, case_folder_name)
        os.makedirs(local_case_path, exist_ok=True)
        
        # Download all files
        downloaded_files = []
        for i, url in enumerate(download_links, 1):
            logger.info(f"Downloading file {i}/{len(download_links)} from: {url}")
            
            downloaded_file = self.downloader.download_file(
                url,
                case_folder_name,
                login_creds
            )
            
            if downloaded_file:
                downloaded_files.append(downloaded_file)
                logger.info(f"Successfully downloaded: {downloaded_file}")
            else:
                logger.warning(f"Failed to download from: {url}")
        
        if not downloaded_files:
            logger.error(f"No files downloaded for case: {suspect_name}")
            self.notion.update_case_status(page_id, "Auto Download Failed")
            return False
        
        logger.info(f"Downloaded {len(downloaded_files)} file(s) for {suspect_name}")
        
        # Update status to Uploading
        self.notion.update_case_status(page_id, "Auto Uploading")
        
        # Upload to Dropbox
        dropbox_folder_path = f"/Auto Foia/{case_folder_name}"
        
        logger.info(f"Uploading to Dropbox: {dropbox_folder_path}")
        upload_success = self.dropbox.upload_folder(local_case_path, dropbox_folder_path)
        
        if upload_success:
            # Get shared link
            shared_link = self.dropbox.get_shared_link(dropbox_folder_path)
            
            if shared_link:
                # Add Dropbox link to Notion
                self.notion.add_dropbox_link(page_id, shared_link)
            
            # Update status to Uploaded
            self.notion.update_case_status(page_id, "Auto Uploaded")
            logger.info(f"Successfully processed case: {suspect_name}")
            
            # Clean up local files
            try:
                shutil.rmtree(local_case_path)
                logger.info(f"Cleaned up local files for: {suspect_name}")
            except Exception as e:
                logger.warning(f"Error cleaning up {local_case_path}: {e}")
            
            return True
        else:
            logger.error(f"Failed to upload to Dropbox for case: {suspect_name}")
            self.notion.update_case_status(page_id, "Auto Upload Failed")
            return False
    
    def run_once(self):
        """Run the download process once"""
        logger.info("Starting case download process...")
        
        # Get cases ready for download
        limit = self.test_case_limit if self.test_mode else 100
        cases = self.notion.get_cases_ready_for_download(limit=limit)
        
        if not cases:
            logger.info("No cases ready for download")
            return
        
        logger.info(f"Found {len(cases)} case(s) ready for download")
        
        # Process each case
        success_count = 0
        for i, case in enumerate(cases, 1):
            logger.info(f"\n{'='*60}")
            logger.info(f"Processing case {i}/{len(cases)}")
            logger.info(f"{'='*60}\n")
            
            try:
                if self.process_case(case):
                    success_count += 1
            except Exception as e:
                logger.error(f"Error processing case {case['suspect_name']}: {e}")
                continue
        
        logger.info(f"\n{'='*60}")
        logger.info(f"Download process completed")
        logger.info(f"Successfully processed: {success_count}/{len(cases)} cases")
        logger.info(f"{'='*60}\n")
    
    def run_continuous(self):
        """Run continuously, checking for new cases periodically"""
        logger.info("Starting continuous monitoring mode...")
        logger.info(f"Check interval: {self.check_interval} seconds ({self.check_interval//60} minutes)")
        
        while True:
            try:
                self.run_once()
            except Exception as e:
                logger.error(f"Error in continuous run: {e}")
            
            logger.info(f"Waiting {self.check_interval} seconds before next check...")
            time.sleep(self.check_interval)
    
    def _sanitize_filename(self, filename: str) -> str:
        """Remove invalid characters from filename and truncate if too long"""
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        filename = filename.strip()

        # Limit to 200 characters to stay well under filesystem limit (255)
        # This leaves room for date suffix and file extensions
        if len(filename) > 200:
            filename = filename[:200].strip()

        return filename

def main():
    orchestrator = CaseDownloadOrchestrator()
    
    # Check if we should run in test mode or continuous mode
    if orchestrator.test_mode:
        logger.info("Running in TEST MODE (one-time run)")
        orchestrator.run_once()
    else:
        logger.info("Running in CONTINUOUS MODE")
        orchestrator.run_continuous()

if __name__ == '__main__':
    main()
