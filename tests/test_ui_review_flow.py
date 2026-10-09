"""docs/ui-review/review.html의 인라인 JS 구문 검증 및 완료 제어 흐름 자동 테스트."""

import re
import subprocess
from pathlib import Path

REVIEW_HTML_PATH = Path("docs/ui-review/review.html")


def extract_inline_js(html_content: str) -> str:
    """review.html에서 application/json을 제외한 executable script 태그 내용을 추출한다."""
    matches = re.findall(
        r'<script(?![^>]*type=["\']application/json["\'])(.*?)>(.*?)</script>',
        html_content,
        re.DOTALL,
    )
    js_blocks = [m[1] for m in matches]
    return "\n".join(js_blocks)


def extract_embedded_json(html_content: str) -> str:
    """review.html에서 embedded-json 스크립트 태그 텍스트를 추출한다."""
    match = re.search(
        r'<script id="embedded-json" type="application/json">(.*?)</script>',
        html_content,
        re.DOTALL,
    )
    return match.group(1) if match else "{}"


def test_ui_review_inline_js_syntax(tmp_path):
    """review.html의 인라인 JS 구문을 node --check로 검증한다."""
    html_content = REVIEW_HTML_PATH.read_text(encoding="utf-8")
    js_code = extract_inline_js(html_content)
    assert len(js_code) > 0, "No inline JS extracted from review.html"

    js_file = tmp_path / "review_inline.js"
    js_file.write_text(js_code, encoding="utf-8")

    res = subprocess.run(["node", "--check", str(js_file)], capture_output=True, text=True)
    assert res.returncode == 0, f"node --check failed:\n{res.stderr}"


def test_ui_review_terminal_flow_and_sample_reset(tmp_path):
    """Node environment에서 docs/ui-review/review.html의 인라인 JS 제어 흐름을 실행하여:
    1) terminal 상태(COMPLETED)에서 result fetch 전에 AbortController가 중단(abort)되지 않는지,
    2) 샘플 전환 시 활성 작업이 중단되고 submit 버튼이 idle(disabled=false) 상태로 복원되는지 회귀 검증한다.
    """
    html_content = REVIEW_HTML_PATH.read_text(encoding="utf-8")
    js_code = extract_inline_js(html_content)
    json_text = extract_embedded_json(html_content)

    js_file = tmp_path / "review_inline.js"
    js_file.write_text(js_code, encoding="utf-8")

    json_file = tmp_path / "embedded.json"
    json_file.write_text(json_text, encoding="utf-8")

    test_runner_js = """
const vm = require('vm');
const fs = require('fs');

const jsPath = process.argv[2];
const jsonPath = process.argv[3];
const jsCode = fs.readFileSync(jsPath, 'utf8');
const jsonText = fs.readFileSync(jsonPath, 'utf8');

class MockAbortSignal {
  constructor() {
    this.aborted = false;
    this.onabort = null;
  }
}

class MockAbortController {
  constructor() {
    this.signal = new MockAbortSignal();
  }
  abort() {
    this.signal.aborted = true;
    if (this.signal.onabort) this.signal.onabort();
  }
}

class ElementStub {
  constructor(id, tag = 'div') {
    this.id = id;
    this.tagName = tag;
    this.textContent = '';
    this.value = 'mock_val';
    this.disabled = false;
    this.dataset = {};
    this.listeners = {};
    this.attributes = {};
  }
  addEventListener(event, fn) {
    if (!this.listeners[event]) this.listeners[event] = [];
    this.listeners[event].push(fn);
  }
  dispatchEvent(event) {
    const type = typeof event === 'string' ? event : (event && event.type);
    const evtObj = typeof event === 'string' ? { type: event } : event;
    const evts = this.listeners[type] || [];
    evts.forEach(fn => fn(evtObj));
  }
  setAttribute(k, v) { this.attributes[k] = String(v); }
  getAttribute(k) { return this.attributes[k]; }
  append() {}
  replaceChildren() {}
}

const elements = {
  'embedded-json': new ElementStub('embedded-json', 'script'),
  'preview': new ElementStub('preview'),
  'preview-content': new ElementStub('preview-content'),
  'current-sample-label': new ElementStub('current-sample-label'),
  'briefing-form': new ElementStub('briefing-form', 'form'),
  'submit-briefing-btn': new ElementStub('submit-briefing-btn', 'button'),
  'api-status-text': new ElementStub('api-status-text'),
  'form-company-name': new ElementStub('form-company-name', 'input'),
  'form-sales-company': new ElementStub('form-sales-company', 'input'),
  'form-sales-industry': new ElementStub('form-sales-industry', 'input'),
  'form-sales-product': new ElementStub('form-sales-product', 'input'),
  'form-sales-target': new ElementStub('form-sales-target', 'input'),
  'form-sales-goal': new ElementStub('form-sales-goal', 'input'),
  'form-ctx-department': new ElementStub('form-ctx-department', 'input'),
  'form-ctx-role': new ElementStub('form-ctx-role', 'input'),
  'form-ctx-purpose': new ElementStub('form-ctx-purpose', 'input'),
  'form-ctx-notes': new ElementStub('form-ctx-notes', 'textarea'),
};

elements['embedded-json'].textContent = jsonText;

const sampleBtn = new ElementStub('sample-success', 'button');
sampleBtn.dataset.sampleId = 'success';

const documentStub = {
  getElementById(id) {
    return elements[id] || new ElementStub(id);
  },
  querySelectorAll(selector) {
    if (selector === '[data-sample-id]') return [sampleBtn];
    if (selector === '#width-controls button[data-width]') return [];
    return [];
  },
  createElement(tag) {
    return new ElementStub('dynamic', tag);
  },
  createTextNode(text) {
    return { textContent: text };
  }
};

let fetchCalls = [];

const sandbox = {
  document: documentStub,
  window: {
    location: { protocol: 'http:', pathname: '/ui-review' },
    addEventListener() {}
  },
  AbortController: MockAbortController,
  URL: URL,
  setInterval: (fn, ms) => {
    sandbox._intervalFn = fn;
    return 123;
  },
  clearInterval: (id) => {
    sandbox._intervalCleared = true;
  },
  fetch: (url, opts = {}) => {
    fetchCalls.push({ url, opts, signalAborted: opts.signal ? opts.signal.aborted : undefined });
    if (url === '/v1/briefings' && opts.method === 'POST') {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ job_id: 'job-123', status_url: '/v1/briefing-jobs/job-123', result_url: '/v1/briefings/job-123' })
      });
    }
    if (url === '/v1/briefing-jobs/job-123') {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ status: 'COMPLETED' })
      });
    }
    if (url === '/v1/briefings/job-123') {
      if (opts.signal && opts.signal.aborted) {
        sandbox._resultFetchSignalAborted = true;
      } else {
        sandbox._resultFetchSignalAborted = false;
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ status: 'SUCCESS', company: { name: '가상테스트고객A' } })
      });
    }
    return Promise.reject(new Error('Unknown url: ' + url));
  },
  console: console,
  setTimeout: setTimeout,
};

vm.createContext(sandbox);
vm.runInContext(jsCode, sandbox);

async function runTest() {
  // 1. Submit form
  elements['form-company-name'].value = '가상테스트고객A';
  const form = elements['briefing-form'];
  let prevented = false;
  form.dispatchEvent({ type: 'submit', preventDefault: () => { prevented = true; } });

  // Allow initial POST fetch promise to resolve
  await new Promise(r => setTimeout(r, 20));

  if (!sandbox._intervalFn) throw new Error('Interval function not registered');

  // 2. Trigger interval polling callback (receives COMPLETED)
  sandbox._intervalFn();
  await new Promise(r => setTimeout(r, 20));

  // ASSERTION 1: Result fetch signal must NOT be aborted during COMPLETED flow
  if (sandbox._resultFetchSignalAborted === true) {
    throw new Error('FAILED: result_url fetch was called with an aborted signal!');
  }
  if (sandbox._resultFetchSignalAborted !== false) {
    throw new Error('FAILED: result_url fetch was not called!');
  }

  // 3. Test Sample Button click reset behavior while submit button is disabled/submitting
  elements['submit-briefing-btn'].disabled = true;
  sampleBtn.dispatchEvent({ type: 'click' });

  // ASSERTION 2: Submit button must be restored to disabled=false (idle)
  if (elements['submit-briefing-btn'].disabled !== false) {
    throw new Error('FAILED: Sample click did not restore submit button disabled state to false!');
  }
}

runTest().then(() => {
  process.exit(0);
}).catch(err => {
  console.error(err);
  process.exit(1);
});
"""

    runner_file = tmp_path / "run_flow_test.js"
    runner_file.write_text(test_runner_js, encoding="utf-8")

    res = subprocess.run(["node", str(runner_file), str(js_file), str(json_file)], capture_output=True, text=True)
    assert res.returncode == 0, f"Flow test failed:\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}"


def test_ui_review_http_status_helper_vm(tmp_path):
    """Node vm 환경에서 review.html의 getHttpStatusLabel pure helper의 HTTP 상태 라벨 결정 동작을 회귀 검증한다."""
    html_content = REVIEW_HTML_PATH.read_text(encoding="utf-8")
    js_code = extract_inline_js(html_content)

    test_runner_js = """
const vm = require('vm');
const fs = require('fs');

const jsPath = process.argv[2];
const jsCode = fs.readFileSync(jsPath, 'utf8');

const matchMap = jsCode.match(/const httpStatusByError = \\{[^}]+\\};/);
const startIdx = jsCode.indexOf('function getHttpStatusLabel(');
const endIdx = jsCode.indexOf('const sampleNames =');

if (!matchMap || startIdx === -1 || endIdx === -1) {
  console.error("Failed to extract httpStatusByError or getHttpStatusLabel");
  process.exit(1);
}

const mapCode = matchMap[0];
const fnCode = jsCode.substring(startIdx, endIdx).trim();
const helperCode = mapCode + '\\n' + fnCode;
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(helperCode, sandbox);

const getHttpStatusLabel = sandbox.getHttpStatusLabel;

const testCases = [
  { code: 'PROVIDER_AUTH_ERROR', expected: '502' },
  { code: 'PROVIDER_TIMEOUT', expected: '504' },
  { code: 'INVALID_CITATION', expected: '422' },
  { code: 'HTTP_503', expected: '503' },
  { code: 'HTTP_404', expected: '404' },
  { code: 'POLLING_TIMEOUT', expected: '해당 없음' },
  { code: 'SUBMIT_ERROR', expected: '해당 없음' },
  { code: 'FETCH_ERROR', expected: '해당 없음' },
  { code: 'POLLING_ERROR', expected: '해당 없음' },
  { code: 'UNKNOWN_CODE', expected: '해당 없음' },
  { code: undefined, expected: '해당 없음' }
];

for (const tc of testCases) {
  const actual = getHttpStatusLabel(tc.code);
  if (String(actual) !== tc.expected) {
    console.error(`Mismatch for code "${tc.code}": expected "${tc.expected}", got "${actual}"`);
    process.exit(1);
  }
  if (String(actual) === 'undefined') {
    console.error(`Value "undefined" returned for code "${tc.code}"`);
    process.exit(1);
  }
}

process.exit(0);
"""

    runner_file = tmp_path / "run_helper_test.js"
    runner_file.write_text(test_runner_js, encoding="utf-8")

    js_file = tmp_path / "review_inline.js"
    js_file.write_text(js_code, encoding="utf-8")

    res = subprocess.run(["node", str(runner_file), str(js_file)], capture_output=True, text=True)
    assert res.returncode == 0, f"Helper test failed:\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}"


def test_ui_review_non_virtual_company_boundary_and_url_security_and_gphilos_render(tmp_path):
    """Node vm 환경에서 review.html의:
    1) company_name='지필로스' (비-가상) 제출 시 fetch 0회 호출, submit disabled=false, 안내 문구 표시 검증
    2) 초기 render gphilos 버튼 활성화 검증
    """
    html_content = REVIEW_HTML_PATH.read_text(encoding="utf-8")
    js_code = extract_inline_js(html_content)
    json_text = extract_embedded_json(html_content)

    js_file = tmp_path / "review_inline.js"
    js_file.write_text(js_code, encoding="utf-8")

    json_file = tmp_path / "embedded.json"
    json_file.write_text(json_text, encoding="utf-8")

    runner_js = """
const vm = require('vm');
const fs = require('fs');

const jsPath = process.argv[2];
const jsonPath = process.argv[3];
const jsCode = fs.readFileSync(jsPath, 'utf8');
const jsonText = fs.readFileSync(jsonPath, 'utf8');

class ElementStub {
  constructor(id, tag = 'div') {
    this.id = id;
    this.tagName = tag.toUpperCase();
    this.textContent = '';
    this.value = '';
    this.disabled = false;
    this.dataset = {};
    this.listeners = {};
    this.attributes = {};
    this.children = [];
  }
  addEventListener(event, fn) {
    if (!this.listeners[event]) this.listeners[event] = [];
    this.listeners[event].push(fn);
  }
  dispatchEvent(event) {
    const type = typeof event === 'string' ? event : (event && event.type);
    const evtObj = typeof event === 'string' ? { type: event } : event;
    const evts = this.listeners[type] || [];
    evts.forEach(fn => fn(evtObj));
  }
  setAttribute(k, v) { this.attributes[k] = String(v); }
  getAttribute(k) { return this.attributes[k]; }
  append(...nodes) {
    nodes.forEach(n => {
      if (n) this.children.push(n);
    });
  }
  replaceChildren(...nodes) {
    this.children = [];
    nodes.forEach(n => {
      if (n) this.children.push(n);
    });
  }
}

const gphilosBtn = new ElementStub('sample-gphilos', 'button');
gphilosBtn.dataset.sampleId = 'gphilos';
const successBtn = new ElementStub('sample-success', 'button');
successBtn.dataset.sampleId = 'success';

const elements = {
  'embedded-json': new ElementStub('embedded-json', 'script'),
  'preview': new ElementStub('preview'),
  'preview-content': new ElementStub('preview-content'),
  'current-sample-label': new ElementStub('current-sample-label'),
  'briefing-form': new ElementStub('briefing-form', 'form'),
  'submit-briefing-btn': new ElementStub('submit-briefing-btn', 'button'),
  'api-status-text': new ElementStub('api-status-text'),
  'form-company-name': new ElementStub('form-company-name', 'input'),
  'form-sales-company': new ElementStub('form-sales-company', 'input'),
  'form-sales-industry': new ElementStub('form-sales-industry', 'input'),
  'form-sales-product': new ElementStub('form-sales-product', 'input'),
  'form-sales-target': new ElementStub('form-sales-target', 'input'),
  'form-sales-goal': new ElementStub('form-sales-goal', 'input'),
  'form-ctx-department': new ElementStub('form-ctx-department', 'input'),
  'form-ctx-role': new ElementStub('form-ctx-role', 'input'),
  'form-ctx-purpose': new ElementStub('form-ctx-purpose', 'input'),
  'form-ctx-notes': new ElementStub('form-ctx-notes', 'textarea'),
  'sample-gphilos': gphilosBtn,
  'sample-success': successBtn,
};

elements['embedded-json'].textContent = jsonText;

const documentStub = {
  getElementById(id) {
    return elements[id] || new ElementStub(id);
  },
  querySelectorAll(selector) {
    if (selector === '[data-sample-id]') return [gphilosBtn, successBtn];
    if (selector === '#width-controls button[data-width]') return [];
    return [];
  },
  createElement(tag) {
    return new ElementStub('dynamic', tag);
  },
  createTextNode(text) {
    return { textContent: text };
  }
};

let fetchCalls = [];

const sandbox = {
  document: documentStub,
  window: {
    location: { protocol: 'http:', pathname: '/ui-review' },
    addEventListener() {}
  },
  AbortController: class { constructor() { this.signal = {}; } abort() {} },
  setInterval: () => 1,
  clearInterval: () => {},
  fetch: (url, opts = {}) => {
    fetchCalls.push({ url, opts });
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  },
  console: console,
  setTimeout: setTimeout,
  URL: global.URL
};

vm.createContext(sandbox);
vm.runInContext(jsCode, sandbox);

// 1. Check Non-virtual company boundary ('지필로스')
fetchCalls = [];
elements['form-company-name'].value = '지필로스';
const form = elements['briefing-form'];
form.dispatchEvent({ type: 'submit', preventDefault: () => {} });

if (fetchCalls.length !== 0) {
  throw new Error('FAILED: Non-virtual company submission called fetch! Count: ' + fetchCalls.length);
}
if (elements['submit-briefing-btn'].disabled !== false) {
  throw new Error('FAILED: Submit button was left disabled after non-virtual company check!');
}
const noticeText = elements['api-status-text'].textContent;
if (!noticeText.includes('Mock 분석은 가상 고객사명만 실행할 수 있습니다')) {
  throw new Error('FAILED: Notice message missing expected text. Got: ' + noticeText);
}

// 2. Check Initial GPhilos render
if (gphilosBtn.getAttribute('aria-pressed') !== 'true') {
  throw new Error('FAILED: Initial gphilos sample button aria-pressed is not true');
}
const labelText = elements['current-sample-label'].textContent;
if (!labelText.includes('지필로스 시안')) {
  throw new Error('FAILED: Sample label does not include 지필로스 시안. Got: ' + labelText);
}

process.exit(0);
"""

    runner_file = tmp_path / "run_boundary_test.js"
    runner_file.write_text(runner_js, encoding="utf-8")

    res = subprocess.run(["node", str(runner_file), str(js_file), str(json_file)], capture_output=True, text=True)
    assert res.returncode == 0, f"Boundary and URL test failed:\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}"

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

