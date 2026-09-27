import re
import math

def extract_numbers(text: str) -> list[float]:
    """
    Extracts all numeric tokens from text.
    Strips thousands separators (,) and currency symbols/prefixes/suffixes (Rs, USD, $, INR, %).
    Handles decimals.
    """
    if not text:
        return []
    
    pattern = r'-?\d{1,3}(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?'
    
    matches = re.findall(pattern, text)
    result = []
    for m in matches:
        clean_num = m.replace(',', '')
        try:
            result.append(float(clean_num))
        except ValueError:
            pass
            
    return result

def normalize(x: float) -> float:
    """Round to 4 significant figures for tolerance-safe comparison."""
    if x == 0.0:
        return 0.0
    order = math.floor(math.log10(abs(x)))
    digits = 4 - 1 - order
    # Handle extremely large orders where rounding negative digits returns an int but it's safe as float
    return round(x, int(digits))

def is_grounded(number: float, allowed_numbers: list[float], rel_tol=0.005) -> bool:
    """Membership within 0.5 percent relative tolerance."""
    norm_num = normalize(number)
    for allowed in allowed_numbers:
        norm_allow = normalize(allowed)
        if norm_num == norm_allow:
            return True
        if norm_allow != 0.0:
            if abs(norm_num - norm_allow) / abs(norm_allow) <= rel_tol:
                return True
        elif abs(norm_num) <= rel_tol:
            return True
    return False

def faithfulness_rate(answers: list[dict]) -> dict:
    """
    answers is a list of dicts with keys: 'answer', 'allowed_numbers'
    returns dict with per-answer detail and totals.
    """
    results = []
    passed = 0
    total = len(answers)
    
    for ans in answers:
        text = ans.get('answer', '')
        allowed = ans.get('allowed_numbers', [])
        nums = extract_numbers(text)
        
        is_pass = True
        for num in nums:
            if not is_grounded(num, allowed):
                is_pass = False
                break
                
        results.append({
            "answer": text,
            "extracted": nums,
            "allowed": allowed,
            "pass": is_pass
        })
        if is_pass:
            passed += 1
            
    return {
        "passed": passed,
        "total": total,
        "rate": passed / total if total > 0 else 0.0,
        "details": results
    }
