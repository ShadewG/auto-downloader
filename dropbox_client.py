import os
import dropbox
from dropbox import DropboxOAuth2FlowNoRedirect, DropboxTeam
from dropbox.common import PathRoot
from datetime import datetime
from typing import Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Chunk size for large file uploads (4MB chunks)
CHUNK_SIZE = 4 * 1024 * 1024

class DropboxClient:
    def __init__(self, app_key: str, app_secret: str, member_id: str = None, token_file: str = '.dropbox_token'):
        self.app_key = app_key
        self.app_secret = app_secret
        self.member_id = member_id
        self.token_file = token_file
        self.dbx = None
        self.dbx_team = None
        
        # Initialize connection
        self._connect()
    
    def _connect(self):
        """Connect to Dropbox using OAuth with team folder namespace access"""
        # Try to load existing token
        access_token = self._load_token()
        
        if not access_token:
            # Generate new token
            access_token = self._generate_new_token()
            if access_token:
                self._save_token(access_token)
        
        if access_token:
            try:
                # Get refresh token for auto-renewal
                refresh_token = self._load_refresh_token()
                
                # Create team client with OAuth2FlowResult for auto-refresh
                if refresh_token:
                    self.dbx_team = DropboxTeam(
                        oauth2_access_token=access_token,
                        oauth2_refresh_token=refresh_token,
                        app_key=self.app_key,
                        app_secret=self.app_secret
                    )
                    logger.info("Connected with refresh token - will auto-renew")
                else:
                    self.dbx_team = DropboxTeam(access_token)
                    logger.warning("No refresh token - token will expire!")
                
                # Access team folder namespace using a team member
                if self.member_id:
                    # Get team folder namespace ID for 'Insanity'
                    team_folders = self.dbx_team.team_team_folder_list()
                    insanity_namespace_id = None
                    for folder in team_folders.team_folders:
                        if folder.name == 'Insanity':
                            # Get the namespace ID from the team folder
                            insanity_namespace_id = folder.team_folder_id
                            logger.info(f"Found Insanity folder with namespace ID: {insanity_namespace_id}")
                            break
                    
                    # Create client with team member access
                    self.dbx = self.dbx_team.as_user(self.member_id)
                    
                    # CRITICAL: Set path root to the team folder namespace
                    # This makes all paths relative to the Insanity team folder
                    if insanity_namespace_id:
                        self.dbx = self.dbx.with_path_root(PathRoot.namespace_id(insanity_namespace_id))
                        logger.info(f"Connected to Dropbox Team with namespace access (member: {self.member_id}, namespace: {insanity_namespace_id})")
                    else:
                        logger.warning("Could not find Insanity team folder namespace ID")
                        logger.info(f"Connected to Dropbox Team (member: {self.member_id})")
                else:
                    # Fallback to regular client
                    self.dbx = dropbox.Dropbox(access_token)
                    logger.info("Connected to Dropbox")
                
            except Exception as e:
                logger.error(f"Error connecting to Dropbox: {e}")
    
    def _load_token(self) -> Optional[str]:
        """Load access token from file"""
        if os.path.exists(self.token_file):
            with open(self.token_file, 'r') as f:
                data = f.read().strip()
                # Handle both old format (just token) and new format (JSON)
                if data.startswith('{'):
                    import json
                    token_data = json.loads(data)
                    return token_data.get('access_token')
                return data
        return None
    
    def _load_refresh_token(self) -> Optional[str]:
        """Load refresh token from file"""
        if os.path.exists(self.token_file):
            with open(self.token_file, 'r') as f:
                data = f.read().strip()
                if data.startswith('{'):
                    import json
                    token_data = json.loads(data)
                    return token_data.get('refresh_token')
        return None
    
    def _save_token(self, token: str, refresh_token: str = None):
        """Save access and refresh tokens to file"""
        import json
        token_data = {
            'access_token': token,
            'refresh_token': refresh_token
        }
        with open(self.token_file, 'w') as f:
            json.dump(token_data, f)
        logger.info("Dropbox tokens saved (access + refresh)")
    
    def _generate_new_token(self) -> Optional[str]:
        """Generate new OAuth token using app key and secret"""
        try:
            auth_flow = DropboxOAuth2FlowNoRedirect(
                self.app_key,
                consumer_secret=self.app_secret,
                token_access_type='offline'
            )
            
            authorize_url = auth_flow.start()
            logger.info(f"""
            ====================================
            DROPBOX AUTHORIZATION REQUIRED
            ====================================
            1. Go to: {authorize_url}
            2. Click 'Allow' (you might need to log in first)
            3. Copy the authorization code
            4. Enter it below
            ====================================""")
            
            auth_code = input("Enter the authorization code here: ").strip()
            
            oauth_result = auth_flow.finish(auth_code)
            access_token = oauth_result.access_token
            
            logger.info("Successfully generated new Dropbox token")
            return access_token
        
        except Exception as e:
            logger.error(f"Error generating Dropbox token: {e}")
            return None
    
    def upload_file(self, local_path: str, dropbox_path: str) -> bool:
        """Upload a file to Dropbox (handles large files with chunked upload)"""
        try:
            file_size = os.path.getsize(local_path)
            
            # For files larger than 150MB, use chunked upload
            if file_size > 150 * 1024 * 1024:
                return self._upload_large_file(local_path, dropbox_path, file_size)
            
            # Standard upload for smaller files
            with open(local_path, 'rb') as f:
                file_data = f.read()
            
            self.dbx.files_upload(
                file_data,
                dropbox_path,
                mode=dropbox.files.WriteMode.overwrite
            )
            
            logger.info(f"Uploaded: {local_path} -> {dropbox_path}")
            return True
        
        except Exception as e:
            logger.error(f"Error uploading file {local_path}: {e}")
            return False
    
    def _upload_large_file(self, local_path: str, dropbox_path: str, file_size: int) -> bool:
        """Upload large file using chunked upload"""
        try:
            logger.info(f"Uploading large file ({file_size / 1024 / 1024:.1f} MB) in chunks: {local_path}")
            
            with open(local_path, 'rb') as f:
                # Start upload session
                session_start = self.dbx.files_upload_session_start(f.read(CHUNK_SIZE))
                cursor = dropbox.files.UploadSessionCursor(
                    session_id=session_start.session_id,
                    offset=f.tell()
                )
                
                # Upload chunks
                while f.tell() < file_size:
                    chunk_size = min(CHUNK_SIZE, file_size - f.tell())
                    
                    if f.tell() + chunk_size >= file_size:
                        # Last chunk - finish session
                        commit = dropbox.files.CommitInfo(
                            path=dropbox_path,
                            mode=dropbox.files.WriteMode.overwrite
                        )
                        self.dbx.files_upload_session_finish(
                            f.read(chunk_size),
                            cursor,
                            commit
                        )
                    else:
                        # Continue uploading
                        self.dbx.files_upload_session_append_v2(
                            f.read(chunk_size),
                            cursor
                        )
                        cursor.offset = f.tell()
                    
                    # Log progress
                    progress = (f.tell() / file_size) * 100
                    logger.info(f"Upload progress: {progress:.1f}%")
            
            logger.info(f"Large file uploaded successfully: {local_path} -> {dropbox_path}")
            return True
        
        except Exception as e:
            logger.error(f"Error uploading large file {local_path}: {e}")
            return False
    
    def create_folder(self, folder_path: str) -> bool:
        """Create a folder in Dropbox"""
        try:
            # Check if folder already exists
            try:
                self.dbx.files_get_metadata(folder_path)
                logger.info(f"Folder already exists: {folder_path}")
                return True
            except:
                pass
            
            # Create folder
            self.dbx.files_create_folder_v2(folder_path)
            logger.info(f"Created folder: {folder_path}")
            return True
        
        except Exception as e:
            # Folder might already exist
            if 'conflict' in str(e).lower():
                logger.info(f"Folder already exists: {folder_path}")
                return True
            logger.error(f"Error creating folder {folder_path}: {e}")
            return False
    
    def get_shared_link(self, dropbox_path: str) -> Optional[str]:
        """Get or create a shared link for a file/folder"""
        try:
            # Try to get existing shared link
            try:
                links = self.dbx.sharing_list_shared_links(path=dropbox_path)
                if links.links:
                    return links.links[0].url
            except:
                pass
            
            # Create new shared link
            shared_link = self.dbx.sharing_create_shared_link_with_settings(dropbox_path)
            return shared_link.url
        
        except Exception as e:
            logger.error(f"Error getting shared link for {dropbox_path}: {e}")
            return None
    
    def upload_folder(self, local_folder: str, dropbox_folder: str) -> bool:
        """Upload entire folder to Dropbox"""
        try:
            # Create base folder
            self.create_folder(dropbox_folder)
            
            # Walk through local folder and upload all files
            for root, dirs, files in os.walk(local_folder):
                for filename in files:
                    local_file_path = os.path.join(root, filename)
                    
                    # Calculate relative path
                    relative_path = os.path.relpath(local_file_path, local_folder)
                    dropbox_file_path = os.path.join(dropbox_folder, relative_path).replace('\\', '/')
                    
                    # Ensure Dropbox path starts with /
                    if not dropbox_file_path.startswith('/'):
                        dropbox_file_path = '/' + dropbox_file_path
                    
                    # Upload file (handles both small and large files)
                    if not self.upload_file(local_file_path, dropbox_file_path):
                        logger.error(f"Failed to upload: {local_file_path}")
                        return False
            
            logger.info(f"Uploaded folder: {local_folder} -> {dropbox_folder}")
            return True
        
        except Exception as e:
            logger.error(f"Error uploading folder {local_folder}: {e}")
            return False
