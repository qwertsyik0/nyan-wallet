(() => {
    const card = document.getElementById("wallet-card");
    if (!card) return;

    let frame = 0;

    const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

    function applyMotion(x, y) {
        if (!card.classList.contains("is-owner")) return;

        cancelAnimationFrame(frame);
        frame = requestAnimationFrame(() => {
            const nx = clamp(Number(x) || 0, -1, 1);
            const ny = clamp(Number(y) || 0, -1, 1);

            card.style.setProperty("--owner-holo-x", `${50 + nx * 24}%`);
            card.style.setProperty("--owner-holo-y", `${50 + ny * 20}%`);
            card.style.setProperty("--owner-tilt-y", `${nx * 2.2}deg`);
            card.style.setProperty("--owner-tilt-x", `${ny * -1.8}deg`);
            card.classList.add("owner-holo-active");
        });
    }

    function resetMotion() {
        if (!card.classList.contains("is-owner")) return;

        cancelAnimationFrame(frame);
        card.style.setProperty("--owner-holo-x", "50%");
        card.style.setProperty("--owner-holo-y", "50%");
        card.style.setProperty("--owner-tilt-y", "0deg");
        card.style.setProperty("--owner-tilt-x", "0deg");
        card.classList.remove("owner-holo-active");
    }

    function onPointerMove(event) {
        if (!card.classList.contains("is-owner")) return;

        const rect = card.getBoundingClientRect();
        if (!rect.width || !rect.height) return;

        const x = ((event.clientX - rect.left) / rect.width - 0.5) * 2;
        const y = ((event.clientY - rect.top) / rect.height - 0.5) * 2;
        applyMotion(x, y);
    }

    function onOrientation(event) {
        if (!card.classList.contains("is-owner")) return;
        if (typeof event.gamma !== "number" || typeof event.beta !== "number") return;

        const x = clamp(event.gamma / 35, -1, 1);
        const y = clamp((event.beta - 45) / 45, -1, 1);
        applyMotion(x, y);
    }

    card.addEventListener("pointermove", onPointerMove, { passive: true });
    card.addEventListener("pointerleave", resetMotion, { passive: true });

    if ("DeviceOrientationEvent" in window) {
        window.addEventListener("deviceorientation", onOrientation, { passive: true });
    }

    document.addEventListener("visibilitychange", () => {
        if (document.hidden) resetMotion();
    });
})();