# ============================================================
# FILE: gallery_dl_downloader.py (IMPROVED - BETTER VIDEO HANDLING)
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
        self._check_ffmpeg()
    
    def _check_ffmpeg(self) -> bool:
        """Check if ffmpeg/ffprobe is installed for video metadata."""
        try:
            result = subprocess.run(
                ['ffprobe', '-version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                logger.info("✓ ffmpeg found")
                return True
            else:
                logger.warning("ffmpeg not found, video metadata will be limited")
                return False
        except (subprocess.TimeoutExpired, FileNotFoundError):
            logger.warning("ffmpeg not found, video metadata will be limited")
            return False
    
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
        download_path = self.download_dir / f"url_{url_hash}"
        download_path.mkdir(exist_ok=True)
        
        logger.info(f"Downloading from URL: {url}")
        logger.info(f"Download path: {download_path}")
        
        # Build gallery-dl command with better options
        cmd = [
            'gallery-dl',
            url,
            '--directory', str(download_path),
            '--range', f'1:{limit}',
            '--no-mtime',
            '--write-metadata',  # Save metadata to JSON files
            '--write-info-json'   # Save gallery-dl info
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
            
            # Scan for downloaded files and rename them
            downloaded_media = self._scan_and_rename_files(download_path, url)
            
            if result.returncode != 0 and result.returncode != 1:
                logger.warning(f"gallery-dl returned code {result.returncode}: {result.stderr[:200]}")
            
            # Generate previews
            if Config.PREVIEW_ENABLED and downloaded_media:
                self._generate_previews(downloaded_media)
            
            if downloaded_media:
                images = [m for m in downloaded_media if m['type'] == 'image']
                videos = [m for m in downloaded_media if m['type'] == 'video']
                logger.info(f"Successfully downloaded {len(downloaded_media)} items from {url}: {len(images)} images, {len(videos)} videos")
            else:
                logger.warning(f"No items downloaded from {url}")
            
            return downloaded_media
            
        except subprocess.TimeoutExpired:
            logger.error(f"gallery-dl timeout for {url}")
            time.sleep(2)
            downloaded_media = self._scan_and_rename_files(download_path, url)
            if downloaded_media:
                images = [m for m in downloaded_media if m['type'] == 'image']
                videos = [m for m in downloaded_media if m['type'] == 'video']
                logger.info(f"Found {len(downloaded_media)} items despite timeout: {len(images)} images, {len(videos)} videos")
                return downloaded_media
            return []
            
        except Exception as e:
            logger.error(f"gallery-dl execution error for {url}: {e}")
            try:
                downloaded_media = self._scan_and_rename_files(download_path, url)
                if downloaded_media:
                    images = [m for m in downloaded_media if m['type'] == 'image']
                    videos = [m for m in downloaded_media if m['type'] == 'video']
                    logger.info(f"Found {len(downloaded_media)} items despite error: {len(images)} images, {len(videos)} videos")
                    return downloaded_media
            except:
                pass
            return []
    
    def _scan_and_rename_files(self, directory: Path, source_url: str) -> List[Dict]:
        """
        Scan directory for downloaded files, rename them to simple numbers,
        and extract metadata.
        """
        media_files = []
        
        if not directory.exists():
            return media_files
        
        # Supported extensions
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
        video_extensions = {'.mp4', '.webm', '.mov', '.avi', '.mkv', '.flv', '.m4v', '.mpeg', '.mpg'}
        all_extensions = image_extensions.union(video_extensions)
        
        # Get all files with supported extensions
        all_files = []
        for ext in all_extensions:
            all_files.extend(directory.rglob(f'*{ext}'))
        
        # Also look in subdirectories (gallery-dl sometimes creates them)
        for subdir in directory.iterdir():
            if subdir.is_dir():
                for ext in all_extensions:
                    all_files.extend(subdir.rglob(f'*{ext}'))
        
        # Remove duplicates and sort
        all_files = list(set(all_files))
        all_files.sort(key=lambda p: str(p))
        
        logger.debug(f"Found {len(all_files)} files to process in {directory}")
        
        # Counter for new filenames
        file_counter = 1
        
        # First, collect all JSON metadata files
        metadata_files = {}
        for json_path in directory.rglob('*.json'):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Try to find associated media file
                    if 'filename' in data:
                        media_name = data['filename']
                        metadata_files[media_name] = data
                    elif '_filename' in data:
                        media_name = data['_filename']
                        metadata_files[media_name] = data
            except:
                pass
        
        for file_path in all_files:
            if file_path.is_dir():
                continue
            
            file_ext = file_path.suffix.lower()
            file_name = file_path.name
            
            # Generate new simplified filename (just a number + extension)
            new_file_name = f"{file_counter}{file_ext}"
            new_file_path = file_path.parent / new_file_name
            
            # Store original name for metadata lookup
            original_name = file_name
            
            # Rename the file if the name is different
            if file_name != new_file_name:
                # Avoid overwriting existing files
                if new_file_path.exists():
                    logger.warning(f"Target file {new_file_path} already exists, using original name")
                    final_path = file_path
                else:
                    file_path.rename(new_file_path)
                    final_path = new_file_path
                    logger.debug(f"Renamed {file_name} -> {new_file_name}")
                    
                    # Also rename associated JSON metadata if exists
                    old_json = file_path.with_suffix('.json')
                    if old_json.exists():
                        new_json = new_file_path.with_suffix('.json')
                        if not new_json.exists():
                            old_json.rename(new_json)
            else:
                final_path = file_path
            
            try:
                file_size = final_path.stat().st_size
                if file_size < 100:  # Skip empty/corrupt files
                    file_counter += 1
                    continue
                
                # Get metadata from JSON if available
                metadata = metadata_files.get(original_name, {})
                
                if file_ext in image_extensions:
                    width, height = self._get_media_dimensions(final_path, metadata)
                    media_files.append({
                        'url': source_url,
                        'local_path': str(final_path),
                        'preview_path': None,
                        'file_name': final_path.name,
                        'file_size': file_size,
                        'width': width,
                        'height': height,
                        'type': 'image',
                        'caption': self._extract_caption(file_path, metadata),
                    })
                    logger.debug(f"Found image: {final_path.name} ({width}x{height})")
                
                elif file_ext in video_extensions:
                    width, height, duration = self._get_video_metadata(final_path, metadata)
                    media_files.append({
                        'url': source_url,
                        'local_path': str(final_path),
                        'preview_path': None,
                        'file_name': final_path.name,
                        'file_size': file_size,
                        'width': width,
                        'height': height,
                        'type': 'video',
                        'caption': self._extract_caption(file_path, metadata),
                        'duration': duration
                    })
                    logger.debug(f"Found video: {final_path.name} ({width}x{height}, {duration}s)")
                
                file_counter += 1
                    
            except Exception as e:
                logger.error(f"Error processing file {final_path}: {e}")
                continue
        
        return media_files
    
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
                # Take last part of path
                name = path.split('/')[-1]
                name = re.sub(r'[^\w\-_]', '_', name)
                if name and len(name) > 3:
                    return name[:30]
        except:
            pass
        return hashlib.md5(url.encode()).hexdigest()[:16]
    
    def _get_media_dimensions(self, file_path: Path, metadata: Dict = None) -> tuple:
        """Get image dimensions from file or metadata."""
        # Try metadata first
        if metadata:
            if 'width' in metadata and 'height' in metadata:
                try:
                    return (int(metadata['width']), int(metadata['height']))
                except:
                    pass
        
        # Fallback to PIL
        try:
            from PIL import Image
            with Image.open(file_path) as img:
                return img.size
        except Exception:
            return (0, 0)
    
    def _get_video_metadata(self, file_path: Path, metadata: Dict = None) -> tuple:
        """Get video metadata from file or metadata."""
        # Try metadata first
        if metadata:
            width = metadata.get('width', 0)
            height = metadata.get('height', 0)
            duration = metadata.get('duration', 0)
            if width and height and duration:
                try:
                    return (int(width), int(height), float(duration))
                except:
                    pass
        
        # Fallback to ffprobe
        try:
            result = subprocess.run(
                ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', '-show_format', str(file_path)],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0 and result.stdout:
                data = json.loads(result.stdout)
                
                # Try to get duration from format
                duration = float(data.get('format', {}).get('duration', 0))
                
                # Get video stream info
                for stream in data.get('streams', []):
                    if stream.get('codec_type') == 'video':
                        width = int(stream.get('width', 0))
                        height = int(stream.get('height', 0))
                        if duration == 0:
                            duration = float(stream.get('duration', 0))
                        return (width, height, duration)
            
            return (0, 0, 0)
        except Exception as e:
            logger.debug(f"Could not get video metadata for {file_path}: {e}")
            return (0, 0, 0)
    
    def _extract_caption(self, file_path: Path, metadata: Dict = None) -> Optional[str]:
        """Extract caption from metadata or JSON."""
        # Try metadata first
        if metadata:
            for field in ['title', 'description', 'caption', 'alt_text', 'text']:
                if field in metadata and metadata[field]:
                    text = str(metadata[field])
                    if len(text) > 10:  # Reasonable caption length
                        return text[:500]
        
        # Try JSON file
        json_file = file_path.with_suffix('.json')
        if json_file.exists():
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for field in ['title', 'description', 'caption', 'alt_text', 'text']:
                    if field in data and data[field]:
                        return str(data[field])[:500]
            except:
                pass
        
        # Try TXT file
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