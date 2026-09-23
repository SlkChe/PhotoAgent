export default function(component) {
    const root = component.parentElement.querySelector("[data-f01-controls]");
    root.innerHTML = `
        <p role="status" aria-live="polite"></p>
        <button type="button" data-action="check">Проверить связь</button>
        <button type="button" data-action="create">Начать тестовую сессию</button>
        <button type="button" data-action="marker">Записать тестовую отметку</button>
        <button type="button" data-action="clear">Очистить тестовую сессию</button>
        <p>Очистка затрагивает все вкладки этого профиля на данном хосте.</p>`;
    if (!window.isSecureContext || !navigator.locks) {
        root.querySelector('[role="status"]').textContent =
            "Нужны HTTPS и Web Locks. Небезопасный обход синхронизации отключён.";
        root.querySelectorAll("button").forEach(button => { button.disabled = true; });
        return () => {};
    }
    const key = Symbol.for("photoagent.f01.document");
    const continuationKey = "photoagent.f01.continuation";
    if (!window[key]) {
        let continuation = false;
        try {
            continuation = sessionStorage.getItem(continuationKey) === "yes";
            sessionStorage.removeItem(continuationKey);
        } catch (_) { /* Недоступность хранилища проверяется перед служебным reload. */ }
        window[key] = {
            pageId: crypto.randomUUID(), opened: continuation, busy: false,
            message: "Проверяем браузерный маршрут…", listeners: new Set(),
        };
    }
    const state = window[key];
    const show = () => {
        root.querySelector('[role="status"]').textContent = state.message;
        root.querySelectorAll("button").forEach(button => { button.disabled = state.busy; });
    };
    const update = message => {
        if (message) state.message = message;
        state.listeners.forEach(listener => listener());
    };
    const request = async (path, body, csrf) => {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), component.data.timeout_ms);
        try {
            const response = await fetch(`/f01/browser/${path}`, {
                method: body === undefined ? "GET" : "POST", credentials: "same-origin",
                cache: "no-store", redirect: "error", signal: controller.signal,
                headers: body === undefined ? {} : {
                    "Content-Type": "application/json", "X-F01-CSRF": csrf,
                },
                body: body === undefined ? undefined : JSON.stringify(body),
            });
            if (!response.ok) throw new Error("request_failed");
            return response.status === 204 ? null : await response.json();
        } finally { clearTimeout(timer); }
    };
    const context = async () => {
        const value = await request("context");
        if (!value || typeof value.csrf_token !== "string" || !value.csrf_token ||
            !(value.session_id === null || typeof value.session_id === "string")) {
            throw new Error("invalid_context");
        }
        return value;
    };
    const reload = () => {
        sessionStorage.setItem(continuationKey, "yes");
        window.location.reload();
    };
    const execute = async action => {
        if (state.busy) return;
        if (action === "clear" && !window.confirm("Очистить тестовую сессию во всех вкладках?")) {
            return;
        }
        state.busy = true;
        update("Выполняется проверка…");
        try {
            // Одна блокировка на origin: контекст читается уже после ожидания другой вкладки.
            await navigator.locks.request("photoagent.f01.session", async () => {
                const current = await context();
                if (action === "create") {
                    sessionStorage.setItem(continuationKey, "probe");
                    sessionStorage.removeItem(continuationKey);
                    await request("create", {request_id: state.pageId}, current.csrf_token);
                    reload();
                } else if (action === "clear") {
                    await request("clear", {}, current.csrf_token);
                    reload();
                } else if (action === "marker") {
                    await request("marker", {marker: "Проверка F-01"}, current.csrf_token);
                    update("Тестовая отметка сохранена. Дождитесь ближайшего опроса UI.");
                } else if (current.session_id) {
                    if (!state.opened) {
                        await request("opened", {request_id: state.pageId}, current.csrf_token);
                        state.opened = true;
                    }
                    update("Браузер видит живую сессию. Сравните снимок API ниже.");
                } else {
                    update("Живой сессии нет. Начните новую явно.");
                }
            });
        } catch (_) {
            update("Браузерная операция не подтверждена. Проверьте маршруты API и соединение.");
        } finally {
            state.busy = false;
            update();
        }
    };
    const click = event => {
        const button = event.target.closest("button[data-action]");
        if (button) void execute(button.dataset.action);
    };
    state.listeners.add(show);
    root.addEventListener("click", click);
    show();
    void execute("check");
    return () => {
        state.listeners.delete(show);
        root.removeEventListener("click", click);
    };
}
