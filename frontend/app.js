(() => {
    const form = document.querySelector(".investigation-form");
    const status = document.querySelector("#approval-status");

    if (!form || !status) {
        return;
    }

    form.addEventListener("submit", () => {
        const statusIcon = status.querySelector(".approval-icon");
        const statusText = status.querySelector("strong");
        const statusNote = status.querySelector("small");

        status.classList.remove("approval-status-error");
        status.setAttribute("aria-busy", "true");

        if (statusIcon) {
            statusIcon.textContent = "...";
        }
        if (statusText) {
            statusText.textContent = "Review status: waiting for an investigation.";
        }
        if (statusNote) {
            statusNote.textContent = "Your investigation is being processed.";
        }
    });
})();
