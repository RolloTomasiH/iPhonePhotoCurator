"""
Image and File Hashing & Quality Utilities for iPhone Photo Curator.
Features:
- Fast multi-stage file MD5 (Size -> Header/Footer -> Full) for exact duplicates
- Difference Hash (dHash) for perceptual similarity
- Laplacian Variance for image sharpness/quality scoring
"""

import os
import hashlib
import tempfile
import subprocess
import numpy as np
from PIL import Image

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

def get_file_fast_hash(file_path: str, block_size: int = 65536) -> str:
    """
    Computes a fast multi-stage hash:
    Size + MD5 of first 64KB + MD5 of last 64KB.
    If two files match this, full MD5 is checked.
    """
    try:
        size = os.path.getsize(file_path)
        if size == 0:
            return "empty_0"
        
        hasher = hashlib.md5()
        hasher.update(str(size).encode('utf-8'))
        
        with open(file_path, 'rb') as f:
            # First block
            hasher.update(f.read(block_size))
            if size > block_size * 2:
                # Last block
                f.seek(-block_size, os.SEEK_END)
                hasher.update(f.read(block_size))
                
        return f"{size}_{hasher.hexdigest()}"
    except Exception:
        return ""

def get_full_file_md5(file_path: str, block_size: int = 1048576) -> str:
    """Computes standard full MD5 hash of a file."""
    try:
        hasher = hashlib.md5()
        with open(file_path, 'rb') as f:
            while chunk := f.read(block_size):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return ""

def load_grayscale_matrix(image_path: str, target_width: int = 128) -> np.ndarray:
    """
    Loads an image into a grayscale numpy array.
    Supports HEIC, JPG, PNG, DNG, etc. via PIL and fallback to macOS sips.
    """
    ext = os.path.splitext(image_path)[1].lower()
    
    # Try PIL direct open first if standard format
    if ext in ['.jpg', '.jpeg', '.png', '.webp', '.bmp']:
        try:
            with Image.open(image_path) as im:
                im.draft('L', (target_width, target_width))
                im_gray = im.convert('L')
                im_gray.thumbnail((target_width, target_width))
                return np.array(im_gray)
        except Exception:
            pass

    # Fallback to macOS sips (supports HEIC, TIFF, DNG, etc.)
    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
        tmp_name = tmp.name

    try:
        cmd = ['sips', '-s', 'format', 'jpeg', '--resampleWidth', str(target_width), image_path, '--out', tmp_name]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        with Image.open(tmp_name) as im:
            im_gray = im.convert('L')
            return np.array(im_gray)
    except Exception:
        return None
    finally:
        if os.path.exists(tmp_name):
            try:
                os.remove(tmp_name)
            except OSError:
                pass

def compute_dhash(matrix: np.ndarray, hash_size: int = 8) -> str:
    """
    Computes 64-bit Difference Hash (dHash) from image matrix.
    Resize matrix to (hash_size, hash_size + 1), compare adjacent horizontal pixels.
    """
    if matrix is None or matrix.size == 0:
        return ""
    try:
        pil_img = Image.fromarray(matrix)
        # resize to width = hash_size + 1, height = hash_size
        resized = pil_img.resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
        pixels = np.array(resized)
        
        # compare pixels: pixels[:, 1:] > pixels[:, :-1]
        diff = pixels[:, 1:] > pixels[:, :-1]
        # convert boolean array to integer / hex string
        decimal_val = 0
        for bit in diff.flatten():
            decimal_val = (decimal_val << 1) | int(bit)
        return f"{decimal_val:016x}"
    except Exception:
        return ""

def hamming_distance(hash1: str, hash2: str) -> int:
    """Computes Hamming distance between two hex string hashes."""
    if not hash1 or not hash2 or len(hash1) != len(hash2):
        return 999
    try:
        val1 = int(hash1, 16)
        val2 = int(hash2, 16)
        xor_val = val1 ^ val2
        return bin(xor_val).count('1')
    except Exception:
        return 999

def compute_sharpness(matrix: np.ndarray) -> float:
    """
    Computes image sharpness score using Laplacian variance.
    Higher score means sharper image with crisper edges and details.
    """
    if matrix is None or matrix.size == 0:
        return 0.0
    try:
        if HAS_CV2:
            lap = cv2.Laplacian(matrix, cv2.CV_64F)
            return float(lap.var())
        else:
            # Fallback standard Laplacian kernel with NumPy
            kernel = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]])
            from scipy.signal import convolve2d
            filtered = convolve2d(matrix, kernel, mode='valid')
            return float(np.var(filtered))
    except Exception:
        return 0.0
