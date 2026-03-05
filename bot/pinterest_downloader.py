# ============================================================
# FILE: pinterest_downloader.py (FIXED - ONLY FOR SEARCH QUERIES)
# ============================================================

"""Pinterest downloader module for search queries using pinterest-dl."""

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
    """Handles Pinterest image and video downloading via pinterest-dl for search queries only."""
    
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
        Download images and videos using pinterest-dl search command.
        ONLY for search queries, NOT for URLs.
        Returns list of downloaded media info.
        """
        # Create unique download directory for this query
        query_hash = hashlib.md5(query.encode()).hexdigest()[:8]
        safe_query = re.sub(r'[^\w\-_]', '_', query)[:30]
        download_path = self.download_dir / f"search_{query_hash}"
        download_path.mkdir(exist_ok=True)
        
        # Build command for search
        cmd = [
            'pinterest-dl',
            'search',
            query,
            '-o', str(download_path),
            '--num', str(limit)
        ]
        
        # Add video flag if needed Пока убрал загрузки видео, потому что незагружаются видео в telegram почему-то
        # if include_videos:
        #    cmd.append('--video')
        
        cmd_str = ' '.join(cmd)
        logger.info(f"Executing search command: {cmd_str}")
        
        try:
            # Execute command
            result = subprocess.run(
                cmd_str,
                shell=True,
                capture_output=True,
                text=True,
                timeout=self.timeout
            )
            
            # Wait for files to be written
            time.sleep(2)
            
            # Scan for downloaded files
            downloaded_media = self._scan_downloaded_files(download_path, f"search:{query}")
            
            if result.returncode != 0:
                error_msg = result.stderr.strip() if result.stderr else "Unknown error"
                logger.warning(f"pinterest-dl search returned error {result.returncode}: {error_msg}")
            
            # Generate previews
            if Config.PREVIEW_ENABLED and downloaded_media:
                self._generate_previews(downloaded_media)
            
            if downloaded_media:
                images = [m for m in downloaded_media if m['type'] == 'image']
                videos = [m for m in downloaded_media if m['type'] == 'video']
                logger.info(f"Successfully processed {len(downloaded_media)} items: {len(images)} images, {len(videos)} videos")
            else:
                logger.warning(f"No items were downloaded for query: {query}")
            
            return downloaded_media
            
        except subprocess.TimeoutExpired:
            logger.error(f"pinterest-dl timeout for query: {query}")
            time.sleep(2)
            downloaded_media = self._scan_downloaded_files(download_path, f"search:{query}")
            if downloaded_media:
                logger.info(f"Found {len(downloaded_media)} items despite timeout")
                return downloaded_media
            return []
            
        except Exception as e:
            logger.error(f"pinterest-dl execution error for query {query}: {e}")
            try:
                downloaded_media = self._scan_downloaded_files(download_path, f"search:{query}")
                if downloaded_media:
                    logger.info(f"Found {len(downloaded_media)} items despite error")
                    return downloaded_media
            except:
                pass
            return []
    
    def _generate_previews(self, media_items: List[Dict]) -> None:
        """Generate previews for media items."""
        preview_count = 0
        for media in media_items:
            if media['type'] == 'image' and media.get('local_path'):
                preview_path = self.preview_generator.generate_preview(
                    Path(media['local_path'])
                )
                if preview_path:
                    media['preview_path'] = preview_path
                    preview_count += 1
        logger.info(f"Generated {preview_count} previews")
    
    def _scan_downloaded_files(self, directory: Path, source: str) -> List[Dict]:
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
        logger.debug(f"Scanning {len(all_files)} files in {directory}")
        
        i = 1        
        for file_path in all_files:
            if file_path.is_dir():
                continue
                
            file_ext = file_path.suffix.lower()

            source_local = source + "-" + str(i)
            i += 1
            
            try:
                # Check if it's an image
                if file_ext in image_extensions:
                    stat = file_path.stat()
                    width, height = self._get_media_dimensions(file_path)
                    caption = self._extract_caption(file_path)
                    
                    media_files.append({
                        'url': source_local,
                        'local_path': str(file_path),
                        'preview_path': None,
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
                    stat = file_path.stat()
                    width, height, duration = self._get_video_metadata(file_path)
                    thumbnail = self._find_thumbnail(file_path)
                    
                    media_files.append({
                        'url': source_local,
                        'local_path': str(file_path),
                        'preview_path': None,
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
            result = subprocess.run(
                ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', str(file_path)],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0 and result.stdout:
                data = json.loads(result.stdout)
                
                for stream in data.get('streams', []):
                    if stream.get('codec_type') == 'video':
                        width = int(stream.get('width', 0))
                        height = int(stream.get('height', 0))
                        duration = float(stream.get('duration', 0))
                        if duration == 0:
                            duration = float(data.get('format', {}).get('duration', 0))
                        return (width, height, duration)
            
            return (0, 0, 0)
        except Exception as e:
            logger.debug(f"Could not get video metadata for {file_path}: {e}")
            return (0, 0, 0)
    
    def _find_thumbnail(self, video_path: Path) -> Optional[str]:
        """Find thumbnail for video."""
        possible_thumbnails = [
            video_path.with_suffix('.jpg'),
            video_path.with_suffix('.png'),
            video_path.with_suffix('.webp'),
            video_path.parent / f"{video_path.stem}_thumb.jpg",
            video_path.parent / f"{video_path.stem}_thumb.png",
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
        
        desc_file = file_path.with_suffix('.description')
        if desc_file.exists():
            try:
                return desc_file.read_text(encoding='utf-8').strip()
            except Exception as e:
                logger.debug(f"Could not read description file {desc_file}: {e}")
        
        return None