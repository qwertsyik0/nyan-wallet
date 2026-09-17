const tg = window.Telegram?.WebApp;

if (tg) {
    tg.ready();
    tg.expand();

    const user = tg.initDataUnsafe?.user;

    if (user) {
        const name =
            user.first_name ||
            user.username ||
            "пользователь";

        document.getElementById("username").textContent = name;
    }
}
