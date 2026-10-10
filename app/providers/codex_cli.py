"""Codex CLI 기반 ReasoningProvider — 로컬 PC에 로그인된 Codex CLI로 GPT-6 Luna를 호출한다.

API 키 없이 `codex login`(ChatGPT 계정) 상태를 그대로 쓴다.
호출 방식: codex exec - (프롬프트는 stdin) → 최종 메시지를 파일(-o)로 받아 JSON 파싱.

안전장치
- 임시 빈 폴더에서 실행하고 --sandbox read-only, --ephemeral, --skip-git-repo-check 사용
  (외부 기사 문구에 섞인 지시문이 저장소 파일을 읽거나 바꾸지 못하게 한다)
- 출력은 서버가 Pydantic으로 다시 검증하므로 여기서는 JSON 객체 추출까지만 한다.
"""

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import anyio

from app.domain.models import ProviderResult

JSON_INSTRUCTION = (
    "\n\n[출력 형식]\n"
    "도구나 셸 명령을 쓰지 말고, 아래 JSON Schema를 만족하는 JSON 객체 하나만 출력한다. "
    "설명 문장이나 코드펜스 없이 JSON만 출력한다.\n"
)


def extract_json_object(text: str) -> dict[str, Any] | None:
    """모델 응답에서 첫 '{'부터 마지막 '}'까지를 JSON 객체로 파싱한다."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


class CodexCliReasoningProvider:
    def __init__(self, command: str = "codex", default_model: str = "gpt-6-luna", timeout_s: int = 180):
        self.command = command
        self.default_model = default_model
        self.timeout_s = timeout_s

    def resolve_executable(self) -> str | None:
        # Windows에서는 npm 설치본이 codex.cmd라서 which로 실제 경로를 찾는다.
        return shutil.which(self.command)

    def build_prompt(self, messages: list[dict[str, Any]], response_schema: dict[str, Any]) -> str:
        parts = [f"[{m.get('role', 'user')}]\n{m.get('content', '')}" for m in messages]
        return "\n\n".join(parts) + JSON_INSTRUCTION + json.dumps(response_schema, ensure_ascii=False)

    def build_args(self, executable: str, model: str, output_file: Path) -> list[str]:
        args = [executable, "exec", "--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral",
                "-o", str(output_file)]
        if model:
            args += ["--model", model]
        return args + ["-"]

    async def generate_structured(
        self,
        *,
        task: str,
        messages: list[dict[str, Any]],
        response_schema: dict[str, Any],
        model: str | None = None,
        timeout_s: int | None = None,
    ) -> ProviderResult:
        # 파이프라인 서비스가 넘기는 "mock-model" 기본값은 무시하고 설정된 모델을 쓴다.
        use_model = self.default_model if not model or model == "mock-model" else model
        timeout = max(timeout_s or 0, self.timeout_s)

        def fail(code: str, message: str) -> ProviderResult:
            return ProviderResult(provider="codex_cli", requested_model=use_model, actual_model=use_model,
                                  success=False, error=message, error_code=code)

        executable = self.resolve_executable()
        if executable is None:
            return fail("PROVIDER_AUTH_ERROR", f"'{self.command}' 명령을 찾을 수 없습니다. Codex CLI 설치를 확인하세요.")

        prompt = self.build_prompt(messages, response_schema)
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="ahthere-codex-") as workdir:
            output_file = Path(workdir) / "last_message.txt"
            args = self.build_args(executable, use_model, output_file)
            try:
                proc = await anyio.to_thread.run_sync(
                    lambda: subprocess.run(
                        args, input=prompt, capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=workdir, timeout=timeout,
                    )
                )
            except subprocess.TimeoutExpired:
                return fail("PROVIDER_TIMEOUT", f"Codex CLI 응답이 {timeout}초를 넘었습니다.")
            except OSError as exc:
                return fail("PROVIDER_ERROR", f"Codex CLI 실행 실패: {type(exc).__name__}")

            if proc.returncode != 0:
                stderr = (proc.stderr or "").lower()
                code = "PROVIDER_AUTH_ERROR" if ("login" in stderr or "auth" in stderr) else "PROVIDER_ERROR"
                return fail(code, f"Codex CLI 종료 코드 {proc.returncode}")

            text = output_file.read_text(encoding="utf-8") if output_file.exists() else (proc.stdout or "")

        data = extract_json_object(text)
        if data is None:
            return fail("PROVIDER_INVALID_JSON", f"{task}: Codex 응답에서 JSON 객체를 찾지 못했습니다.")
        return ProviderResult(
            provider="codex_cli",
            requested_model=use_model,
            actual_model=use_model,
            content=text,
            structured_data=data,
            latency_ms=(time.perf_counter() - started) * 1000,
        )
