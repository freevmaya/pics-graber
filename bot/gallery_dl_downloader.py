# ============================================================
# FILE: gallery_dl_downloader.py (FIXED - ONLY FOR URLS)
# ============================================================

"""Gallery-dl downloader module for downloading from various sites by URL."""

import os
import subprocess
import time
import json
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import hashlib
import logging
from urllib.parse import urlparse

from config import Config
from preview_generator import PreviewGenerator

logger = logging.getLogger(__name__)

class GalleryDLDownloader:
    """Handles downloading from various sites using gallery-dl for URLs only."""
    
    # Supported domains (can be expanded)
    SUPPORTED_DOMAINS = {
        'pinterest.com', 'pin.it',
        'instagram.com', 'instagr.am',
        'twitter.com', 'x.com',
        'tumblr.com',
        'flickr.com',
        'deviantart.com',
        'behance.net',
        '500px.com',
        'unsplash.com',
        'pexels.com',
        'pixabay.com',
        'reddit.com',
        'imgur.com',
        'gfycat.com',
        'streamable.com',
        'tiktok.com',
        'youtube.com', 'youtu.be',
        'vimeo.com',
        'dailymotion.com',
        'facebook.com',
        'telegram.org'
    }
    
    def __init__(self):
        """Initialize gallery-dl downloader."""
        self.download_dir = Config.DOWNLOAD_DIR
        self.download_dir.mkdir(exist_ok=True)
        self.timeout = Config.DOWNLOAD_TIMEOUT
        self.preview_generator = PreviewGenerator()
        self._check_gallery_dl()
    
    def _check_gallery_dl(self) -> bool:
        """Check if gallery-dl is installed."""
        try:
            result = subprocess.run(
                ['gallery-dl', '--version'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                version = result.stdout.strip()
                logger.info(f"✓ gallery-dl found: {version}")
                return True
            else:
                logger.warning("gallery-dl not found")
                return False
        except (subprocess.TimeoutExpired, FileNotFoundError):
            logger.warning("gallery-dl not found")
            return False
    
    @staticmethod
    def is_supported_url(url: str) -> Tuple[bool, str]:
        """
        Check if URL is supported by gallery-dl.
        Returns (is_supported, reason)
        """
        if not url or not isinstance(url, str):
            return False, "Empty or invalid URL"
        
        url = url.strip()
        
        # Check domain
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            
            # Remove www. prefix
            if domain.startswith('www.'):
                domain = domain[4:]
            
            # Check against supported domains
            for supported in GalleryDLDownloader.SUPPORTED_DOMAINS:
                if domain == supported or domain.endswith('.' + supported):
                    return True, f"Supported domain: {domain}"
            
            return False, f"Domain not supported: {domain}"
            
        except Exception as e:
            logger.error(f"Error parsing URL {url}: {e}")
            return False, f"Invalid URL format"
    
    def download_from_url(self, url: str, limit: int = 50) -> List[Dict]:
        """
        Download media from URL using gallery-dl.
        Returns list of downloaded media info.
        """
        # Create unique download directory for this URL
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        safe_name = self._get_safe_name(url)[:30]
        download_path = self.download_dir / f"url_{safe_name}_{url_hash}"
        download_path.mkdir(exist_ok=True)
        
        logger.info(f"Downloading from URL: {url}")
        logger.info(f"Download path: {download_path}")
        
        # Build gallery-dl command
        cmd = [
            'gallery-dl',
            url,
            '--directory', str(download_path),
            '--range', f'1:{limit}',
            '--no-mtime'
        ]
        
        cmd_str = ' '.join(cmd)
        logger.info(f"Executing: {cmd_str}")
        
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
            downloaded_media = self._scan_downloaded_files(download_path, url)
            
            if result.returncode != 0 and result.returncode != 1:
                logger.warning(f"gallery-dl returned code {result.returncode}: {result.stderr[:200]}")
            
            # Generate previews
            if Config.PREVIEW_ENABLED and downloaded_media:
                self._generate_previews(downloaded_media)
            
            if downloaded_media:
                logger.info(f"Successfully downloaded {len(downloaded_media)} items from {url}")
            else:
                logger.warning(f"No items downloaded from {url}")
            
            return downloaded_media
            
        except subprocess.TimeoutExpired:
            logger.error(f"gallery-dl timeout for {url}")
            time.sleep(2)
            downloaded_media = self._scan_downloaded_files(download_path, url)
            if downloaded_media:
                logger.info(f"Found {len(downloaded_media)} items despite timeout")
                return downloaded_media
            return []
            
        except Exception as e:
            logger.error(f"gallery-dl execution error for {url}: {e}")
            try:
                downloaded_media = self._scan_downloaded_files(download_path, url)
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
    
    def _get_safe_name(self, url: str) -> str:
        """Generate safe name from URL."""
        try:
            parsed = urlparse(url)
            path = parsed.path.strip('/')
            if path:
                name = path.replace('/', '_').replace('-', '_')
                return re.sub(r'[^\w\-_]', '', name)[:30]
        except:
            pass
        return hashlib.md5(url.encode()).hexdigest()[:16]
    
    def _scan_downloaded_files(self, directory: Path, source_url: str) -> List[Dict]:
        """Scan directory for downloaded files and extract metadata."""
        media_files = []
        
        if not directory.exists():
            return media_files
        
        # Supported extensions
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
        video_extensions = {'.mp4', '.webm', '.mov', '.avi', '.mkv', '.flv', '.m4v'}
        
        # Get all files recursively
        all_files = []
        for ext in image_extensions.union(video_extensions):
            all_files.extend(directory.rglob(f'*{ext}'))
        
        logger.debug(f"Scanning {len(all_files)} files in {directory}")
        
        for file_path in all_files:
            if file_path.is_dir():
                continue
            
            file_ext = file_path.suffix.lower()
            
            try:
                file_size = file_path.stat().st_size
                if file_size < 100:
                    continue
                
                if file_ext in image_extensions:
                    width, height = self._get_media_dimensions(file_path)
                    media_files.append({
                        'url': source_url,
                        'local_path': str(file_path),
                        'preview_path': None,
                        'file_name': file_path.name,
                        'file_size': file_size,
                        'width': width,
                        'height': height,
                        'type': 'image',
                        'caption': self._extract_caption(file_path),
                    })
                    logger.debug(f"Found image: {file_path.name} ({width}x{height})")
                
                elif file_ext in video_extensions:
                    width, height, duration = self._get_video_metadata(file_path)
                    media_files.append({
                        'url': source_url,
                        'local_path': str(file_path),
                        'preview_path': None,
                        'file_name': file_path.name,
                        'file_size': file_size,
                        'width': width,
                        'height': height,
                        'type': 'video',
                        'caption': self._extract_caption(file_path),
                        'duration': duration
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
        except Exception:
            return (0, 0)
    
    def _get_video_metadata(self, file_path: Path) -> tuple:
        """Get video metadata."""
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
        except Exception:
            return (0, 0, 0)
    
    def _extract_caption(self, file_path: Path) -> Optional[str]:
        """Extract caption from metadata."""
        json_file = file_path.with_suffix('.json')
        if json_file.exists():
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                for field in ['title', 'description', 'caption']:
                    if field in metadata and metadata[field]:
                        return str(metadata[field])[:500]
            except:
                pass
        
        txt_file = file_path.with_suffix('.txt')
        if txt_file.exists():
            try:
                return txt_file.read_text(encoding='utf-8').strip()[:500]
            except:
                pass
        
        return None
    
    def cleanup_old_downloads(self, max_age_hours: int = 24):
        """Clean up download directories older than specified hours."""
        try:
            current_time = time.time()
            for item in self.download_dir.glob('url_*'):
                if item.is_dir():
                    age_hours = (current_time - item.stat().st_mtime) / 3600
                    if age_hours > max_age_hours:
                        logger.info(f"Cleaning up old directory: {item}")
                        import shutil
                        shutil.rmtree(item, ignore_errors=True)
        except Exception as e:
            logger.error(f"Error cleaning up downloads: {e}")