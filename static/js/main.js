document.addEventListener('DOMContentLoaded', () => {
    const shortenForm = document.getElementById('shorten-form');
    const advancedToggleButton = document.getElementById('advanced-toggle');
    const advancedOptions = document.getElementById('advanced-options');
    const resultDiv = document.getElementById('result');
    const shortLinkResultInput = document.getElementById('short-link-result');
    const copyButton = document.getElementById('copy-button');
    const longUrlInput = document.getElementById('long_url');

    // --- 1. Utility Function to Fetch Translations ---
    // This function assumes your pages pass the global '_' function into the template
    // and that the translations object is available globally (e.g., from an API call
    // or embedded JSON, or passed via Jinja2 context).
    const _ = window._ || ((key) => key); 

    /**
     * Toggles the visibility of the advanced options panel.
     */
    advancedToggleButton.addEventListener('click', () => {
        const isHidden = advancedOptions.classList.toggle('hidden');
        advancedToggleButton.textContent = isHidden ? _('advanced_options_button') : '▲ Hide Options';
    });


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
        resultDiv.classList.add('hidden');
        resultDiv.style.opacity = '0'; // For smooth CSS transition

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
        }
    });


    /**
     * Updates the UI with the successful short link data.
     * @param {Object} data - The response data from the API.
     */
    function displaySuccess(data) {
        // --- 1. Update Links ---
        const baseShortUrl = data.short_url.replace('/r/', '/'); // Use the preview URL for display

        shortLinkResultInput.value = baseShortUrl;

        // --- 2. Update Stats and Delete Links ---
        // Find existing elements or create them if they don't exist
        let statsLink = document.getElementById('stats-link');
        let deleteLink = document.getElementById('delete-link');
        let saveText = document.getElementById('save-text');
        
        if (!statsLink) {
            statsLink = document.createElement('a');
            statsLink.id = 'stats-link';
            statsLink.classList.add('btn-secondary', 'mt-3');
            statsLink.textContent = _('result_view_clicks');
            resultDiv.appendChild(statsLink);
        }
        statsLink.href = data.stats_url;

        if (!deleteLink) {
            deleteLink = document.createElement('a');
            deleteLink.id = 'delete-link';
            deleteLink.classList.add('btn-secondary', 'mt-3', 'ml-2');
            deleteLink.textContent = '🗑️ ' + _('delete_success'); // Using the word 'delete' for the button for clarity
            resultDiv.appendChild(deleteLink);
        }
        deleteLink.href = data.delete_url;

        if (!saveText) {
             saveText = document.createElement('p');
             saveText.id = 'save-text';
             saveText.classList.add('small-text', 'mt-3', 'text-muted');
             saveText.innerHTML = `<strong>${_('result_save_link_strong')}</strong> ${_('result_save_link_text')}`;
             resultDiv.appendChild(saveText);
        }
        
        // --- 3. Show Result Div with Animation ---
        resultDiv.classList.remove('hidden');
        // Simple JS fade in if no CSS animation is used:
        setTimeout(() => {
            resultDiv.style.opacity = '1';
        }, 10); 
    }


    /**
     * Handles the copy to clipboard action.
     */
    copyButton.addEventListener('click', () => {
        shortLinkResultInput.select();
        shortLinkResultInput.setSelectionRange(0, 99999); // For mobile devices

        try {
            navigator.clipboard.writeText(shortLinkResultInput.value);
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
