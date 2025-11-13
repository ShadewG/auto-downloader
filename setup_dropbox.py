#!/usr/bin/env python3
"""
Helper script to set up Dropbox OAuth authorization
Run this interactively to generate and save the Dropbox access token
"""
import os
from dotenv import load_dotenv
from dropbox_client import DropboxClient

def main():
    load_dotenv()
    
    app_key = os.getenv('DROPBOX_APP_KEY')
    app_secret = os.getenv('DROPBOX_APP_SECRET')
    
    print("Dropbox Authorization Setup")
    print("="*50)
    print(f"App Key: {app_key}")
    print("="*50)
    
    # This will prompt for authorization
    client = DropboxClient(app_key, app_secret)
    
    if client.dbx:
        print("\n✓ Dropbox successfully authorized!")
        print("Token saved to .dropbox_token")
        print("You can now run main.py")
    else:
        print("\n✗ Dropbox authorization failed")

if __name__ == '__main__':
    main()
