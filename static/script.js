/**
 * Main script for handling UI interactions.
 */

document.addEventListener('DOMContentLoaded', function() {
    const shortenForm = document.getElementById('shorten-form');

    // This part of the script is specific to the main page (index.html)
    if (shortenForm) {
        const longUrlInput = document.getElementById('long-url-input');
        const submitButton = document.getElementById('submit-button');
        const buttonText = submitButton.querySelector('.button-text');
        const spinner = submitButton.querySelector('.spinner');
        const resultBox = document.getElementById('result-box');
        const shortUrlLink = document.getElementById('short-url-link');
        const copyButton = document.getElementById('copy-button');
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

                // Display new result
                shortUrlLink.href = data.short_url;
                shortUrlLink.textContent = data.short_url.replace(/^https?:\/\//, ''); // Show clean URL
                resultBox.classList.remove('d-none');
                resultBox.classList.add('fade-in-up');

                // Reset copy button state
                copyButton.textContent = copyButton.dataset.copyText || 'Copy';
                copyButton.classList.remove('btn-success', 'copied');

            } catch (error) {
                showToast(error.message, 'danger');
            } finally {
                // Restore button state
                spinner.style.display = 'none';
                submitButton.disabled = false;
                buttonText.classList.remove('d-none');
            }
        });

        // --- Copy Button Handler (now inside the shortenForm check) ---
        if (copyButton) {
            copyButton.addEventListener('click', () => {
                navigator.clipboard.writeText(shortUrlLink.href).then(function() {
                    copyButton.textContent = copyButton.dataset.copiedText || 'Copied!';
                    copyButton.classList.add('btn-success', 'copied');
                    // Optional: Revert after a few seconds
                    setTimeout(() => {
                        copyButton.textContent = copyButton.dataset.copyText || 'Copy';
                        copyButton.classList.remove('btn-success', 'copied');
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

                if (copyButton) {
                    copyButton.dataset.copyText = i18n.copy;
                    copyButton.dataset.copiedText = i18n.copied;
                    copyButton.textContent = i18n.copy;
                }

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

/**
 * Builds the language switcher on any page that has the 'language-switcher' div.
 * This is in its own listener to ensure it runs independently.
 */
document.addEventListener('DOMContentLoaded', function() {
    (function buildLanguageSwitcher() {
        const toggleBtn = document.getElementById('language-toggle-btn');
        const switcherContainer = document.getElementById('language-switcher'); // This is now the bar itself
        const barContainer = document.getElementById('language-bar-container');

        if (!switcherContainer) return;

        const currentLang = document.documentElement.lang || 'en';
        const currentPage = window.location.pathname.includes('/about') ? 'about' : 'index';

        const languages = [
            { code: 'en', name: 'English', flag: 'gb' },
            { code: 'de', name: 'Deutsch', flag: 'de' },
            { code: 'fr', name: 'Français', flag: 'fr' },
            { code: 'ru', name: 'Русский', flag: 'ru' },
            { code: 'nl', name: 'Nederlands', flag: 'nl' },
            { code: 'zh', name: '中文', flag: 'cn' },
            { code: 'ja', name: '日本語', flag: 'jp' },
            { code: 'ar', name: 'العربية', flag: 'sa' },
            { code: 'he', name: 'עברית', flag: 'il' }
        ];

        languages.forEach(lang => {
            const a = document.createElement('a');
            const path = (currentPage === 'about') ? `/ui/${lang.code}/about/` : `/ui/${lang.code}/`;
            a.href = path;
            a.title = lang.name;

            const img = document.createElement('img');
            img.src = `https://cdn.jsdelivr.net/gh/lipis/flag-icons/flags/4x3/${lang.flag}.svg`;
            img.alt = lang.name;
            img.classList.add('flag-icon');
            a.appendChild(img);

            if (lang.code === currentLang) {
                a.classList.add('active');
            }
            
            switcherContainer.appendChild(a);
        });

        // Handle toggling the bar
        toggleBtn.addEventListener('click', (event) => {
            event.stopPropagation(); // Prevent click from bubbling to the document
            switcherContainer.classList.toggle('show');
        });

        // Handle clicking a flag (for setting cookie)
        switcherContainer.addEventListener('click', (event) => {
            const link = event.target.closest('a');
            if (!link) return;

            const lang = link.pathname.split('/')[2];
            if (lang) {
                document.cookie = `lang=${lang}; path=/; max-age=31536000; samesite=lax`;
            }
        });

        // Close the bar when clicking anywhere else on the page
        document.addEventListener('click', (event) => {
            if (!barContainer.contains(event.target) && switcherContainer.classList.contains('show')) {
                switcherContainer.classList.remove('show');
            }
        });
    })();
});