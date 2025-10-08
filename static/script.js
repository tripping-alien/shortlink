/**
 * Main script for handling UI interactions.
 */
document.addEventListener('DOMContentLoaded', function() {
    // --- Dynamic Comic Book Theming Experiment ---
    const comicPalette = {
        '--bg-color': '#fefae0', // Creamy, off-white "newsprint" background
        '--panel-bg': '#ffffff', // Clean white for the panel
        '--text-color': '#212529', // Standard dark text for high contrast
        '--primary-color': '#2962ff', // A vibrant, classic comic blue
        '--primary-color-hover': '#0039cb', // A darker blue for hover
        '--secondary-color': '#d50000', // A bold comic red for accents
        '--border-color': '#000000', // Strong black for outlines
        '--input-bg': '#2d3748', // A dark slate grey for high contrast
        '--bs-primary-rgb': '41, 98, 255',
        '--animation-color-vec': [0.16, 0.38, 1.0] // Matching blue for the (currently disabled) animation
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

        // Focus the input field on page load for immediate use
        longUrlInput.focus();

        const submitButton = document.getElementById('submit-button');
        const buttonText = submitButton.querySelector('.button-text');
        const spinner = submitButton.querySelector('.spinner');
        const resultBox = document.getElementById('result-box');
        const shortUrlLink = document.getElementById('short-url-link');
        const toastContainer = document.getElementById('toast-container');
        const ttlSelect = document.getElementById('ttl-select');

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
                ttl: ttlSelect.value
            };

            try {
                const response = await fetch('/api/v1/links', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                const data = await response.json();

                if (!response.ok) {
                    let errorMessage = "An unexpected error occurred.";
                    if (data.detail) {
                        // Handle both string and Pydantic validation error formats
                        if (Array.isArray(data.detail) && data.detail[0] && data.detail[0].msg) {
                            errorMessage = data.detail[0].msg;
                        } else if (typeof data.detail === 'string') {
                            errorMessage = data.detail;
                        }
                    }
                    throw new Error(errorMessage);
                }

                // Use the full URL for the clipboard, but a relative path for the link's href
                // to ensure it works in the local development environment.
                const fullUrl = data.short_url;
                const relativePath = new URL(fullUrl).pathname; // Extracts "/get/Bx7vq"

                // Set up the link for display and functionality
                shortUrlLink.href = fullUrl; // The href should point to the full, live URL
                shortUrlLink.dataset.relativeHref = relativePath; // Store relative path for local navigation
                shortUrlLink.dataset.fullUrl = fullUrl; // Store the full URL for the copy button

                // Build the comic-style link display
                const urlObject = new URL(fullUrl);
                const domain = urlObject.hostname;
                const code = urlObject.pathname;
                shortUrlLink.innerHTML = `<span class="short-url-domain">${domain}</span><span class="short-url-code">${code}</span>`;

                resultBox.classList.remove('d-none');
                resultBox.classList.add('fade-in-up');

                // Reset copy button state
                shortUrlLink.classList.remove('copied');

            } catch (error) {
                showToast(error.message, 'danger');
            } finally {
                // Restore button state
                spinner.style.display = 'none';
                submitButton.disabled = false;
                buttonText.classList.remove('d-none');
            }
        });

        // --- Click-to-Copy Handler ---
        if (shortUrlLink) {
            shortUrlLink.addEventListener('click', (event) => {
                event.preventDefault(); // Prevent navigation
                const urlToCopy = shortUrlLink.dataset.fullUrl || shortUrlLink.href;
                navigator.clipboard.writeText(urlToCopy).then(function() {
                    const originalHTML = shortUrlLink.innerHTML;
                    shortUrlLink.innerHTML = `<span class="short-url-code">${shortUrlLink.dataset.copiedText || 'Copied!'}</span>`;
                    shortUrlLink.classList.add('copied');

                    setTimeout(() => {
                        shortUrlLink.innerHTML = originalHTML;
                        shortUrlLink.classList.remove('copied');
                    }, 2000);
                }).catch(function(err) {
                    showToast('Failed to copy link.', 'danger');
                    console.error('Copy failed:', err);
                });
            });
        }

        // --- TTL Persistence and UI Update (now inside the shortenForm check) ---
        const TTL_STORAGE_KEY = 'bijective_shorty_ttl';

        const updateTtlInfo = (i18n) => {
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
                ttlInfoText.textContent = i18n.expire_in_duration.replace('{duration}', durationText);
            }
        };

        (async function initMainPage() {
            const langCode = document.documentElement.lang || 'en';
            try {
                const response = await fetch(`/api/v1/translations/${langCode}`);
                if (!response.ok) throw new Error('Failed to load translations');
                const i18n = await response.json();

                // Set translations for the copy functionality
                shortUrlLink.dataset.copyText = i18n.copy;
                shortUrlLink.dataset.copiedText = i18n.copied;

                const savedTtl = localStorage.getItem(TTL_STORAGE_KEY);
                if (savedTtl) { ttlSelect.value = savedTtl; }

                ttlSelect.addEventListener('change', () => {
                    localStorage.setItem(TTL_STORAGE_KEY, ttlSelect.value);
                    updateTtlInfo(i18n);
                });

                updateTtlInfo(i18n);
            } catch (error) {
                console.error("Failed to initialize page:", error);
                showToast('Could not load page settings.', 'warning');
            }
        })();
    }
});