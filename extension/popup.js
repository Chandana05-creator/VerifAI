/*
 * VerifAI Chrome Extension
 * Connects to the local VerifAI backend.
 */

const DEFAULT_SERVER = "http://127.0.0.1:8000";

let server = DEFAULT_SERVER;
let running = false;
let errors = [];
let gotResult = false;
let ctx = { text: "", pageUrl: "" };

const $ = (id) => document.getElementById(id);

const pct = (value) =>
    Math.round((Number(value) || 0) * 100);

function el(tag, cls, text) {
    const element = document.createElement(tag);

    if (cls) element.className = cls;
    if (text !== undefined) element.textContent = text;

    return element;
}

function safeUrl(value) {
    try {
        const url = new URL(String(value));

        if (
            url.protocol === "http:" ||
            url.protocol === "https:"
        ) {
            return url.href;
        }

        return null;
    } catch {
        return null;
    }
}

function link(url, text) {
    const safe = safeUrl(url);

    if (!safe) {
        return el("span", "", text);
    }

    const anchor = el("a", "", text);
    anchor.href = safe;
    anchor.target = "_blank";
    anchor.rel = "noopener noreferrer";

    return anchor;
}

function msg(message, info = false) {
    const element = $("msg");

    if (!element) return;

    element.textContent = message || "";
    element.className = info ? "msg info" : "msg";
    element.hidden = !message;
}

/* SETTINGS */

async function loadSettings() {
    const saved = await chrome.storage.local.get({
        server: DEFAULT_SERVER
    });

    server = String(saved.server || DEFAULT_SERVER)
        .replace(/\/+$/, "");

    $("server").value = server;
}

async function saveSettings() {
    const value = $("server").value.trim().replace(/\/+$/, "");
    const validUrl = safeUrl(value);

    if (!validUrl) {
        $("settingsmsg").textContent =
            "Enter a valid server URL, such as http://127.0.0.1:8000";
        return;
    }

    const parsed = new URL(validUrl);
    const origin = parsed.origin;

    if (
        parsed.pathname !== "/" ||
        parsed.search ||
        parsed.hash
    ) {
        $("settingsmsg").textContent =
            "Enter only the server address, without a path.";
        return;
    }

    const localServer =
        parsed.hostname === "localhost" ||
        parsed.hostname === "127.0.0.1";

    if (!localServer) {
        try {
            const granted = await chrome.permissions.request({
                origins: [origin + "/*"]
            });

            if (!granted) {
                $("settingsmsg").textContent =
                    "Permission was not granted for " + origin;
                return;
            }
        } catch (error) {
            $("settingsmsg").textContent =
                "Could not request permission: " + error.message;
            return;
        }
    }

    server = origin;

    await chrome.storage.local.set({ server });

    $("server").value = server;
    $("settingsmsg").textContent = "Server address saved.";
    $("settings").hidden = true;
}

/* PAGE AND TEXT INPUT */

async function getContext() {
    const params = new URLSearchParams(location.search);

    if (params.has("text") || params.has("pageUrl")) {
        return {
            text: params.get("text") || "",
            pageUrl: params.get("pageUrl") || "",
            auto: params.get("auto") || ""
        };
    }

    let text = "";
    let pageUrl = "";

    try {
        const [tab] = await chrome.tabs.query({
            active: true,
            currentWindow: true
        });

        pageUrl = tab?.url || "";

        if (tab?.id !== undefined) {
            const result = await chrome.scripting.executeScript({
                target: { tabId: tab.id },
                func: () => String(window.getSelection())
            });

            text = result?.[0]?.result || "";
        }
    } catch (error) {
        console.warn("Could not read the current page:", error);
    }

    return { text, pageUrl, auto: "" };
}

/* API REQUESTS */

async function post(path, body) {
    const response = await fetch(
        server + "/api/v1" + path,
        {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(body)
        }
    );

    if (!response.ok) {
        let message = "Server returned HTTP " + response.status;

        try {
            const result = await response.json();

            if (result.detail) {
                message =
                    typeof result.detail === "string"
                        ? result.detail
                        : JSON.stringify(result.detail);
            }
        } catch {
            // Keep the HTTP status message.
        }

        throw new Error(message);
    }

    return response.json();
}

/* PROGRESS */

function steps(names) {
    $("steps").textContent = "";

    names.forEach(([id, label]) => {
        const element = el("span", "step", label);
        element.id = "st-" + id;
        $("steps").append(element);
    });
}

function step(id, status, tip) {
    const element = $("st-" + id);

    if (!element) return;

    element.className = "step " + status;

    if (tip) {
        element.title = tip;
    }
}

function finish() {
    running = false;

    ["verify", "page", "plag"].forEach((id) => {
        if ($(id)) $(id).disabled = false;
    });
}

/* RUN VERIFICATION */

async function start(kind) {
    if (running) return;

    const text = $("text").value.trim();

    let path;
    let body;
    let flow;

    if (kind === "page") {
    if (!safeUrl(ctx.pageUrl)) {
        return msg(
            "This page cannot be checked. Open a normal HTTP or HTTPS webpage."
        );
    }

    path = "/research";
    body = {
        query:
            "Research and fact-check the content of this webpage: " +
            ctx.pageUrl,
        mode: "quick"
    };
}else if (kind === "plag") {
        if (text.split(/\s+/).filter(Boolean).length < 15) {
            return msg(
                "Enter at least 15 words to check for plagiarism."
            );
        }

        path = "/plagiarism";
        body = { text };
    } else {
        if (text.length < 3) {
            return msg(
                "Select text on a webpage or type a claim first."
            );
        }

        path = "/research";
body = {
    query: text,
    mode: "quick"
};
        }
    }

    if (kind === "plag") {
        flow = [
            ["plagiarism", "Plagiarism check"]
        ];
    } else {
        flow = kind === "plag"
    ? [["plagiarism", "Plagiarism check"]]
    : [
        ["research", "Research"],
        ["factcheck", "Fact-check"],
        ["critic", "Critic"],
        ["bias_detector", "Bias"],
        ["summarizer", "Summary"]
    ];
    }

    running = true;
    gotResult = false;
    errors = [];

    msg("");
    $("result").textContent = "";
    steps(flow);

    ["verify", "page", "plag"].forEach((id) => {
        $(id).disabled = true;
    });

    try {
        const result = await post(path, body);

        if (!result.session_id) {
            throw new Error(
                "The server response did not contain a session ID."
            );
        }

        const wsUrl =
            server.replace(/^http/, "ws") +
            "/api/v1/ws/research/" +
            encodeURIComponent(result.session_id);

        const socket = new WebSocket(wsUrl);

        socket.onmessage = (event) => {
            let data;

            try {
                data = JSON.parse(event.data);
            } catch {
                return;
            }

            onEvent(data, socket, result.session_id);
        };

        socket.onclose = () => finish();

        socket.onerror = () => {
            msg(
                "The live connection failed. Check the VerifAI server and WebSocket endpoint."
            );
        };
    } catch (error) {
        console.error("VerifAI request failed:", error);

        msg(
            "Verification failed: " +
            (error.message || "Unknown error")
        );

        finish();
    }
}

/* PROCESS SERVER EVENTS */

function onEvent(event, socket, sessionId) {
    if (event.type === "agent_update") {
        step(
            event.agent,
            event.status === "done"
                ? "done"
                : event.status === "error"
                    ? "error"
                    : "running",
            event.message
        );
    } else if (event.type === "error") {
        step(event.agent, "error", event.message);
        errors.push(event.agent + ": " + event.message);
    } else if (event.type === "final_report") {
        gotResult = true;
        showReport(event.payload, sessionId);
    } else if (event.type === "plagiarism_report") {
        gotResult = true;
        step("plagiarism", "done");
        showPlag(event.payload, sessionId);
    } else if (event.type === "pipeline_complete") {
        if (errors.length) {
            msg(
                "Some steps reported errors: " +
                errors.slice(0, 2).join(" | ")
            );
        } else if (!gotResult) {
            msg("The run finished without a result.");
        }

        socket.close();
    }
}

/* REPORT DISPLAY */

function openFull(sessionId) {
    const container = el("div", "small");

    container.append(
        link(
            server + "/ui/report.html?id=" +
            encodeURIComponent(sessionId),
            "Open the full report in VerifAI"
        )
    );

    return container;
}

function showReport(report, sessionId) {
    const root = $("result");

    root.textContent = "";

    const card = el("div", "card");
    const reliability = report.reliability || {};

    if (reliability.score !== undefined) {
        card.append(
            el("div", "big", pct(reliability.score) + "%"),
            el(
                "div",
                "small",
                "Overall reliability — " +
                (reliability.label || "")
            )
        );
    }

    card.append(
        el("p", null, report.executive_summary || "")
    );

    root.append(card, el("h3", null, "Claims"));

    (report.all_claims || []).forEach((claim) => {
        const container = el("div", "claim");

        container.append(
            el("div", null, claim.text || "")
        );

        const metadata = el("div", "meta");
        const track = el("div", "track");
        const fill = el("div", "fill");

        fill.style.width = pct(claim.confidence) + "%";

        fill.style.background =
            claim.verdict === "VERIFIED"
                ? "var(--ok)"
                : claim.verdict === "DISPUTED"
                    ? "var(--warn)"
                    : "var(--bad)";

        track.append(fill);

        metadata.append(
            el(
                "span",
                "badge " + (claim.verdict || ""),
                claim.verdict || "UNKNOWN"
            ),
            track,
            el("span", "small", pct(claim.confidence) + "%")
        );

        if (claim.critic?.outcome) {
            metadata.append(
                el(
                    "span",
                    "badge " + claim.critic.outcome,
                    "Critic: " + claim.critic.outcome
                )
            );
        }

        container.append(metadata);
        root.append(container);
    });

    const citations = report.citation_items || [];

    if (citations.length) {
        root.append(el("h3", null, "Sources"));

        citations.slice(0, 12).forEach((citation) => {
            const container = el("div", "cite");

            container.append(
                el("span", "small", "[" + citation.n + "] "),
                link(
                    citation.url,
                    citation.title || citation.url
                )
            );

            root.append(container);
        });
    }

    root.append(openFull(sessionId));
}

function showPlag(report, sessionId) {
    const root = $("result");

    root.textContent = "";

    const card = el("div", "card");

    card.append(
        el(
            "div",
            "big",
            (report.originality_percent ?? "N/A") + "% original"
        ),
        el(
            "span",
            "badge " + (report.risk || ""),
            (report.risk || "Unknown") + " risk"
        ),
        el(
            "div",
            "small",
            "Checked " +
            (report.passages_checked ?? 0) +
            " of " +
            (report.passages_total ?? 0) +
            " passages"
        )
    );

    root.append(card, el("h3", null, "Matching sources"));

    const sources = report.sources || [];

    if (!sources.length) {
        root.append(
            el("div", "small", "No matching sources found.")
        );
    }

    sources.forEach((source) => {
        const container = el("div", "cite");

        container.append(
            el("span", "small", "[" + source.n + "] "),
            link(
                source.url,
                source.title || source.domain || source.url
            ),
            el(
                "span",
                "small",
                " — up to " + pct(source.max_overlap) + "% overlap"
            )
        );

        root.append(container);
    });

    root.append(openFull(sessionId));
}

/* INITIALIZE */

(async function init() {
    try {
        await loadSettings();

        $("gear").onclick = () => {
            $("settings").hidden = !$("settings").hidden;
        };

        $("save").onclick = saveSettings;

        $("verify").onclick = () => start("text");
        $("page").onclick = () => start("page");
        $("plag").onclick = () => start("plag");

        ctx = await getContext();

        $("text").value = ctx.text || "";

        if (ctx.auto === "text" && ctx.text) {
            start("text");
        } else if (ctx.auto === "page") {
            start("page");
        }
    } catch (error) {
        console.error("VerifAI extension initialization failed:", error);
        msg("Extension initialization failed: " + error.message);
    }
})();