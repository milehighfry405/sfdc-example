"""
Quick test script for SFDC Deduplication Agent API
Run this after starting the server to verify all endpoints work
"""

import requests
import time
import json

BASE_URL = "http://localhost:8000"


def test_health():
    """Test health check endpoint"""
    print("\n🔍 Testing /health endpoint...")
    response = requests.get(f"{BASE_URL}/health")

    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")

    assert response.status_code == 200
    assert response.json()["status"] in ["healthy", "degraded"]
    print("✅ Health check passed")


def test_root():
    """Test root endpoint"""
    print("\n🔍 Testing / endpoint...")
    response = requests.get(f"{BASE_URL}/")

    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")

    assert response.status_code == 200
    print("✅ Root endpoint passed")


def test_dashboard():
    """Test dashboard metrics endpoint"""
    print("\n🔍 Testing /api/dashboard endpoint...")
    response = requests.get(f"{BASE_URL}/api/dashboard")

    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")

    assert response.status_code == 200
    print("✅ Dashboard endpoint passed")


def test_start_job():
    """Test starting a job"""
    print("\n🔍 Testing POST /api/dedup/start endpoint...")

    payload = {
        "batch_size": 10,  # Small batch for testing
        "auto_approve": True  # Skip human-in-the-loop for test
    }

    response = requests.post(
        f"{BASE_URL}/api/dedup/start",
        json=payload
    )

    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")

    assert response.status_code == 200

    job_id = response.json()["job_id"]
    print(f"✅ Job started with ID: {job_id}")

    return job_id


def test_job_status(job_id):
    """Test getting job status"""
    print(f"\n🔍 Testing GET /api/dedup/status/{job_id} endpoint...")

    # Poll for a few seconds
    for i in range(5):
        response = requests.get(f"{BASE_URL}/api/dedup/status/{job_id}")

        print(f"\nAttempt {i+1}/5:")
        print(f"Status Code: {response.status_code}")
        data = response.json()
        print(f"Job Status: {data['status']}")
        print(f"Progress: {data['progress']['message']}")

        assert response.status_code == 200

        if data["status"] in ["completed", "failed"]:
            print(f"✅ Job {data['status']}")
            break

        time.sleep(2)


def test_list_jobs():
    """Test listing all jobs"""
    print("\n🔍 Testing GET /api/dedup/jobs endpoint...")

    response = requests.get(f"{BASE_URL}/api/dedup/jobs")

    print(f"Status Code: {response.status_code}")
    data = response.json()
    print(f"Total Jobs: {len(data['jobs'])}")

    if data['jobs']:
        print(f"First Job: {json.dumps(data['jobs'][0], indent=2)}")

    assert response.status_code == 200
    print("✅ List jobs passed")


def test_docs():
    """Test OpenAPI docs"""
    print("\n🔍 Testing /docs endpoint...")

    response = requests.get(f"{BASE_URL}/docs")

    print(f"Status Code: {response.status_code}")
    assert response.status_code == 200
    print("✅ Docs endpoint accessible")


def run_all_tests():
    """Run all tests"""
    print("=" * 70)
    print("SFDC Deduplication Agent API - Test Suite")
    print("=" * 70)

    try:
        # Basic endpoints
        test_root()
        test_health()
        test_docs()
        test_dashboard()

        # Job management
        job_id = test_start_job()
        test_job_status(job_id)
        test_list_jobs()

        print("\n" + "=" * 70)
        print("✅ ALL TESTS PASSED")
        print("=" * 70)
        print("\nYour API is ready for deployment! 🚀")
        print(f"\nAPI Documentation: {BASE_URL}/docs")

    except requests.exceptions.ConnectionError:
        print("\n❌ ERROR: Could not connect to API")
        print(f"\nMake sure the server is running:")
        print("  python main.py")
        print(f"  or")
        print("  uvicorn main:app --reload")

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")

    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    run_all_tests()
