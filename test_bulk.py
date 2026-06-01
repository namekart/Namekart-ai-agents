import sys
from agents.bulk_classifier import run_bulk_classifier

def test_bulk_classifier():
    test_domains = [
        "notion.io",
        "solarfy.com",
        "randomxzqtfp.com",
        "apple.com",
        "verylongdomainnamethatmakessense.com"
    ]
    
    print(f"Running bulk classifier on {len(test_domains)} domains...")
    try:
        results = run_bulk_classifier(test_domains)
        print(f"Received {len(results)} results:")
        for r in results:
            print(f"- {r.domain_name}: score={r.brandability_score}, passed={r.llm_filter_passed}, reason='{r.llm_filter_reason}'")
            
    except Exception as e:
        print(f"Failed to run: {e}")
        print("Make sure you have set OPENROUTER_API_KEY in your .env file!")

if __name__ == "__main__":
    test_bulk_classifier()
