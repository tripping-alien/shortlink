document.addEventListener('DOMContentLoaded', () => {
    const htmlElement = document.documentElement;
    let i18nData = {};

    // --- Client-Side Bijective Logic ---
    const toBijective = (n) => {
        try {
            if (n <= 0) return "(N/A)";
            const chars = "123456";
            let result = '';
            while (n > 0) {
                result = chars[(n - 1) % 6] + result;
                n = Math.floor((n - 1) / 6);
            }
            return result;
        } catch (err) {
            console.error("Error in toBijective:", err);
            return "(Error)";
        }
    };

    const fromBijective = (s) => {
        if (!s || !/^[1-6]+$/.test(s)) throw new Error("Invalid bijective base-6 input.");
        let n = 0;
        for (let char of s) {
            n = n * 6 + parseInt(char, 10);
        }
        return n;
    };

    // --- Internationalization (i18n) Logic ---
    const supportedLangs = {
        'en': { flag: 'us', name: 'English' },
        'ru': { flag: 'ru', name: 'Русский' },
        'de': { flag: 'de', name: 'Deutsch' },
        'fr': { flag: 'fr', name: 'Français' },
        'he': { flag: 'il', name: 'עברית' },
        'ar': { flag: 'sa', name: 'العربية' },
        'zh': { flag: 'cn', name: '中文' },
        'ja': { flag: 'jp', name: '日本語' }
    };

    async function setLanguage(lang) {
        if (!supportedLangs[lang]) { console.warn(`Language '${lang}' not supported.`); return; }
        try {
            const response = await fetch(`/locales/${lang}.json`);
            if (!response.ok) { console.error(`Failed to fetch locale file for ${lang}.`); return; }
            i18nData = await response.json();
            applyTranslations(i18nData);
            htmlElement.setAttribute('lang', lang);
            htmlElement.dir = ['he', 'ar'].includes(lang) ? 'rtl' : 'ltr';
            localStorage.setItem('language', lang);
            updateSeoLangTags(lang);
        } catch (error) { console.error(`Error setting language to ${lang}:`, error); }
    }

    function updateSeoLangTags(currentLang) {
        // Remove old hreflang tags
        document.querySelectorAll('link[rel="alternate"]').forEach(el => el.remove());
        
        const head = document.head;
        const baseUrl = window.location.origin + window.location.pathname;

        for (const langCode in supportedLangs) {
            const link = document.createElement('link');
            link.rel = 'alternate';
            link.hreflang = langCode;
            link.href = `${baseUrl}?lang=${langCode}`;
            head.appendChild(link);
        }
    }

    function applyTranslations(data) {
        document.title = data.pageTitle || "Bijective Base-6 Calculator";
        document.querySelector('meta[name="description"]').setAttribute('content', data.pageDescription || "");

        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.dataset.i18n;
            if (data[key] !== undefined) el.innerHTML = data[key];
        });
        document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
            const key = el.dataset.i18nPlaceholder;
            if (data[key] !== undefined) el.placeholder = data[key];
        });
        document.querySelectorAll('[data-i18n-aria-label]').forEach(el => {
            const key = el.dataset.i18nAriaLabel;
            if (data[key] !== undefined) el.setAttribute('aria-label', data[key]);
        });
        document.querySelectorAll('[data-i18n-property]').forEach(el => {
            const key = el.dataset.i18nProperty.split(':')[1];
            const property = el.dataset.i18nProperty;
            if (data[key] !== undefined) {
                // This handles og:title, twitter:title, etc.
                el.setAttribute('content', data[key]);
            }
        });
        document.querySelectorAll('[data-i18n-list]').forEach(ul => {
            const key = ul.dataset.i18nList;
            if (data[key] && Array.isArray(data[key])) {
                ul.innerHTML = data[key].map(item => `<li class="list-group-item">${item.replace(/<strong>/g, '<strong class="text-success">')}</li>`).join('');
            }
        });
        document.querySelectorAll('[data-i18n-html]').forEach(el => {
            const key = el.dataset.i18nHtml;
            if (data[key] !== undefined) el.innerHTML = data[key];
        });
    }

    function setupTabMemory() {
        const tabButtons = document.querySelectorAll('#myTab button[data-bs-toggle="tab"]');
        tabButtons.forEach(tab => {
            tab.addEventListener('shown.bs.tab', (event) => {
                if (event.target.dataset.bsTarget) {
                    localStorage.setItem('lastActiveTab', event.target.dataset.bsTarget);
                }
            });
        });

        const lastTabId = localStorage.getItem('lastActiveTab');
        if (lastTabId) {
            const lastTab = document.querySelector(`button[data-bs-target="${lastTabId}"]`);
            if (lastTab) new bootstrap.Tab(lastTab).show();
        }
    }

    // --- Tab & Table Logic ---
    const tablesTab = document.getElementById('tables-tab');
    let tablesData = null;
    if (tablesTab) {
        tablesTab.addEventListener('shown.bs.tab', async () => {
            if (!tablesData) {
                const addContainer = document.getElementById('addition-table-container');
                const mulContainer = document.getElementById('multiplication-table-container');
                if(addContainer) addContainer.innerHTML = `<p class="text-center">${i18nData.ui_loading || 'Loading...'}</p>`;
                const response = await fetch('/get-tables');
                tablesData = await response.json();
                if(addContainer) renderTable(tablesData.header, tablesData.addition, addContainer);
                if(mulContainer) renderTable(tablesData.header, tablesData.multiplication, mulContainer);
            }
        });
    }

    function renderTable(header, data, container) {
        let tableHTML = '<table class="table table-bordered table-hover table-sm"><thead><tr><th>#</th>';
        header.forEach(h => tableHTML += `<th>${h}</th>`);
        tableHTML += '</tr></thead><tbody>';
        data.forEach((row, rowIndex) => {
            tableHTML += `<tr><th>${header[rowIndex]}</th>`;
            row.forEach(cell => tableHTML += `<td>${cell}</td>`);
            tableHTML += '</tr>';
        });
        tableHTML += '</tbody></table>';
        container.innerHTML = tableHTML;
    }

    // --- Calculator & Converter Logic ---
    function setupCalculator() {
        const num1Input = document.getElementById('num1');
        const num2Input = document.getElementById('num2');
        const calculateAllBtn = document.getElementById('calculate-all-btn');
        const resultArea = document.getElementById('result-area');
        const opsResultsGrid = document.getElementById('ops-results-grid');
        const errorDisplay = document.getElementById('error-display');
        const decimalInput = document.getElementById('decimal-input');
        const conversionResults = document.getElementById('conversion-results');

        if (decimalInput) {
            decimalInput.addEventListener('input', (e) => {
                try {
                    const decimalValue = parseInt(e.target.value, 10);
                    if (!decimalValue || decimalValue <= 0) {
                        if (conversionResults) conversionResults.innerHTML = '';
                        return;
                    }
                    if (conversionResults) {
                        conversionResults.innerHTML = `
                            <div class="result-grid">
                                <div><strong>Decimal:</strong> <code>${decimalValue}</code></div>
                                <div><strong>Binary:</strong> <code>${decimalValue.toString(2)}</code></div>
                                <div><strong>Hexadecimal:</strong> <code>${decimalValue.toString(16).toUpperCase()}</code></div>
                                <div><strong>Bijective Base-6:</strong> <code>${toBijective(decimalValue)}</code></div>
                            </div>`;
                    }
                } catch (err) {
                    console.error("Conversion error:", err);
                }
            });
        }

        if (calculateAllBtn) {
            calculateAllBtn.addEventListener('click', () => {
                try {
                    if (!num1Input || !num2Input) throw new Error("Number inputs not found.");
                    const num1 = num1Input.value.trim();
                    const num2 = num2Input.value.trim();
                    if (!num1 || !num2) throw new Error(i18nData.errorBothNumbers || "Please enter both numbers.");

                    const n1 = fromBijective(num1);
                    const n2 = fromBijective(num2);

                    const results = {
                        addition: { dec: n1 + n2, op: '+' },
                        subtraction: { dec: n1 - n2, op: '-' },
                        multiplication: { dec: n1 * n2, op: '×' },
                        division: { dec: n2 !== 0 ? (n1 / n2) : null, op: '÷', rem: n2 !== 0 ? (n1 % n2) : null }
                    };

                    displayAllOpsResults(num1, num2, results);
                    if (resultArea) {
                        resultArea.style.display = 'block';
                        resultArea.classList.add('visible');
                    }
                } catch (e) {
                    console.warn("Calculator error:", e);
                    if (errorDisplay) errorDisplay.textContent = `${i18nData.errorGeneric || 'Error:'} ${e.message}`;
                    resultArea?.classList.add('visible');
                    if (opsResultsGrid) opsResultsGrid.innerHTML = '';
                }
            });
        }

        function displayAllOpsResults(num1, num2, data) {
            if (!opsResultsGrid) return;
            opsResultsGrid.innerHTML = Object.entries(data).map(([opName, res]) => {
                let bijectiveResult;
                if (opName === 'division') {
                    if (res.dec === null) bijectiveResult = '(N/A)';
                    else if (res.rem !== 0) bijectiveResult = `${toBijective(Math.floor(res.dec))} (Rem: ${toBijective(res.rem)})`;
                    else bijectiveResult = toBijective(res.dec);
                } else {
                    bijectiveResult = toBijective(res.dec);
                }
                const decimalDisplay = res.dec !== null ? (Number.isInteger(res.dec) ? res.dec : res.dec.toFixed(2)) : 'N/A';
                return `
                    <div class="col">
                        <div class="op-result-item h-100">
                            <div class="op-title">${opName.charAt(0).toUpperCase() + opName.slice(1)}</div>
                            <div class="op-problem">${num1} ${res.op} ${num2}</div>
                            <div class="op-answer">${bijectiveResult}</div>
                            <div class="op-step">(Decimal: ${decimalDisplay})</div>
                        </div>
                    </div>`;
            }).join('');
        }
    }

    // --- Practice Mode ---
    function setupPracticeMode() {
        const container = document.getElementById('quiz-container');
        if (!container) return;

        const difficultyRadios = document.querySelectorAll('input[name="difficulty"]');
        const conversionCheckbox = document.getElementById('quiz-type-conversions');
        const arithmeticCheckbox = document.getElementById('quiz-type-arithmetic');
        let currentQuestion = null;

        // Load saved settings from localStorage
        const savedDifficulty = localStorage.getItem('quizDifficulty') || 'easy';
        const difficultyRadio = document.getElementById(`difficulty-${savedDifficulty}`);
        if (difficultyRadio) difficultyRadio.checked = true;

        const savedConvChecked = localStorage.getItem('quizConvChecked');
        if (conversionCheckbox && savedConvChecked !== null) {
            conversionCheckbox.checked = (savedConvChecked === 'true');
        }

        const savedArithChecked = localStorage.getItem('quizArithChecked');
        if (arithmeticCheckbox && savedArithChecked !== null) {
            arithmeticCheckbox.checked = (savedArithChecked === 'true');
        }

        const generateQuestion = () => {
            try {
                const checkedRadio = document.querySelector('input[name="difficulty"]:checked');
                const selectedDifficulty = checkedRadio ? checkedRadio.value : 'easy';
                const difficultyMap = { easy: 6, medium: 20, hard: 50 };
                const maxNum = difficultyMap[selectedDifficulty] || 6;

                const types = [];
                if (conversionCheckbox?.checked) types.push('conversion');
                if (arithmeticCheckbox?.checked) types.push('arithmetic');
                if (types.length === 0) {
                    if (conversionCheckbox) conversionCheckbox.checked = true;
                    types.push('conversion');
                }

                const type = types[Math.floor(Math.random() * types.length)];
                let questionText = '';
                let answer = '';

                if (type === 'conversion') {
                    const num = Math.floor(Math.random() * maxNum) + 1;
                    questionText = (i18nData.quizQuestionConversion || "What is {number} in bijective base-6?").replace('{number}', `<code>${num}</code>`);
                    answer = toBijective(num);
                } else {
                    const num1 = Math.floor(Math.random() * maxNum) + 1;
                    const num2 = Math.floor(Math.random() * maxNum) + 1;
                    const op = Math.random() > 0.5 ? '+' : '×';
                    questionText = (i18nData.quizQuestionArithmetic || "What is {num1} {op} {num2}?")
                        .replace('{num1}', `<code>${toBijective(num1)}</code>`)
                        .replace('{op}', op)
                        .replace('{num2}', `<code>${toBijective(num2)}</code>`);
                    answer = toBijective(op === '+' ? num1 + num2 : num1 * num2);
                }
                currentQuestion = { questionText, answer };
                renderQuizUI();
            } catch (err) {
                console.error("Error generating quiz question:", err);
            }
        };

        const renderQuizUI = () => {
            if (!container || !currentQuestion) return;
            container.innerHTML = `
                <div class="mb-3 fs-4">${currentQuestion.questionText}</div>
                <div class="input-group" style="max-width: 300px; margin: auto;">
                    <input type="text" id="quiz-answer" class="form-control" data-i18n-placeholder="quizAnswerPlaceholder">
                    <button id="quiz-submit" class="btn btn-primary" data-i18n="quizSubmitBtn"></button>
                </div>
                <div id="quiz-feedback" class="mt-3"></div>
            `;
            applyTranslations(i18nData);
            document.getElementById('quiz-submit')?.addEventListener('click', checkAnswer);
            document.getElementById('quiz-answer')?.addEventListener('keypress', (e) => { if (e.key === 'Enter') checkAnswer(); });
        };

        const checkAnswer = () => {
            try {
                const answerEl = document.getElementById('quiz-answer');
                const feedbackEl = document.getElementById('quiz-feedback');
                if (!answerEl || !feedbackEl) return;
                const userAnswer = answerEl.value.trim().toUpperCase();
                if (userAnswer === currentQuestion.answer) {
                    feedbackEl.innerHTML = `<div class="alert alert-success">${i18nData.quizCorrectFeedback || 'Correct!'}</div>`;
                    setTimeout(generateQuestion, 1500);
                } else {
                    feedbackEl.innerHTML = `<div class="alert alert-danger">${(i18nData.quizIncorrectFeedback || 'Not quite! The correct answer was {answer}.').replace('{answer}', `<strong>${currentQuestion.answer}</strong>`)}</div>`;
                    setTimeout(generateQuestion, 3000); // Generate next question after a longer delay on failure
                }
            } catch (err) {
                console.error("Error checking quiz answer:", err);
            }
        };

        difficultyRadios.forEach(radio => {
            radio.addEventListener('change', (e) => {
                localStorage.setItem('quizDifficulty', e.target.value);
                generateQuestion();
            });
        });
        if (conversionCheckbox) conversionCheckbox.addEventListener('change', () => {
            localStorage.setItem('quizConvChecked', conversionCheckbox.checked);
            generateQuestion();
        });
        if (arithmeticCheckbox) arithmeticCheckbox.addEventListener('change', () => {
            localStorage.setItem('quizArithChecked', arithmeticCheckbox.checked);
            generateQuestion();
        });

        generateQuestion();
    }

    // --- Settings Modal Logic ---
    function setupSettingsModal() {
        const themeSwitch = document.getElementById('theme-switch-modal');
        const themeLabel = document.getElementById('theme-switch-label');
        const languageList = document.getElementById('language-list-modal');

        if (!themeSwitch || !languageList) return;

        // Theme Switcher
        function updateThemeUI(theme) {
            themeSwitch.checked = theme === 'dark';
            themeLabel.textContent = theme === 'dark' ? (i18nData.themeDark || 'Dark Mode') : (i18nData.themeLight || 'Light Mode');
        }

        function setTheme(theme) {
            htmlElement.setAttribute('data-theme', theme);
            localStorage.setItem('theme', theme);
            updateThemeUI(theme);
        }

        themeSwitch.addEventListener('change', () => {
            setTheme(themeSwitch.checked ? 'dark' : 'light');
        });

        // Language List
        function populateLanguageList() {
            languageList.innerHTML = '';
            const currentLang = localStorage.getItem('language') || 'en';
            for (const [code, details] of Object.entries(supportedLangs)) {
                const langItem = document.createElement('a');
                langItem.href = '#';
                langItem.className = 'list-group-item list-group-item-action language-option';
                if (code === currentLang) {
                    langItem.classList.add('active');
                }
                langItem.innerHTML = `<span class="fi fi-${details.flag} me-2"></span> ${details.name}`;
                langItem.addEventListener('click', (e) => {
                    e.preventDefault();
                    setLanguage(code).then(() => {
                        // Repopulate to update active state and labels
                        populateLanguageList();
                        updateThemeUI(localStorage.getItem('theme') || 'dark');
                    });
                });
                languageList.appendChild(langItem);
            }
        }

        // Initial setup
        const initialTheme = localStorage.getItem('theme') || 'dark';
        setTheme(initialTheme);
        populateLanguageList();
    }

    // --- Initial Load ---
    setupSettingsModal();
    setupTabMemory();
    setupCalculator();
    setupPracticeMode();

    const initialLang = localStorage.getItem('language') || 'en';
    setLanguage(initialLang);
});
