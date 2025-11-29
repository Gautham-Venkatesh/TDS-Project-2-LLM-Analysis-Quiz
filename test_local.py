#!/usr/bin/env python3
"""
Local testing script for LLM Quiz Solver
Run this before deploying to verify everything works
"""

import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()

# Configuration
BASE_URL = "http://localhost:5000"  # Change to your Render URL for remote testing
EMAIL = os.getenv('STUDENT_EMAIL')
SECRET = os.getenv('STUDENT_SECRET')

def test_health_check():
    """Test the health endpoint"""
    print("Testing health check...")
    try:
        response = requests.get(f"{BASE_URL}/health")
        print(f"Status: {response.status_code}")
        print(f"Response: {response.json()}")
        return response.status_code == 200
    except Exception as e:
        print(f"Error: {e}")
        return False

def test_invalid_json():
    """Test with invalid JSON"""
    print("\nTesting invalid JSON...")
    try:
        response = requests.post(
            f"{BASE_URL}/quiz",
            data="not json",
            headers={"Content-Type": "application/json"}
        )
        print(f"Status: {response.status_code}")
        print(f"Expected: 400, Got: {response.status_code}")
        return response.status_code == 400
    except Exception as e:
        print(f"Error: {e}")
        return False

def test_invalid_secret():
    """Test with invalid secret"""
    print("\nTesting invalid secret...")
    try:
        response = requests.post(
            f"{BASE_URL}/quiz",
            json={
                "email": EMAIL,
                "secret": "wrong-secret",
                "url": "https://example.com/quiz"
            }
        )
        print(f"Status: {response.status_code}")
        print(f"Expected: 403, Got: {response.status_code}")
        return response.status_code == 403
    except Exception as e:
        print(f"Error: {e}")
        return False

def test_demo_quiz():
    """Test with demo quiz"""
    print("\nTesting demo quiz...")
    try:
        response = requests.post(
            f"{BASE_URL}/quiz",
            json={
                "email": EMAIL,
                "secret": SECRET,
                "url": "https://tds-llm-analysis.s-anand.net/demo"
            },
            timeout=180
        )
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        return response.status_code == 200
    except Exception as e:
        print(f"Error: {e}")
        return False

def run_all_tests():
    """Run all tests"""
    print("=" * 50)
    print("LLM Quiz Solver - Test Suite")
    print("=" * 50)
    
    if not EMAIL or not SECRET:
        print("\n❌ Error: STUDENT_EMAIL and STUDENT_SECRET must be set in .env file")
        return
    
    print(f"\nConfiguration:")
    print(f"Base URL: {BASE_URL}")
    print(f"Email: {EMAIL}")
    print(f"Secret: {'*' * len(SECRET)}")
    
    tests = [
        ("Health Check", test_health_check),
        ("Invalid JSON", test_invalid_json),
        ("Invalid Secret", test_invalid_secret),
        ("Demo Quiz", test_demo_quiz)
    ]
    
    results = []
    for name, test_func in tests:
        try:
            passed = test_func()
            results.append((name, passed))
        except Exception as e:
            print(f"Test '{name}' crashed: {e}")
            results.append((name, False))
    
    print("\n" + "=" * 50)
    print("Test Results")
    print("=" * 50)
    
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {name}")
    
    total = len(results)
    passed_count = sum(1 for _, p in results if p)
    
    print(f"\nTotal: {passed_count}/{total} tests passed")
    
    if passed_count == total:
        print("\n🎉 All tests passed! Ready for deployment.")
    else:
        print("\n⚠️  Some tests failed. Please fix issues before deploying.")

if __name__ == "__main__":
    run_all_tests()