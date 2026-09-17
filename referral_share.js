(() => {
    const tg = window.Telegram?.WebApp;
    const API = "https://nyan-wallet-api.onrender.com";
    const BOT_URL = "https://t.me/nyancash_bot";
    let referralCode = null;

    function headers() {
        return { "X-Telegram-Init-Data": tg?.initData || "" };
    }

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function addStyles() {
        if (document.getElementById("ref-share-styles")) return;
        const style = document.createElement("style");
        style.id = "ref-share-styles";
        style.textContent = `
          .ref-share-actions{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px}
          .ref-share-actions button{width:100%;padding:10px 11px;border-radius:11px;font-size:11px}
          .ref-share-actions .ref-share-secondary{background:#fff;color:#7e4059;border:1px solid #dfbbc9}
          .ref-qr-overlay{position:fixed;inset:0;z-index:9998;display:flex;align-items:flex-end;justify-content:center;padding:16px;background:rgba(57,24,38,.24);backdrop-filter:blur(5px)}
          .ref-qr-overlay[hidden]{display:none}
          .ref-qr-sheet{position:relative;width:min(100%,420px);padding:22px 20px 20px;border:1px solid #efd8e2;border-radius:24px;background:#fffafc;box-shadow:0 18px 50px rgba(74,28,48,.18);text-align:center}
          .ref-qr-sheet h2{margin:0 38px 6px;font-size:18px;color:#7e284c}.ref-qr-sheet p{margin:0 auto;color:#a67589;font-size:11px;line-height:1.45;max-width:300px}
          .ref-qr-box{width:214px;height:214px;margin:18px auto 12px;padding:12px;border-radius:20px;background:#fff;border:1px solid #efd8e2;display:grid;place-items:center}
          .ref-qr-box img{width:190px;height:190px;display:block;border-radius:8px}.ref-qr-code{font-size:15px;font-weight:850;color:#7e284c;letter-spacing:.04em}.ref-qr-note{margin-top:6px!important;font-size:10px!important}
          .ref-qr-close{position:absolute;top:12px;right:12px;width:34px;height:34px;padding:0;border-radius:12px;background:#fff0f6;color:#8f2955;font-size:20px;line-height:1}
          .ref-share-toast{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);z-index:9999;width:min(86vw,330px);padding:11px 13px;border-radius:15px;background:#6f2747;color:#fff;box-shadow:0 12px 35px rgba(67,24,43,.22);font-size:11px;font-weight:700;text-align:center}
          @media(max-width:360px){.ref-share-actions{grid-template-columns:1fr}}
        `;
        document.head.appendChild(style);
    }

    function toast(text) {
        document.querySelector(".ref-share-toast")?.remove();
        const el = document.createElement("div");
        el.className = "ref-share-toast";
        el.textContent = text;
        document.body.appendChild(el);
        setTimeout(() => el.remove(), 2200);
    }

    async function getCode() {
        if (referralCode) return referralCode;
        if (!tg?.initData) return null;
        try {
            const response = await fetch(`${API}/api/profile`, { headers: headers() });
            const data = await response.json();
            if (!response.ok) return null;
            referralCode = data?.referral?.code || null;
            return referralCode;
        } catch (_) {
            return null;
        }
    }

    function shareText(code) {
        return `Присоединяйся к Nyan Wallet 🐾\nМой реферальный код: ${code}\nОткрой бота и введи код в профиле.`;
    }

    async function share(code) {
        const text = shareText(code);
        const shareUrl = `https://t.me/share/url?url=${encodeURIComponent(BOT_URL)}&text=${encodeURIComponent(text)}`;

        if (tg?.openTelegramLink) {
            tg.openTelegramLink(shareUrl);
            return;
        }

        if (navigator.share) {
            try {
                await navigator.share({ title: "Nyan Wallet", text, url: BOT_URL });
                return;
            } catch (_) {}
        }

        try {
            await navigator.clipboard.writeText(`${text}\n${BOT_URL}`);
            toast("Приглашение скопировано");
        } catch (_) {
            window.open(shareUrl, "_blank", "noopener,noreferrer");
        }
    }

    function ensureQrOverlay() {
        let overlay = document.getElementById("ref-qr-overlay");
        if (overlay) return overlay;

        overlay = document.createElement("div");
        overlay.id = "ref-qr-overlay";
        overlay.className = "ref-qr-overlay";
        overlay.hidden = true;
        overlay.innerHTML = `
          <section class="ref-qr-sheet" role="dialog" aria-modal="true" aria-labelledby="ref-qr-title">
            <button class="ref-qr-close" type="button" aria-label="Закрыть">×</button>
            <h2 id="ref-qr-title">Пригласить друга</h2>
            <p>Покажите этот QR-код другу. После открытия он увидит приглашение в Nyan Wallet и ваш код.</p>
            <div class="ref-qr-box"><img id="ref-qr-image" alt="QR-код приглашения"></div>
            <div id="ref-qr-code" class="ref-qr-code"></div>
            <p class="ref-qr-note">Код можно также ввести вручную в разделе «Профиль».</p>
          </section>`;
        document.body.appendChild(overlay);

        const close = () => {
            overlay.hidden = true;
            document.body.style.overflow = "";
        };
        overlay.querySelector(".ref-qr-close")?.addEventListener("click", close);
        overlay.addEventListener("click", (event) => {
            if (event.target === overlay) close();
        });
        return overlay;
    }

    function showQr(code) {
        const overlay = ensureQrOverlay();
        const payload = `Nyan Wallet\n${BOT_URL}\nРеферальный код: ${code}`;
        const image = overlay.querySelector("#ref-qr-image");
        const codeNode = overlay.querySelector("#ref-qr-code");
        if (image) image.src = `https://api.qrserver.com/v1/create-qr-code/?size=380x380&margin=8&data=${encodeURIComponent(payload)}`;
        if (codeNode) codeNode.textContent = code;
        overlay.hidden = false;
        document.body.style.overflow = "hidden";
    }

    async function enhanceReferralBox() {
        const box = document.getElementById("adv-referral-box");
        if (!box || box.querySelector("#ref-share-actions")) return;

        let code = null;
        const title = box.querySelector(".adv-row-title");
        if (title) {
            const match = title.textContent.match(/Ваш код:\s*([A-Z0-9_-]+)/i);
            if (match) code = match[1].toUpperCase();
        }
        if (!code) code = await getCode();
        if (!code || !document.body.contains(box) || box.querySelector("#ref-share-actions")) return;
        referralCode = code;

        const target = box.querySelector(".adv-row .adv-actions") || box.querySelector(".adv-row") || box;
        const actions = document.createElement("div");
        actions.id = "ref-share-actions";
        actions.className = "ref-share-actions";
        actions.innerHTML = `
          <button id="ref-share-button" type="button">Поделиться</button>
          <button id="ref-qr-button" class="ref-share-secondary" type="button">QR-код</button>`;
        target.insertAdjacentElement("afterend", actions);

        actions.querySelector("#ref-share-button")?.addEventListener("click", () => share(code));
        actions.querySelector("#ref-qr-button")?.addEventListener("click", () => showQr(code));
    }

    function watch() {
        addStyles();
        enhanceReferralBox();
        const observer = new MutationObserver(() => enhanceReferralBox());
        observer.observe(document.body, { childList: true, subtree: true });
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", watch, { once: true });
    else watch();
})();
