import makeWASocket, {
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
  downloadMediaMessage,
} from "@whiskeysockets/baileys";
import { Boom } from "@hapi/boom";
import qrcodeTerminal from "qrcode-terminal";
import QRCode from "qrcode";
import axios from "axios";
import express from "express";
import dotenv from "dotenv";
import fs from "fs";

dotenv.config();

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";
const PORT = parseInt(process.env.PORT || "3000");
const AUTH_DIR = process.env.AUTH_DIR || "auth_info_baileys";
const QR_FILE = process.env.QR_FILE || "/data/qr.txt";
const MY_JID = process.env.MY_WHATSAPP_JID || null; // ex: "5531999999999@s.whatsapp.net"

// System/bot message types to ignore — these cause crypto noise when processed
const IGNORED_MESSAGE_TYPES = new Set([
  "buttonsMessage",
  "templateMessage",
  "listMessage",
  "protocolMessage",
  "reactionMessage",
  "stickerMessage",
  "audioMessage",
  "imageMessage",
  "videoMessage",
  "documentMessage",
  "contactMessage",
  "locationMessage",
  "liveLocationMessage",
  "pollCreationMessage",
  "pollUpdateMessage",
  "callLogMessage",
  "encReactionMessage",
  "editedMessage",
  "keepInChatMessage",
]);

let sock = null;
let isConnecting = false;
let currentQR = null;
let waConnected = false;
let alfredGroupJID = process.env.ALFRED_GROUP_JID || null;
let lastMessageAt = null;
let sessionStartedAt = null;
const recentLogs = [];

// ── Express server ──────────────────────────────────────────────────────────
const app = express();
app.use(express.json());
app.use((_req, res, next) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  next();
});

app.post("/send", async (req, res) => {
  const { to, text } = req.body;
  if (!to || !text) return res.status(400).json({ ok: false, reason: "missing to or text" });
  if (!sock) return res.status(503).json({ ok: false, reason: "not connected" });

  const MAX_ATTEMPTS = 2;
  let lastErr = null;
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    try {
      await sock.sendMessage(to, { text, linkPreview: false });
      return res.json({ ok: true });
    } catch (err) {
      lastErr = err;
      console.error(`[send] attempt ${attempt}/${MAX_ATTEMPTS} failed: ${err.message}`);
      if (attempt < MAX_ATTEMPTS) await sleep(1000 * attempt);
    }
  }
  res.status(500).json({ ok: false, reason: lastErr?.message });
});

app.get("/health", (_req, res) => {
  const uptimeSec = Math.floor(process.uptime());
  const sessionAgeSec = sessionStartedAt
    ? Math.floor((Date.now() - sessionStartedAt) / 1000)
    : null;
  res.json({
    connected: waConnected,
    uptime: uptimeSec,
    last_message_at: lastMessageAt,
    session_age: sessionAgeSec,
    alfred_group: alfredGroupJID,
  });
});

app.get("/logs", (_req, res) => {
  res.json(recentLogs);
});

app.get("/qr", (_req, res) => {
  if (waConnected) return res.json({ connected: true, qr: null });
  if (!currentQR) return res.json({ connected: false, qr: null });
  res.json({ connected: false, qr: currentQR });
});

app.post("/reset", async (_req, res) => {
  console.log("🔄 Reset solicitado — limpando sessão...");
  try {
    await closeSocket();
    sessionStartedAt = null;

    if (fs.existsSync(AUTH_DIR)) {
      fs.rmSync(AUTH_DIR, { recursive: true, force: true });
      console.log("🗑️  auth_info_baileys removido");
    }

    setTimeout(connect, 800);
    res.json({ ok: true });
  } catch (err) {
    console.error("[reset] erro:", err.message);
    res.status(500).json({ ok: false, reason: err.message });
  }
});

app.listen(PORT, () => console.log(`🚀 WhatsApp gateway na porta ${PORT}`));

// ── Helpers ──────────────────────────────────────────────────────────────────
function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function extractText(msg) {
  return (
    msg.message?.conversation ||
    msg.message?.extendedTextMessage?.text ||
    msg.message?.ephemeralMessage?.message?.extendedTextMessage?.text ||
    msg.message?.viewOnceMessage?.message?.extendedTextMessage?.text ||
    ""
  );
}

function getMessageType(msg) {
  if (!msg.message) return null;
  return Object.keys(msg.message).find((k) => k !== "messageContextInfo") || null;
}

async function closeSocket() {
  if (sock) {
    try { sock.ev.removeAllListeners(); } catch {}
    try { sock.ws?.close(); } catch {}
    sock = null;
  }
  waConnected = false;
  currentQR = null;
}

async function discoverAlfredGroup(socket) {
  if (alfredGroupJID) {
    console.log(`📌 Alfred group JID (env): ${alfredGroupJID}`);
    return;
  }
  try {
    const groups = await socket.groupFetchAllParticipating();
    for (const [jid, meta] of Object.entries(groups)) {
      if (meta.subject?.toLowerCase().includes("alfred")) {
        alfredGroupJID = jid;
        console.log(`✅ Grupo alfred encontrado: "${meta.subject}" → ${jid}`);
        return;
      }
    }
    console.warn("⚠️  Grupo 'alfred' não encontrado. Crie o grupo ou defina ALFRED_GROUP_JID no .env");
  } catch (err) {
    console.error("[discover-alfred]", err.message);
  }
}

// ── Baileys connection ───────────────────────────────────────────────────────
async function connect() {
  if (isConnecting) {
    console.log("[connect] já está conectando, pulando chamada duplicada");
    return;
  }
  isConnecting = true;

  try {
    // Reuse existing session — never delete auth dir here
    const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
    const { version } = await fetchLatestBaileysVersion();

    const logger = {
      level: "silent",
      trace: () => {}, debug: () => {}, info: () => {}, warn: () => {},
      error: (...args) => console.error(...args),
      child: () => logger,
    };

    sock = makeWASocket({
      version,
      auth: state,
      logger,
      printQRInTerminal: false,
      syncFullHistory: false,
      markOnlineOnConnect: false,
      generateHighQualityLinkPreview: false,
      // Returning undefined causes Baileys to lose message keys → "Aguardando mensagem".
      // Returning null signals "not found but don't retry" — safer than undefined.
      getMessage: async () => null,
      cachedGroupMetadata: async () => undefined,
      transactionOpts: { maxCommitRetries: 1, delayBetweenTriesMs: 10 },
    });

    sock.ev.on("creds.update", saveCreds);

    sock.ev.on("connection.update", async (update) => {
      const { connection, lastDisconnect, qr } = update;

      if (qr) {
        currentQR = qr;
        waConnected = false;
        console.log("\nEscaneia o QR code (ou veja no dashboard):\n");
        qrcodeTerminal.generate(qr, { small: true });
        try { fs.writeFileSync(QR_FILE, qr); } catch {}
      }

      if (connection === "open") {
        currentQR = null;
        waConnected = true;
        sessionStartedAt = Date.now();
        console.log("✅ WhatsApp conectado!");
        try { fs.unlinkSync(QR_FILE); } catch {}
        await discoverAlfredGroup(sock);
      }

      if (connection === "close") {
        waConnected = false;
        const reason = new Boom(lastDisconnect?.error)?.output?.statusCode;
        if (reason === DisconnectReason.loggedOut) {
          console.error("❌ Deslogado. Delete auth_info_baileys/ e reinicie.");
          process.exit(1);
        }
        console.log(`🔄 Reconectando em 3s (razão: ${reason})...`);
        // Close cleanly before reconnecting to avoid duplicate sockets
        await closeSocket();
        setTimeout(connect, 3000);
      }
    });

    function log(msg) {
      const entry = { ts: new Date().toISOString(), msg };
      recentLogs.push(entry);
      if (recentLogs.length > 100) recentLogs.shift();
      console.log(msg);
    }

    sock.ev.on("messages.upsert", async ({ messages, type }) => {
      log(`[upsert] type=${type} count=${messages.length}`);
      if (type !== "notify") return;

      for (const msg of messages) {
        try {
          const jid = msg.key.remoteJid || "";
          const fromMe = msg.key.fromMe;
          const msgType = getMessageType(msg);

          // Caso especial ANTES do filtro: imageMessage com URL na caption →
          // salva como referência visual (Pedro forwardou um post de IG/etc)
          if (msgType === "imageMessage" && jid.endsWith("@g.us") &&
              (!alfredGroupJID || jid === alfredGroupJID)) {
            const caption = msg.message?.imageMessage?.caption || "";
            const urlMatch = caption.match(/https?:\/\/\S+/);
            if (urlMatch) {
              try {
                const buffer = await downloadMediaMessage(msg, "buffer", {}, { logger });
                const base64 = buffer.toString("base64");
                const mimetype = msg.message.imageMessage.mimetype || "image/jpeg";
                log(`📎 [alfred] imageMessage + URL → ref (${urlMatch[0].slice(0, 60)})`);
                lastMessageAt = new Date().toISOString();
                await axios.post(
                  `${BACKEND_URL}/api/whatsapp/webhook`,
                  {
                    message_id: msg.key.id,
                    from: jid,
                    text: `ref: ${caption}`,
                    image_base64: base64,
                    image_mimetype: mimetype,
                  },
                  { timeout: 20_000 }
                );
              } catch (err) {
                log(`[wa media] erro baixando/enviando: ${err.message}`);
              }
              continue;
            }
          }

          // 1. Skip system/bot message types
          if (msgType && IGNORED_MESSAGE_TYPES.has(msgType)) {
            log(`[wa] ignored: system/bot message type=${msgType} jid=${jid}`);
            continue;
          }

          // 2. Validate JID — skip empty
          if (!jid) {
            log(`[wa] ignored: empty JID`);
            continue;
          }

          // 3. Direct messages: only from MY_JID (or fromMe if MY_JID not set)
          if (!jid.endsWith("@g.us")) {
            if (MY_JID && jid !== MY_JID && !fromMe) {
              log(`[wa] ignored: direct msg from unknown JID ${jid}`);
              continue;
            }
            // Direct messages not in scope for this gateway (group-based workflow)
            log(`[wa] ignored: direct message from ${jid} (not a group)`);
            continue;
          }

          // 4. Group messages: only alfred group
          if (alfredGroupJID && jid !== alfredGroupJID) {
            log(`[wa] ignored: wrong group ${jid} (expected ${alfredGroupJID})`);
            continue;
          }
          if (!alfredGroupJID) {
            log(`[wa] warning: ALFRED_GROUP_JID not set, accepting group ${jid}`);
          }

          // 5. Require text content
          const text = extractText(msg).trim();
          if (!text) {
            log(`[wa] ignored: no text content (type=${msgType}) jid=${jid}`);
            continue;
          }

          lastMessageAt = new Date().toISOString();
          log(`📨 [alfred] "${text}"`);

          await axios.post(
            `${BACKEND_URL}/api/whatsapp/webhook`,
            { message_id: msg.key.id, from: jid, text },
            { timeout: 10_000 }
          );
        } catch (err) {
          log(`[messages.upsert] error: ${err.message}`);
        }
      }
    });
  } finally {
    isConnecting = false;
  }
}

process.on("uncaughtException", async (err) => {
  console.error("[uncaughtException]", err.message);
  // Close the broken socket before reconnecting to avoid duplicate sockets
  // with divergent key state — that's what causes "Aguardando mensagem"
  await closeSocket();
  setTimeout(() => connect().catch(console.error), 3000);
});

process.on("unhandledRejection", (reason) => {
  console.error("[unhandledRejection]", reason);
});

connect().catch(console.error);
