#!/usr/bin/env python3
"""Add text-based selectors to downloader.py"""
import re

with open('downloader.py', 'r') as f:
    content = f.read()

# Find the selectors list and add text-based selectors if not present
if 'a:has-text(".zip")' not in content:
    # Find the line with 'a[href$=".m4a"]', and add text selectors after it
    pattern = r"(\s+)'a\[href\$=\"\.m4a\"\]',"
    
    text_selectors = r"""\1'a[href$=".m4a"]',
\1
\1# Text-based file extension detection (for links where filename is in text)
\1'a:has-text(".zip")',
\1'a:has-text(".pdf")',
\1'a:has-text(".xlsx")',
\1'a:has-text(".docx")',
\1'a:has-text(".mp4")',
\1'a:has-text(".mp3")',"""
    
    content = re.sub(pattern, text_selectors, content)
    print("✓ Added text-based selectors")
else:
    print("✓ Text-based selectors already present")

with open('downloader.py', 'w') as f:
    f.write(content)

print("Done!")
