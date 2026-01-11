const el = (id) => document.getElementById(id);

const fileInput = el("fileInput");
const uploadBtn = el("uploadBtn");
const resetBtn = el("resetBtn");

const alertBox = el("alertBox");
const uploadStatus = el("uploadStatus");

const sessionIdEl = el("sessionId");
const copySessionBtn = el("copySessionBtn");

const chatReadyBadge = el("chatReadyBadge");
const chatMessages = el("chatMessages");
const chatForm = el("chatForm");
const chatInput = el("chatInput");
const sendBtn = el("sendBtn");

function showAlert(type, msg) {
  alertBox.className = `alert alert-${type}`;
  alertBox.textContent = msg;
}

function hideAlert() {
  alertBox.className = "alert d-none";
  alertBox.textContent = "";
}

function setSession(sessionId) {
  sessionIdEl.textContent = sessionId || "—";
  copySessionBtn.disabled = !sessionId;
  chatInput.disabled = !sessionId;
  sendBtn.disabled = !sessionId;

  chatReadyBadge.className = `badge rounded-pill ${sessionId ? "text-bg-success" : "text-bg-secondary"}`;
  chatReadyBadge.textContent = sessionId ? "Ready" : "Upload to start";

  if (sessionId) {
    localStorage.setItem("multidocchat_session_id", sessionId);
  } else {
    localStorage.removeItem("multidocchat_session_id");
  }
}

function appendMsg(role, text) {
  // Remove hint if present
  const hint = chatMessages.querySelector(".chat-hint");
  if (hint) hint.remove();

  const wrap = document.createElement("div");
  wrap.className = `msg ${role === "user" ? "user" : "bot"}`;

  const meta = document.createElement("div");
  meta.className = "msg-meta";
  meta.textContent = `${role === "user" ? "You" : "Assistant"} • ${new Date().toLocaleTimeString()}`;

  wrap.textContent = text;
  wrap.appendChild(meta);

  chatMessages.appendChild(wrap);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function appendTyping() {
  const wrap = document.createElement("div");
  wrap.className = "msg bot";
  wrap.id = "typingBubble";

  wrap.innerHTML = `
    <div class="typing">
      <span class="dot"></span><span class="dot"></span><span class="dot"></span>
      <span class="ms-2" style="opacity:.75">Thinking…</span>
    </div>
  `;
  chatMessages.appendChild(wrap);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function removeTyping() {
  const t = document.getElementById("typingBubble");
  if (t) t.remove();
}

async function uploadAndIndex() {
  hideAlert();
  const files = fileInput.files;
  if (!files || files.length === 0) {
    showAlert("warning", "Please select at least one file to upload.");
    return;
  }

  uploadBtn.disabled = true;
  uploadBtn.textContent = "Uploading…";
  uploadStatus.textContent = "Uploading & indexing…";

  try {
    const fd = new FormData();
    for (const f of files) fd.append("files", f);

    const res = await fetch("/upload", { method: "POST", body: fd });
    const data = await res.json().catch(() => ({}));

    if (!res.ok) {
      const detail = data?.detail || `Upload failed with status ${res.status}`;
      throw new Error(detail);
    }

    setSession(data.session_id);
    uploadStatus.textContent = data.message || "Indexing complete.";
    showAlert("success", "Upload & indexing completed. You can now chat.");
  } catch (err) {
    showAlert("danger", err.message || "Upload failed.");
    uploadStatus.textContent = "";
  } finally {
    uploadBtn.disabled = false;
    uploadBtn.textContent = "Upload & Index";
  }
}

async function sendChatMessage(text) {
  hideAlert();
  const sessionId = sessionIdEl.textContent;
  if (!sessionId || sessionId === "—") {
    showAlert("warning", "No session_id found. Upload documents first.");
    return;
  }

  appendMsg("user", text);
  appendTyping();

  try {
    const res = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message: text }),
    });

    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = data?.detail || `Chat failed with status ${res.status}`;
      throw new Error(detail);
    }

    removeTyping();
    appendMsg("bot", data.answer ?? "(No answer returned)");
  } catch (err) {
    removeTyping();
    showAlert("danger", err.message || "Chat failed.");
  }
}

uploadBtn.addEventListener("click", uploadAndIndex);

resetBtn.addEventListener("click", () => {
  hideAlert();
  fileInput.value = "";
  uploadStatus.textContent = "";
  setSession(null);
  chatMessages.innerHTML = `<div class="chat-hint">Upload documents to create an index, then ask a question here.</div>`;
});

copySessionBtn.addEventListener("click", async () => {
  const s = sessionIdEl.textContent;
  if (!s || s === "—") return;
  await navigator.clipboard.writeText(s);
  showAlert("info", "Session ID copied to clipboard.");
});

chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = chatInput.value.trim();
  if (!text) return;
  chatInput.value = "";
  await sendChatMessage(text);
});

// Restore session_id if you want (handy during local dev)
const saved = localStorage.getItem("multidocchat_session_id");
if (saved) {
  setSession(saved);
}
