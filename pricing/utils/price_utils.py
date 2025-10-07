import re

def parse_price_from_response(price_response):
    """Extract decimal price from AI response"""
    match = re.search(r"(.*)FINAL:\s*£\s*(\d+(?:\.\d+)?)", price_response, re.DOTALL)
    if match:
        price_str = match.group(2)
        return float(price_str)
    # Fallback: try to extract any number if the pattern doesn't match
    match_fallback = re.search(r"£?\s*(\d+(?:\.\d+)?)", price_response)
    if match_fallback:
        return float(match_fallback.group(1))
    return 0.0  # Default fallback


def calculate_confidence(competitor_count):
    """Calculate confidence score based on competitor count"""
    return min(100, competitor_count * 15)

