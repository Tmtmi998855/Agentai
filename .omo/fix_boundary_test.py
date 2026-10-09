from pathlib import Path

path = Path("tests/test_ui_review_flow.py")
text = path.read_text(encoding="utf-8")
text = text.replace(
    """    1) company_name='지필로스' (비-가상) 제출 시 fetch 0회 호출, submit disabled=false, 안내 문구 표시 검증
    2) URL 안전 헬퍼 http/https 허용 및 javascript/data/file/invalid 차단 검증
    3) 초기 render gphilos 버튼 활성화 및 섹션 순서 구조 검증
""",
    """    1) company_name='지필로스' (비-가상) 제출 시 fetch 0회 호출, submit disabled=false, 안내 문구 표시 검증
    2) 초기 render gphilos 버튼 활성화 검증
""",
    1,
)
start = text.index("// 2. Check URL safety helper")
end = text.index("// 3. Check Initial GPhilos render", start)
text = text[:start] + "// 2. Check Initial GPhilos render" + text[end + len("// 3. Check Initial GPhilos render"):]
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
path.write_text(text, encoding="utf-8", newline="")
