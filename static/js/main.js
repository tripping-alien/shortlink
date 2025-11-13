document.addEventListener('DOMContentLoaded', () => {
    const shortenForm = document.getElementById('shorten-form');
    const advancedToggleButton = document.querySelector('[data-bs-target="#advanced-options"]');
    const advancedOptions = document.getElementById('advanced-options'); // This is correct
    const resultCard = document.getElementById('result-card'); // FIX: Changed from 'result' to 'result-card'
    const shortLinkHref = document.getElementById('short-link-href'); // FIX: Changed from 'short-link-result' input
    const copyButton = document.getElementById('copy-button');
    const shortenButton = document.getElementById('shorten-button');
    const longUrlInput = document.getElementById('long_url');

    // --- 1. Utility Function to Fetch Translations ---
    // This function assumes your pages pass the global '_' function into the template
    // and that the translations object is available globally (e.g., from an API call
    // or embedded JSON, or passed via Jinja2 context).
    const _ = window._ || ((key) => key); 

    /**
     * Reads a cookie by name.
     * @param {string} name - The name of the cookie.
     * @returns {string|null} The cookie value or null if not found.
     */
    function getCookie(name) {
        const value = `; ${document.cookie}`;
        const parts = value.split(`; ${name}=`);
        if (parts.length === 2) return parts.pop().split(';').shift();
        return null;
    }

    /**
     * Shows a Bootstrap toast notification.
     * @param {string} message - The message to display.
     * @param {string} level - 'success' or 'danger'.
     */
    function showToast(message, level = 'danger') {
        const toastContainer = document.getElementById('toast-container');
        const toastId = `toast-${Date.now()}`;
        const toastHTML = `
            <div id="${toastId}" class="toast align-items-center text-white bg-${level} border-0" role="alert" aria-live="assertive" aria-atomic="true">
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
    }

    /**
     * Handles the form submission to create the short link.
     */
    shortenForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const longUrl = longUrlInput.value.trim();
        if (!longUrl) {
            showToast(_('js_enter_url'));
            return;
        }

        const customCode = document.getElementById('custom_code').value.trim();
        const utmTags = document.getElementById('utm_tags').value.trim();
        const ttl = document.getElementById('ttl').value;
        
        // Hide previous result and error messages
        resultCard.classList.add('d-none'); // FIX: Use 'd-none' for Bootstrap
        resultCard.style.opacity = '0'; // For smooth CSS transition

        // Disable button and show loading state
        const originalButtonText = shortenButton.innerHTML;
        shortenButton.disabled = true;
        shortenButton.innerHTML = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> ${_('js_creating_link')}`;

        // --- Prepare Payload ---
        const payload = {
            long_url: longUrl,
            ttl: ttl,
            custom_code: customCode || null,
            utm_tags: utmTags || null,
            // FIX: owner_id is now handled by the server from the secure cookie
            // owner_id: getCookie('owner_id')
        };

        try {
            // NOTE: Assuming your API is accessible via '/api/v1/links'
            const response = await fetch('/api/v1/links', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(payload),
            });

            const data = await response.json();

            if (response.ok) {
                displaySuccess(data);
            } else {
                // Handle API errors (e.g., 409 Custom code exists, 400 Invalid URL)
                const errorMessage = data.detail || _('js_error_creating_link');
                showToast(errorMessage);
                console.error('API Error:', data);
            }
        } catch (error) {
            console.error('Network or Server Error:', error);
            showToast(_('js_error_server'));
        } finally {
            // Re-enable button and restore text
            shortenButton.disabled = false;
            shortenButton.innerHTML = originalButtonText;
        }
    });


    /**
     * Updates the UI with the successful short link data.
     * @param {Object} data - The response data from the API.
     */
    function displaySuccess(data) {
        // --- 1. Get all the elements in the result card ---
        const qrCodeImage = document.getElementById('qr-code-image');
        const statsLink = document.getElementById('stats-link');
        const deleteLink = document.getElementById('delete-link');

        // --- 2. Populate the data ---
        // The preview URL is the user-facing "short link"
        const previewUrl = data.stats_url.replace('/info/', '/preview/');
        shortLinkHref.href = previewUrl;
        shortLinkHref.textContent = previewUrl.replace(/^https?:\/\//, ''); // Display without protocol

        // Set the stats and delete links
        statsLink.href = data.stats_url;
        deleteLink.href = data.delete_url;

        // Set the QR code
        if (data.qr_code_data) {
            qrCodeImage.src = data.qr_code_data;
            qrCodeImage.alt = _('qr_code_alt');
            qrCodeImage.parentElement.classList.remove('d-none');
        } else {
            qrCodeImage.parentElement.classList.add('d-none');
        }

        // --- 4. Show Result Div with Animation ---
        resultCard.classList.remove('d-none');
        // Simple JS fade in if no CSS animation is used:
        setTimeout(() => {
            resultCard.style.opacity = '1';
        }, 10);
    }


    /**
     * Handles the copy to clipboard action.
     */
    copyButton.addEventListener('click', () => {
        const textToCopy = shortLinkHref.href;

        try {
            // Use the Clipboard API for modern, secure copying
            navigator.clipboard.writeText(textToCopy).then(() => {
                copyButton.innerHTML = `<i class="bi bi-check-lg"></i> ${_('js_copied')}`;
                copyButton.classList.remove('btn-outline-secondary');
                return copyButton.classList.add('btn-success');
            });
        } catch (err) {
            copyButton.innerHTML = `<i class="bi bi-x-lg"></i> ${_('js_copy_failed')}`;
            copyButton.classList.remove('btn-outline-secondary');
            copyButton.classList.add('btn-danger');
            console.error('Failed to copy text: ', err);
        }
        
        // Reset button text after a short delay
        setTimeout(() => {
            // FIX: Restore the icon along with the text
            copyButton.innerHTML = `<i class="bi bi-clipboard"></i> ${_('copy_button')}`;
            copyButton.classList.remove('btn-success', 'btn-danger');
            copyButton.classList.add('btn-outline-secondary');
        }, 3000);
    });

});
