#!/usr/bin/env python3
from dropbox_client import DropboxClient
import os
from dotenv import load_dotenv

load_dotenv()

# Initialize Dropbox client
DROPBOX_ACCESS_TOKEN = os.getenv('DROPBOX_ACCESS_TOKEN')
dropbox_client = DropboxClient(DROPBOX_ACCESS_TOKEN) if DROPBOX_ACCESS_TOKEN else None

def upload_to_dropbox(suspect_name, local_file_path):
    """Upload file to Dropbox"""
    if not dropbox_client:
        print(f"Warning: Dropbox not configured, skipping upload")
        return False
    
    try:
        return dropbox_client.upload_file(local_file_path, suspect_name)
    except Exception as e:
        print(f"Error uploading to Dropbox: {e}")
        return False
