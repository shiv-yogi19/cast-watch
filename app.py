import os
import json
import random
import string
import time
import re

from flask import Flask, Response, request
from flask_sock import Sock

app = Flask(__name__)
sock = Sock(app)

rooms = {}
ROOM_CODE_RE = re.compile(r"^\d{6}$")
ROOM_TTL_SECONDS = 6 * 60 * 60


def build_ice_servers():
    servers = []
    stun_env = os.environ.get(
        "STUN_SERVERS",
        "stun:stun.l.google.com:19302,stun:stun1.l.google.com:19302",
    )
    for url in [u.strip() for u in stun_env.split(",") if u.strip()]:
        servers.append({"urls": url})
    turn_server = os.environ.get("TURN_SERVER")
    turn_username = os.environ.get("TURN_USERNAME")
    turn_password = os.environ.get("TURN_PASSWORD")
    if turn_server and turn_username and turn_password:
        servers.append(
            {"urls": turn_server, "username": turn_username, "credential": turn_password}
        )
    return servers


ICE_SERVERS = build_ice_servers()


def new_room():
    return {"cast": None, "watch": None, "created": time.time(), "has_video": False}


def cleanup_rooms():
    now = time.time()
    stale = [
        rid
        for rid, r in rooms.items()
        if r["cast"] is None and r["watch"] is None and now - r["created"] > ROOM_TTL_SECONDS
    ]
    for rid in stale:
        rooms.pop(rid, None)


def new_room_id():
    cleanup_rooms()
    while True:
        candidate = "".join(random.choices(string.digits, k=6))
        if candidate not in rooms:
            return candidate


def safe_send(ws, payload):
    if ws is None:
        return
    try:
        ws.send(json.dumps(payload))
    except Exception:
        pass


@sock.route("/ws")
def websocket(ws):
    conn = {"rid": None, "role": None}

    def teardown():
        rid = conn["rid"]
        role = conn["role"]
        if not rid or rid not in rooms:
            return
        room = rooms[rid]
        if role == "cast" and room["cast"] is ws:
            room["cast"] = None
            safe_send(room["watch"], {"t": "peer_left", "role": "cast"})
        elif role == "watch" and room["watch"] is ws:
            room["watch"] = None
            safe_send(room["cast"], {"t": "peer_left", "role": "watch"})
        if room["cast"] is None and room["watch"] is None:
            rooms.pop(rid, None)

    try:
        while True:
            raw = ws.receive()
            if raw is None:
                break

            try:
                msg = json.loads(raw)
            except Exception:
                safe_send(ws, {"t": "error", "code": "bad_message", "msg": "Invalid message"})
                continue

            if not isinstance(msg, dict):
                continue

            t = msg.get("t")

            if t == "ping":
                safe_send(ws, {"t": "pong"})
                continue

            if t == "create":
                if conn["rid"]:
                    safe_send(ws, {"t": "error", "code": "already_in_room", "msg": "Already connected to a room"})
                    continue
                rid = new_room_id()
                rooms[rid] = new_room()
                rooms[rid]["cast"] = ws
                conn["rid"] = rid
                conn["role"] = "cast"
                safe_send(ws, {"t": "room", "id": rid, "iceServers": ICE_SERVERS})
                continue

            if t == "join":
                rid = str(msg.get("id") or "").strip()
                if not ROOM_CODE_RE.match(rid):
                    safe_send(ws, {"t": "error", "code": "invalid_code", "msg": "Enter a valid 6-digit code"})
                    continue
                room = rooms.get(rid)
                if not room or room["cast"] is None:
                    safe_send(ws, {"t": "error", "code": "room_not_found", "msg": "Room not found or CAST is offline"})
                    continue
                old_watch = room["watch"]
                if old_watch is not None and old_watch is not ws:
                    safe_send(old_watch, {"t": "kicked", "msg": "Connected from another device"})
                    try:
                        old_watch.close()
                    except Exception:
                        pass
                room["watch"] = ws
                conn["rid"] = rid
                conn["role"] = "watch"
                safe_send(ws, {"t": "ok", "id": rid, "has_video": room["has_video"], "iceServers": ICE_SERVERS})
                safe_send(room["cast"], {"t": "watch_joined"})
                continue

            rid = conn["rid"]
            role = conn["role"]
            if not rid or rid not in rooms:
                safe_send(ws, {"t": "error", "code": "not_in_room", "msg": "Not connected to a room"})
                continue
            room = rooms[rid]

            if t == "video_ready":
                if role == "cast":
                    room["has_video"] = True
                    safe_send(room["watch"], {"t": "video_ready"})
                continue

            if t in ("offer", "answer", "ice"):
                target = room["watch"] if role == "cast" else room["cast"]
                if target is None:
                    safe_send(ws, {"t": "error", "code": "peer_offline", "msg": "The other device is not connected"})
                    continue
                safe_send(target, msg)
                continue

            if t == "control":
                if role == "watch":
                    safe_send(room["cast"], msg)
                continue

            if t == "state":
                if role == "cast":
                    safe_send(room["watch"], msg)
                continue

            if t == "leave":
                break

    except Exception:
        pass
    finally:
        teardown()


HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Cast &amp; Watch</title>
<link rel="icon" href="data:,">
<style>
:root{
  --bg:#06070b;
  --surface:rgba(19,22,31,.72);
  --surface2:rgba(255,255,255,.04);
  --border:rgba(255,255,255,.09);
  --text:#f4f6fb;
  --muted:#8b93a7;
  --accent:#7c5cff;
  --accent2:#38bdf8;
  --danger:#ff5c7a;
  --success:#22d97a;
  --radius:22px;
}
*{box-sizing:border-box}
html,body{height:100%}
body{
  margin:0;
  min-height:100%;
  background:var(--bg);
  color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif;
  overflow-x:hidden;
  padding-top:env(safe-area-inset-top,0px);
  padding-bottom:env(safe-area-inset-bottom,0px);
}
.bg{position:fixed;inset:0;z-index:-2;background:
  radial-gradient(circle at 15% 20%, rgba(124,92,255,.25), transparent 45%),
  radial-gradient(circle at 85% 15%, rgba(56,189,248,.18), transparent 45%),
  radial-gradient(circle at 50% 90%, rgba(124,92,255,.15), transparent 50%),
  #06070b;
}
.blob{position:fixed;border-radius:50%;filter:blur(70px);opacity:.5;z-index:-1;mix-blend-mode:screen;animation:drift 22s ease-in-out infinite alternate}
.b1{width:340px;height:340px;background:#7c5cff;top:-80px;left:-100px;animation-delay:0s}
.b2{width:280px;height:280px;background:#38bdf8;bottom:-60px;right:-80px;animation-delay:3s}
.b3{width:220px;height:220px;background:#22d97a;top:40%;right:10%;opacity:.25;animation-delay:6s}
@keyframes drift{
  0%{transform:translate(0,0) scale(1)}
  100%{transform:translate(30px,-40px) scale(1.15)}
}
.brand{
  position:fixed;top:14px;left:18px;z-index:5;
  font-weight:800;font-size:14px;letter-spacing:.5px;
  background:linear-gradient(90deg,#7c5cff,#38bdf8,#7c5cff);
  background-size:200% auto;
  -webkit-background-clip:text;background-clip:text;color:transparent;
  animation:shimmer 5s linear infinite;
  display:flex;align-items:center;gap:6px;
  user-select:none;pointer-events:none;
}
.brand svg{width:16px;height:16px}
@keyframes shimmer{
  0%{background-position:0% center}
  100%{background-position:200% center}
}
main{
  min-height:100vh;
  min-height:100dvh;
  display:grid;
  place-items:center;
  padding:64px 16px 24px;
}
.wrap{width:min(760px,100%)}
.card{
  background:var(--surface);
  border:1px solid var(--border);
  border-radius:var(--radius);
  padding:26px;
  backdrop-filter:blur(22px);
  -webkit-backdrop-filter:blur(22px);
  box-shadow:0 20px 60px rgba(0,0,0,.45);
}
.hidden{display:none !important}
h1{text-align:center;margin:2px 0 6px;font-size:30px;font-weight:800;letter-spacing:-.5px}
.subtitle{color:var(--muted);text-align:center;margin:0 0 28px;font-size:15px}
.modes{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.mode-btn{
  border:1px solid var(--border);
  border-radius:18px;
  padding:26px 16px;
  background:var(--surface2);
  color:var(--text);
  cursor:pointer;
  display:flex;flex-direction:column;align-items:center;gap:10px;
  transition:transform .18s ease, border-color .18s ease, background .18s ease;
  font-size:16px;font-weight:700;
}
.mode-btn .ic{width:34px;height:34px}
.mode-btn:active{transform:scale(.97)}
.mode-btn:hover{border-color:var(--accent);background:rgba(124,92,255,.1)}
.mode-btn.primary{background:linear-gradient(135deg,#7c5cff,#5a3fe0);border-color:transparent}
.mode-btn small{color:var(--muted);font-weight:400;font-size:12.5px}
.mode-btn.primary small{color:rgba(255,255,255,.75)}
.back{
  background:none;border:0;color:var(--muted);cursor:pointer;font-size:14px;
  padding:6px 0;margin-bottom:10px;display:flex;align-items:center;gap:6px;
}
.back:hover{color:var(--text)}
h2{margin:0 0 18px;font-size:22px;font-weight:800;display:flex;align-items:center;gap:8px}
.badge{
  display:inline-flex;align-items:center;gap:7px;
  padding:7px 13px;border-radius:999px;font-size:13px;font-weight:600;
  border:1px solid var(--border);background:var(--surface2);color:var(--muted);
}
.badge .dot{width:8px;height:8px;border-radius:50%;background:var(--muted)}
.badge.idle .dot{background:var(--muted)}
.badge.connecting .dot{background:#facc15;animation:pulse 1.1s ease-in-out infinite}
.badge.ok .dot{background:var(--success);box-shadow:0 0 10px var(--success);animation:pulse 1.4s ease-in-out infinite}
.badge.err .dot{background:var(--danger)}
@keyframes pulse{
  0%,100%{opacity:1;transform:scale(1)}
  50%{opacity:.45;transform:scale(1.3)}
}
.room-code-card{
  margin:20px 0;
  border:1px dashed rgba(124,92,255,.5);
  border-radius:18px;
  padding:22px;
  text-align:center;
  background:radial-gradient(circle at 50% 0%, rgba(124,92,255,.14), transparent 70%);
  position:relative;
}
.room-code-card .label{color:var(--muted);font-size:12.5px;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:10px}
.code{
  font-size:44px;font-weight:800;letter-spacing:10px;
  background:linear-gradient(90deg,#fff,#cfd6ff,#fff);
  background-size:200% auto;-webkit-background-clip:text;background-clip:text;color:transparent;
  animation:shimmer 4s linear infinite;
}
.copy-btn{
  margin-top:14px;border:1px solid var(--border);background:var(--surface2);color:var(--text);
  padding:9px 18px;border-radius:12px;font-size:13.5px;font-weight:600;cursor:pointer;
}
.copy-btn:active{transform:scale(.96)}
.status-row{display:flex;flex-wrap:wrap;gap:10px;justify-content:center;margin-top:14px}
.pick{
  display:flex;align-items:center;justify-content:center;gap:10px;
  border:1.5px dashed rgba(255,255,255,.22);border-radius:16px;
  padding:20px;cursor:pointer;margin-top:18px;color:var(--muted);font-weight:600;
  transition:border-color .18s ease, color .18s ease;
}
.pick:hover{border-color:var(--accent);color:var(--text)}
.pick input{display:none}
.filename{text-align:center;color:var(--text);font-size:13.5px;margin-top:10px;word-break:break-all}
.error-text{color:var(--danger);text-align:center;font-size:13.5px;margin-top:10px}
.player{
  position:relative;margin-top:20px;border-radius:18px;overflow:hidden;background:#000;
  box-shadow:0 15px 45px rgba(0,0,0,.5);
}
video{width:100%;max-height:62vh;display:block;background:#000}
.player .overlay-tap{
  position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
  background:rgba(0,0,0,.45);cursor:pointer;
}
.overlay-tap button{
  background:#fff;color:#06070b;border:0;border-radius:14px;padding:14px 22px;font-weight:800;font-size:15px;cursor:pointer;
}
.buffering{
  position:absolute;top:14px;right:14px;width:26px;height:26px;border-radius:50%;
  border:3px solid rgba(255,255,255,.25);border-top-color:#fff;animation:spin .8s linear infinite;
}
@keyframes spin{to{transform:rotate(360deg)}}
.controls{
  display:flex;align-items:center;gap:8px;margin-top:12px;flex-wrap:wrap;
  background:var(--surface2);border:1px solid var(--border);border-radius:16px;padding:10px 12px;
}
.controls button{
  background:rgba(255,255,255,.06);color:var(--text);border:1px solid var(--border);
  border-radius:12px;padding:10px 13px;font-size:16px;cursor:pointer;flex-shrink:0;
}
.controls button:active{transform:scale(.94)}
.seek{flex:1 1 140px;min-width:100px;accent-color:var(--accent)}
.vol{width:90px;accent-color:var(--accent)}
.time{font-size:12.5px;color:var(--muted);min-width:84px;text-align:center;flex-shrink:0}
.hint{color:var(--muted);text-align:center;font-size:12.5px;margin-top:14px}
.join-form{display:flex;flex-direction:column;gap:12px;margin-top:6px}
.input{
  width:100%;padding:16px;border-radius:14px;border:1px solid var(--border);
  background:var(--surface2);color:var(--text);font-size:22px;text-align:center;
  letter-spacing:6px;outline:0;font-weight:700;
}
.input:focus{border-color:var(--accent)}
.primary-btn{
  border:0;border-radius:14px;padding:15px;font-size:16px;font-weight:800;
  background:linear-gradient(135deg,#7c5cff,#5a3fe0);color:#fff;cursor:pointer;
}
.primary-btn:active{transform:scale(.98)}
.status-line{text-align:center;color:var(--muted);font-size:13.5px;margin-top:14px}
@media(max-width:600px){
  .modes{grid-template-columns:1fr}
  .code{font-size:34px;letter-spacing:7px}
  .vol{width:60px}
}
</style>
</head>
<body>
<div class="bg"></div>
<div class="blob b1"></div>
<div class="blob b2"></div>
<div class="blob b3"></div>
<div class="brand">
  <svg viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="2"/></svg>
  Shiv Yogi
</div>

<main>
<div class="wrap">

<section class="card" id="home">
  <h1>🎬 Cast &amp; Watch</h1>
  <p class="subtitle">Stream locally. Watch anywhere.</p>
  <div class="modes">
    <button class="mode-btn primary" id="castModeBtn">
      <svg class="ic" viewBox="0 0 24 24" fill="none"><path d="M2 8V5a1 1 0 011-1h18a1 1 0 011 1v14a1 1 0 01-1 1h-7" stroke="#fff" stroke-width="2" stroke-linecap="round"/><path d="M2 12a7 7 0 017 7M2 16a3 3 0 013 3M2 20h.01" stroke="#fff" stroke-width="2" stroke-linecap="round"/></svg>
      CAST
      <small>Stream a local video</small>
    </button>
    <button class="mode-btn" id="watchModeBtn">
      <svg class="ic" viewBox="0 0 24 24" fill="none"><rect x="2" y="4" width="20" height="14" rx="2" stroke="currentColor" stroke-width="2"/><path d="M8 21h8" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
      WATCH
      <small>Join with a code</small>
    </button>
  </div>
</section>

<section class="card hidden" id="castScreen">
  <button class="back" id="castBackBtn">&larr; Home</button>
  <h2>📡 Cast</h2>
  <div class="status-row">
    <span class="badge idle" id="castConnBadge"><span class="dot"></span><span class="txt">Connecting to server…</span></span>
    <span class="badge idle" id="castWatchBadge"><span class="dot"></span><span class="txt">Waiting for WATCH device…</span></span>
  </div>

  <div class="room-code-card">
    <div class="label">Cast Code</div>
    <div class="code" id="roomCode">------</div>
    <div><button class="copy-btn" id="copyBtn">Copy code</button></div>
  </div>

  <label class="pick" id="pickLabel">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none"><path d="M12 16V4m0 0L7 9m5-5l5 5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M4 16v3a2 2 0 002 2h12a2 2 0 002-2v-3" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
    Select a video to cast
    <input id="fileInput" type="file" accept="video/*">
  </label>
  <div class="filename hidden" id="castFileName"></div>
  <div class="error-text hidden" id="castFileError"></div>

  <div class="player hidden" id="castPlayer">
    <video id="castVideo" controls playsinline></video>
  </div>
  <div class="hint">The video file never leaves this device — it streams directly to WATCH over WebRTC.</div>
</section>

<section class="card hidden" id="watchScreen">
  <button class="back" id="watchBackBtn">&larr; Home</button>
  <h2>📺 Watch</h2>

  <div id="watchJoin" class="join-form">
    <input class="input" id="roomInput" maxlength="6" inputmode="numeric" placeholder="000000">
    <button class="primary-btn" id="joinBtn">Connect</button>
  </div>
  <div class="status-line" id="watchStatus">Enter the 6-digit code from CAST</div>

  <div class="player hidden" id="watchPlayer">
    <video id="watchVideo" playsinline></video>
    <div class="overlay-tap hidden" id="watchTapOverlay"><button id="watchTapBtn">Tap to play ▶</button></div>
    <div class="buffering hidden" id="watchBuffering"></div>
  </div>
  <div class="controls hidden" id="watchControls">
    <button id="watchBackTen" title="Back 10s">↶10</button>
    <button id="watchPlayBtn" title="Play/Pause"><span id="watchPlayIcon">▶</span></button>
    <button id="watchFwdTen" title="Forward 10s">10↷</button>
    <input class="seek" id="watchSeek" type="range" min="0" max="100" value="0">
    <input class="vol" id="watchVol" type="range" min="0" max="1" step="0.01" value="1">
    <span class="time" id="watchTime">--:-- / --:--</span>
    <button id="watchFullscreenBtn" title="Fullscreen">⛶</button>
  </div>
</section>

</div>
</main>

<script>
(function(){
"use strict";

var els = {
  home: document.getElementById("home"),
  castScreen: document.getElementById("castScreen"),
  watchScreen: document.getElementById("watchScreen"),
  castModeBtn: document.getElementById("castModeBtn"),
  watchModeBtn: document.getElementById("watchModeBtn"),
  castBackBtn: document.getElementById("castBackBtn"),
  watchBackBtn: document.getElementById("watchBackBtn"),
  castConnBadge: document.getElementById("castConnBadge"),
  castWatchBadge: document.getElementById("castWatchBadge"),
  roomCode: document.getElementById("roomCode"),
  copyBtn: document.getElementById("copyBtn"),
  pickLabel: document.getElementById("pickLabel"),
  fileInput: document.getElementById("fileInput"),
  castFileName: document.getElementById("castFileName"),
  castFileError: document.getElementById("castFileError"),
  castPlayer: document.getElementById("castPlayer"),
  castVideo: document.getElementById("castVideo"),
  watchJoin: document.getElementById("watchJoin"),
  roomInput: document.getElementById("roomInput"),
  joinBtn: document.getElementById("joinBtn"),
  watchStatus: document.getElementById("watchStatus"),
  watchPlayer: document.getElementById("watchPlayer"),
  watchVideo: document.getElementById("watchVideo"),
  watchTapOverlay: document.getElementById("watchTapOverlay"),
  watchTapBtn: document.getElementById("watchTapBtn"),
  watchBuffering: document.getElementById("watchBuffering"),
  watchControls: document.getElementById("watchControls"),
  watchBackTen: document.getElementById("watchBackTen"),
  watchPlayBtn: document.getElementById("watchPlayBtn"),
  watchPlayIcon: document.getElementById("watchPlayIcon"),
  watchFwdTen: document.getElementById("watchFwdTen"),
  watchSeek: document.getElementById("watchSeek"),
  watchVol: document.getElementById("watchVol"),
  watchTime: document.getElementById("watchTime"),
  watchFullscreenBtn: document.getElementById("watchFullscreenBtn")
};

var DEFAULT_ICE = [{urls:"stun:stun.l.google.com:19302"},{urls:"stun:stun1.l.google.com:19302"}];

var cast = {
  ws:null, pc:null, rid:null, stream:null,
  watchConnected:false, hasVideo:false,
  pendingCandidates:[], remoteSet:false,
  iceServers:DEFAULT_ICE, lastStateSent:0, negotiateTimer:null
};

var watch = {
  ws:null, pc:null, rid:null, connected:false,
  pendingCandidates:[], remoteSet:false,
  iceServers:DEFAULT_ICE, seeking:false
};

function wsUrl(){
  return (location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws";
}

function showScreen(name){
  els.home.classList.toggle("hidden", name !== "home");
  els.castScreen.classList.toggle("hidden", name !== "cast");
  els.watchScreen.classList.toggle("hidden", name !== "watch");
}

function setBadge(el, cls, text){
  el.className = "badge " + cls;
  el.querySelector(".txt").textContent = text;
}

function formatTime(sec){
  if (!isFinite(sec) || sec < 0) return "--:--";
  var m = Math.floor(sec / 60);
  var s = Math.floor(sec % 60);
  return m + ":" + (s < 10 ? "0" : "") + s;
}

function startPing(ws){
  var iv = setInterval(function(){
    if (ws.readyState === 1) {
      try { ws.send(JSON.stringify({t:"ping"})); } catch(e){}
    } else {
      clearInterval(iv);
    }
  }, 20000);
}

function flushPending(peer){
  if (!peer.pc) { peer.pendingCandidates = []; return; }
  peer.pendingCandidates.forEach(function(c){
    peer.pc.addIceCandidate(c).catch(function(){});
  });
  peer.pendingCandidates = [];
}

function handleIce(peer, candidate){
  if (!candidate) return;
  if (peer.pc && peer.remoteSet) {
    peer.pc.addIceCandidate(candidate).catch(function(){});
  } else {
    peer.pendingCandidates.push(candidate);
  }
}

/* ---------------- CAST ---------------- */

function sendCastMsg(o){
  if (cast.ws && cast.ws.readyState === 1) cast.ws.send(JSON.stringify(o));
}

function startCast(){
  setBadge(els.castConnBadge, "connecting", "Connecting to server…");
  cast.ws = new WebSocket(wsUrl());
  cast.ws.onopen = function(){ sendCastMsg({t:"create"}); };
  cast.ws.onmessage = handleCastMessage;
  cast.ws.onclose = function(){ setBadge(els.castConnBadge, "err", "Disconnected from server"); };
  cast.ws.onerror = function(){};
  startPing(cast.ws);
}

function handleCastMessage(evt){
  var m;
  try { m = JSON.parse(evt.data); } catch(e){ return; }

  if (m.t === "room") {
    cast.rid = m.id;
    if (m.iceServers && m.iceServers.length) cast.iceServers = m.iceServers;
    els.roomCode.textContent = m.id;
    setBadge(els.castConnBadge, "ok", "Room ready");
  } else if (m.t === "watch_joined") {
    cast.watchConnected = true;
    setBadge(els.castWatchBadge, "ok", "🟢 WATCH connected");
    negotiateCast();
  } else if (m.t === "peer_left" && m.role === "watch") {
    cast.watchConnected = false;
    setBadge(els.castWatchBadge, "idle", "Waiting for WATCH device…");
    teardownCastPC();
  } else if (m.t === "answer") {
    if (cast.pc) {
      cast.pc.setRemoteDescription(m.sdp).then(function(){
        cast.remoteSet = true;
        flushPending(cast);
      }).catch(function(){
        setBadge(els.castWatchBadge, "err", "Connection failed");
      });
    }
  } else if (m.t === "ice") {
    handleIce(cast, m.candidate);
  } else if (m.t === "control") {
    applyControlToCastVideo(m.c, m.v);
  } else if (m.t === "error") {
    setBadge(els.castConnBadge, "err", m.msg || "Server error");
  }
}

function teardownCastPC(){
  if (cast.negotiateTimer) { clearTimeout(cast.negotiateTimer); cast.negotiateTimer = null; }
  if (cast.pc) {
    try { cast.pc.close(); } catch(e){}
    cast.pc = null;
  }
  cast.remoteSet = false;
  cast.pendingCandidates = [];
}

function negotiateCast(){
  if (!cast.stream || !cast.watchConnected) return;
  teardownCastPC();
  cast.pc = new RTCPeerConnection({iceServers: cast.iceServers});
  cast.stream.getTracks().forEach(function(track){ cast.pc.addTrack(track, cast.stream); });
  cast.pc.onicecandidate = function(e){
    if (e.candidate) sendCastMsg({t:"ice", candidate: e.candidate});
  };
  cast.pc.onconnectionstatechange = function(){
    var s = cast.pc ? cast.pc.connectionState : "closed";
    if (s === "connected") setBadge(els.castWatchBadge, "ok", "🟢 Streaming");
    else if (s === "failed" || s === "disconnected") setBadge(els.castWatchBadge, "err", "Connection " + s);
    else if (s === "connecting") setBadge(els.castWatchBadge, "connecting", "Connecting stream…");
  };
  cast.negotiateTimer = setTimeout(function(){
    if (cast.pc && cast.pc.connectionState !== "connected") {
      setBadge(els.castWatchBadge, "err", "Still connecting — a TURN server may be required on this network");
    }
  }, 15000);
  cast.pc.createOffer().then(function(offer){
    return cast.pc.setLocalDescription(offer).then(function(){
      sendCastMsg({t:"offer", sdp: cast.pc.localDescription});
    });
  }).catch(function(){
    setBadge(els.castWatchBadge, "err", "Failed to start stream");
  });
}

function applyControlToCastVideo(c, v){
  var vid = els.castVideo;
  if (!vid) return;
  if (c === "play") { if (vid.paused) vid.play().catch(function(){}); else vid.pause(); }
  else if (c === "back") { vid.currentTime = Math.max(0, vid.currentTime - 10); }
  else if (c === "fwd") { vid.currentTime = Math.min(vid.duration || 0, vid.currentTime + 10); }
  else if (c === "seek") { if (vid.duration) vid.currentTime = (Number(v) / 100) * vid.duration; }
  else if (c === "volume") { vid.volume = Number(v); }
}

function sendState(type){
  var vid = els.castVideo;
  if (!vid || !cast.watchConnected) return;
  sendCastMsg({
    t:"state", type:type,
    paused: vid.paused,
    currentTime: vid.currentTime || 0,
    duration: isFinite(vid.duration) ? vid.duration : 0,
    volume: vid.volume,
    buffering: vid.readyState < 3
  });
}

function bindCastVideoEvents(vid){
  vid.addEventListener("play", function(){ sendState("play"); });
  vid.addEventListener("pause", function(){ sendState("pause"); });
  vid.addEventListener("seeked", function(){ sendState("seek"); });
  vid.addEventListener("volumechange", function(){ sendState("volume"); });
  vid.addEventListener("loadedmetadata", function(){ sendState("meta"); });
  vid.addEventListener("waiting", function(){ sendState("buffering"); });
  vid.addEventListener("playing", function(){ sendState("sync"); });
  vid.addEventListener("timeupdate", function(){
    var now = Date.now();
    if (now - cast.lastStateSent > 1000) { cast.lastStateSent = now; sendState("sync"); }
  });
}

function selectFile(file){
  if (!file) return;
  var vid = els.castVideo;
  els.castFileError.classList.add("hidden");
  if (!(vid.captureStream || vid.mozCaptureStream)) {
    els.castFileError.textContent = "This browser can't capture video for streaming. Try a recent Chrome, Edge, or Firefox.";
    els.castFileError.classList.remove("hidden");
    return;
  }
  var url = URL.createObjectURL(file);
  vid.src = url;
  els.castPlayer.classList.remove("hidden");
  els.castFileName.textContent = file.name;
  els.castFileName.classList.remove("hidden");
  vid.onloadedmetadata = function(){
    try {
      cast.stream = vid.captureStream ? vid.captureStream() : vid.mozCaptureStream();
    } catch(e) {
      els.castFileError.textContent = "Could not capture this video for streaming.";
      els.castFileError.classList.remove("hidden");
      return;
    }
    cast.hasVideo = true;
    bindCastVideoEvents(vid);
    sendCastMsg({t:"video_ready"});
    negotiateCast();
  };
}

els.castModeBtn.onclick = function(){ showScreen("cast"); startCast(); };
els.castBackBtn.onclick = function(){ location.reload(); };
els.fileInput.onchange = function(e){ selectFile(e.target.files[0]); };
els.copyBtn.onclick = function(){
  if (!cast.rid) return;
  var done = function(){
    var orig = els.copyBtn.textContent;
    els.copyBtn.textContent = "Copied ✓";
    setTimeout(function(){ els.copyBtn.textContent = orig; }, 1400);
  };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(cast.rid).then(done).catch(function(){});
  } else {
    done();
  }
};

/* ---------------- WATCH ---------------- */

function sendWatchMsg(o){
  if (watch.ws && watch.ws.readyState === 1) watch.ws.send(JSON.stringify(o));
}

function teardownWatchPC(){
  if (watch.pc) {
    try { watch.pc.close(); } catch(e){}
    watch.pc = null;
  }
  watch.remoteSet = false;
  watch.pendingCandidates = [];
}

function resetWatchUi(){
  els.watchJoin.classList.remove("hidden");
  els.watchPlayer.classList.add("hidden");
  els.watchControls.classList.add("hidden");
  els.watchTapOverlay.classList.add("hidden");
  els.watchVideo.srcObject = null;
  watch.connected = false;
}

function joinRoom(code){
  if (!/^\d{6}$/.test(code)) {
    els.watchStatus.textContent = "Enter a valid 6-digit code";
    return;
  }
  teardownWatchPC();
  if (watch.ws) { try { watch.ws.close(); } catch(e){} }
  watch.ws = new WebSocket(wsUrl());
  watch.ws.onopen = function(){
    sendWatchMsg({t:"join", id: code});
    els.watchStatus.textContent = "Connecting to CAST…";
  };
  watch.ws.onmessage = handleWatchMessage;
  watch.ws.onclose = function(){
    if (watch.connected) {
      els.watchStatus.textContent = "Connection lost";
      resetWatchUi();
    }
  };
  watch.ws.onerror = function(){};
  startPing(watch.ws);
}

function handleWatchMessage(evt){
  var m;
  try { m = JSON.parse(evt.data); } catch(e){ return; }

  if (m.t === "ok") {
    watch.rid = m.id;
    watch.connected = true;
    if (m.iceServers && m.iceServers.length) watch.iceServers = m.iceServers;
    els.watchJoin.classList.add("hidden");
    els.watchStatus.textContent = m.has_video ? "CAST is ready — connecting stream…" : "🟢 Connected — waiting for CAST to choose a video";
  } else if (m.t === "offer") {
    handleOffer(m.sdp);
  } else if (m.t === "ice") {
    handleIce(watch, m.candidate);
  } else if (m.t === "peer_left" && m.role === "cast") {
    els.watchStatus.textContent = "CAST disconnected";
    teardownWatchPC();
    resetWatchUi();
  } else if (m.t === "video_ready") {
    els.watchStatus.textContent = "CAST selected a video — connecting stream…";
  } else if (m.t === "state") {
    applyRemoteState(m);
  } else if (m.t === "error") {
    els.watchStatus.textContent = m.msg || "Something went wrong";
  } else if (m.t === "kicked") {
    els.watchStatus.textContent = "This room is now connected from another device";
    teardownWatchPC();
    resetWatchUi();
  }
}

function handleOffer(sdp){
  teardownWatchPC();
  watch.pc = new RTCPeerConnection({iceServers: watch.iceServers});
  watch.pc.onicecandidate = function(e){
    if (e.candidate) sendWatchMsg({t:"ice", candidate: e.candidate});
  };
  watch.pc.onconnectionstatechange = function(){
    var s = watch.pc ? watch.pc.connectionState : "closed";
    if (s === "connected") els.watchStatus.textContent = "🟢 Connected";
    else if (s === "failed" || s === "disconnected") els.watchStatus.textContent = "Connection " + s;
    else if (s === "connecting") els.watchStatus.textContent = "Connecting to CAST…";
  };
  watch.pc.ontrack = function(e){
  var video = els.watchVideo;

  video.autoplay = true;
  video.playsInline = true;
  video.preload = "auto";
  video.srcObject = e.streams[0];

  els.watchPlayer.classList.remove("hidden");
  els.watchControls.classList.remove("hidden");

  attemptAutoplay();
}watch.pc.ontrack = function(e){
  var video = els.watchVideo;

  video.autoplay = true;
  video.playsInline = true;
  video.preload = "auto";
  video.srcObject = e.streams[0];

  els.watchPlayer.classList.remove("hidden");
  els.watchControls.classList.remove("hidden");

  attemptAutoplay();
}
  watch.pc.setRemoteDescription(sdp).then(function(){
    watch.remoteSet = true;
    flushPending(watch);
    return watch.pc.createAnswer();
  }).then(function(answer){
    return watch.pc.setLocalDescription(answer);
  }).then(function(){
    sendWatchMsg({t:"answer", sdp: watch.pc.localDescription});
  }).catch(function(){
    els.watchStatus.textContent = "Failed to connect to stream";
  });
}

function attemptAutoplay(){
  var p = els.watchVideo.play();
  if (p && p.catch) {
    p.catch(function(){ els.watchTapOverlay.classList.remove("hidden"); });
  }
}

function applyRemoteState(m){
  els.watchPlayIcon.textContent = m.paused ? "▶" : "⏸";
  if (!watch.seeking) {
    var pct = m.duration ? (m.currentTime / m.duration) * 100 : 0;
    els.watchSeek.value = pct;
  }
  els.watchTime.textContent = formatTime(m.currentTime) + " / " + formatTime(m.duration);
  els.watchBuffering.classList.toggle("hidden", !m.buffering);
}

function sendControl(c, v){
  sendWatchMsg({t:"control", c:c, v:v});
}

els.watchModeBtn.onclick = function(){ showScreen("watch"); };
els.watchBackBtn.onclick = function(){ location.reload(); };
els.joinBtn.onclick = function(){ joinRoom(els.roomInput.value.trim()); };
els.roomInput.addEventListener("keydown", function(e){
  if (e.key === "Enter") joinRoom(els.roomInput.value.trim());
});
els.watchTapBtn.onclick = function(){
  els.watchVideo.play().then(function(){
    els.watchTapOverlay.classList.add("hidden");
  }).catch(function(){});
};
els.watchPlayBtn.onclick = function(){ sendControl("play"); };
els.watchBackTen.onclick = function(){ sendControl("back"); };
els.watchFwdTen.onclick = function(){ sendControl("fwd"); };
els.watchSeek.addEventListener("mousedown", function(){ watch.seeking = true; });
els.watchSeek.addEventListener("touchstart", function(){ watch.seeking = true; });
els.watchSeek.addEventListener("change", function(){
  sendControl("seek", this.value);
  watch.seeking = false;
});
els.watchVol.addEventListener("input", function(){
  sendControl("volume", this.value);
  els.watchVideo.volume = this.value;
});
els.watchFullscreenBtn.onclick = function(){
  var v = els.watchVideo;
  if (v.requestFullscreen) v.requestFullscreen();
  else if (v.webkitRequestFullscreen) v.webkitRequestFullscreen();
  else if (v.webkitEnterFullscreen) v.webkitEnterFullscreen();
};

})();
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return Response(HTML, mimetype="text/html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
