const thread = document.querySelector("#thread");
const keyForm = document.querySelector("#key-form");
const keyReady = document.querySelector("#key-ready");
const keyError = document.querySelector("#key-error");
const keySummary = document.querySelector("#key-summary");
const fingerprint = document.querySelector("#fingerprint");
const storageMode = document.querySelector("#storage-mode");
const modelPicker = document.querySelector("#model-picker");
const modelError = document.querySelector("#model-error");
const composer = document.querySelector("#composer");
const messageBox = document.querySelector("#message");
const sendButton = document.querySelector("#send");
const chatError = document.querySelector("#chat-error");
const historyNote = document.querySelector("#history-note");
const saveButton = document.querySelector("#save-key");

const state = {
  models: [],
  defaultModelId: "gemini-3.6-flash",
  session: null,
  selectedModelId: "gemini-3.6-flash",
  sending: false,
  checking: false,
};

const suggestions = [
  "I have four weeks until mock exams and I keep rewriting notes. Can you give me a weekly plan?",
  "Help me start a UCAS personal statement for computer science. Ask what you need to know.",
  "Explain how a bicycle gear works, in plain language.",
];

init();

async function init() {
  try {
    const [models, session] = await Promise.all([api("/api/models"), api("/api/session")]);
    state.models = models.models;
    state.defaultModelId = models.defaultModelId;
    state.selectedModelId = session.modelId || models.defaultModelId;
    state.session = session;
    renderModels();
    renderSession();
  } catch (error) {
    show(keyError, errorMessage(error));
  }
}

keyForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  hide(keyError);
  const apiKey = document.querySelector("#api-key").value.trim();
  if (!apiKey) {
    show(keyError, "Paste your Google AI Studio API key.");
    return;
  }
  state.checking = true;
  renderBusy();
  try {
    state.session = await api("/api/key", {
      method: "POST",
      body: JSON.stringify({
        apiKey,
        modelId: state.selectedModelId,
        remember: document.querySelector("#remember").checked,
      }),
    });
    document.querySelector("#api-key").value = "";
    renderSession();
  } catch (error) {
    show(keyError, errorMessage(error));
  } finally {
    state.checking = false;
    renderBusy();
  }
});

document.querySelector("#remove-key").addEventListener("click", async () => {
  hide(keyError);
  try {
    state.session = await api("/api/key", { method: "DELETE" });
    state.selectedModelId = state.session.modelId || state.defaultModelId;
    renderModels();
    renderSession();
  } catch (error) {
    show(keyError, errorMessage(error));
  }
});

document.querySelector("#new-chat").addEventListener("click", async () => {
  hide(chatError);
  if (!state.session?.hasKey) {
    renderThread([]);
    return;
  }
  try {
    state.session = await api("/api/chat/reset", { method: "POST", body: "{}" });
    renderSession();
  } catch (error) {
    show(chatError, errorMessage(error));
  }
});

modelPicker.addEventListener("change", async (event) => {
  const input = event.target;
  if (input.name !== "model") return;
  state.selectedModelId = input.value;
  hide(modelError);
  if (!state.session?.hasKey) return;
  try {
    state.session = await api("/api/model", {
      method: "PATCH",
      body: JSON.stringify({ modelId: input.value }),
    });
    renderSession();
  } catch (error) {
    show(modelError, errorMessage(error));
  }
});

composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  await sendCurrentMessage();
});

messageBox.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    composer.requestSubmit();
  }
});

async function sendCurrentMessage() {
  const text = messageBox.value.trim();
  if (!text || state.sending || !state.session?.hasKey) return;
  hide(chatError);
  state.sending = true;
  const previous = state.session.messages;
  state.session = { ...state.session, messages: [...previous, { role: "user", text }] };
  messageBox.value = "";
  renderThread(state.session.messages, true);
  renderBusy();
  try {
    const response = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({ text }),
    });
    state.session = response;
    historyNote.hidden = !response.historyTruncated;
    renderSession();
  } catch (error) {
    state.session = { ...state.session, messages: previous };
    messageBox.value = text;
    renderThread(previous);
    show(chatError, errorMessage(error));
  } finally {
    state.sending = false;
    renderBusy();
    messageBox.focus();
  }
}

function renderModels() {
  modelPicker.replaceChildren();
  for (const model of state.models) {
    const label = document.createElement("label");
    label.className = "model-option";
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "model";
    input.value = model.id;
    input.checked = model.id === state.selectedModelId;
    const copy = document.createElement("span");
    const title = document.createElement("strong");
    title.textContent = model.label;
    const detail = document.createElement("span");
    detail.textContent = `${model.id} — ${model.blurb}`;
    copy.append(title, detail);
    label.append(input, copy);
    modelPicker.append(label);
  }
}

function renderSession() {
  const connected = Boolean(state.session?.hasKey);
  keyForm.hidden = connected;
  keyReady.hidden = !connected;
  messageBox.disabled = !connected || state.sending;
  sendButton.disabled = !connected || state.sending;
  if (connected) {
    fingerprint.textContent = state.session.fingerprint;
    storageMode.textContent = state.session.remember
      ? "The key is encrypted on this server. Removing it deletes that copy."
      : "The key is only in this server’s memory and is dropped when that session ends.";
    keySummary.textContent = "Gemini will answer with your key and the model selected below.";
    state.selectedModelId = state.session.modelId;
    renderModels();
  } else {
    keySummary.textContent = "Connect your own Google AI Studio key. This app has no shared key.";
  }
  historyNote.hidden = (state.session?.messages?.length || 0) <= 40;
  renderThread(state.session?.messages || []);
  renderBusy();
}

function renderThread(messages, pending = false) {
  thread.replaceChildren();
  if (!messages.length && !pending) {
    const empty = document.createElement("div");
    const title = document.createElement("h2");
    title.textContent = "Start a conversation";
    const copy = document.createElement("p");
    copy.className = "muted";
    copy.textContent = state.session?.hasKey
      ? "Ask about study, university in Britain, a habit you want to change, or anything else."
      : "Add your API key first. Then ask in your own words.";
    empty.append(title, copy);
    if (state.session?.hasKey) {
      const row = document.createElement("div");
      row.className = "suggestions";
      for (const prompt of suggestions) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = prompt;
        button.addEventListener("click", () => {
          messageBox.value = prompt;
          messageBox.focus();
        });
        row.append(button);
      }
      empty.append(row);
    }
    thread.append(empty);
    return;
  }
  for (const message of messages) thread.append(bubble(message));
  if (pending) {
    const waiting = document.createElement("div");
    waiting.className = "bubble agent pending";
    waiting.textContent = `Gemini is writing with ${state.selectedModelId}…`;
    thread.append(waiting);
  }
  thread.scrollTop = thread.scrollHeight;
}

function bubble(message) {
  const item = document.createElement("div");
  item.className = `bubble ${message.role === "user" ? "you" : "agent"}`;
  const who = document.createElement("span");
  who.className = "who";
  who.textContent = message.role === "user"
    ? "You"
    : `AI Support Agent · ${message.modelId || state.selectedModelId}`;
  const body = document.createElement("div");
  if (message.role === "user") {
    const paragraph = document.createElement("p");
    paragraph.textContent = message.text;
    body.append(paragraph);
  } else {
    renderModelText(body, message.text || "");
  }
  item.append(who, body);
  return item;
}

function renderModelText(container, text) {
  const fence = text.split(/```/);
  fence.forEach((part, index) => {
    if (index % 2 === 1) {
      const pre = document.createElement("pre");
      const code = document.createElement("code");
      code.textContent = part.replace(/^\w+\n/, "");
      pre.append(code);
      container.append(pre);
      return;
    }
    for (const block of part.split(/\n{2,}/)) {
      if (!block.trim()) continue;
      const lines = block.split("\n");
      const list = lines.every((line) => !line.trim() || /^[-*]\s+/.test(line.trim()));
      if (list) {
        const ul = document.createElement("ul");
        for (const line of lines) {
          if (!line.trim()) continue;
          const li = document.createElement("li");
          appendInline(li, line.trim().replace(/^[-*]\s+/, ""));
          ul.append(li);
        }
        container.append(ul);
      } else {
        const paragraph = document.createElement("p");
        lines.forEach((line, lineIndex) => {
          if (lineIndex) paragraph.append(document.createElement("br"));
          appendInline(paragraph, line);
        });
        container.append(paragraph);
      }
    }
  });
}

function appendInline(parent, text) {
  const pattern = /`([^`]+)`|\*\*([^*]+)\*\*/g;
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index > last) parent.append(document.createTextNode(text.slice(last, match.index)));
    if (match[1] != null) {
      const code = document.createElement("code");
      code.textContent = match[1];
      parent.append(code);
    } else {
      const strong = document.createElement("strong");
      strong.textContent = match[2];
      parent.append(strong);
    }
    last = match.index + match[0].length;
  }
  if (last < text.length) parent.append(document.createTextNode(text.slice(last)));
}

function renderBusy() {
  saveButton.disabled = state.checking;
  saveButton.textContent = state.checking ? "Checking key…" : "Check key and continue";
  sendButton.disabled = state.sending || !state.session?.hasKey;
  sendButton.textContent = state.sending ? "Sending…" : "Send";
  messageBox.disabled = state.sending || !state.session?.hasKey;
}

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      ...options,
    });
  } catch {
    const error = new Error("The connection to AI Support Agent failed. Check your network and try again.");
    error.code = "network";
    throw error;
  }
  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  if (!response.ok) {
    const error = new Error(data?.error?.message || "The request failed.");
    error.code = data?.error?.code || "unknown";
    throw error;
  }
  return data;
}

function errorMessage(error) {
  if (error && error.message) return error.message;
  return "Something went wrong. Try again.";
}

function show(node, text) {
  node.hidden = false;
  node.textContent = text;
}

function hide(node) {
  node.hidden = true;
  node.textContent = "";
}
