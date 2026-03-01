import os
import subprocess
import time
from pathlib import Path
from typing import List, Dict, Optional
import hashlib
import re
from config import Config

class PinterestDownloader:
    """Handles Pinterest image downloading via pinterest-dl."""
    
    def __init__(self):
        """Initialize downloader."""
        self.download_dir = Config.DOWNLOAD_DIR
        self.download_dir.mkdir(exist_ok=True)
        self.timeout = Config.DOWNLOAD_TIMEOUT
    
    @staticmethod
    def check_pinterest_dl() -> bool:
        """Check if pinterest-dl is installed."""
        try:
            result = subprocess.run(
                ['pinterest-dl', '--help'],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
    
    def download_images(self, query: str, limit: int = 50) -> List[Dict]:
        """
        Download images using pinterest-dl.
        Returns list of downloaded image info.
        """
        # Create unique download directory for this query
        query_hash = hashlib.md5(query.encode()).hexdigest()[:8]
        safe_query = re.sub(r'[^\w\-_]', '_', query)[:30]
        download_path = self.download_dir / f"{safe_query}_{query_hash}"
        download_path.mkdir(exist_ok=True)
        
        # Build command
        cmd = [
            'pinterest-dl', 'search', query,
            '-o', str(download_path),
            '--num', str(limit)
        ]
        
        cmd_str = ' '.join(cmd)
        print(f"▶ Executing: {cmd_str}")
        
        try:
            # Execute command
            result = subprocess.run(
                cmd_str,
                shell=True,
                capture_output=True,
                text=True,
                timeout=self.timeout
            )
            
            if result.returncode != 0:
                print(f"✗ Pinterest-dl error: {result.stderr}")
                return []
            
            # Wait for files to be written
            time.sleep(2)
            
            # Scan downloaded files
            downloaded_images = self._scan_downloaded_files(download_path, query)
            
            return downloaded_images
            
        except subprocess.TimeoutExpired:
            print("✗ Pinterest-dl timeout")
            return []
        except Exception as e:
            print(f"✗ Pinterest-dl execution error: {e}")
            return []
    
    def _scan_downloaded_files(self, directory: Path, query: str) -> List[Dict]:
        """Scan directory for downloaded files and extract metadata."""
        images = []
        
        if not directory.exists():
            return images
        
        # Supported extensions
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
        
        for file_path in directory.glob('*'):
            if file_path.suffix.lower() in image_extensions:
                # Get file info
                stat = file_path.stat()
                
                # Try to extract dimensions (simplified)
                width, height = self._get_image_dimensions(file_path)
                
                # Extract caption from filename or separate file
                caption = self._extract_caption(file_path)
                
                images.append({
                    'url': f"local://{file_path.name}",  # Placeholder URL
                    'local_path': str(file_path),
                    'file_name': file_path.name,
                    'file_size': stat.st_size,
                    'width': width,
                    'height': height,
                    'type': 'image',
                    'caption': caption
                })
        
        return images
    
    def _get_image_dimensions(self, file_path: Path) -> tuple:
        """Get image dimensions (simplified)."""
        try:
            from PIL import Image
            with Image.open(file_path) as img:
                return img.size
        except:
            return (0, 0)
    
    def _extract_caption(self, file_path: Path) -> Optional[str]:
        """Extract caption from accompanying .txt file."""
        caption_file = file_path.with_suffix('.txt')
        if caption_file.exists():
            try:
                return caption_file.read_text(encoding='utf-8').strip()
            except:
                pass
        return None