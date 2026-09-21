(() => {
    "use strict";

    const UI_CACHE_VERSION = "20260921-7";

    function forceFreshTelegramDocument() {
        try {
            const url = new URL(window.location.href);
            if (url.origin !== "https://qwertsyik0.github.io") return;
            if (!url.pathname.startsWith("/nyan-wallet")) return;
            if (url.searchParams.get("ui_v") === UI_CACHE_VERSION) return;

            const key = "nyan-ui-document-refresh:" + UI_CACHE_VERSION;
            if (sessionStorage.getItem(key) === "1") return;
            sessionStorage.setItem(key, "1");

            url.searchParams.set("ui_v", UI_CACHE_VERSION);
            window.location.replace(url.toString());
        } catch (_) {}
    }

    forceFreshTelegramDocument();

    const nativeFetch = window.fetch.bind(window);
    const API_ORIGIN = "https://nyan-wallet-api.onrender.com";
    const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
    const RETRY_DELAYS_MS = [1500, 3000, 6500, 12000];

    function wait(ms) {
        return new Promise(resolve => window.setTimeout(resolve, ms));
    }

    function requestUrl(input) {
        try {
            if (input instanceof Request) return new URL(input.url, window.location.href);
            return new URL(String(input), window.location.href);
        } catch (_) {
            return null;
        }
    }

    function requestMethod(input, init) {
        const explicit = init?.method;
        const inherited = input instanceof Request ? input.method : null;
        return String(explicit || inherited || "GET").toUpperCase();
    }

    function requestSignal(input, init) {
        return init?.signal || (input instanceof Request ? input.signal : null) || null;
    }

    async function isRetryableResponse(response) {
        if (![502, 503, 504].includes(response.status)) return false;

        if (response.status === 503) {
            try {
                const data = await response.clone().json();
                if (data?.detail === "maintenance") return false;
            } catch (_) {
                // Render may return an HTML/empty 503 while an instance is waking.
            }
        }

        return true;
    }

    async function resilientFetch(input, init) {
        const url = requestUrl(input);
        const method = requestMethod(input, init);
        const signal = requestSignal(input, init);

        if (!url || url.origin !== API_ORIGIN || !SAFE_METHODS.has(method)) {
            return nativeFetch(input, init);
        }

        let lastError = null;

        for (let attempt = 0; attempt <= RETRY_DELAYS_MS.length; attempt += 1) {
            if (attempt > 0) {
                const delay = RETRY_DELAYS_MS[attempt - 1];
                if (signal?.aborted) throw signal.reason || new DOMException("Aborted", "AbortError");
                await wait(delay);
            }

            try {
                const response = await nativeFetch(input, init);

                if (
                    attempt < RETRY_DELAYS_MS.length &&
                    await isRetryableResponse(response)
                ) {
                    lastError = new Error(`HTTP ${response.status}`);
                    continue;
                }

                return response;
            } catch (error) {
                if (signal?.aborted || error?.name === "AbortError") throw error;

                const networkFailure =
                    error instanceof TypeError ||
                    error?.name === "NetworkError";

                if (!networkFailure) throw error;

                lastError = error;
                if (attempt >= RETRY_DELAYS_MS.length) break;
            }
        }

        const error = new Error(
            "Сервер Nyan Wallet временно недоступен. Подождите несколько секунд и попробуйте снова."
        );
        error.name = "NyanNetworkError";
        error.cause = lastError;
        throw error;
    }

    window.fetch = resilientFetch;
    window.__nyanNetworkRetryEnabled = true;
})();
