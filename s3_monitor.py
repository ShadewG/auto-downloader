#!/usr/bin/env python3
"""
S3 Monitor - Detects files uploaded by Cloud Skyvern and processes them
"""
import boto3
import json
import os
import time
from pathlib import Path
from datetime import datetime
from dropbox_uploader import upload_to_dropbox

class S3Monitor:
    def __init__(self, bucket_name, aws_access_key, aws_secret_key, region='us-east-1'):
        self.bucket_name = bucket_name
        self.s3_client = boto3.client(
            's3',
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key,
            region_name=region
        )
        self.processed_files_path = '/root/case-downloader/s3_processed_files.json'
        self.processed_files = self.load_processed_files()
        
    def load_processed_files(self):
        """Load list of already processed S3 files"""
        if os.path.exists(self.processed_files_path):
            with open(self.processed_files_path, 'r') as f:
                return json.load(f)
        return {}
    
    def save_processed_files(self):
        """Save list of processed files"""
        with open(self.processed_files_path, 'w') as f:
            json.dump(self.processed_files, f, indent=2)
    
    def list_new_files(self):
        """List files in S3 bucket that haven't been processed yet"""
        try:
            response = self.s3_client.list_objects_v2(Bucket=self.bucket_name)
            
            if 'Contents' not in response:
                return []
            
            new_files = []
            for obj in response['Contents']:
                key = obj['Key']
                etag = obj['ETag'].strip('"')
                
                # Skip if already processed
                if key in self.processed_files and self.processed_files[key] == etag:
                    continue
                
                # Only process evidence files (skip metadata, etc)
                if key.endswith(('.zip', '.pdf', '.mp4', '.avi', '.mov', '.doc', '.docx')):
                    new_files.append({
                        'key': key,
                        'size': obj['Size'],
                        'etag': etag,
                        'last_modified': obj['LastModified']
                    })
            
            return new_files
        except Exception as e:
            print(f"Error listing S3 files: {e}")
            return []
    
    def download_file(self, s3_key, local_path):
        """Download file from S3 to local filesystem"""
        try:
            print(f"Downloading from S3: {s3_key}")
            self.s3_client.download_file(self.bucket_name, s3_key, local_path)
            print(f"✅ Downloaded to: {local_path}")
            return True
        except Exception as e:
            print(f"❌ Error downloading {s3_key}: {e}")
            return False
    
    def process_new_files(self, suspect_name_from_path=True):
        """Process all new files from S3"""
        new_files = self.list_new_files()
        
        if not new_files:
            return 0
        
        print(f"\n{'='*80}")
        print(f"Found {len(new_files)} new file(s) in S3 bucket: {self.bucket_name}")
        print(f"{'='*80}")
        
        processed_count = 0
        
        for file_info in new_files:
            s3_key = file_info['key']
            etag = file_info['etag']
            
            print(f"\nProcessing: {s3_key}")
            print(f"  Size: {file_info['size'] / (1024*1024):.2f} MB")
            print(f"  Modified: {file_info['last_modified']}")
            
            # Extract suspect name from S3 path if possible
            # Example: workflow_runs/wr_123/suspect_name/file.zip
            path_parts = s3_key.split('/')
            if suspect_name_from_path and len(path_parts) >= 3:
                suspect_name = path_parts[-2]  # Second to last part
            else:
                suspect_name = "Cloud_Skyvern_Download"
            
            # Create local download directory
            local_dir = f"/mnt/HC_Volume_103781006/evidence_files/{suspect_name}"
            os.makedirs(local_dir, exist_ok=True)
            
            # Local file path
            filename = os.path.basename(s3_key)
            local_path = os.path.join(local_dir, filename)
            
            # Download from S3
            if self.download_file(s3_key, local_path):
                # Upload to Dropbox
                print(f"Uploading to Dropbox...")
                dropbox_success = upload_to_dropbox(suspect_name, local_path)
                
                if dropbox_success:
                    # Mark as processed
                    self.processed_files[s3_key] = etag
                    self.save_processed_files()
                    processed_count += 1
                    print(f"✅ Successfully processed: {s3_key}")
                else:
                    print(f"⚠️ Dropbox upload failed for: {s3_key}")
            
            print()
        
        return processed_count

def monitor_s3_bucket(bucket_name, aws_access_key, aws_secret_key, poll_interval=60):
    """Continuously monitor S3 bucket for new files"""
    monitor = S3Monitor(bucket_name, aws_access_key, aws_secret_key)
    
    print(f"\n{'='*80}")
    print(f"S3 Monitor Started")
    print(f"{'='*80}")
    print(f"Bucket: {bucket_name}")
    print(f"Poll Interval: {poll_interval} seconds")
    print(f"{'='*80}\n")
    
    while True:
        try:
            processed = monitor.process_new_files()
            if processed > 0:
                print(f"\n✅ Processed {processed} file(s) from S3")
            
            # Wait before next check
            time.sleep(poll_interval)
            
        except KeyboardInterrupt:
            print("\n\nS3 Monitor stopped by user")
            break
        except Exception as e:
            print(f"Error in monitoring loop: {e}")
            time.sleep(poll_interval)

if __name__ == "__main__":
    # Load from environment variables
    from dotenv import load_dotenv
    load_dotenv()
    
    BUCKET_NAME = os.getenv('S3_BUCKET_NAME')
    AWS_ACCESS_KEY = os.getenv('AWS_ACCESS_KEY_ID')
    AWS_SECRET_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
    POLL_INTERVAL = int(os.getenv('S3_POLL_INTERVAL', '60'))
    
    if not all([BUCKET_NAME, AWS_ACCESS_KEY, AWS_SECRET_KEY]):
        print("ERROR: Missing S3 credentials in .env file")
        print("Required: S3_BUCKET_NAME, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY")
        exit(1)
    
    monitor_s3_bucket(BUCKET_NAME, AWS_ACCESS_KEY, AWS_SECRET_KEY, POLL_INTERVAL)
