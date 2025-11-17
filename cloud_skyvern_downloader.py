#!/usr/bin/env python3
"""
Cloud Skyvern API Downloader - Fallback for when local Skyvern fails
"""
import requests
import json
import time

CLOUD_SKYVERN_API_BASE = "https://api.skyvern.com/v1"
CLOUD_SKYVERN_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjQ5MDc3Mjc1MTgsInN1YiI6Im9fNDU5OTIzNjM1MjE0NTIzOTQ4In0.M4e1HPultXky47lUO6S3STWM6PHPPJ0S2a9va8VEUfo"
CLOUD_WORKFLOW_ID = "wpid_461522695995697924"

def download_with_cloud_skyvern(url, username=None, password=None, suspect_name=None):
    """
    Trigger download using Cloud Skyvern API
    Files will be uploaded to S3, where S3 monitor will process them
    
    Returns:
        tuple: (success: bool, workflow_run_id: str or None)
    """
    
    headers = {
        "Content-Type": "application/json",
        "x-api-key": CLOUD_SKYVERN_API_KEY
    }
    
    # Format credentials
    if username and password:
        login = f"Email: {username}\nPassword: {password}"
    else:
        login = ""
    
    payload = {
        "workflow_id": CLOUD_WORKFLOW_ID,
        "parameters": {
            "URL": url,
            "login": login
        },
        "proxy_location": "RESIDENTIAL_ISP",
        "browser_session_id": None,
        "browser_address": None,
        "run_with": "agent",
        "ai_fallback": True,
        "extra_http_headers": {}
    }
    
    try:
        print(f"\n{'='*80}")
        print("☁️  CLOUD SKYVERN FALLBACK")
        print(f"{'='*80}")
        print(f"URL: {url}")
        print(f"Suspect: {suspect_name or 'Unknown'}")
        print(f"Credentials: {'Provided' if username else 'None'}")
        print()
        
        # Trigger workflow
        response = requests.post(
            f"{CLOUD_SKYVERN_API_BASE}/run/workflows",
            headers=headers,
            json=payload,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            workflow_run_id = result.get('workflow_run_id')
            
            print(f"✅ Cloud workflow triggered successfully!")
            print(f"   Workflow Run ID: {workflow_run_id}")
            print(f"   Files will be uploaded to S3 bucket")
            print(f"   S3 monitor will auto-download and upload to Dropbox")
            print(f"{'='*80}\n")
            
            return True, workflow_run_id
        else:
            print(f"❌ Cloud Skyvern API error: {response.status_code}")
            print(f"   Response: {response.text[:200]}")
            print(f"{'='*80}\n")
            return False, None
            
    except Exception as e:
        print(f"❌ Error calling Cloud Skyvern API: {e}")
        print(f"{'='*80}\n")
        return False, None

if __name__ == "__main__":
    # Test
    success, run_id = download_with_cloud_skyvern(
        url="https://matchermedia.sharefile.com/d/a2af57c1b3054ce9",
        username="eric-foia@matcher.com",
        password="Insanity10M!",
        suspect_name="Test Case"
    )
    
    if success:
        print(f"\n✅ Test successful! Workflow Run ID: {run_id}")
    else:
        print(f"\n❌ Test failed")
