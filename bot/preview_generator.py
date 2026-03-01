# ============================================================
# FILE: preview_generator.py
# ============================================================

"""Preview image generation module."""

from pathlib import Path
from PIL import Image
import logging
from typing import Optional, Tuple
import os

from config import Config

logger = logging.getLogger(__name__)

class PreviewGenerator:
    """Generates preview images for downloaded media."""
    
    def __init__(self):
        """Initialize preview generator."""
        self.max_width = Config.PREVIEW_MAX_WIDTH
        self.max_height = Config.PREVIEW_MAX_HEIGHT
        self.quality = Config.PREVIEW_QUALITY
        self.enabled = Config.PREVIEW_ENABLED
    
    def generate_preview(self, image_path: Path) -> Optional[str]:
        """
        Generate preview image.
        Returns path to preview image or None if failed.
        """
        if not self.enabled:
            return None
        
        try:
            # Check if original image exists
            if not image_path.exists():
                logger.error(f"Original image not found: {image_path}")
                return None
            
            # Generate preview filename
            preview_filename = f"{image_path.stem}.jpg"
            preview_dir = image_path.parent / Config.PREVIEW_SUBDIR
            preview_dir.mkdir(exist_ok=True)
            
            preview_path = preview_dir / preview_filename
            
            # If preview already exists, return it
            if preview_path.exists():
                logger.debug(f"Preview already exists: {preview_path}")
                return str(preview_path)
            
            # Open and resize image
            with Image.open(image_path) as img:
                # Convert to RGB if necessary (for PNG with alpha)
                if img.mode in ('RGBA', 'LA', 'P'):
                    rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    rgb_img.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                    img = rgb_img
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # Calculate new size maintaining aspect ratio
                original_width, original_height = img.size
                new_width, new_height = self._calculate_size(
                    original_width, original_height
                )
                
                # Resize image
                if new_width < original_width or new_height < original_height:
                    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                
                # Save preview
                img.save(
                    preview_path,
                    'JPEG',
                    quality=self.quality,
                    optimize=True
                )
                
                logger.info(f"Generated preview: {preview_path} ({new_width}x{new_height})")
                return str(preview_path)
                
        except Exception as e:
            logger.error(f"Error generating preview for {image_path}: {e}")
            return None
    
    def _calculate_size(self, width: int, height: int) -> Tuple[int, int]:
        """Calculate new dimensions maintaining aspect ratio."""
        if width <= self.max_width and height <= self.max_height:
            return width, height
        
        ratio = min(self.max_width / width, self.max_height / height)
        new_width = int(width * ratio)
        new_height = int(height * ratio)
        
        return new_width, new_height