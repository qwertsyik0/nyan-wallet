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
    let playerRequested = false;

    tg?.ready?.();
    tg?.expand?.();

    function setStatus(text) {
        if (status) status.textContent = text || "";
    }

    function enableSound() {
        if (!player || !playerReady) return;
        try {
            player.setVolume(100);
            player.unMute();
            player.playVideo();
            soundButton.hidden = true;
        } catch (_) {
            soundButton.hidden = false;
        }
    }

    function createRickrollPlayer() {
        if (playerRequested) return;
        playerRequested = true;

        if (!window.YT?.Player) {
            soundButton.hidden = false;
            return;
        }

        player = new YT.Player("rickroll-player", {
            videoId: "dQw4w9WgXcQ",
            playerVars: {
                autoplay: 1,
                mute: 0,
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
                        event.target.setVolume(100);
                        event.target.unMute();
                        event.target.playVideo();
                        soundButton.hidden = true;
                    } catch (_) {
                        soundButton.hidden = false;
                    }
                },
                onError() {
                    soundButton.hidden = false;
                },
            },
        });
    }

    function revealRickroll() {
        if (revealRequested) return;
        revealRequested = true;

        setStatus("активируем промокод…");
        tg?.HapticFeedback?.impactOccurred?.("medium");

        // First remove the promo screen, only then create/show the YouTube player.
        cover?.classList.add("revealed");
        cover?.setAttribute("aria-hidden", "true");
        stage?.classList.add("active");
        stage?.setAttribute("aria-hidden", "false");

        createRickrollPlayer();
        tg?.MainButton?.hide?.();
    }

    window.onYouTubeIframeAPIReady = () => {
        if (revealRequested) createRickrollPlayer();
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
        if (!document.hidden && revealRequested && playerReady) {
            enableSound();
        }
    });
})();
