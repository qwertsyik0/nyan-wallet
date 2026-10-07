(() => {
    "use strict";

    const tg = window.Telegram?.WebApp;
    const cover = document.getElementById("promo-cover");
    const stage = document.getElementById("rickroll-stage");
    const activateButton = document.getElementById("promo-activate");
    const soundButton = document.getElementById("sound-button");
    const status = document.getElementById("promo-status");

    let player = null;
    let playerReady = false;
    let revealRequested = false;

    tg?.ready?.();
    tg?.expand?.();

    function setStatus(text) {
        if (status) status.textContent = text || "";
    }

    function preloadMuted() {
        if (!player || !playerReady || revealRequested) return;
        try {
            player.mute();
            player.setVolume(100);
            player.playVideo();
        } catch (_) {}
    }

    function revealRickroll() {
        if (revealRequested) return;
        revealRequested = true;

        setStatus("активируем промокод…");
        tg?.HapticFeedback?.impactOccurred?.("medium");

        stage?.classList.add("active");
        stage?.setAttribute("aria-hidden", "false");
        cover?.classList.add("revealed");

        try {
            if (player && playerReady) {
                player.setVolume(100);
                player.unMute();
                player.playVideo();
                soundButton.hidden = true;
            } else {
                soundButton.hidden = false;
            }
        } catch (_) {
            soundButton.hidden = false;
        }

        tg?.MainButton?.hide?.();
    }

    function enableSound() {
        if (!player || !playerReady) return;
        try {
            player.setVolume(100);
            player.unMute();
            player.playVideo();
            soundButton.hidden = true;
        } catch (_) {}
    }

    window.onYouTubeIframeAPIReady = () => {
        player = new YT.Player("rickroll-player", {
            videoId: "dQw4w9WgXcQ",
            playerVars: {
                autoplay: 1,
                mute: 1,
                controls: 0,
                disablekb: 1,
                fs: 0,
                playsinline: 1,
                rel: 0,
                modestbranding: 1,
                loop: 1,
                playlist: "dQw4w9WgXcQ",
            },
            events: {
                onReady(event) {
                    playerReady = true;
                    try {
                        event.target.mute();
                        event.target.setVolume(100);
                        event.target.playVideo();
                    } catch (_) {}

                    if (revealRequested) enableSound();
                },
                onStateChange(event) {
                    if (!revealRequested && event.data === YT.PlayerState.PAUSED) {
                        preloadMuted();
                    }
                },
            },
        });
    };

    activateButton?.addEventListener("click", revealRickroll);
    soundButton?.addEventListener("click", enableSound);

    if (tg?.MainButton) {
        tg.MainButton.setText("Активировать NYANROFL700");
        tg.MainButton.show();
        tg.MainButton.enable?.();
        tg.MainButton.onClick(revealRickroll);
    }

    document.addEventListener("visibilitychange", () => {
        if (document.hidden || !playerReady) return;
        if (revealRequested) enableSound();
        else preloadMuted();
    });
})();
