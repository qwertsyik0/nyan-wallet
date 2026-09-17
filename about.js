(() => {
    const tg = window.Telegram?.WebApp;
    const wallet = document.getElementById("wallet-view");
    const app = document.querySelector(".app");
    if (!wallet || !app || document.getElementById("about-wallet-link")) return;

    const style = document.createElement("style");
    style.id = "about-wallet-styles";
    style.textContent = `
      .about-link-wrap{margin:18px 0 0;text-align:center}
      .about-link{appearance:none;border:0;background:transparent;padding:4px 8px;font:inherit;font-size:11px;color:#9d7485;opacity:.78;text-decoration:none}
      .about-link:active{opacity:1}
      .about-page{padding-bottom:24px}
      .about-hero{margin-top:12px;padding:20px;border:1px solid #efd8e2;border-radius:22px;background:linear-gradient(145deg,#fff,#fff7fa)}
      .about-brand{font-size:20px;font-weight:850;color:#7e284c;letter-spacing:-.02em}
      .about-lead{margin-top:7px;font-size:12px;line-height:1.55;color:#9b7082}
      .about-card{margin-top:12px;padding:17px;border:1px solid #efd8e2;border-radius:19px;background:#fff}
      .about-title{font-size:14px;font-weight:800;color:#71334e}
      .about-text{margin-top:7px;font-size:11px;line-height:1.58;color:#9a7182}
      .about-features{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:11px}
      .about-feature{padding:10px 11px;border-radius:13px;background:#fff7fa;border:1px solid #f1dfe7;font-size:10px;font-weight:700;color:#7e4059}
      .about-note{margin-top:12px;padding:14px 15px;border-radius:16px;background:#fff5f8;border:1px solid #efd8e2;font-size:10px;line-height:1.55;color:#936a7b}
      .about-footer{margin:18px 0 4px;text-align:center;color:#b08d9c;font-size:10px;line-height:1.7}
      .about-privacy{appearance:none;border:0;background:transparent;padding:2px 5px;font:inherit;font-size:10px;color:#9d7485;text-decoration:underline;text-underline-offset:2px}
      @media(max-width:350px){.about-features{grid-template-columns:1fr}}
    `;
    document.head.appendChild(style);

    const linkWrap = document.createElement("div");
    linkWrap.className = "about-link-wrap";
    linkWrap.innerHTML = `<button id="about-wallet-link" class="about-link" type="button">О Nyan Wallet</button>`;
    wallet.appendChild(linkWrap);

    const view = document.createElement("main");
    view.id = "about-wallet-view";
    view.className = "view hidden about-page";
    view.innerHTML = `
      <div class="subpage-header">
        <button id="about-wallet-back" class="back-button" type="button" aria-label="Назад">‹</button>
        <div>
          <div class="page-title">О Nyan Wallet</div>
          <div class="page-subtitle">кошелёк экосистемы Нян</div>
        </div>
      </div>

      <section class="about-hero">
        <div class="about-brand">Nyan Wallet</div>
        <div class="about-lead">Единый кошелёк экосистемы Нян. Здесь хранятся ваши лапкоины 🐾, история операций, награды, достижения, реферальные бонусы и другие возможности проектов Нян.</div>
      </section>

      <section class="about-card">
        <div class="about-title">Что такое лапкоины</div>
        <div class="about-text">Лапкоины — внутренняя валюта экосистемы Нян. Их можно получать за покупки в Нян Шопе, участие в активностях, отзывы, промокоды, приглашения друзей и другие действия внутри проектов Нян.</div>
      </section>

      <section class="about-card">
        <div class="about-title">На что их можно потратить</div>
        <div class="about-text">Лапкоины можно обменивать на доступные награды из каталога Nyan Wallet. Каталог постепенно пополняется новыми предложениями, лимитированными наградами и специальными событиями.</div>
      </section>

      <section class="about-card">
        <div class="about-title">Возможности Nyan Wallet</div>
        <div class="about-features">
          <div class="about-feature">Баланс и история</div>
          <div class="about-feature">Промокоды</div>
          <div class="about-feature">Каталог наград</div>
          <div class="about-feature">Реферальная система</div>
          <div class="about-feature">Уровни</div>
          <div class="about-feature">Достижения</div>
          <div class="about-feature">Уведомления</div>
          <div class="about-feature">События</div>
        </div>
      </section>

      <div class="about-note">Лапкоины нельзя купить за реальные деньги, вывести или обменять обратно на деньги. Все начисления, списания и действия с кошельком сохраняются в истории.</div>

      <section class="about-card">
        <div class="about-title">Поддержка</div>
        <div class="about-text">Если у вас возник вопрос по балансу, награде или работе Nyan Wallet, обратитесь в поддержку проектов Нян.</div>
      </section>

      <div class="about-footer">
        <div>Nyan Wallet · часть экосистемы Нян 🐾</div>
        <div>Версия 1.0</div>
        <button id="about-privacy-button" class="about-privacy" type="button">Политика конфиденциальности</button>
      </div>
    `;
    app.appendChild(view);

    const show = () => {
        document.querySelectorAll(".view").forEach(el => el.classList.add("hidden"));
        view.classList.remove("hidden");
        window.scrollTo({ top: 0, behavior: "smooth" });
        tg?.BackButton?.show?.();
    };

    const close = () => {
        view.classList.add("hidden");
        wallet.classList.remove("hidden");
        window.scrollTo({ top: 0, behavior: "smooth" });
        tg?.BackButton?.hide?.();
    };

    document.getElementById("about-wallet-link")?.addEventListener("click", show);
    document.getElementById("about-wallet-back")?.addEventListener("click", close);
    document.getElementById("about-privacy-button")?.addEventListener("click", () => {
        document.getElementById("privacy-link")?.click();
    });
})();
