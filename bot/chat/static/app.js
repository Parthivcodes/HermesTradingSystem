document.addEventListener("DOMContentLoaded", () => {
  const chatForm = document.getElementById("chatForm");
  const chatInput = document.getElementById("chatInput");
  const chatMessages = document.getElementById("chatMessages");
  const sendBtn = document.getElementById("sendBtn");
  const connectionStatus = document.getElementById("connectionStatus");

  const modeValue = document.getElementById("modeValue");
  const safetyValue = document.getElementById("safetyValue");
  const equityValue = document.getElementById("equityValue");
  const positionsValue = document.getElementById("positionsValue");

  // Fetch initial status
  async function refreshStatus() {
    try {
      const res = await fetch("/api/status");
      if (res.ok) {
        const data = await res.json();
        modeValue.textContent = (data.mode || "PAPER").toUpperCase();
        safetyValue.textContent = data.live_trading ? "LIVE ACTIVE" : "DISABLED";
        safetyValue.style.color = data.live_trading ? "var(--accent-red)" : "var(--accent-amber)";
        equityValue.textContent = "$" + Number(data.equity || 100000).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        positionsValue.textContent = `${data.open_positions || 0} Active`;
      }
    } catch (e) {
      console.warn("Status poll error:", e);
    }
  }

  refreshStatus();
  setInterval(refreshStatus, 10000);

  function appendMessage(text, isUser = false) {
    const bubble = document.createElement("div");
    bubble.className = `message-bubble ${isUser ? "user-msg" : "bot-msg"}`;

    const header = document.createElement("div");
    header.className = "msg-header";
    const author = document.createElement("span");
    author.className = "msg-author";
    author.textContent = isUser ? "TRADER" : "APEX ENGINE";

    const time = document.createElement("span");
    time.className = "msg-time";
    time.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

    header.appendChild(author);
    header.appendChild(time);

    const body = document.createElement("div");
    body.className = "msg-body";
    body.textContent = text;

    bubble.appendChild(header);
    bubble.appendChild(body);
    chatMessages.appendChild(bubble);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  async function executeCommand(cmdText) {
    if (!cmdText.trim()) return;

    appendMessage(cmdText, true);
    chatInput.value = "";
    chatInput.disabled = true;
    sendBtn.disabled = true;
    connectionStatus.textContent = "● Processing Strategy...";
    connectionStatus.style.color = "var(--accent-cyan)";

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: cmdText })
      });

      if (!res.ok) {
        const err = await res.json();
        appendMessage(`Error: ${err.detail || "Command execution failed"}`);
      } else {
        const data = await res.json();
        appendMessage(data.reply);
        refreshStatus();
      }
    } catch (err) {
      appendMessage(`Network / API Error: ${err.message}`);
    } finally {
      chatInput.disabled = false;
      sendBtn.disabled = false;
      chatInput.focus();
      connectionStatus.textContent = "● Engine Ready";
      connectionStatus.style.color = "var(--accent-green)";
    }
  }

  // Handle Form Submit
  chatForm.addEventListener("submit", (e) => {
    e.preventDefault();
    executeCommand(chatInput.value);
  });

  // Handle Quick Command Buttons
  document.querySelectorAll(".cmd-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const cmd = btn.getAttribute("data-cmd");
      if (cmd) {
        executeCommand(cmd);
      }
    });
  });
});
