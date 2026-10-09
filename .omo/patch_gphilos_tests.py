from pathlib import Path

html_path = Path("docs/ui-review/review.html")
html = html_path.read_text(encoding="utf-8")
html = html.replace(
    "현재 법인 차량 운용 방식(장기렌트, 리스, 자선 구매 등)은 어떻게 되시나요?",
    "현재 법인 차량 운용 방식(장기렌트, 리스, 자산 구매 등)은 어떻게 되시나요?",
)
html_path.write_text(html, encoding="utf-8", newline="")

test_path = Path("tests/test_ui_review_flow.py")
text = test_path.read_text(encoding="utf-8")
text = text.replace(
    "  AbortController: MockAbortController,\n",
    "  AbortController: MockAbortController,\n  URL: URL,\n",
    1,
)
old = """async function runTest() {
  // 1. Submit form
  elements['form-company-name'].value = '가상테스트고객A';
  const form = elements['briefing-form'];
  let prevented = false;
  form.dispatchEvent({ type: 'submit', preventDefault: () => { prevented = true; } });

  // Allow initial POST fetch promise to resolve
"""
new = """async function runTest() {
  const form = elements['briefing-form'];

  // 1. 실제 회사명은 로컬 Mock API로 전송하지 않아야 한다.
  elements['form-company-name'].value = '지필로스';
  form.dispatchEvent({ type: 'submit', preventDefault: () => {} });
  await new Promise(r => setTimeout(r, 0));
  if (fetchCalls.length !== 0) {
    throw new Error('FAILED: real company name reached Mock API fetch!');
  }
  if (elements['submit-briefing-btn'].disabled !== false) {
    throw new Error('FAILED: blocked real-company submit did not restore idle state!');
  }
  if (!elements['api-status-text'].textContent.includes('가상 고객사명만')) {
    throw new Error('FAILED: real-company submit guard guidance is missing!');
  }

  // 2. 가상 고객사명은 기존 POST/POLL 흐름을 유지한다.
  elements['form-company-name'].value = '가상테스트고객A';
  let prevented = false;
  form.dispatchEvent({ type: 'submit', preventDefault: () => { prevented = true; } });

  // Allow initial POST fetch promise to resolve
"""
if old not in text:
    raise SystemExit("flow test insertion target not found")
text = text.replace(old, new, 1)
append = r'''

def test_ui_review_safe_url_helper_vm(tmp_path):
    """출처 링크는 http/https만 허용하고 실행 가능한 URL 스킴을 차단한다."""
    html_content = REVIEW_HTML_PATH.read_text(encoding="utf-8")
    js_code = extract_inline_js(html_content)
    start_idx = js_code.index("function isSafeHttpUrl(")
    end_idx = js_code.index("function renderSourceUrl(")
    helper_code = js_code[start_idx:end_idx].strip()

    runner = r"""
const vm = require('vm');
const fs = require('fs');
const helperCode = fs.readFileSync(process.argv[2], 'utf8');
const sandbox = { URL };
vm.createContext(sandbox);
vm.runInContext(helperCode, sandbox);

const cases = [
  ['https://example.com/path', true],
  ['http://example.com/path', true],
  ['javascript:alert(1)', false],
  ['data:text/html,test', false],
  ['file:///C:/secret.txt', false],
  ['not a url', false],
  ['', false],
];
for (const [value, expected] of cases) {
  const actual = sandbox.isSafeHttpUrl(value);
  if (actual !== expected) {
    throw new Error('Unexpected safe URL result for ' + JSON.stringify(value));
  }
}
"""

    helper_file = tmp_path / "safe_url_helper.js"
    helper_file.write_text(helper_code, encoding="utf-8")
    runner_file = tmp_path / "run_safe_url_test.js"
    runner_file.write_text(runner, encoding="utf-8")

    res = subprocess.run(
        ["node", str(runner_file), str(helper_file)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, (
        f"Safe URL helper test failed:\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}"
    )
'''
if "def test_ui_review_safe_url_helper_vm" not in text:
    text = text.rstrip() + append + chr(10)
test_path.write_text(text, encoding="utf-8", newline="")

