/**
 * Main script for handling UI interactions.
 */
document.addEventListener('DOMContentLoaded', function() {
    // --- Dynamic Comic Book Theming Experiment ---
    const comicPalette = {
        '--bg-color': '#f0f4f8', // A very light, cool grey background
        '--panel-bg': '#ffffff', // Keep panel white for a clean look
        '--text-color': '#212529', // Standard dark text for high contrast
        '--primary-color': '#0052cc', // A more classic, slightly desaturated blue
        '--primary-color-hover': '#0039cb',
        '--secondary-color': '#d50000', // A bold comic red for accents
        '--border-color': '#000000', // Strong black for outlines
        '--input-bg': '#f1f3f5', // A very light grey for the default input state
        '--bs-primary-rgb': '0, 82, 204',
        '--animation-color-vec': [0.0, 0.32, 0.8] // Matching blue for the (currently disabled) animation
        }

    const chosenPalette = comicPalette;

    // Apply the chosen palette to the root element
    for (const [key, value] of Object.entries(chosenPalette)) {
        if (key !== '--animation-color-vec') { // Don't set the animation color as a CSS var
            document.documentElement.style.setProperty(key, value);
        }
    }

    // Add a class to the body once the DOM is ready to trigger animations
    document.body.classList.add('page-loaded');
});

document.addEventListener('DOMContentLoaded', function() {
    const shortenForm = document.getElementById('shorten-form');

    // This part of the script is specific to the main page (index.html)
    if (shortenForm) {
        const longUrlInput = document.getElementById('long-url-input');
        const customCodeInput = document.getElementById('custom-short-code-input'); // <-- NEW: Get the custom code input

        // Focus the input field on page load for immediate use
        longUrlInput.focus();

        const submitButton = document.getElementById('submit-button');
        const buttonText = submitButton.querySelector('.button-text');
        const spinner = submitButton.querySelector('.spinner');
        const resultBox = document.getElementById('result-box');
        const shortUrlLink = document.getElementById('short-url-link');
        const copyButton = document.getElementById('copy-button');
        const toastContainer = document.getElementById('toast-container');
        const ttlSelect = document.getElementById('ttl-select');

        // --- Default Translations for Fallback ---
        // This helps prevent "Could not load settings" errors by providing 
        // essential fallbacks if the API call fails.
        const defaultI18n = {
            copy: 'Copy',
            copied: 'Copied!',
            ttl_1_hour: '1 Hour',
            ttl_24_hours: '24 Hours',
            ttl_1_week: '1 Week',
            expire_never: 'Your link will not expire.',
            expire_in_duration: 'Your link is private and will automatically expire in {duration}.',
            default_error: 'An unexpected error occurred.',
            network_error: 'Failed to connect to the server. Check your network or try again later.'
        };
        let i18n = defaultI18n; // Use the default until translations are loaded

        function showToast(message, type = 'danger') {
        if (!toastContainer) return;

        const toastId = `toast-${Date.now()}`;
        const toastHTML = `
            <div id="${toastId}" class="toast align-items-center text-bg-${type} border-0" role="alert" aria-live="assertive" aria-atomic="true">
                <div class="d-flex">
                    <div class="toast-body">
                        ${message}
                    </div>
                    <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
                </div>
            </div>
        `;
        toastContainer.insertAdjacentHTML('beforeend', toastHTML);

        const toastElement = document.getElementById(toastId);
        const toast = new bootstrap.Toast(toastElement, { delay: 5000 });
        toast.show();

        // Clean up the element from the DOM after it's hidden
        toastElement.addEventListener('hidden.bs.toast', () => {
            toastElement.remove();
        });
        }

        shortenForm.addEventListener('submit', async(event) => {
            event.preventDefault();

            // Hide previous result
            resultBox.classList.add('d-none');
            resultBox.classList.remove('fade-in-up');

            // Show loading state
            buttonText.classList.add('d-none');
            spinner.style.display = 'inline-block';
            submitButton.disabled = true;

            const payload = {
                long_url: longUrlInput.value,
                ttl: ttlSelect.value,
                // Add custom_code to payload if it's not empty
                custom_code: customCodeInput.value.trim() || undefined // <-- NEW: Include custom code
            };

            try {
                const response = await fetch('/api/v1/links', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                // Check for network errors first
                if (!response.ok && response.status === 0) {
                    throw new Error(i18n.network_error);
                }

                const data = await response.json();

                if (!response.ok) {
                    let errorMessage = i18n.default_error;
                    
                    // 2. Fix for "Invalid short code format" and other validation errors
                    if (data.detail) {
                        // Handle Pydantic validation error format (list of dicts)
                        if (Array.isArray(data.detail) && data.detail[0] && data.detail[0].msg) {
                            errorMessage = data.detail.map(d => d.msg).join('; ');
                        } else if (typeof data.detail === 'string') {
                            errorMessage = data.detail;
                        } else if (data.detail.msg) {
                            // Handle simple error messages like the short code format
                            errorMessage = data.detail.msg;
                        } else if (typeof data.detail === 'object') {
                            // Catch all for other JSON error responses
                             errorMessage = JSON.stringify(data.detail);
                        }
                    }
                    throw new Error(errorMessage);
                }

                // 1. Clear the custom URL field after successful shortening
                longUrlInput.value = '';
                customCodeInput.value = ''; // <-- FIX: Clear the custom code input

                // Use the full URL for the clipboard, but a relative path for the link's href
                const fullUrl = data.short_url;
                const relativePath = new URL(fullUrl).pathname; // Extracts "/get/Bx7vq"

                shortUrlLink.href = relativePath;
                copyButton.dataset.fullUrl = fullUrl;

                // Build the comic-style link display
                const urlObject = new URL(fullUrl);
                const domain = urlObject.hostname;
                const code = urlObject.pathname;
                shortUrlLink.innerHTML = `<span class="short-url-domain">${domain}</span><span class="short-url-code">${code}</span>`;

                resultBox.classList.remove('d-none');
                resultBox.classList.add('fade-in-up');

                // Reset copy button state
                copyButton.innerHTML = '<i class="bi bi-clipboard"></i>';
                copyButton.title = copyButton.dataset.copyText || defaultI18n.copy;

            } catch (error) {
                showToast(error.message, 'danger');
            } finally {
                // Restore button state
                spinner.style.display = 'none';
                submitButton.disabled = false;
                buttonText.classList.remove('d-none');
            }
        });

        // --- Copy Button Handler ---
        if (copyButton) {
            copyButton.addEventListener('click', () => {
                const urlToCopy = copyButton.dataset.fullUrl;
                if (!urlToCopy) return;

                // Use the older execCommand for better cross-iframe compatibility
                const tempTextArea = document.createElement('textarea');
                tempTextArea.value = urlToCopy;
                document.body.appendChild(tempTextArea);
                tempTextArea.select();
                try {
                    document.execCommand('copy');
                    copyButton.innerHTML = '<i class="bi bi-clipboard-check-fill"></i>';
                    copyButton.title = copyButton.dataset.copiedText || defaultI18n.copied;

                    setTimeout(() => {
                        copyButton.innerHTML = '<i class="bi bi-clipboard"></i>';
                        copyButton.title = copyButton.dataset.copyText || defaultI18n.copy;
                    }, 2000);
                } catch (err) {
                    showToast('Failed to copy link. Please copy manually.', 'danger');
                }
                document.body.removeChild(tempTextArea);

            });
        }

        // --- TTL Persistence and UI Update (now inside the shortenForm check) ---
        const TTL_STORAGE_KEY = 'bijective_shorty_ttl';

        const updateTtlInfo = () => {
            const ttlInfoText = document.getElementById('ttl-info-text');
            if (!ttlInfoText || !ttlSelect) return;

            const selectedValue = ttlSelect.value;
            let durationText = '';

            if (selectedValue === '1h') {
                durationText = i18n.ttl_1_hour;
            } else if (selectedValue === '1d') {
                durationText = i18n.ttl_24_hours;
            } else if (selectedValue === '1w') {
                durationText = i18n.ttl_1_week;
            }

            if (selectedValue === 'never') {
                ttlInfoText.textContent = i18n.expire_never;
            } else {
                // Use replace() method for simple string substitution
                ttlInfoText.textContent = i18n.expire_in_duration.replace('{duration}', durationText);
            }
        };

        // 3. Fix for "Could not load settings" (yellow) on start
        (async function initMainPage() {
            const langCode = document.documentElement.lang || 'en';
            try {
                const response = await fetch(`/api/v1/translations/${langCode}`);
                if (!response.ok) throw new Error('Failed to load translations');
                
                // Successfully loaded translations, overwrite default
                i18n = await response.json(); 
                
                // Set translations for the copy button tooltips
                copyButton.dataset.copyText = i18n.copy;
                copyButton.dataset.copiedText = i18n.copied;

            } catch (error) {
                // If translation loading fails, we silently fall back to defaultI18n 
                // but still show a warning to the user.
                console.error("Failed to load translations:", error);
                showToast('Could not load page settings. Using English defaults.', 'warning');
            }
            
            // Now proceed with localStorage and UI updates using loaded or default i18n
            const savedTtl = localStorage.getItem(TTL_STORAGE_KEY);
            if (savedTtl) { ttlSelect.value = savedTtl; }

            ttlSelect.addEventListener('change', () => {
                localStorage.setItem(TTL_STORAGE_KEY, ttlSelect.value);
                updateTtlInfo();
            });

            updateTtlInfo();
        })();
    }
});
