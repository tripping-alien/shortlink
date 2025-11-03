// Global translation map setup outside of main logic
let translations = {};

// Function to safely access the global translations
const translate = (key, fallback = key) => translations[key] || fallback;

// Utility to show Bootstrap Toasts
const showToast = (message, type = 'info') => {
    const toastContainer = document.getElementById('toast-container');
    const toastHtml = `
        <div class="toast align-items-center text-white bg-${type} border-0" role="alert" aria-live="assertive" aria-atomic="true" data-bs-delay="3000">
            <div class="d-flex">
                <div class="toast-body">${message}</div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
            </div>
        </div>
    `;
    const tempDiv = document.createElement('div');
    tempDiv.innerHTML = toastHtml;
    const toastEl = tempDiv.firstChild;
    toastContainer.appendChild(toastEl);
    
    const toast = new bootstrap.Toast(toastEl);
    toast.show();

    toastEl.addEventListener('hidden.bs.toast', () => {
        toastEl.remove();
    });
};


// Function to ensure URL has a protocol (scheme)
const normalizeUrl = (url) => {
    // Trim whitespace
    let normalized = url.trim();

    // Check if it's a relative path (starts with /)
    if (normalized.startsWith('/')) {
        return normalized;
    }

    // Check if it already has http:// or https://
    if (!normalized.match(/^[a-zA-Z]+:\/\//)) {
        // If no scheme is present, assume https://
        normalized = 'https://' + normalized;
    }
    return normalized;
};


// Main execution block
document.addEventListener('DOMContentLoaded', async () => {
    const form = document.getElementById('shorten-form');
    const longUrlInput = document.getElementById('long-url-input');
    const customCodeInput = document.getElementById('custom-short-code-input');
    const submitButton = document.getElementById('submit-button');
    const resultBox = document.getElementById('result-box');
    const shortUrlLink = document.getElementById('short-url-link');
    const copyButton = document.getElementById('copy-button');
    const ttlSelect = document.getElementById('ttl-select');
    const ttlInfoText = document.getElementById('ttl-info-text');

    // 1. Fetch Translations
    // Note: The base URL for the API is dynamically determined by the context, 
    // but in a browser context, we can often rely on relative paths.
    try {
        const langCodeMatch = window.location.pathname.match(/\/ui\/(\w{2})\//);
        const langCode = langCodeMatch ? langCodeMatch[1] : 'en';
        const response = await fetch(`/api/v1/translations/${langCode}`);
        if (response.ok) {
            translations = await response.json();
        }
    } catch (e) {
        console.error("Could not load translations:", e);
    }

    // 2. TTL Info Text Handler
    const updateTtlInfo = () => {
        const selectedOption = ttlSelect.options[ttlSelect.selectedIndex];
        const ttlValue = selectedOption.value;
        const durationText = selectedOption.textContent;
        
        const info = document.getElementById('ttl-info-text');
        
        if (ttlValue === 'never') {
            info.textContent = translate('expire_never', 'Your link will not expire.');
        } else {
            // Replace the placeholder {duration} in the translated string
            let text = translate('expire_in_duration', 'Your link is private and will automatically expire in {duration}.');
            info.textContent = text.replace('{duration}', durationText);
        }
    };

    ttlSelect.addEventListener('change', updateTtlInfo);
    updateTtlInfo(); // Initial call

    // 3. Form Submission Handler
    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        // 3.1 Get and normalize URL
        const rawLongUrl = longUrlInput.value;
        const longUrl = normalizeUrl(rawLongUrl);

        // 3.2 Validate custom code (must be lowercase alphanumeric only)
        let customCode = customCodeInput.value.trim().toLowerCase();
        const customCodePattern = /^[a-z0-9]*$/; 

        if (customCode && !customCodePattern.test(customCode)) {
            showToast(
                translate('invalid_custom_code', "Custom suffix must only contain lowercase letters (a-z) and numbers (0-9)."), 
                'warning'
            );
            return;
        }

        // 3.3 Prepare payload (only include custom_code if it has content)
        const payload = {
            long_url: longUrl,
            ttl: ttlSelect.value
        };
        // CRITICAL FIX: Only send custom_code if it is non-empty
        if (customCode) {
            payload.custom_code = customCode;
        }

        // 3.4 UI State: Loading
        submitButton.disabled = true;
        submitButton.querySelector('.button-text').style.display = 'none';
        submitButton.querySelector('.spinner').classList.add('spinner-border', 'spinner-border-sm');
        submitButton.querySelector('.spinner').style.display = 'inline-block';
        resultBox.classList.add('d-none'); // Hide previous result

        try {
            // 3.5 API Call
            const response = await fetch('/api/v1/links', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            // 3.6 Handle Response
            if (response.ok) {
                const result = await response.json();
                
                shortUrlLink.href = result.short_url;
                shortUrlLink.textContent = result.short_url;
                copyButton.setAttribute('data-clipboard-text', result.short_url);
                resultBox.classList.remove('d-none');
                
                // Clear inputs on success
                longUrlInput.value = '';
                customCodeInput.value = '';

                // Trigger a confetti animation (conceptual)
                document.getElementById('animation-overlay').innerHTML = `<div class="confetti">🎉 Link Created!</div>`;
                setTimeout(() => document.getElementById('animation-overlay').innerHTML = '', 1500);

            } else {
                const errorData = await response.json();
                let errorMessage = translate('default_error', 'An unexpected error occurred.');
                
                if (response.status === 409) {
                    // Custom code collision
                    errorMessage = errorData.detail;
                } else if (response.status === 422) {
                    // Validation errors (e.g., long_url format)
                    errorMessage = "Invalid URL format. Ensure it starts with http:// or https://";
                } else {
                    errorMessage = errorData.detail || errorMessage;
                }
                
                showToast(errorMessage, 'danger');
            }
        } catch (error) {
            console.error('Network or unexpected error:', error);
            showToast(translate('network_error', 'Failed to connect to the server.'), 'danger');
        } finally {
            // 3.7 UI State: Reset
            submitButton.disabled = false;
            submitButton.querySelector('.button-text').style.display = 'inline-block';
            submitButton.querySelector('.spinner').classList.remove('spinner-border', 'spinner-border-sm');
            submitButton.querySelector('.spinner').style.display = 'none';
        }
    });

    // 4. Copy Button Handler
    copyButton.addEventListener('click', (e) => {
        e.preventDefault();
        const textToCopy = shortUrlLink.textContent;
        
        // Use the older execCommand approach for broader compatibility in sandboxed environments
        const tempInput = document.createElement('textarea');
        tempInput.value = textToCopy;
        document.body.appendChild(tempInput);
        tempInput.select();
        try {
            document.execCommand('copy');
            copyButton.querySelector('i').className = 'bi bi-check-lg';
            copyButton.setAttribute('title', translate('copied', 'Copied!'));
            showToast(translate('copied', 'Copied!'), 'success');
            
            setTimeout(() => {
                copyButton.querySelector('i').className = 'bi bi-clipboard';
                copyButton.setAttribute('title', translate('copy', 'Copy'));
            }, 2000);

        } catch (err) {
            console.error('Failed to copy text: ', err);
            showToast('Failed to copy URL.', 'warning');
        } finally {
            document.body.removeChild(tempInput);
        }
    });
});
