from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from tempfile import NamedTemporaryFile

import requests

from ..config import settings


DONE_STATES = {"done", "completed", "complete", "success", "succeeded", "finished"}
FAILED_STATES = {"failed", "error", "cancelled", "canceled"}


@dataclass
class MinerUTaskResult:
    task_id: str
    state: str
    zip_url: str
    raw: dict


class MinerUError(RuntimeError):
    pass


class MinerUClient:
    def __init__(self, api_base: str | None = None, token: str | None = None) -> None:
        self.api_base = (api_base or settings.mineru_api_base).rstrip("/")
        self.token = token if token is not None else settings.mineru_api_token

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise MinerUError("MINERU_API_TOKEN is required for real MinerU extraction.")
        return {"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"}

    def submit_task(self, pdf_url: str) -> str:
        payload = {"url": pdf_url, "model_version": settings.mineru_model_version}
        response = requests.post(
            f"{self.api_base}/extract/task", headers=self._headers(), json=payload, timeout=30
        )
        response.raise_for_status()
        data = response.json()
        if data.get("code") not in (0, "0", None):
            raise MinerUError(data.get("msg") or "MinerU task submission failed.")
        task_data = data.get("data") or {}
        task_id = task_data.get("task_id") or task_data.get("batch_id") or task_data.get("id")
        if not task_id:
            raise MinerUError(f"MinerU response did not include a task id: {data}")
        return str(task_id)

    def poll_until_done(self, task_id: str) -> MinerUTaskResult:
        latest: dict = {}
        for _ in range(settings.mineru_max_poll_attempts):
            latest = self.get_task(task_id)
            data = latest.get("data") or latest
            state = str(
                data.get("state") or data.get("status") or data.get("task_state") or ""
            ).lower()
            if state in DONE_STATES:
                zip_url = self._extract_zip_url(data)
                if not zip_url:
                    raise MinerUError(f"MinerU task completed without a zip URL: {latest}")
                return MinerUTaskResult(task_id=task_id, state=state, zip_url=zip_url, raw=latest)
            if state in FAILED_STATES:
                raise MinerUError(data.get("err_msg") or data.get("message") or "MinerU task failed.")
            time.sleep(settings.mineru_poll_interval_seconds)
        raise MinerUError(f"MinerU task timed out after polling {task_id}. Last response: {latest}")

    def get_task(self, task_id: str) -> dict:
        response = requests.get(
            f"{self.api_base}/extract/task/{task_id}", headers=self._headers(), timeout=30
        )
        response.raise_for_status()
        data = response.json()
        if data.get("code") not in (0, "0", None):
            raise MinerUError(data.get("msg") or "MinerU task polling failed.")
        return data

    def download_zip(self, zip_url: str) -> bytes:
        last_error: Exception | None = None
        for _ in range(settings.mineru_download_retry_count):
            try:
                response = requests.get(zip_url, timeout=120)
                response.raise_for_status()
                return response.content
            except requests.RequestException as exc:
                last_error = exc
                time.sleep(settings.mineru_download_retry_delay_seconds)
        try:
            return self._download_zip_with_curl(zip_url)
        except Exception as curl_error:
            raise MinerUError(
                f"Failed to download MinerU zip: {last_error}; curl fallback failed: {curl_error}"
            ) from curl_error

    @staticmethod
    def _download_zip_with_curl(zip_url: str) -> bytes:
        with NamedTemporaryFile(suffix=".zip") as tmp:
            completed = subprocess.run(
                ["curl", "-L", "--fail", "--silent", "--show-error", "-o", tmp.name, zip_url],
                check=False,
                capture_output=True,
                text=True,
            )
            if completed.returncode != 0:
                raise MinerUError(completed.stderr.strip() or "curl returned a non-zero exit code")
            tmp.seek(0)
            return tmp.read()

    @staticmethod
    def _extract_zip_url(data: dict) -> str:
        for key in ("full_zip_url", "zip_url", "download_url", "file_url", "result_url"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
        result = data.get("result") or {}
        if isinstance(result, dict):
            for key in ("full_zip_url", "zip_url", "download_url", "file_url", "result_url"):
                value = result.get(key)
                if isinstance(value, str) and value:
                    return value
        return ""
