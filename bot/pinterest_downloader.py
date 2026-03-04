# ============================================================
# FILE: pinterest_downloader.py (UPDATED WITH ERROR RESILIENCE)
# ============================================================

"""Pinterest downloader module with video support and preview generation."""

import os
import subprocess
import time
from pathlib import Path
from typing import List, Dict, Optional
import hashlib
import re
import json
from config import Config
from preview_generator import PreviewGenerator
import logging

logger = logging.getLogger(__name__)

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
        Continues even if some files fail to download.
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
            
            # Wait for files to be written even if there was an error
            time.sleep(2)
            
            # Always scan for downloaded files, regardless of return code
            downloaded_media = self._scan_downloaded_files(download_path, query)
            
            # Log error but continue processing
            if result.returncode != 0:
                error_msg = result.stderr.strip() if result.stderr else "Unknown error"
                print(f"⚠ Pinterest-dl reported errors: {error_msg}")
                print(f"⚠ Continuing with {len(downloaded_media)} successfully downloaded items")
                logger.warning(f"pinterest-dl returned error {result.returncode}: {error_msg}")
            
            # Generate previews for images
            if Config.PREVIEW_ENABLED and downloaded_media:
                preview_count = 0
                for media in downloaded_media:
                    if media['type'] == 'image' and media.get('local_path'):
                        preview_path = self.preview_generator.generate_preview(
                            Path(media['local_path'])
                        )
                        if preview_path:
                            media['preview_path'] = preview_path
                            preview_count += 1
                print(f"  - Generated {preview_count} previews")
            
            if downloaded_media:
                print(f"✓ Successfully processed {len(downloaded_media)} items")
                images = [m for m in downloaded_media if m['type'] == 'image']
                videos = [m for m in downloaded_media if m['type'] == 'video']
                if images:
                    print(f"  - Images: {len(images)}")
                if videos:
                    print(f"  - Videos: {len(videos)}")
            else:
                print(f"✗ No items were downloaded successfully")
            
            return downloaded_media
            
        except subprocess.TimeoutExpired:
            print("✗ Pinterest-dl timeout")
            logger.error("pinterest-dl timeout expired")
            
            # Still try to scan for any files that might have been downloaded
            time.sleep(2)
            downloaded_media = self._scan_downloaded_files(download_path, query)
            if downloaded_media:
                print(f"✓ Found {len(downloaded_media)} items despite timeout")
                return downloaded_media
            return []
            
        except Exception as e:
            print(f"✗ Pinterest-dl execution error: {e}")
            logger.error(f"pinterest-dl execution error: {e}")
            
            # One last attempt to scan for files
            try:
                downloaded_media = self._scan_downloaded_files(download_path, query)
                if downloaded_media:
                    print(f"✓ Found {len(downloaded_media)} items despite error")
                    return downloaded_media
            except:
                pass
            return []
    
    def _scan_downloaded_files(self, directory: Path, query: str) -> List[Dict]:
        """Scan directory for downloaded files and extract metadata."""
        media_files = []
        
        if not directory.exists():
            logger.warning(f"Download directory does not exist: {directory}")
            return media_files
        
        # Supported extensions
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
        video_extensions = {'.mp4', '.webm', '.mov', '.avi', '.mkv', '.flv', '.m4v'}
        
        # Get all files in directory
        all_files = list(directory.glob('*'))
        logger.info(f"Scanning {len(all_files)} files in {directory}")
        
        for file_path in all_files:
            # Skip directories
            if file_path.is_dir():
                continue
                
            file_ext = file_path.suffix.lower()
            
            try:
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
                    logger.debug(f"Found image: {file_path.name} ({width}x{height})")
                
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
                    logger.debug(f"Found video: {file_path.name} ({width}x{height}, {duration}s)")
                    
            except Exception as e:
                logger.error(f"Error processing file {file_path}: {e}")
                # Skip this file but continue with others
                continue
        
        return media_files
    
    def _get_media_dimensions(self, file_path: Path) -> tuple:
        """Get image dimensions."""
        try:
            from PIL import Image
            with Image.open(file_path) as img:
                return img.size
        except Exception as e:
            logger.debug(f"Could not get dimensions for {file_path}: {e}")
            return (0, 0)
    
    def _get_video_metadata(self, file_path: Path) -> tuple:
        """Get video metadata (width, height, duration)."""
        try:
            # Try to use ffprobe if available
            result = subprocess.run(
                ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', str(file_path)],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0 and result.stdout:
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
        except Exception as e:
            logger.debug(f"Could not get video metadata for {file_path}: {e}")
            return (0, 0, 0)
    
    def _find_thumbnail(self, video_path: Path) -> Optional[str]:
        """Find thumbnail for video."""
        # Check for common thumbnail naming patterns
        possible_thumbnails = [
            video_path.with_suffix('.jpg'),
            video_path.with_suffix('.png'),
            video_path.with_suffix('.webp'),
            video_path.parent / f"{video_path.stem}_thumb.jpg",
            video_path.parent / f"{video_path.stem}_thumb.png",
            video_path.parent / f"thumb_{video_path.name}.jpg",
            video_path.parent / f"{video_path.stem}.thumbnail.jpg"
        ]
        
        for thumb in possible_thumbnails:
            if thumb.exists():
                logger.debug(f"Found thumbnail: {thumb}")
                return str(thumb)
        
        return None
    
    def _extract_caption(self, file_path: Path) -> Optional[str]:
        """Extract caption from accompanying .txt file."""
        caption_file = file_path.with_suffix('.txt')
        if caption_file.exists():
            try:
                return caption_file.read_text(encoding='utf-8').strip()
            except Exception as e:
                logger.debug(f"Could not read caption file {caption_file}: {e}")
        
        # Also try .description file
        desc_file = file_path.with_suffix('.description')
        if desc_file.exists():
            try:
                return desc_file.read_text(encoding='utf-8').strip()
            except Exception as e:
                logger.debug(f"Could not read description file {desc_file}: {e}")
        
        return None