(() => {
    const wallet = document.getElementById("wallet-view");
    if (!wallet || document.getElementById("privacy-link")) return;

    const style = document.createElement("style");
    style.textContent = `
        .privacy-link-wrap{margin:22px 0 4px;text-align:center}
        .privacy-link{font:inherit;font-size:10px;color:#a98a97;opacity:.55;text-decoration:none}
        .privacy-link:active{opacity:.8}
        .privacy-overlay{position:fixed;inset:0;z-index:9998;display:flex;align-items:flex-end;justify-content:center;padding:16px;background:rgba(57,24,38,.24);backdrop-filter:blur(5px)}
        .privacy-overlay[hidden]{display:none}
        .privacy-sheet{position:relative;width:min(100%,500px);max-height:78vh;overflow:auto;padding:22px 20px 20px;border:1px solid #efd8e2;border-radius:24px;background:#fffafc;box-shadow:0 18px 50px rgba(74,28,48,.18);color:#704156}
        .privacy-sheet h2{margin:0 40px 12px 0;font-size:18px;color:#7e284c}
        .privacy-sheet p{margin:9px 0;font-size:12px;line-height:1.55;color:#8f6678}
        .privacy-sheet ul{margin:8px 0 10px;padding-left:18px;font-size:12px;line-height:1.55;color:#8f6678}
        .privacy-close{position:absolute;top:12px;right:12px;width:34px;height:34px;padding:0;border-radius:12px;background:#fff0f6;color:#8f2955;font-size:20px;line-height:1}
        .privacy-date{padding-top:5px;font-size:10px!important;color:#b08e9d!important}
    `;
    document.head.appendChild(style);

    const wrap = document.createElement("div");
    wrap.className = "privacy-link-wrap";
    wrap.innerHTML = `<a id="privacy-link" class="privacy-link" href="#">Политика конфиденциальности</a>`;
    wallet.appendChild(wrap);

    const overlay = document.createElement("div");
    overlay.className = "privacy-overlay";
    overlay.id = "privacy-overlay";
    overlay.hidden = true;
    overlay.innerHTML = `
        <section class="privacy-sheet" role="dialog" aria-modal="true" aria-labelledby="privacy-title">
            <button class="privacy-close" type="button" aria-label="Закрыть">×</button>
            <h2 id="privacy-title">Конфиденциальность</h2>
            <p>Nyan Wallet хранит только данные, необходимые для работы кошелька и его функций.</p>
            <ul>
                <li>Telegram ID, имя и username, если они доступны;</li>
                <li>баланс лапкоинов и историю операций;</li>
                <li>промокоды, заявки на награды и их статусы;</li>
                <li>данные реферальной системы, уведомления, дату регистрации и последней активности.</li>
            </ul>
            <p>Эти данные используются для сохранения баланса, обработки операций, выдачи наград, работы промокодов и реферальной системы, статистики и защиты от злоупотреблений.</p>
            <p>Nyan Wallet не продаёт пользовательские данные третьим лицам и не использует их для сторонней рекламы.</p>
            <p>По вопросам доступа к своим данным или их удаления пользователь может обратиться в поддержку Нян. Отдельные записи об операциях могут сохраняться, если это необходимо для корректного учёта и предотвращения злоупотреблений.</p>
            <p class="privacy-date">Последнее обновление: 17 сентября 2026 года.</p>
        </section>
    `;
    document.body.appendChild(overlay);

    const open = () => {
        overlay.hidden = false;
        document.body.style.overflow = "hidden";
    };
    const close = () => {
        overlay.hidden = true;
        document.body.style.overflow = "";
    };

    wrap.querySelector("a")?.addEventListener("click", (event) => {
        event.preventDefault();
        open();
    });
    overlay.querySelector(".privacy-close")?.addEventListener("click", close);
    overlay.addEventListener("click", (event) => {
        if (event.target === overlay) close();
    });
})();

(() => {
    if (document.getElementById("activity-streak-script")) return;
    const script = document.createElement("script");
    script.id = "activity-streak-script";
    script.src = "./activity_streak.js?v=20260921-1";
    script.defer = true;
    document.body.appendChild(script);
})();
