import makeWASocket, {
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
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

let sock = null;
let currentQR = null;
let waConnected = false;
let alfredGroupJID = process.env.ALFRED_GROUP_JID || null;
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
  try {
    await sock.sendMessage(to, { text });
    res.json({ ok: true });
  } catch (err) {
    console.error("[send] error:", err.message);
    res.status(500).json({ ok: false, reason: err.message });
  }
});

app.get("/health", (_req, res) => {
  res.json({ ok: true, connected: waConnected, alfred_group: alfredGroupJID });
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
    if (sock) {
      try { sock.ws?.close(); } catch {}
      sock = null;
    }
    waConnected = false;
    currentQR = null;
    alfredGroupJID = process.env.ALFRED_GROUP_JID || null;

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
function extractText(msg) {
  return (
    msg.message?.conversation ||
    msg.message?.extendedTextMessage?.text ||
    msg.message?.ephemeralMessage?.message?.extendedTextMessage?.text ||
    msg.message?.viewOnceMessage?.message?.extendedTextMessage?.text ||
    ""
  );
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
    getMessage: async () => undefined,
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
        const text = extractText(msg).trim();
        const jid = msg.key.remoteJid || "";
        const fromMe = msg.key.fromMe;
        const participant = msg.key.participant || "";

        if (jid.endsWith("@g.us")) {
          const tag = alfredGroupJID
            ? (jid === alfredGroupJID ? "alfred" : "other-group")
            : "any-group";
          log(`[wa] fromMe=${fromMe} participant=${participant} group=${tag} hasText=${!!text} text="${text.slice(0, 60)}"`);
        }

        if (!text) continue;
        if (!jid) continue;

        // Only messages from alfred group
        if (!jid.endsWith("@g.us")) continue;
        if (alfredGroupJID && jid !== alfredGroupJID) {
          log(`[wa] skipped: not alfred group (${jid})`);
          continue;
        }

        // alfred group is Pedro's private task inbox — accept all messages

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
}

process.on("uncaughtException", (err) => {
  console.error("[uncaughtException]", err.message);
  // Crypto/noise errors from Baileys during reconnect — restart connection instead of crashing
  setTimeout(() => connect().catch(console.error), 3000);
});

process.on("unhandledRejection", (reason) => {
  console.error("[unhandledRejection]", reason);
});

connect().catch(console.error);
