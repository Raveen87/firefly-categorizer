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

    async def get_transactions(self, start_date: datetime = None, end_date: datetime = None, limit: int = 50) -> List[dict]:
        if not self.base_url or not self.token:
            print("Firefly credentials missing.")
            return []
            
        async with httpx.AsyncClient() as client:
            try:
                # Firefly API filtering by date is via query params
                params = {
                    "limit": limit,
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

    async def get_categories(self) -> List[dict]:
        if not self.base_url or not self.token:
            return []
            
        async with httpx.AsyncClient() as client:
            try:
                # Firefly API for categories
                response = await client.get(f"{self.base_url}/api/v1/categories", headers=self.headers)
                response.raise_for_status()
                data = response.json()
                return data.get("data", [])
            except Exception as e:
                print(f"Error fetching categories: {e}")
                return []

    async def update_transaction(self, transaction_id: str, category_name: str) -> bool:
        if not self.base_url or not self.token:
            return False
            
        async with httpx.AsyncClient() as client:
            try:
                # Update transaction category
                # Payload format: { "transactions": [ { "category_name": "New Category" } ] }
                payload = {
                    "transactions": [
                        {
                            "category_name": category_name
                        }
                    ]
                }
                response = await client.put(
                    f"{self.base_url}/api/v1/transactions/{transaction_id}", 
                    headers=self.headers,
                    json=payload
                )
                response.raise_for_status()
                return True
            except Exception as e:
                print(f"Error updating transaction {transaction_id}: {e}")
                return False
