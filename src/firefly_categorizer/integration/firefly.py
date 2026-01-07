import os
import httpx
from typing import List, Optional
from datetime import datetime

class FireflyClient:
    def __init__(self, base_url: str = None, token: str = None):
        self.base_url = base_url or os.getenv("FIREFLY_URL")
        self.token = token or os.getenv("FIREFLY_TOKEN")
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def get_transactions(self, start_date: datetime = None, end_date: datetime = None, liimt: int = 50) -> List[dict]:
        if not self.base_url or not self.token:
            print("Firefly credentials missing.")
            return []
            
        async with httpx.AsyncClient() as client:
            try:
                # Firefly API filtering by date is via query params
                params = {
                    "limit": liimt,
                    "type": "withdrawal", # Usually we categorize withdrawals
                }
                if start_date:
                    params["start"] = start_date.strftime("%Y-%m-%d")
                if end_date:
                    params["end"] = end_date.strftime("%Y-%m-%d")
                    
                response = await client.get(f"{self.base_url}/api/v1/transactions", headers=self.headers, params=params)
                response.raise_for_status()
                data = response.json()
                return data.get("data", [])
            except Exception as e:
                print(f"Error fetching transactions: {e}")
                return []
