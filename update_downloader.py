#!/usr/bin/env python3
"""Update downloader.py with improved login handler"""

# Read the file
with open('downloader.py', 'r') as f:
    lines = f.readlines()

# The new methods to insert
new_methods = '''    def _parse_credentials(self, login_creds: str) -> tuple:
        """
        Intelligently parse login credentials from various formats:
        - 'Username: user@email.com\\nPassword: pass123'
        - 'user@email.com:password'
        - 'user@email.com'
        - 'Reference Number is: 12345'
        """
        # Try to find email/username and password patterns
        email_patterns = [
            r'(?:username|user|email|login)[:\s]+([^\s\n]+)',  # Username: xxx or Email: xxx
            r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',  # Direct email pattern
        ]

        password_patterns = [
            r'(?:password|pass|pwd)[:\s]+([^\s\n]+)',  # Password: xxx
        ]

        username = None
        password = None

        # Try to extract username/email
        for pattern in email_patterns:
            match = re.search(pattern, login_creds, re.IGNORECASE)
            if match:
                username = match.group(1)
                break

        # Try to extract password
        for pattern in password_patterns:
            match = re.search(pattern, login_creds, re.IGNORECASE)
            if match:
                password = match.group(1)
                break

        # Fallback: Check for simple 'username:password' format
        if not username and ':' in login_creds and '\\n' not in login_creds:
            parts = login_creds.split(':', 1)
            username = parts[0].strip()
            password = parts[1].strip() if len(parts) > 1 else ''

        # If we still don't have a username, treat the whole string as username
        if not username:
            username = login_creds.strip()

        logger.info(f'Parsed credentials - Username: {username}, Has password: {bool(password)}')
        return username, password or ''

    def _handle_login(self, page, login_creds: str) -> bool:
        """Handle login using credentials"""
        try:
            # Parse credentials intelligently
            username, password = self._parse_credentials(login_creds)

            if not username:
                logger.error('No username found in credentials')
                return False

            logger.info(f'Attempting login with username: {username}')

            # Find and fill username/email field
            email_selectors = [
                'input[type="email"]',
                'input[type="text"]',
                'input[name*="email"]',
                'input[name*="user"]',
                'input[id*="email"]',
                'input[id*="user"]',
                'input[name="username"]',
                'input[id="username"]'
            ]

            filled = False
            for selector in email_selectors:
                try:
                    if page.locator(selector).count() > 0:
                        page.fill(selector, username, timeout=5000)
                        logger.info(f'Filled username field with selector: {selector}')
                        filled = True
                        break
                except:
                    pass

            if not filled:
                logger.warning('Could not find email/username field')
                return False

            # Fill password field if password exists
            if password:
                try:
                    password_selector = 'input[type="password"]'
                    if page.locator(password_selector).count() > 0:
                        page.fill(password_selector, password, timeout=5000)
                        logger.info('Filled password field')
                    else:
                        logger.warning('No password field found')
                except Exception as e:
                    logger.warning(f'Could not fill password field: {e}')

            # Find and click submit button
            submit_selectors = [
                'button[type="submit"]',
                'input[type="submit"]',
                'button:has-text("Sign in")',
                'button:has-text("Log in")',
                'button:has-text("Login")',
                'button:has-text("Submit")',
                'button:has-text("Continue")',
                'button:has-text("Next")',
                'a:has-text("Sign in")'
            ]

            for selector in submit_selectors:
                try:
                    if page.locator(selector).count() > 0:
                        page.click(selector, timeout=5000)
                        page.wait_for_timeout(5000)
                        logger.info(f'Clicked submit button with selector: {selector}')
                        return True
                except:
                    pass

            logger.warning('Could not find submit button')
            return False

        except Exception as e:
            logger.error(f'Error handling login: {e}')
            import traceback
            traceback.print_exc()
            return False

'''

# Replace the old _handle_login method (lines 434-497 in 0-indexed, so that's lines 435-498 in the file)
new_lines = lines[:434] + [new_methods] + lines[498:]

# Write back
with open('downloader.py', 'w') as f:
    f.writelines(new_lines)

print('Successfully updated downloader.py with improved login handler')
