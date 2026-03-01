# ============================================================
# FILE: pinterest_downloader.py (UPDATED WITH PREVIEW SUPPORT)
# ============================================================

"""Pinterest downloader module with video support and preview generation."""

import os
import subprocess
import time
from pathlib import Path
from typing import List, Dict, Optional
import hashlib
import re
from config import Config
from preview_generator import PreviewGenerator

class PinterestDownloader:
    """Handles Pinterest image and video downloading via pinterest-dl."""
    
    def __init__(self):
        """Initialize downloader."""
        self.download_dir = Config.DOWNLOAD_DIR
        self.download_dir.mkdir(exist_ok=True)
        self.timeout = Config.DOWNLOAD_TIMEOUT
        self.preview_generator = PreviewGenerator()
    
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
    
    def download_images(self, query: str, limit: int = 50, include_videos: bool = True) -> List[Dict]:
        """
        Download images and videos using pinterest-dl.
        Returns list of downloaded media info.
        """
        # Create unique download directory for this query
        query_hash = hashlib.md5(query.encode()).hexdigest()[:8]
        safe_query = re.sub(r'[^\w\-_]', '_', query)[:30]
        download_path = self.download_dir / f"{safe_query}_{query_hash}"
        download_path.mkdir(exist_ok=True)
        
        # Build command
        cmd = [
            'pinterest-dl', 'search', f'"{query}"',
            '-o', str(download_path),
            '--num', str(limit)
        ]
        
        # Add video flag if needed
        if include_videos:
            cmd.append('--video')
        
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
            downloaded_media = self._scan_downloaded_files(download_path, query)
            
            # Generate previews for images
            if Config.PREVIEW_ENABLED:
                for media in downloaded_media:
                    if media['type'] == 'image' and media.get('local_path'):
                        preview_path = self.preview_generator.generate_preview(
                            Path(media['local_path'])
                        )
                        if preview_path:
                            media['preview_path'] = preview_path
            
            print(f"✓ Downloaded {len(downloaded_media)} items")
            images = [m for m in downloaded_media if m['type'] == 'image']
            videos = [m for m in downloaded_media if m['type'] == 'video']
            if images:
                print(f"  - Images: {len(images)}")
                if Config.PREVIEW_ENABLED:
                    print(f"  - Previews: {len([m for m in images if m.get('preview_path')])}")
            if videos:
                print(f"  - Videos: {len(videos)}")
            
            return downloaded_media
            
        except subprocess.TimeoutExpired:
            print("✗ Pinterest-dl timeout")
            return []
        except Exception as e:
            print(f"✗ Pinterest-dl execution error: {e}")
            return []
    
    def _scan_downloaded_files(self, directory: Path, query: str) -> List[Dict]:
        """Scan directory for downloaded files and extract metadata."""
        media_files = []
        
        if not directory.exists():
            return media_files
        
        # Supported extensions
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
        video_extensions = {'.mp4', '.webm', '.mov', '.avi', '.mkv', '.flv'}
        
        for file_path in directory.glob('*'):
            file_ext = file_path.suffix.lower()
            
            # Check if it's an image
            if file_ext in image_extensions:
                # Get file info
                stat = file_path.stat()
                
                # Try to extract dimensions
                width, height = self._get_media_dimensions(file_path)
                
                # Extract caption from filename or separate file
                caption = self._extract_caption(file_path)
                
                media_files.append({
                    'url': f"local://{file_path.name}",
                    'local_path': str(file_path),
                    'preview_path': None,  # Will be filled after preview generation
                    'file_name': file_path.name,
                    'file_size': stat.st_size,
                    'width': width,
                    'height': height,
                    'type': 'image',
                    'caption': caption,
                })
            
            # Check if it's a video
            elif file_ext in video_extensions:
                # Get file info
                stat = file_path.stat()
                
                # Try to get video metadata
                width, height, duration = self._get_video_metadata(file_path)
                
                # Look for thumbnail
                thumbnail = self._find_thumbnail(file_path)
                
                media_files.append({
                    'url': f"local://{file_path.name}",
                    'local_path': str(file_path),
                    'preview_path': None,  # Videos don't get previews (for now)
                    'file_name': file_path.name,
                    'file_size': stat.st_size,
                    'width': width,
                    'height': height,
                    'type': 'video',
                    'caption': None,
                    'duration': duration,
                    'thumbnail': thumbnail
                })
        
        return media_files
    
    def _get_media_dimensions(self, file_path: Path) -> tuple:
        """Get image dimensions."""
        try:
            from PIL import Image
            with Image.open(file_path) as img:
                return img.size
        except:
            return (0, 0)
    
    def _get_video_metadata(self, file_path: Path) -> tuple:
        """Get video metadata (width, height, duration)."""
        try:
            # Try to use ffprobe if available
            result = subprocess.run(
                ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', str(file_path)],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                import json
                data = json.loads(result.stdout)
                
                # Find video stream
                for stream in data.get('streams', []):
                    if stream.get('codec_type') == 'video':
                        width = int(stream.get('width', 0))
                        height = int(stream.get('height', 0))
                        
                        # Get duration
                        duration = float(stream.get('duration', 0))
                        if duration == 0:
                            # Try format duration
                            duration = float(data.get('format', {}).get('duration', 0))
                        
                        return (width, height, duration)
            
            return (0, 0, 0)
        except:
            return (0, 0, 0)
    
    def _find_thumbnail(self, video_path: Path) -> Optional[str]:
        """Find thumbnail for video."""
        # Check for common thumbnail naming patterns
        possible_thumbnails = [
            video_path.with_suffix('.jpg'),
            video_path.with_suffix('.png'),
            video_path.with_suffix('.webp'),
            video_path.parent / f"{video_path.stem}_thumb.jpg",
            video_path.parent / f"{video_path.stem}_thumb.png"
        ]
        
        for thumb in possible_thumbnails:
            if thumb.exists():
                return str(thumb)
        
        return None
    
    def _extract_caption(self, file_path: Path) -> Optional[str]:
        """Extract caption from accompanying .txt file."""
        caption_file = file_path.with_suffix('.txt')
        if caption_file.exists():
            try:
                return caption_file.read_text(encoding='utf-8').strip()
            except:
                pass
        return None