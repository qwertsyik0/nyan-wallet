(() => {
    "use strict";

    const nativeFetch = window.fetch.bind(window);
    const API_ORIGIN = "https://nyan-wallet.tail327bb6.ts.net";
    const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
    const RETRY_DELAYS_MS = [1500, 3000, 6500, 12000];

    function wait(ms, signal) {
        return new Promise((resolve, reject) => {
            if (signal?.aborted) {
                reject(signal.reason || new DOMException("Aborted", "AbortError"));
                return;
            }
            let timer = null;
            const onAbort = () => {
                window.clearTimeout(timer);
                signal?.removeEventListener("abort", onAbort);
                reject(signal.reason || new DOMException("Aborted", "AbortError"));
            };
            timer = window.setTimeout(() => {
                signal?.removeEventListener("abort", onAbort);
                resolve();
            }, ms);
            signal?.addEventListener("abort", onAbort, { once: true });
        });
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

        // The wallet bootstrap has its own bounded retry and status screen.
        // Avoid nesting the generic retries inside the wallet bootstrap timeout.
        if (!url || url.origin !== API_ORIGIN || !SAFE_METHODS.has(method) ||
            (method === "GET" && url.pathname === "/api/me")) {
            return nativeFetch(input, init);
        }

        let lastError = null;

        for (let attempt = 0; attempt <= RETRY_DELAYS_MS.length; attempt += 1) {
            if (attempt > 0) {
                const delay = RETRY_DELAYS_MS[attempt - 1];
                if (signal?.aborted) throw signal.reason || new DOMException("Aborted", "AbortError");
                await wait(delay, signal);
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

    function ensureInlineErrorStyles() {
        if (document.getElementById("nyan-inline-error-style")) return;
        const style = document.createElement("style");
        style.id = "nyan-inline-error-style";
        style.textContent = `
            .nyan-inline-error {
                margin: 12px 0;
                padding: 14px;
                border: 1px solid rgba(176, 52, 93, .18);
                border-radius: 16px;
                background: rgba(255, 245, 249, .92);
                color: #7f3655;
                font-size: 13px;
                line-height: 1.45;
            }
            .nyan-inline-error-title {
                margin-bottom: 5px;
                font-weight: 800;
                color: #8d2f55;
            }
            .nyan-inline-error button {
                width: 100%;
                margin-top: 10px;
                padding: 11px 14px;
                border: 0;
                border-radius: 12px;
                background: #922954;
                color: #fff;
                font: inherit;
                font-weight: 700;
                cursor: pointer;
            }
        `;
        document.head.appendChild(style);
    }

    window.NyanInlineError = function (container, message, retry) {
        if (!container) return;
        ensureInlineErrorStyles();
        const box = document.createElement("div");
        box.className = "nyan-inline-error";

        const title = document.createElement("div");
        title.className = "nyan-inline-error-title";
        title.textContent = "Не удалось загрузить данные";

        const text = document.createElement("div");
        text.textContent = message || "Проверьте соединение и попробуйте ещё раз.";

        box.append(title, text);

        if (typeof retry === "function") {
            const button = document.createElement("button");
            button.type = "button";
            button.textContent = "Попробовать снова";
            button.addEventListener("click", () => {
                button.disabled = true;
                button.textContent = "Повторяем…";
                Promise.resolve(retry()).finally(() => {
                    button.disabled = false;
                    button.textContent = "Попробовать снова";
                });
            });
            box.appendChild(button);
        }

        container.innerHTML = "";
        container.appendChild(box);
    };

    window.fetch = resilientFetch;
    window.__nyanNetworkRetryEnabled = true;
    window.__nyanDocumentAutoReloadDisabled = true;
})();
