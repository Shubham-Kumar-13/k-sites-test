/**
 * K-Sites API helper.
 *
 * The same pages run in three modes:
 *  - local:   served by the Flask app; relative URLs and the cookie login are used.
 *  - remote:  static pages calling a separate backend. config.js sets
 *             window.KSITES_CONFIG = { apiBase: "https://....hf.space" } and the lab
 *             access token is kept in this browser (localStorage).
 *  - browser: static pages (GitHub Pages) where the analysis itself runs in this browser.
 *             config.js sets window.KSITES_CONFIG = { mode: "browser", keggBase: "kegg-data/" };
 *             there is no server and no sign-in.
 */
(function () {
    const config = window.KSITES_CONFIG || {};
    const apiBase = String(config.apiBase || '').replace(/\/+$/, '');
    const browserMode = config.mode === 'browser';
    const hosted = apiBase !== '' && !browserMode;     // a separate backend with an access token
    const staticSite = hosted || browserMode;          // pages are plain .html files
    const scriptUrl = document.currentScript ? document.currentScript.src : '';
    const KEYS = { token: 'ksites.token', name: 'ksites.userName', email: 'ksites.userEmail' };
    const memory = {};  // used when localStorage is blocked (private windows)

    function read(key) {
        try { return localStorage.getItem(key) || ''; } catch (e) { return memory[key] || ''; }
    }
    function write(key, value) {
        memory[key] = value;
        try { localStorage.setItem(key, value); } catch (e) { /* kept in memory only */ }
    }
    function remove(key) {
        delete memory[key];
        try { localStorage.removeItem(key); } catch (e) { /* nothing to do */ }
    }

    function user() {
        return { token: read(KEYS.token), name: read(KEYS.name), email: read(KEYS.email) };
    }

    function saveLogin(token, name, email) {
        write(KEYS.token, token);
        write(KEYS.name, name);
        write(KEYS.email, email);
    }

    /** Address of one of the site's pages, in either mode. */
    function page(name, params) {
        params = params || {};
        if (staticSite) {
            if (name === 'results') return 'results.html?job=' + encodeURIComponent(params.job || '');
            return { home: 'index.html', jobs: 'jobs.html', help: 'help.html', login: 'login.html' }[name] || 'index.html';
        }
        if (name === 'results') return '/results/' + encodeURIComponent(params.job || '');
        return { home: '/', jobs: '/jobs', help: '/help', login: '/login' }[name] || '/';
    }

    function logout() {
        remove(KEYS.token);
        remove(KEYS.name);
        remove(KEYS.email);
        window.location.href = page('login');
    }

    function goToLogin() {
        const here = window.location.pathname.split('/').pop() + window.location.search;
        window.location.href = page('login') + '?next=' + encodeURIComponent(here);
    }

    function banner(message, kind) {
        let el = document.getElementById('ksitesBanner');
        if (!el) {
            el = document.createElement('div');
            el.id = 'ksitesBanner';
            el.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:2000;text-align:center;padding:8px 12px;font-size:0.95rem;';
            (document.body || document.documentElement).appendChild(el);
        }
        el.className = 'alert alert-' + (kind || 'warning') + ' mb-0 rounded-0';
        el.textContent = message;
    }

    function clearBanner() {
        const el = document.getElementById('ksitesBanner');
        if (el) el.remove();
    }

    /**
     * Free hosting puts the backend to sleep when idle. Ping it until it answers so the
     * first real request does not simply fail.
     */
    let awake = null;
    function ensureAwake() {
        if (!hosted) return Promise.resolve();
        if (awake) return awake;
        awake = (async function () {
            const started = Date.now();
            let shown = false;
            while (Date.now() - started < 180000) {
                try {
                    const response = await fetch(apiBase + '/api/health', { cache: 'no-store' });
                    if (response.ok) {
                        if (shown) clearBanner();
                        return;
                    }
                } catch (e) { /* still starting */ }
                if (!shown && Date.now() - started > 2500) {
                    banner('Starting the K-Sites analysis server (free hosting sleeps when idle). This can take a minute or two...', 'info');
                    shown = true;
                }
                await new Promise(function (resolve) { setTimeout(resolve, 3000); });
            }
            banner('The K-Sites analysis server did not respond. Please try again in a few minutes.', 'danger');
            awake = null;
            throw new Error('Backend did not wake up');
        })();
        return awake;
    }

    let backendPromise = null;
    function getBackend() {
        if (!backendPromise) {
            const engine = new URL('engine/browserBackend.js', scriptUrl).href;
            const keggBase = new URL(config.keggBase || 'kegg-data/', window.location.href).href;
            backendPromise = import(engine).then((module) => module.createBrowserBackend({ keggBase }));
        }
        return backendPromise;
    }

    /** fetch() against the K-Sites API in any mode. */
    async function apiFetch(path, options) {
        options = Object.assign({}, options);
        if (browserMode) {
            const backend = await getBackend();
            return backend.handle(path, options);
        }
        if (hosted) {
            await ensureAwake();
            const u = user();
            options.headers = Object.assign({}, options.headers, { 'X-KSites-Token': u.token });
            if (u.name) options.headers['X-KSites-User-Name'] = u.name;
            if (u.email) options.headers['X-KSites-User-Email'] = u.email;
        }
        const response = await fetch(apiBase + path, options);
        if (hosted && response.status === 401) {
            remove(KEYS.token);
            goToLogin();
        }
        return response;
    }

    /** Download a result file (hosted mode needs the token header, so it goes through fetch). */
    async function download(jobId, type) {
        const response = await apiFetch('/api/jobs/' + encodeURIComponent(jobId) + '/download/' + type);
        if (!response.ok) {
            let message = 'This file is not available.';
            try { message = (await response.json()).error || message; } catch (e) { /* keep default */ }
            alert(message);
            return;
        }
        const blob = await response.blob();
        const disposition = response.headers.get('Content-Disposition') || '';
        const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = match ? decodeURIComponent(match[1]) : 'ksites_' + jobId.slice(0, 8) + '.' + type;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(function () { URL.revokeObjectURL(link.href); }, 5000);
    }

    /** Hook a download button: plain link locally, token-aware fetch when hosted. */
    function bindDownload(elementId, jobId, type) {
        const el = document.getElementById(elementId);
        if (!el) return;
        el.style.display = 'inline-block';
        if (staticSite) {
            el.href = '#';
            el.onclick = function (event) { event.preventDefault(); download(jobId, type); };
        } else {
            el.href = '/api/jobs/' + jobId + '/download/' + type;
        }
    }

    function initBrowserMode() {
        // no accounts: nothing to sign in to, and results stay in this browser
        const dropdown = document.getElementById('userDropdown');
        if (dropdown && dropdown.parentElement) dropdown.parentElement.remove();
        const emailField = document.getElementById('user_email');
        const emailCard = emailField && emailField.closest('.card');
        if (emailCard) emailCard.remove();

        const row = document.getElementById('ncbiKeyRow');
        const input = document.getElementById('ncbi_api_key');
        if (row && input) {
            row.style.display = '';
            try { input.value = localStorage.getItem('ksites.ncbiApiKey') || ''; } catch (e) { /* not available */ }
            input.addEventListener('change', function () {
                try { localStorage.setItem('ksites.ncbiApiKey', input.value.trim()); } catch (e) { /* not available */ }
            });
        }
        const notes = document.querySelectorAll('[data-hosted-note]');
        notes.forEach(function (note) { note.style.display = ''; });
    }

    function initNav() {
        if (browserMode) { initBrowserMode(); return; }
        if (!hosted) return;
        const u = user();
        const label = document.getElementById('userNameLabel');
        if (label) label.textContent = u.name || 'Lab member';
        const profile = document.getElementById('profileMenuItem');
        if (profile) profile.remove();
        const logoutLink = document.getElementById('logoutLink');
        if (logoutLink) logoutLink.addEventListener('click', function (event) { event.preventDefault(); logout(); });
    }

    window.KSITES = {
        hosted: hosted, browserMode: browserMode, apiBase: apiBase, user: user, saveLogin: saveLogin, logout: logout,
        page: page, ensureAwake: ensureAwake, bindDownload: bindDownload, banner: banner, clearBanner: clearBanner
    };
    window.ksFetch = apiFetch;
    window.ksPage = page;
    window.ksBindDownload = bindDownload;

    // Hosted pages other than the login page need the access token.
    if (hosted && !window.KSITES_PUBLIC_PAGE && !user().token) {
        goToLogin();
    }
    document.addEventListener('DOMContentLoaded', initNav);
})();
