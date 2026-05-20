import pytest

from backend.app.services.mineru import MinerUClient, MinerUError


def test_extract_zip_url_from_done_payload():
    data = {"state": "done", "full_zip_url": "https://example.com/result.zip"}

    assert MinerUClient._extract_zip_url(data) == "https://example.com/result.zip"


def test_client_requires_token_for_real_calls():
    client = MinerUClient(token="")

    with pytest.raises(MinerUError, match="MINERU_API_TOKEN"):
        client.submit_task("https://example.com/file.pdf")
