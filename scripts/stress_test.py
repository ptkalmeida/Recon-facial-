import asyncio
import httpx
import time
import statistics
import concurrent.futures
from datetime import datetime

# Configurações de teste
BASE_URL = "http://localhost:8001/api"
ADMIN_PASSWORD = "admin123" # Altere se necessário
LOGIN_URL = f"{BASE_URL}/auth/login"
HEALTH_URL = f"{BASE_URL}/health"
STATS_URL = f"{BASE_URL}/stats"

async def test_endpoint_latency(client, url, name, iterations=10):
    latencies = []
    print(f"Testing {name}...")
    for _ in range(iterations):
        start = time.perf_counter()
        try:
            resp = await client.get(url)
            if resp.status_code == 200:
                latencies.append(time.perf_counter() - start)
        except Exception as e:
            print(f"Error calling {name}: {e}")
    
    if latencies:
        print(f"  Avg: {statistics.mean(latencies)*1000:.2f}ms")
        print(f"  Min: {statistics.min(latencies)*1000:.2f}ms")
        print(f"  Max: {statistics.max(latencies)*1000:.2f}ms")

async def test_concurrent_logins(num_concurrent=10):
    print(f"\nSimulating {num_concurrent} concurrent login attempts...")
    async with httpx.AsyncClient() as client:
        tasks = []
        for i in range(num_concurrent):
            tasks.append(client.post(LOGIN_URL, json={
                "username": "admin",
                "password": "wrong_password" if i % 2 == 0 else ADMIN_PASSWORD
            }))
        
        start = time.perf_counter()
        responses = await asyncio.gather(*tasks)
        duration = time.perf_counter() - start
        
        success = [r for r in responses if r.status_code == 200]
        blocked = [r for r in responses if r.status_code == 429]
        others = [r for r in responses if r.status_code not in [200, 429]]
        
        print(f"Done in {duration:.2f}s")
        print(f"  Success: {len(success)}")
        print(f"  Rate Limited (429): {len(blocked)}")
        print(f"  Other (401/etc): {len(others)}")

async def run_suite():
    print("=== STARTING STRESS TEST SUITE ===")
    async with httpx.AsyncClient() as client:
        await test_endpoint_latency(client, HEALTH_URL, "Health Check")
        await test_endpoint_latency(client, STATS_URL, "Dashboard Stats (Unauthenticated)")
        
    await test_concurrent_logins(15)
    print("\n=== STRESS TEST SUITE COMPLETE ===")

if __name__ == "__main__":
    asyncio.run(run_suite())
