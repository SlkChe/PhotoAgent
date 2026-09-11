export default function(component) {
    const closeSession = () => {
        if (!navigator.sendBeacon(component.data.url)) {
            fetch(component.data.url, {
                method: "POST", keepalive: true, mode: "no-cors", credentials: "omit"
            }).catch(() => {});
        }
    };
    window.addEventListener("pagehide", closeSession);
    const marker = component.parentElement.querySelector("[data-photo-lifecycle]");
    marker.dataset.closeUrl = component.data.url;
    marker.dataset.photoLifecycle = "ready";
    return () => window.removeEventListener("pagehide", closeSession);
}
