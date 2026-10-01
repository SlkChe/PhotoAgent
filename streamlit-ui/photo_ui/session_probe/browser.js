export default function(component) {
    const root = component.parentElement.querySelector("[data-f01-controls]");
    root.innerHTML = `
        <p role="status" aria-live="polite"></p>
        <button type="button" data-action="check">Проверить связь</button>
        <button type="button" data-action="create">Начать тестовую сессию</button>
        <button type="button" data-action="marker">Записать тестовую отметку</button>
        <button type="button" data-action="clear">Очистить тестовую сессию</button>
        <button type="button" data-action="reconnect">Обновить подключение</button>
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
            pendingClear: null, pendingOpened: null, displayedSession: null,
            sessionChanged: false,
            message: "Проверяем браузерный маршрут…", listeners: new Set(),
        };
    }
    const state = window[key];
    state.displayedSession = component.data.displayed_session_id;
    const show = () => {
        root.querySelector('[role="status"]').textContent = state.message;
        root.querySelectorAll("button").forEach(button => { button.disabled = state.busy; });
        const clear = root.querySelector('[data-action="clear"]');
        clear.disabled = state.busy || state.sessionChanged || !state.displayedSession;
        clear.textContent = state.pendingClear ? "Повторить очистку" : "Очистить тестовую сессию";
        root.querySelector('[data-action="marker"]').disabled =
            state.busy || state.sessionChanged || !state.displayedSession;
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
            if (!response.ok) {
                const error = new Error("request_failed");
                error.status = response.status;
                const payload = await response.json().catch(() => null);
                error.sessionChanged = response.status === 409 && payload?.detail === "session_changed";
                throw error;
            }
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
        if (action === "reconnect") { reload(); return; }
        if (state.sessionChanged) return;
        if (action === "clear" && !state.pendingClear) {
            if (!state.displayedSession || state.sessionChanged) return;
            // Намерение привязано к показанному snapshot до confirm и ожидания Web Lock.
            const intent = {
                request_id: crypto.randomUUID(), expected_session_id: state.displayedSession,
            };
            if (!window.confirm("Очистить показанную тестовую сессию во всех вкладках?")) return;
            state.pendingClear = intent;
        }
        if (action === "check" && !state.opened && !state.pendingOpened && state.displayedSession) {
            state.pendingOpened = {
                request_id: state.pageId, expected_session_id: state.displayedSession,
            };
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
                    await request("clear", state.pendingClear, current.csrf_token);
                    state.pendingClear = null;
                    reload();
                } else if (action === "marker") {
                    await request("marker", {marker: "Проверка F-01"}, current.csrf_token);
                    update("Тестовая отметка сохранена. Дождитесь ближайшего опроса UI.");
                } else if (current.session_id) {
                    if (!state.opened && state.pendingOpened && !state.sessionChanged) {
                        await request("opened", state.pendingOpened, current.csrf_token);
                        state.opened = true;
                    }
                    update("Браузер видит живую сессию. Сравните снимок API ниже.");
                } else {
                    update("Живой сессии нет. Начните новую явно.");
                }
            });
        } catch (error) {
            if (error.sessionChanged) {
                state.sessionChanged = true;
                state.pendingClear = null;
                update("Сессия изменилась. Обновите подключение; новая очистка потребует подтверждения.");
            } else if (error.status === 422) {
                update("API не поддерживает тело действия. Требуется согласованное обновление B-15.");
            } else {
                update("Операция не подтверждена. При повторе сохраняется исходная сессия действия.");
            }
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
