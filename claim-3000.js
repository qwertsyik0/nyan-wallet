(() => {
    "use strict";

    const tg = window.Telegram?.WebApp;
    const claimButton = document.getElementById("claim-button");
    const claimCard = document.getElementById("claim-card");
    const stage = document.getElementById("rickroll-stage");
    const soundButton = document.getElementById("sound-button");
    const status = document.getElementById("claim-status");

    let player = null;
    let playerReady = false;
    let revealRequested = false;

    tg?.ready?.();
    tg?.expand?.();

    function setStatus(text) {
        if (status) status.textContent = text || "";
    }

    function forcePlaybackMuted() {
        if (!player || !playerReady) return;
        try {
            player.mute();
            player.setVolume(100);
            player.playVideo();
        } catch (_) {}
    }

    function enableSoundAndReveal() {
        revealRequested = true;
        claimCard?.classList.add("revealed");
        stage?.classList.add("active");
        tg?.HapticFeedback?.impactOccurred?.("medium");

        if (!player || !playerReady) {
            setStatus("запускаем награду…");
            return;
        }

        try {
            player.setVolume(100);
            player.unMute();
            player.playVideo();
            soundButton.hidden = true;
        } catch (_) {
            soundButton.hidden = false;
        }
    }

    function retrySound() {
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

                    setStatus("награда готова");
                    if (revealRequested) enableSoundAndReveal();
                },
                onStateChange(event) {
                    if (event.data === YT.PlayerState.PAUSED && !revealRequested) {
                        forcePlaybackMuted();
                    }
                },
                onError() {
                    setStatus("нажмите «Забрать 3000 🐾»");
                },
            },
        });
    };

    claimButton?.addEventListener("click", enableSoundAndReveal);
    soundButton?.addEventListener("click", retrySound);

    // Telegram's bottom MainButton mirrors the fake claim action.
    if (tg?.MainButton) {
        tg.MainButton.setText("Забрать 3000 🐾");
        tg.MainButton.show();
        tg.MainButton.enable?.();
        tg.MainButton.onClick(enableSoundAndReveal);
    }

    document.addEventListener("visibilitychange", () => {
        if (!document.hidden && playerReady) {
            if (revealRequested) retrySound();
            else forcePlaybackMuted();
        }
    });
})();
