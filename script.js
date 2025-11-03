// Minimal, robust frontend that posts to POST /api/v1/links and shows result + copy

// Helpers
const translate = (k, d) => d || k;
const showError = (msg) => {
  const box = document.getElementById('error-box');
  box.textContent = msg;
  box.style.display = msg ? 'block' : 'none';
};

// Basic URL normalizer (adds https:// if missing)
function normalizeUrl(url){
  if(!url) return '';
  let s = url.trim();
  if(s.startsWith('/')) return s;
  if(!/^[a-zA-Z][a-zA-Z0-9+\-.]*:\/\//.test(s)){
    s = 'https://' + s;
  }
  return s;
}

document.addEventListener('DOMContentLoaded', () => {
  // Elements
  const form = document.getElementById('shorten-form');
  const longUrlInput = document.getElementById('long-url-input');
  const customCodeInput = document.getElementById('custom-short-code-input');
  const submitButton = document.getElementById('submit-button');
  const resultBox = document.getElementById('result-box');
  const shortUrlLink = document.getElementById('short-url-link');
  const copyButton = document.getElementById('copy-button');
  const ttlSelect = document.getElementById('ttl-select');
  const ttlReadable = document.getElementById('ttl-readable');

  const API = '/api/v1/links';

  console.log('[shortlink] DOM loaded — binding events');

  // TTL UI
  const updateTtlReadable = () => {
    const selected = ttlSelect.options[ttlSelect.selectedIndex].textContent;
    ttlReadable.textContent = selected;
  };
  ttlSelect.addEventListener('change', updateTtlReadable);
  updateTtlReadable();

  // Click handler
  submitButton.addEventListener('click', async (e) => {
    e.preventDefault();
    showError('');
    console.log('[shortlink] shorten clicked');

    const rawUrl = longUrlInput.value || '';
    const long_url = normalizeUrl(rawUrl);
    if(!long_url){
      showError('Please enter a URL.');
      return;
    }

    // Validate custom code (lowercase letters and numbers only)
    let custom_code = (customCodeInput.value || '').trim().toLowerCase();
    if(custom_code && !/^[a-z0-9]+$/.test(custom_code)){
      showError(translate('invalid_custom_code', 'Custom suffix must only contain lowercase letters and numbers.'));
      return;
    }
    if(custom_code === '') custom_code = undefined;

    // Prepare payload
    const payload = { long_url, ttl: ttlSelect.value };
    if(custom_code) payload.custom_code = custom_code;

    // UI: show spinner
    submitButton.disabled = true;
    submitButton.querySelector('.button-text').style.display = 'none';
    const spinner = submitButton.querySelector('.spinner');
    spinner.style.display = 'inline-block';

    try {
      const res = await fetch(API, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      const data = await res.json().catch(()=>({}));

      if(res.ok){
        console.log('[shortlink] success', data);
        shortUrlLink.href = data.short_url;
        shortUrlLink.textContent = data.short_url;
        resultBox.classList.remove('d-none');
        // Clear input for convenience
        longUrlInput.value = '';
        customCodeInput.value = '';
      } else {
        // show useful error
        const msg = data.detail || data.message || `Server error (${res.status})`;
        console.warn('[shortlink] server error', msg);
        showError(msg);
      }
    } catch (err){
      console.error('[shortlink] network error', err);
      showError(translate('network_error', 'Failed to connect to the server.'));
    } finally {
      // reset UI
      submitButton.disabled = false;
      submitButton.querySelector('.button-text').style.display = 'inline-block';
      submitButton.querySelector('.spinner').style.display = 'none';
    }
  });

  // Copy handler
  copyButton.addEventListener('click', async () => {
    const txt = shortUrlLink.textContent || shortUrlLink.href;
    if(!txt) return;
    try {
      if(navigator.clipboard && navigator.clipboard.writeText){
        await navigator.clipboard.writeText(txt);
      } else {
        // fallback
        const ta = document.createElement('textarea');
        ta.value = txt; document.body.appendChild(ta);
        ta.select(); document.execCommand('copy'); ta.remove();
      }
      copyButton.querySelector('i').className = 'bi bi-check-lg';
      copyButton.title = translate('copied', 'Copied!');
      setTimeout(() => {
        copyButton.querySelector('i').className = 'bi bi-clipboard';
        copyButton.title = 'Copy';
      }, 1400);
    } catch (err){
      console.error('copy failed', err);
      showError('Failed to copy URL to clipboard.');
    }
  });

  // Safety: expose debug console message so you (on phone) can see whether script runs
  console.log('[shortlink] script.js loaded and ready');
});
