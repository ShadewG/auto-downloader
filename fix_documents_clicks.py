#!/usr/bin/env python3
"""Add Documents tab pre-click and re-click logic"""
import re

with open('downloader.py', 'r') as f:
    content = f.read()

# Add pre-click before AI navigation if not present
if 'Pre-clicking Documents tab' not in content:
    pattern = r'(\s+)logger\.info\("Using AI vision to navigate page"\)'
    replacement = r'''\1# Try clicking Documents tab if it exists (common pattern)
\1try:
\1    if page.locator('text=Documents').count() > 0:
\1        logger.info("Pre-clicking Documents tab before AI analysis")
\1        page.click('text=Documents', timeout=5000)
\1        page.wait_for_timeout(2000)
\1except Exception as e:
\1    logger.debug(f"Documents tab not found or click failed: {e}")
\1
\1logger.info("Using AI vision to navigate page")'''
    
    content = re.sub(pattern, replacement, content)
    print("✓ Added Documents pre-click")
else:
    print("✓ Documents pre-click already present")

# Add re-click after AI navigation if not present
if 'Re-clicked Documents tab' not in content:
    pattern = r'(\s+)self\._ai_navigate_to_downloads\(page, download_path\)\n(\s+)# Collect download links'
    replacement = r'''\1self._ai_navigate_to_downloads(page, download_path)
\1
\1# Ensure we're still on Documents tab and page is ready
\1page.wait_for_timeout(2000)
\1try:
\1    if page.locator('text=Documents').count() > 0:
\1        page.click('text=Documents', timeout=3000)
\1        page.wait_for_timeout(2000)
\1        logger.info("Re-clicked Documents tab before scanning")
\1except Exception as e:
\1    logger.debug(f"Could not re-click Documents: {e}")
\1
\2# Collect download links'''
    
    content = re.sub(pattern, replacement, content)
    print("✓ Added Documents re-click")
else:
    print("✓ Documents re-click already present")

with open('downloader.py', 'w') as f:
    f.write(content)

print("Done!")
