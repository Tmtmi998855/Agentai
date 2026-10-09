from pathlib import Path

path = Path("tests/test_ui_review_flow.py")
text = path.read_text(encoding="utf-8")
old = """async function runTest() {
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
new = """async function runTest() {
  // 1. Submit form
  elements['form-company-name'].value = '가상테스트고객A';
  const form = elements['briefing-form'];
  let prevented = false;
  form.dispatchEvent({ type: 'submit', preventDefault: () => { prevented = true; } });

  // Allow initial POST fetch promise to resolve
"""
if old not in text:
    raise SystemExit("duplicate flow guard block not found")
text = text.replace(old, new, 1)
marker = chr(10) + "def test_ui_review_safe_url_helper_vm(tmp_path):"
if marker in text:
    text = text.split(marker, 1)[0].rstrip() + chr(10)
path.write_text(text, encoding="utf-8", newline="")
