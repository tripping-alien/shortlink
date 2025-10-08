document.addEventListener('DOMContentLoaded', () => {
    // --- Element Selectors ---
    const shortenForm = document.getElementById('shorten-form');
    const longUrlInput = document.getElementById('long-url-input');
    const submitButton = document.getElementById('submit-button');
    const buttonText = submitButton.querySelector('.button-text');
    const spinner = submitButton.querySelector('.spinner');
    const resultBox = document.getElementById('result-box');
    const shortUrlLink = document.getElementById('short-url-link');
    const copyButton = document.getElementById('copy-button');
    const ttlSelect = document.getElementById('ttl-select');
    const toastContainer = document.getElementById('toast-container');

    // --- Toast Notification Function ---
    function showToast(message, type = 'danger') { // Default to 'danger' for errors
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

    // --- Form Submission Handler ---
    if (shortenForm) {
        shortenForm.addEventListener('submit', async (event) => {
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
                buttonText.classList.remove('d-none');
                spinner.style.display = 'none';
                submitButton.disabled = false;
            }
        });
    }

    // --- Copy Button Handler ---
    if (copyButton) {
        copyButton.addEventListener('click', () => {
            navigator.clipboard.writeText(shortUrlLink.href).then(() => {
                copyButton.textContent = copyButton.dataset.copiedText || 'Copied!';
                copyButton.classList.add('btn-success', 'copied');
                // Optional: Revert after a few seconds
                setTimeout(() => {
                    copyButton.textContent = copyButton.dataset.copyText || 'Copy';
                    copyButton.classList.remove('btn-success', 'copied');
                }, 2000);
            }).catch(err => {
                showToast('Failed to copy link.', 'danger');
                console.error('Copy failed:', err);
            });
        });
    }

    // --- Dynamic Language Switcher & Cookie Handler ---
    (function buildLanguageSwitcher() {
        const switcherContainer = document.getElementById('language-switcher');
        if (!switcherContainer) return;

        const currentLang = document.documentElement.lang || 'en';
        const currentPage = window.location.pathname.includes('/about') ? 'about' : 'index';

        const languages = [
            { code: 'en', title: 'English', flag: 'gb' },
            { code: 'de', title: 'Deutsch', flag: 'de' },
            { code: 'fr', title: 'Français', flag: 'fr' },
            { code: 'ru', title: 'Русский', flag: 'ru' },
            { code: 'nl', title: 'Nederlands', flag: 'nl' },
            { code: 'zh', title: '中文', flag: 'cn' },
            { code: 'ja', title: '日本語', flag: 'jp' },
            { code: 'ar', title: 'العربية', flag: 'sa' },
            { code: 'he', title: 'עברית', flag: 'il' }
        ];

        languages.forEach(lang => {
            const link = document.createElement('a');
            const path = (currentPage === 'about') ? `/ui/${lang.code}/about/` : `/ui/${lang.code}/`;
            link.href = path;
            link.title = lang.title;
            if (lang.code === currentLang) {
                link.classList.add('active');
            }

            const img = document.createElement('img');
            img.src = `https://cdn.jsdelivr.net/gh/lipis/flag-icons/flags/4x3/${lang.flag}.svg`;
            img.alt = lang.title;

            link.appendChild(img);
            switcherContainer.appendChild(link);
        });

        switcherContainer.addEventListener('click', (event) => {
            const link = event.target.closest('a');
            if (!link) return;

            const lang = link.pathname.split('/')[2];
            if (lang) {
                document.cookie = `lang=${lang}; path=/; max-age=31536000; samesite=lax`;
            }
        });
    })();

    // --- TTL Persistence and UI Update ---
    const TTL_STORAGE_KEY = 'bijective_shorty_ttl';

    function updateTtlInfo(i18n) {
        const ttlInfoText = document.getElementById('ttl-info-text');
        if (!ttlSelect || !ttlInfoText) return;

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
    }

    (async function initPage() {
        if (!ttlSelect) return;
        const langCode = document.documentElement.lang || 'en';
        try {
            const response = await fetch(`/api/v1/translations/${langCode}`);
            if (!response.ok) throw new Error('Failed to load translations');
            const i18n = await response.json();

            // Set copy button text from translations
            if (copyButton) {
                copyButton.dataset.copyText = i18n.copy;
                copyButton.dataset.copiedText = i18n.copied;
                copyButton.textContent = i18n.copy;
            }

            // Restore TTL selection from localStorage
            const savedTtl = localStorage.getItem(TTL_STORAGE_KEY);
            if (savedTtl) {
                ttlSelect.value = savedTtl;
            }

            // Add event listener for future changes
            ttlSelect.addEventListener('change', () => {
                localStorage.setItem(TTL_STORAGE_KEY, ttlSelect.value);
                updateTtlInfo(i18n);
            });

            // Initialize the text on page load
            updateTtlInfo(i18n);

        } catch (error) {
            console.error("Failed to initialize page:", error);
            showToast('Could not load page settings.', 'warning');
        }
    })();
});