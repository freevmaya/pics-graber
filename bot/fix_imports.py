# ============================================================
# FILE: fix_imports.py
# TYPE: .PY
# ============================================================

"""Fix for missing imghdr module in Python 3.13."""

import sys
import os

# Add fallback for imghdr if missing
try:
    import imghdr
except ImportError:
    # Create a simple imghdr replacement
    import struct
    import io
    
    def what(file, h=None):
        """Simple imghdr replacement"""
        if h is None:
            if isinstance(file, str):
                with open(file, 'rb') as f:
                    h = f.read(32)
            else:
                location = file.tell()
                h = file.read(32)
                file.seek(location)
        
        # Check for known image formats
        if h.startswith(b'\xff\xd8'):
            return 'jpeg'
        elif h.startswith(b'\x89PNG\r\n\x1a\n'):
            return 'png'
        elif h.startswith(b'GIF87a') or h.startswith(b'GIF89a'):
            return 'gif'
        elif h.startswith(b'RIFF') and h[8:12] == b'WEBP':
            return 'webp'
        elif h.startswith(b'BM'):
            return 'bmp'
        return None
    
    # Create mock module
    class MockImghdr:
        what = staticmethod(what)
    
    sys.modules['imghdr'] = MockImghdr()
    print("✓ Created mock imghdr module")

print("✓ Imports fixed")