export default function(component) {
    const root = component.parentElement.querySelector(".shell");
    const view = component.data.view;
    const key = Symbol.for("photoagent.layout");
    const memories = window[key] ||= new Map();
    const state = memories.get(component.data.instance_key) || {
        draft: component.data.draft || "", top: 0, sourcesTop: 0, panel: null,
        collapsed: false, lastMessage: null, nearEnd: true, session: view.session_key,
        draftRevision: view.draft_revision, pending: false,
        submissionRevision: view.submission_revision,
        focus: null, selection: null, openCards: [], hasNew: false,
    };
    // Streamlit повторно вызывает mount при data update без cleanup предыдущего вызова.
    // Снять старые listeners до установки новой версии view и восстановления DOM.
    state.dispose?.();
    memories.set(component.data.instance_key, state);
    const $ = selector => root.querySelector(selector);
    const feed = $(".feed");
    const prompt = $("textarea");
    const menu = $(".menu");
    const sources = $(".sources");
    const conversation = $(".conversation");
    const toolbar = $(".toolbar");
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    let draftTimer, highlightTimer, restoreFrame;
    const listeners = [];
    const on = (node, event, handler) => {
        node.addEventListener(event, handler);
        listeners.push(() => node.removeEventListener(event, handler));
    };
    const activeElement = () => root.getRootNode().activeElement;
    const rememberFocus = () => {
        const node = activeElement();
        if (node === prompt) return "textarea";
        if (node?.matches("select[name=detail]")) return "select[name=detail]";
        if (node?.matches("select[name=level]")) return "select[name=level]";
        if (node?.matches("[data-toggle=menu]")) return "[data-toggle=menu]";
        if (node?.matches("[data-toggle=sources]")) return "[data-toggle=sources]";
        if (state.panel && root.contains(node)) return `.${state.panel} [data-close]`;
        return null;
    };
    const emit = (action, values = {}) => component.setTriggerValue("action", {
        event_id: crypto.randomUUID(), action, text: "", detail: view.detail,
        level: view.level, ...values,
    });
    const saveDraft = () => component.setStateValue("draft", state.draft);
    const resizeInput = () => {
        const style = getComputedStyle(prompt);
        const line = parseFloat(style.lineHeight);
        const padding = parseFloat(style.paddingTop) + parseFloat(style.paddingBottom) + 2;
        prompt.style.height = "0px";
        prompt.style.height = `${Math.min(line * 7 + padding,
            Math.max(line * 4 + padding, prompt.scrollHeight + 2))}px`;
    };
    const syncSend = () => {
        $(".send").disabled = view.input_disabled || state.pending || !prompt.value.trim();
    };
    const isOverlay = () => window.innerWidth <= 1150;
    const isPhone = () => window.innerWidth <= 760;
    const setAccess = () => {
        const overlay = isOverlay() && state.panel !== null;
        root.classList.toggle("menu-collapsed", state.collapsed);
        root.classList.toggle("panel-menu", overlay && state.panel === "menu");
        root.classList.toggle("panel-sources", overlay && state.panel === "sources");
        conversation.inert = overlay;
        menu.inert = overlay ? state.panel !== "menu" : isOverlay() || state.collapsed;
        sources.inert = overlay ? state.panel !== "sources" : isPhone();
        conversation.setAttribute("aria-hidden", String(overlay));
        menu.setAttribute("aria-hidden", String(menu.inert));
        sources.setAttribute("aria-hidden", String(sources.inert));
        root.setAttribute("role", overlay ? "dialog" : "region");
        if (overlay) root.setAttribute("aria-modal", "true");
        else root.removeAttribute("aria-modal");
        root.setAttribute("aria-label", overlay
            ? (state.panel === "menu" ? "Настройки диалога" : "Источники диалога")
            : "Диалог с ассистентом фотографа");
        root.querySelectorAll("[data-toggle]").forEach(button => {
            const expanded = button.dataset.toggle === "menu" && !isOverlay()
                ? !state.collapsed : overlay && state.panel === button.dataset.toggle;
            button.setAttribute("aria-expanded", String(expanded));
        });
    };
    const closePanel = (restore = true) => {
        const previous = state.panel;
        state.panel = null;
        setAccess();
        if (restore && previous) $(`[data-toggle="${previous}"]`).focus({preventScroll: true});
    };
    const togglePanel = name => {
        if (name === "menu" && !isOverlay()) {
            state.collapsed = !state.collapsed;
            setAccess();
        } else if (state.panel === name) closePanel();
        else {
            state.panel = name;
            setAccess();
            (name === "menu" ? menu : sources).querySelector("[data-close]").focus();
        }
    };
    const measure = () => {
        const viewport = window.visualViewport;
        const bottom = viewport ? viewport.height + viewport.offsetTop : window.innerHeight;
        root.style.setProperty("--shell-height", `${Math.max(180, bottom - root.getBoundingClientRect().top)}px`);
        root.style.setProperty("--bar-bottom", `${toolbar.offsetHeight}px`);
        if (!isOverlay() || (!isPhone() && state.panel === "sources")) closePanel(false);
        else setAccess();
        resizeInput();
    };
    const safeUrl = value => {
        try {
            const url = new URL(value);
            return ["http:", "https:"].includes(url.protocol) ? value : null;
        } catch (_) { return null; }
    };
    const link = (label, address) => {
        const url = safeUrl(address);
        const node = document.createElement(url ? "a" : "span");
        node.textContent = label;
        if (url) { node.href = url; node.target = "_blank"; node.rel = "noopener noreferrer"; }
        return node;
    };
    const renderMessages = () => {
        const signature = JSON.stringify(view.messages);
        if (state.messageSignature === signature && $(".messages").childElementCount) return;
        const nodes = view.messages.map(message => {
            const article = document.createElement("article");
            article.className = `message ${message.kind}`;
            article.dataset.message = message.message_id;
            article.tabIndex = -1;
            if (message.kind === "assistant") {
                const heading = document.createElement("h3");
                heading.textContent = message.author;
                article.append(heading);
            }
            const text = document.createElement("p");
            text.textContent = message.text;
            article.append(text);
            return article;
        });
        $(".messages").replaceChildren(...nodes);
        state.messageSignature = signature;
    };
    const renderSources = () => {
        const signature = JSON.stringify(view.sources);
        if (state.sourceSignature === signature && $(".cards").childElementCount) return;
        const cards = view.sources.map((source, index) => {
            const card = document.createElement("article");
            card.className = "card";
            card.dataset.card = source.card_id;
            card.append(link(`${index + 1}. ${source.title}`, source.url));
            const comment = document.createElement("p");
            comment.textContent = source.context_comment;
            const details = document.createElement("details");
            const summary = document.createElement("summary");
            summary.textContent = "Действия с источником";
            const nav = document.createElement("nav");
            const go = document.createElement("button");
            go.type = "button";
            go.textContent = "Перейти к диалогу";
            go.dataset.messageTarget = source.first_message_id;
            nav.append(go, link("Открыть ссылку ↗", source.url));
            details.append(summary, nav);
            card.append(comment, details);
            return card;
        });
        $(".cards").replaceChildren(...cards);
        state.sourceSignature = signature;
    };
    if (state.session !== view.session_key) {
        Object.assign(state, {session: view.session_key, draft: "", top: 0,
            sourcesTop: 0, panel: null, lastMessage: null, pending: false,
            hasNew: false, nearEnd: true, openCards: [], focus: null, selection: null});
        saveDraft();
    }
    if (state.draftRevision !== view.draft_revision) {
        state.draft = "";
        state.draftRevision = view.draft_revision;
        state.pending = false;
        saveDraft();
    }
    if (state.submissionRevision !== view.submission_revision) {
        state.pending = false;
        state.submissionRevision = view.submission_revision;
    }
    prompt.value = state.draft;
    prompt.disabled = view.input_disabled;
    $("select[name=detail]").value = view.detail;
    $("select[name=level]").value = view.level;
    root.querySelectorAll("select").forEach(select => { select.disabled = view.settings_disabled; });
    $(".role-caption").textContent = view.current_role ? "Сейчас отвечает" : "";
    $(".role-name").textContent = view.current_role;
    $(".status").textContent = view.status;
    $(".welcome").hidden = view.messages.length > 0;
    $(".sources-empty").hidden = view.sources.length > 0;
    $("[data-toggle=sources]").setAttribute("aria-label", `Источники · ${view.sources.length}`);
    renderMessages();
    renderSources();
    const last = view.messages.at(-1)?.message_id || null;
    const newMessage = last !== state.lastMessage && state.lastMessage !== null;
    if (newMessage && !state.nearEnd) state.hasNew = true;
    $(".new-answer").hidden = !state.hasNew;
    state.lastMessage = last;
    syncSend();
    measure();
    restoreFrame = requestAnimationFrame(() => {
        feed.scrollTop = newMessage && state.nearEnd ? feed.scrollHeight : state.top;
        sources.scrollTop = state.sourcesTop;
        root.querySelectorAll(".card").forEach(card => {
            card.querySelector("details").open = state.openCards.includes(card.dataset.card);
        });
        const focus = state.focus ? $(state.focus) : null;
        if (focus && !focus.disabled && !focus.closest("[inert]") && focus.getClientRects().length) {
            focus.focus({preventScroll: true});
            if (focus === prompt && state.selection) prompt.setSelectionRange(...state.selection);
        }
    });
    on(prompt, "input", () => {
        state.draft = prompt.value;
        resizeInput(); syncSend(); clearTimeout(draftTimer);
        draftTimer = setTimeout(saveDraft, 300);
    });
    on($(".composer"), "submit", event => {
        event.preventDefault();
        if (view.input_disabled || state.pending || !prompt.value.trim()) return;
        state.draft = prompt.value;
        state.pending = true;
        // Trigger уже содержит текст: отдельное обновление draft здесь создаёт лишний rerun.
        clearTimeout(draftTimer); syncSend();
        emit("send", {text: state.draft});
    });
    on(prompt, "keydown", event => {
        if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.isComposing) {
            event.preventDefault(); $(".composer").requestSubmit();
        }
    });
    on(root, "change", event => {
        if (event.target.matches("select") && !view.settings_disabled) {
            emit("settings", {detail: $("select[name=detail]").value,
                level: $("select[name=level]").value});
        }
    });
    on(root, "click", event => {
        const target = event.target.closest("button");
        if (!target) return;
        if (target.dataset.toggle) togglePanel(target.dataset.toggle);
        else if (target.hasAttribute("data-close")) closePanel();
        else if (target.hasAttribute("data-example") && !view.input_disabled) {
            state.draft = target.textContent; prompt.value = state.draft;
            saveDraft(); resizeInput(); syncSend(); prompt.focus();
        } else if (target.dataset.messageTarget) {
            const message = [...root.querySelectorAll("[data-message]")]
                .find(node => node.dataset.message === target.dataset.messageTarget);
            if (message) {
                closePanel(false);
                message.scrollIntoView({block: "center", behavior: reduced.matches ? "auto" : "smooth"});
                message.focus({preventScroll: true});
                message.classList.add("highlight");
                clearTimeout(highlightTimer);
                highlightTimer = setTimeout(() => message.classList.remove("highlight"), 1800);
            }
        } else if (target.matches(".new-answer")) {
            feed.scrollTop = feed.scrollHeight;
            state.hasNew = false;
            target.hidden = true; feed.focus({preventScroll: true});
        }
    });
    on(root, "keydown", event => {
        if (!state.panel || !isOverlay()) return;
        if (event.key === "Escape") { event.preventDefault(); closePanel(); }
        if (event.key !== "Tab") return;
        const focusable = [...root.querySelectorAll("button,a[href],select,summary,textarea")]
            .filter(node => !node.disabled && node.getClientRects().length && !node.closest("[inert]"));
        const index = focusable.indexOf(activeElement());
        if (event.shiftKey && index <= 0) {
            event.preventDefault(); focusable.at(-1)?.focus();
        } else if (!event.shiftKey && (index === focusable.length - 1 || index < 0)) {
            event.preventDefault(); focusable[0]?.focus();
        }
    });
    on(feed, "scroll", () => {
        state.top = feed.scrollTop;
        state.nearEnd = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 48;
        if (state.nearEnd) { state.hasNew = false; $(".new-answer").hidden = true; }
    });
    on(sources, "scroll", () => {
        if (sources.getClientRects().length) state.sourcesTop = sources.scrollTop;
    });
    const observer = new ResizeObserver(measure);
    observer.observe(toolbar);
    on(window, "resize", measure);
    if (window.visualViewport) on(window.visualViewport, "resize", measure);
    let disposed = false;
    const dispose = () => {
        if (disposed) return;
        disposed = true;
        state.draft = prompt.value; state.top = feed.scrollTop;
        if (sources.getClientRects().length) state.sourcesTop = sources.scrollTop;
        state.focus = rememberFocus();
        state.selection = [prompt.selectionStart, prompt.selectionEnd];
        state.openCards = [...root.querySelectorAll(".card")]
            .filter(card => card.querySelector("details").open).map(card => card.dataset.card);
        clearTimeout(draftTimer); clearTimeout(highlightTimer);
        cancelAnimationFrame(restoreFrame);
        observer.disconnect(); listeners.forEach(remove => remove());
    };
    state.dispose = dispose;
    return dispose;
}
