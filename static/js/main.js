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
     * Handles the form submission to create the short link.
     */
    shortenForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const longUrl = longUrlInput.value.trim();
        if (!longUrl) {
            alert(_('js_enter_url'));
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
            // owner_id should be handled securely, likely fetched from a cookie or session
            owner_id: null 
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
                const errorMessage = data.detail || _('js_error_creating');
                alert(`Error: ${errorMessage}`);
                console.error('API Error:', data);
            }

        } catch (error) {
            console.error('Network or Server Error:', error);
            alert(_('js_error_server'));
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
        const previewUrl = data.stats_url.replace('/stats/', '/preview/');
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
            navigator.clipboard.writeText(textToCopy);
            copyButton.textContent = _('js_copied');
            copyButton.style.backgroundColor = 'var(--color-primary-dark)';
        } catch (err) {
            copyButton.textContent = _('js_copy_failed');
            copyButton.style.backgroundColor = 'red';
            console.error('Failed to copy text: ', err);
        }
        
        // Reset button text after a short delay
        setTimeout(() => {
            copyButton.textContent = _('copy_button');
            copyButton.style.backgroundColor = 'var(--color-success)';
        }, 3000);
    });

});
