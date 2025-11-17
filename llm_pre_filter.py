#!/usr/bin/env python3
"""
LLM Pre-filter to evaluate if a case should be downloaded - GPT version
"""
import os
from openai import OpenAI

def should_download_case(case_notes, suspect_name, download_link):
    """
    Use GPT to evaluate if a case should be downloaded based on notes
    
    Returns:
        tuple: (should_download: bool, reason: str)
    """
    
    # Get OpenAI API key from env
    openai_key = os.getenv('OPENAI_API_KEY')
    if not openai_key:
        print("  Warning: No OpenAI API key found, defaulting to DOWNLOAD")
        return True, "No OpenAI API key configured"
    
    client = OpenAI(api_key=openai_key)
    
    prompt = f"""You are evaluating whether a legal case's evidence files should be downloaded via automated web scraping.

Case Details:
- Suspect Name: {suspect_name}
- Download Link: {download_link}
- Case Notes: {case_notes if case_notes else "No notes provided"}

Determine if this case should be downloaded automatically. Answer NO if:
- Notes mention files were "sent via email", "emailed", "mailed on CD", "sent on USB drive", "delivered in person", "sent by mail"
- Notes indicate files are not available online or require physical delivery
- Notes say "no files available", "no evidence", "case closed without files"

Answer YES if:
- Notes indicate files are available online for download
- Notes mention a download link, portal, or online access
- No notes indicate physical delivery or unavailability
- Notes are empty or don't mention delivery method

Respond with ONLY a JSON object (no markdown, no extra text):
{{
  "should_download": true,
  "reason": "Brief explanation"
}}"""
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0
        )
        
        response_text = response.choices[0].message.content.strip()
        
        # Remove markdown code blocks if present
        if response_text.startswith("```"):
            response_text = response_text.split("\n", 1)[1]
            response_text = response_text.rsplit("```", 1)[0]
        
        # Parse JSON response
        import json
        result = json.loads(response_text)
        
        return result.get('should_download', True), result.get('reason', 'No reason provided')
        
    except Exception as e:
        # On error, default to downloading (fail open)
        print(f"  Warning: LLM pre-filter error: {e}")
        print(f"  Defaulting to DOWNLOAD")
        return True, f"LLM error, defaulting to download: {str(e)}"

if __name__ == "__main__":
    # Test cases
    test_cases = [
        {
            "name": "Test 1 - Should Download",
            "notes": "Files available at ShareFile portal",
            "link": "https://example.sharefile.com/test",
            "expected": True
        },
        {
            "name": "Test 2 - Should Skip (Email)",
            "notes": "Files were sent via email on 1/15/2025",
            "link": "https://example.com",
            "expected": False
        },
        {
            "name": "Test 3 - Should Skip (Mailed CD)",
            "notes": "Evidence mailed on CD, tracking#: 123456",
            "link": "",
            "expected": False
        },
        {
            "name": "Test 4 - Should Download (Empty notes)",
            "notes": "",
            "link": "https://example.sharefile.com/test",
            "expected": True
        }
    ]
    
    print("Testing LLM Pre-filter (GPT)")
    print("="*80)
    
    for test in test_cases:
        print(f"\n{test['name']}")
        print(f"  Notes: {test['notes'] or '(empty)'}")
        print(f"  Link: {test['link']}")
        
        should_dl, reason = should_download_case(
            case_notes=test['notes'],
            suspect_name="Test Case",
            download_link=test['link']
        )
        
        print(f"  Decision: {'DOWNLOAD' if should_dl else 'SKIP'}")
        print(f"  Reason: {reason}")
        print(f"  Expected: {'DOWNLOAD' if test['expected'] else 'SKIP'}")
        print(f"  Result: {'✅ PASS' if should_dl == test['expected'] else '❌ FAIL'}")
    
    print("\n" + "="*80)
