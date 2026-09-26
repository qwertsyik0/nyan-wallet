(function () {
    "use strict";

    const originalFetch = window.fetch.bind(window);

    function normalizeRole(value) {
        return String(value || "").replace(/\s+/g, " ").trim();
    }

    function requestUrl(input) {
        if (typeof input === "string") return input;
        if (input && typeof input.url === "string") return input.url;
        return "";
    }

    function requestMethod(input, init) {
        return String(init?.method || input?.method || "GET").toUpperCase();
    }

    function isParisStatusRequest(input, init) {
        const url = requestUrl(input);
        const method = requestMethod(input, init);
        return method === "POST"
            && url.includes("/api/owner/paris/applications/")
            && url.includes("/status");
    }

    function jsonError(detail, status) {
        return new Response(JSON.stringify({ detail }), {
            status,
            headers: { "Content-Type": "application/json" },
        });
    }

    window.fetch = function patchedFetch(input, init) {
        if (!isParisStatusRequest(input, init)) {
            return originalFetch(input, init);
        }

        const nextInit = init ? { ...init } : {};

        try {
            if (typeof nextInit.body !== "string") {
                return originalFetch(input, init);
            }

            const payload = JSON.parse(nextInit.body);
            if (!payload || payload.status !== "accepted" || payload.assigned_role) {
                return originalFetch(input, init);
            }

            const role = normalizeRole(window.prompt("Какую роль выдать участнику Le Nyan Paris?"));
            if (!role) {
                return Promise.resolve(jsonError("Для принятия анкеты нужно указать роль.", 400));
            }

            payload.assigned_role = role.slice(0, 120);
            if (!payload.owner_comment) {
                payload.owner_comment = payload.assigned_role;
            }
            nextInit.body = JSON.stringify(payload);
            return originalFetch(input, nextInit);
        } catch (_) {
            return originalFetch(input, init);
        }
    };
})();
