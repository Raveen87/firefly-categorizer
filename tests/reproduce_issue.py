
import re

from fastapi.testclient import TestClient

from firefly_categorizer.main import app

client = TestClient(app)

def test_index_params() -> None:
    response = client.get("/?start_date=2023-02-01&end_date=2023-02-28")
    assert response.status_code == 200
    content = response.text

    # Check start_date value in input
    match_start = re.search(r'name="start_date" class="border p-2 rounded" value="([^"]*)"', content)
    if match_start:
        print(f"Start date value: '{match_start.group(1)}'")
    else:
        print("Start date input not found")

    # Check end_date value in input
    match_end = re.search(r'name="end_date" class="border p-2 rounded" value="([^"]*)"', content)
    if match_end:
        print(f"End date value: '{match_end.group(1)}'")
    else:
        print("End date input not found")

if __name__ == "__main__":
    test_index_params()
