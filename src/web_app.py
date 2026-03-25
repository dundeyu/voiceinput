"""本地网页录音与识别服务。"""

from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import re
import socket
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from urllib.parse import urlparse

import soundfile as sf
import yaml

from app_factory import build_runtime
from audio_processor import AudioProcessor
from bootstrap import apply_offline_env, build_preload_failure_details, preload_model_or_exit
from recording_session import (
    get_stream_audio_path,
    transcribe_recording_serialized,
    transcribe_stream_audio_path,
)
from vocabulary_suggestion_store import VocabularySuggestionStore
from voice_entry import SOURCE_ROOT, load_runtime_config, setup_logging

logger = logging.getLogger(__name__)
SESSION_ID_PATTERN = re.compile(r"[^a-zA-Z0-9_-]+")
ADMIN_PASSWORD = "voice8765"
ADMIN_COOKIE_NAME = "voiceinput_admin"


@dataclass(frozen=True)
class WebRecognitionWorker:
    """单个网页识别 worker。"""

    worker_id: int
    processor: AudioProcessor
    asr_engine: Any
    temp_audio_path: Path
    supported_languages: list[str]


@dataclass(frozen=True)
class WebServerOptions:
    """网页服务启动参数。"""

    host: str
    port: int
    workers: int
    daemon: bool


def get_lan_addresses() -> list[str]:
    """尽量获取当前机器可用于局域网访问的 IPv4 地址。"""
    addresses: set[str] = set()
    hostnames = {socket.gethostname(), socket.getfqdn(), "localhost"}

    for hostname in hostnames:
        try:
            _, _, resolved = socket.gethostbyname_ex(hostname)
        except OSError:
            continue
        for address in resolved:
            if address.startswith("127."):
                continue
            addresses.add(address)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            address = sock.getsockname()[0]
            if not address.startswith("127."):
                addresses.add(address)
    except OSError:
        pass

    return sorted(addresses)


def resolve_service_path(project_root: Path, raw_path: str | None, default_relative_path: str) -> Path:
    """解析后台服务使用的 PID / 日志路径。"""
    candidate = Path(raw_path).expanduser() if raw_path else project_root / default_relative_path
    if candidate.is_absolute():
        return candidate
    return project_root / candidate


def resolve_web_server_options(config: dict, args: argparse.Namespace) -> WebServerOptions:
    """合并配置文件与命令行参数，命令行优先。"""
    web_config = config.get("web", {})

    host = args.host if args.host is not None else str(web_config.get("host", "127.0.0.1"))
    port = args.port if args.port is not None else int(web_config.get("port", 8765))
    workers = args.workers if args.workers is not None else int(web_config.get("workers", 1))
    daemon = args.daemon if args.daemon is not None else bool(web_config.get("daemon", False))

    return WebServerOptions(
        host=host,
        port=port,
        workers=max(1, int(workers)),
        daemon=bool(daemon),
    )


def daemonize_process(pid_file: Path, stdout_file: Path, stderr_file: Path):
    """将当前进程切换到后台运行。"""
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    stdout_file.parent.mkdir(parents=True, exist_ok=True)
    stderr_file.parent.mkdir(parents=True, exist_ok=True)

    first_pid = os.fork()
    if first_pid > 0:
        os._exit(0)

    os.setsid()

    second_pid = os.fork()
    if second_pid > 0:
        os._exit(0)

    os.chdir("/")
    os.umask(0)

    sys.stdout.flush()
    sys.stderr.flush()

    stdin_stream = open(os.devnull, "r", encoding="utf-8")
    stdout_stream = open(stdout_file, "a", encoding="utf-8")
    stderr_stream = open(stderr_file, "a", encoding="utf-8")

    os.dup2(stdin_stream.fileno(), sys.stdin.fileno())
    os.dup2(stdout_stream.fileno(), sys.stdout.fileno())
    os.dup2(stderr_stream.fileno(), sys.stderr.fileno())

    pid_file.write_text(str(os.getpid()), encoding="utf-8")


def build_web_page_html() -> str:
    """返回本地网页界面 HTML。"""
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>voiceinput web</title>
  <style>
    :root {
      --bg: #071f27;
      --panel: #0b2a34;
      --line: #119cf5;
      --text: #d8f4f9;
      --muted: #91c5cf;
      --accent: #00e58f;
      --warn: #ffd166;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: "SF Mono", "JetBrains Mono", "Fira Code", monospace;
      background:
        radial-gradient(circle at top left, rgba(17,156,245,0.16), transparent 32%),
        radial-gradient(circle at bottom right, rgba(0,229,143,0.12), transparent 28%),
        var(--bg);
      color: var(--text);
      display: grid;
      place-items: center;
      padding: 24px;
    }
    .shell {
      width: min(880px, 100%);
      background: rgba(11, 42, 52, 0.94);
      border: 1px solid rgba(17,156,245,0.35);
      border-radius: 22px;
      box-shadow: 0 28px 90px rgba(0, 0, 0, 0.35);
      overflow: hidden;
    }
    .header {
      padding: 24px 24px 10px;
      border-bottom: 1px solid rgba(17,156,245,0.22);
    }
    .title {
      margin: 0;
      font-size: clamp(30px, 6vw, 58px);
      letter-spacing: 0.18em;
      color: var(--muted);
      text-transform: lowercase;
      font-weight: 300;
    }
    .subtitle {
      margin: 8px 0 0;
      color: var(--muted);
      font-size: 15px;
    }
    .content {
      padding: 24px;
      display: grid;
      gap: 18px;
    }
    .controls {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: center;
    }
    button {
      border: 1px solid rgba(17,156,245,0.45);
      background: rgba(7, 31, 39, 0.86);
      color: var(--text);
      border-radius: 999px;
      padding: 12px 18px;
      cursor: pointer;
      font: inherit;
      transition: transform 140ms ease, border-color 140ms ease, background 140ms ease;
    }
    button:hover { transform: translateY(-1px); border-color: var(--line); }
    button.primary { background: rgba(0,229,143,0.14); border-color: rgba(0,229,143,0.5); }
    button[disabled] { opacity: 0.45; cursor: not-allowed; transform: none; }
    .status {
      min-height: 24px;
      color: var(--warn);
      font-size: 14px;
    }
    .panel {
      border: 1px solid rgba(17,156,245,0.25);
      border-radius: 16px;
      padding: 18px;
      background: rgba(7,31,39,0.62);
    }
    textarea {
      width: 100%;
      min-height: 180px;
      resize: vertical;
      border: none;
      outline: none;
      background: transparent;
      color: var(--text);
      font: inherit;
      line-height: 1.65;
    }
    #preview {
      min-height: 96px;
    }
    #result {
      min-height: 220px;
    }
    .meta {
      display: flex;
      flex-wrap: wrap;
      gap: 16px;
      color: var(--muted);
      font-size: 13px;
    }
    .suggestions {
      display: grid;
      gap: 12px;
    }
    .field-grid {
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    }
    .field {
      display: grid;
      gap: 6px;
    }
    .field.check {
      grid-template-columns: auto 1fr;
      align-items: center;
      gap: 10px;
    }
    label {
      font-size: 13px;
      color: var(--muted);
    }
    input, select, .suggestions textarea {
      width: 100%;
      border: 1px solid rgba(17,156,245,0.25);
      outline: none;
      border-radius: 12px;
      background: rgba(7,31,39,0.62);
      color: var(--text);
      font: inherit;
      padding: 12px 14px;
    }
    .suggestions textarea {
      min-height: 90px;
    }
    input[type="checkbox"] {
      width: 18px;
      height: 18px;
      margin: 0;
    }
  </style>
</head>
<body>
  <main class="shell">
    <header class="header">
      <h1 class="title">voice</h1>
      <p class="subtitle">本地网页录音，调用 Python 识别服务，返回转写结果。</p>
    </header>
    <section class="content">
      <div class="controls">
        <button id="startBtn" class="primary">开始录音</button>
        <button id="stopBtn" disabled>结束录音</button>
        <button id="copyBtn" disabled>复制结果</button>
      </div>
      <div class="meta">
        <span>快捷键: 空格开始 / 空格结束</span>
        <span>结束后自动复制到剪贴板</span>
      </div>
      <div id="status" class="status">待命中</div>
      <div class="panel">
        <div id="previewLabel" class="subtitle">实时预览</div>
        <textarea id="preview" placeholder="录音中会在这里滚动显示实时预览..." spellcheck="false"></textarea>
      </div>
      <div class="panel">
        <div class="subtitle">最终结果</div>
        <textarea id="result" placeholder="识别结果会显示在这里..." spellcheck="false"></textarea>
      </div>
      <div class="meta">
        <span id="duration">时长: 0.0s</span>
        <span id="chars">字符数: 0</span>
        <a href="/admin" style="color: var(--line); text-decoration: none;">管理员入口</a>
      </div>
      <div class="panel suggestions">
        <div class="subtitle">词汇修正建议</div>
        <div class="field-grid">
          <div class="field">
            <label for="wrongText">识别成了什么</label>
            <input id="wrongText" placeholder="例如：open cloud">
          </div>
          <div class="field">
            <label for="suggestedText">建议替换为</label>
            <input id="suggestedText" placeholder="例如：claude code">
          </div>
        </div>
        <div class="controls">
          <button id="submitSuggestionBtn">提交建议</button>
        </div>
        <div id="suggestionStatus" class="status">这些建议会先保存在本地，后续再人工合并到正式词库。</div>
      </div>
    </section>
  </main>
  <script>
    const startBtn = document.getElementById("startBtn");
    const stopBtn = document.getElementById("stopBtn");
    const copyBtn = document.getElementById("copyBtn");
    const statusEl = document.getElementById("status");
    const wrongTextEl = document.getElementById("wrongText");
    const suggestedTextEl = document.getElementById("suggestedText");
    const submitSuggestionBtn = document.getElementById("submitSuggestionBtn");
    const suggestionStatusEl = document.getElementById("suggestionStatus");
    const previewEl = document.getElementById("preview");
    const resultEl = document.getElementById("result");
    const durationEl = document.getElementById("duration");
    const charsEl = document.getElementById("chars");
    const sessionId = getOrCreateSessionId();

    let mediaStream = null;
    let audioContext = null;
    let sourceNode = null;
    let processorNode = null;
    let recording = false;
    let buffers = [];
    let sampleRate = 48000;
    let recordStartTime = 0;
    let previewTimer = null;
    let previewInFlight = false;
    let previewText = "";

    function getOrCreateSessionId() {
      const storageKey = "voiceinput.web.session_id";
      const existing = window.localStorage.getItem(storageKey);
      if (existing) {
        return existing;
      }

      let generated = "";
      if (window.crypto && typeof window.crypto.randomUUID === "function") {
        generated = window.crypto.randomUUID();
      } else {
        generated = `session-${Date.now()}-${Math.random().toString(16).slice(2)}`;
      }

      window.localStorage.setItem(storageKey, generated);
      return generated;
    }

    function setStatus(text) {
      statusEl.textContent = text;
    }

    function setSuggestionStatus(text) {
      suggestionStatusEl.textContent = text;
    }

    function updateMetrics(text, durationSeconds) {
      const charCount = (text || "").replace(/\\n/g, "").length;
      durationEl.textContent = `时长: ${durationSeconds.toFixed(1)}s`;
      charsEl.textContent = `字符数: ${charCount}`;
      copyBtn.disabled = !text;
    }

    function isTypingTarget(target) {
      if (!target) return false;
      const tagName = (target.tagName || "").toLowerCase();
      return tagName === "input" || tagName === "textarea" || target.isContentEditable;
    }

    async function copyResultToClipboard() {
      if (!resultEl.value) return false;
      if (!navigator.clipboard || typeof navigator.clipboard.writeText !== "function") {
        return false;
      }

      await navigator.clipboard.writeText(resultEl.value);
      return true;
    }

    function mergeBuffers(chunks) {
      const totalLength = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
      const output = new Float32Array(totalLength);
      let offset = 0;
      for (const chunk of chunks) {
        output.set(chunk, offset);
        offset += chunk.length;
      }
      return output;
    }

    function encodeWav(samples, sampleRate) {
      const bytesPerSample = 2;
      const blockAlign = bytesPerSample;
      const buffer = new ArrayBuffer(44 + samples.length * bytesPerSample);
      const view = new DataView(buffer);

      function writeString(offset, value) {
        for (let i = 0; i < value.length; i += 1) {
          view.setUint8(offset + i, value.charCodeAt(i));
        }
      }

      writeString(0, "RIFF");
      view.setUint32(4, 36 + samples.length * bytesPerSample, true);
      writeString(8, "WAVE");
      writeString(12, "fmt ");
      view.setUint32(16, 16, true);
      view.setUint16(20, 1, true);
      view.setUint16(22, 1, true);
      view.setUint32(24, sampleRate, true);
      view.setUint32(28, sampleRate * blockAlign, true);
      view.setUint16(32, blockAlign, true);
      view.setUint16(34, 16, true);
      writeString(36, "data");
      view.setUint32(40, samples.length * bytesPerSample, true);

      let offset = 44;
      for (let i = 0; i < samples.length; i += 1) {
        const sample = Math.max(-1, Math.min(1, samples[i]));
        view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
        offset += 2;
      }

      return new Blob([buffer], { type: "audio/wav" });
    }

    async function startRecording() {
      if (recording) return;
      buffers = [];
      previewText = "";
      previewEl.value = "";
      resultEl.value = "";
      updateMetrics("", 0);
      setStatus("正在请求麦克风权限...");

      mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioContext = new (window.AudioContext || window.webkitAudioContext)();
      sampleRate = audioContext.sampleRate;
      sourceNode = audioContext.createMediaStreamSource(mediaStream);
      processorNode = audioContext.createScriptProcessor(4096, 1, 1);

      processorNode.onaudioprocess = (event) => {
        if (!recording) return;
        const input = event.inputBuffer.getChannelData(0);
        buffers.push(new Float32Array(input));
      };

      sourceNode.connect(processorNode);
      processorNode.connect(audioContext.destination);

      recording = true;
      recordStartTime = performance.now();
      startBtn.disabled = true;
      stopBtn.disabled = false;
      setStatus("录音中...");
      previewTimer = window.setInterval(sendPreview, 1800);
    }

    async function sendPreview() {
      if (!recording || previewInFlight || buffers.length === 0) return;
      previewInFlight = true;

      try {
        const merged = mergeBuffers(buffers);
        const wavBlob = encodeWav(merged, sampleRate);
        const response = await fetch("/api/preview", {
          method: "POST",
          headers: {
            "Content-Type": "audio/wav",
            "X-Voice-Session": sessionId,
          },
          body: await wavBlob.arrayBuffer(),
        });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.error || "实时预览失败");
        }
        previewText = payload.text || "";
        previewEl.value = previewText;
      } catch (error) {
        setStatus(`实时预览失败: ${error.message}`);
      } finally {
        previewInFlight = false;
      }
    }

    async function stopRecording() {
      if (!recording) return;
      recording = false;
      startBtn.disabled = false;
      stopBtn.disabled = true;
      setStatus("正在上传并识别...");
      if (previewTimer !== null) {
        window.clearInterval(previewTimer);
        previewTimer = null;
      }

      const durationSeconds = (performance.now() - recordStartTime) / 1000;
      const merged = mergeBuffers(buffers);
      const wavBlob = encodeWav(merged, sampleRate);

      processorNode.disconnect();
      sourceNode.disconnect();
      mediaStream.getTracks().forEach((track) => track.stop());
      await audioContext.close();

      const response = await fetch("/api/transcribe", {
        method: "POST",
        headers: {
          "Content-Type": "audio/wav",
          "X-Voice-Session": sessionId,
        },
        body: await wavBlob.arrayBuffer(),
      });

      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "识别失败");
      }

      previewEl.value = "";
      resultEl.value = payload.text || "";
      updateMetrics(payload.text || "", payload.duration_seconds || durationSeconds);
      try {
        const copied = await copyResultToClipboard();
        setStatus(copied ? "识别完成，已自动复制到剪贴板" : "识别完成");
      } catch (error) {
        setStatus(`识别完成，但自动复制失败: ${error.message}`);
      }
    }

    startBtn.addEventListener("click", async () => {
      try {
        await startRecording();
      } catch (error) {
        setStatus(`启动录音失败: ${error.message}`);
      }
    });

    stopBtn.addEventListener("click", async () => {
      try {
        await stopRecording();
      } catch (error) {
        setStatus(`识别失败: ${error.message}`);
      }
    });

    copyBtn.addEventListener("click", async () => {
      try {
        const copied = await copyResultToClipboard();
        setStatus(copied ? "已复制到剪贴板" : "当前浏览器不支持自动复制");
      } catch (error) {
        setStatus(`复制失败: ${error.message}`);
      }
    });

    window.addEventListener("keydown", async (event) => {
      if (event.code !== "Space") return;
      if (isTypingTarget(event.target)) return;
      event.preventDefault();

      try {
        if (recording) {
          await stopRecording();
        } else {
          await startRecording();
        }
      } catch (error) {
        setStatus(recording ? `识别失败: ${error.message}` : `启动录音失败: ${error.message}`);
      }
    });

    submitSuggestionBtn.addEventListener("click", async () => {
      const wrongText = wrongTextEl.value.trim();
      const suggestedText = suggestedTextEl.value.trim();

      if (!wrongText || !suggestedText) {
        setSuggestionStatus("请先填写“识别成了什么”和“建议替换为”。");
        return;
      }

      submitSuggestionBtn.disabled = true;
      setSuggestionStatus("正在保存建议...");
      try {
        const response = await fetch("/api/suggestions", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            wrong_text: wrongText,
            suggested_text: suggestedText,
          }),
        });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.error || "提交失败");
        }
        wrongTextEl.value = "";
        suggestedTextEl.value = "";
        setSuggestionStatus(`已保存到本地建议箱：${payload.storage_path}`);
      } catch (error) {
        setSuggestionStatus(`提交失败: ${error.message}`);
      } finally {
        submitSuggestionBtn.disabled = false;
      }
    });

  </script>
</body>
</html>
"""


def build_admin_login_html() -> str:
    """管理员登录页。"""
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>voiceinput admin</title>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #071f27; color: #d8f4f9; font-family: "SF Mono", monospace; }
    .card { width: min(420px, calc(100vw - 32px)); padding: 24px; border: 1px solid rgba(17,156,245,0.35); border-radius: 18px; background: rgba(11,42,52,0.94); display: grid; gap: 14px; }
    .login-form { width: min(280px, 100%); display: grid; gap: 12px; }
    input, button { font: inherit; }
    input { width: 100%; padding: 12px 14px; border-radius: 12px; border: 1px solid rgba(17,156,245,0.25); background: rgba(7,31,39,0.62); color: #d8f4f9; }
    button { padding: 12px 16px; border-radius: 999px; border: 1px solid rgba(0,229,143,0.5); background: rgba(0,229,143,0.14); color: #d8f4f9; cursor: pointer; }
    .status { min-height: 24px; color: #ffd166; font-size: 14px; }
    .suggestion-list { display: grid; gap: 10px; }
    .suggestion-item { border: 1px solid rgba(17,156,245,0.2); border-radius: 12px; padding: 12px; display: grid; gap: 8px; background: rgba(7,31,39,0.4); }
    .suggestion-row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
    .suggestion-tag { color: #91c5cf; font-size: 12px; }
    .suggestion-text { font-size: 14px; line-height: 1.5; word-break: break-word; }
    .suggestion-actions { display: flex; gap: 8px; flex-wrap: wrap; }
    .suggestion-actions button { padding: 8px 12px; }
    a { color: #119cf5; text-decoration: none; }
  </style>
</head>
<body>
  <main class="card">
    <h1 style="margin:0;">管理员登录</h1>
    <div style="color:#91c5cf;">配置功能仅对管理员开放。</div>
    <div class="login-form">
      <input id="adminPassword" type="password" placeholder="请输入管理员密码">
      <button id="loginBtn">登录</button>
    </div>
    <div id="loginStatus" class="status">登录后可进入配置页面。</div>
    <a href="/">返回录音页面</a>
  </main>
  <script>
    const adminPasswordEl = document.getElementById("adminPassword");
    const loginBtn = document.getElementById("loginBtn");
    const loginStatusEl = document.getElementById("loginStatus");

    function setLoginStatus(text) {
      loginStatusEl.textContent = text;
    }

    async function login() {
      loginBtn.disabled = true;
      setLoginStatus("正在登录...");
      try {
        const response = await fetch("/api/admin/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ password: adminPasswordEl.value }),
        });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.error || "登录失败");
        }
        window.location.href = "/admin/config";
      } catch (error) {
        setLoginStatus(`登录失败: ${error.message}`);
      } finally {
        loginBtn.disabled = false;
      }
    }

    loginBtn.addEventListener("click", login);
    adminPasswordEl.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        login();
      }
    });
  </script>
</body>
</html>
"""


def build_admin_config_html() -> str:
    """管理员配置页。"""
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>voiceinput admin config</title>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #071f27; color: #d8f4f9; font-family: "SF Mono", monospace; padding: 24px; }
    .shell { width: min(720px, 100%); border: 1px solid rgba(17,156,245,0.35); border-radius: 22px; background: rgba(11,42,52,0.94); overflow: hidden; }
    .header { padding: 20px 22px; border-bottom: 1px solid rgba(17,156,245,0.22); display: flex; justify-content: space-between; gap: 12px; align-items: center; flex-wrap: wrap; }
    .content { padding: 20px 22px; display: grid; gap: 16px; }
    .panel { border: 1px solid rgba(17,156,245,0.25); border-radius: 16px; padding: 16px; background: rgba(7,31,39,0.62); display: grid; gap: 10px; }
    .field-grid { display: grid; gap: 10px; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }
    .field-grid.two-col { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .field-grid.three-col { grid-template-columns: minmax(0, 1.3fr) minmax(110px, 0.8fr) minmax(110px, 0.8fr); }
    .field { display: grid; gap: 6px; }
    .field.check { grid-template-columns: auto 1fr; align-items: center; gap: 10px; }
    input, select, textarea, button { font: inherit; }
    input:not([type="checkbox"]), select { width: 100%; padding: 10px 12px; border-radius: 12px; border: 1px solid rgba(17,156,245,0.25); background: rgba(7,31,39,0.62); color: #d8f4f9; }
    textarea { width: 100%; min-height: 120px; padding: 10px 12px; border-radius: 12px; border: 1px solid rgba(17,156,245,0.25); background: rgba(7,31,39,0.62); color: #d8f4f9; resize: vertical; line-height: 1.5; }
    input[type="checkbox"] { width: 18px; height: 18px; margin: 0; }
    button { padding: 10px 14px; border-radius: 999px; border: 1px solid rgba(17,156,245,0.45); background: rgba(7,31,39,0.86); color: #d8f4f9; cursor: pointer; }
    .primary { border-color: rgba(0,229,143,0.5); background: rgba(0,229,143,0.14); }
    .controls { display: flex; flex-wrap: wrap; gap: 12px; }
    .status { min-height: 24px; color: #ffd166; font-size: 14px; }
    a { color: #119cf5; text-decoration: none; }
    @media (max-width: 900px) {
      body { padding: 12px; place-items: start center; }
      .shell { width: min(560px, 100%); }
      .field-grid { grid-template-columns: 1fr; }
      .field-grid.two-col { grid-template-columns: 1fr; }
      .field-grid.three-col { grid-template-columns: 1fr; }
      textarea { min-height: 96px; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header class="header">
      <div>
        <h1 style="margin:0;">管理员配置</h1>
        <div style="color:#91c5cf;">Host / Port / Workers / Daemon 保存后需要重启 voice-web 才会生效。</div>
      </div>
      <div class="controls">
        <button id="backToVoiceBtn" type="button">返回录音页</button>
        <button id="logoutBtn">退出管理员</button>
      </div>
    </header>
    <section class="content">
      <div class="panel">
        <div class="field-grid two-col">
          <div class="field">
            <label for="configDefaultLanguage">默认语言</label>
            <input id="configDefaultLanguage" placeholder="例如：中文">
          </div>
          <div class="field">
            <label for="configDevice">推理设备</label>
            <input id="configDevice" placeholder="留空自动选择 mps/cuda/cpu">
          </div>
        </div>
        <div class="field-grid three-col">
          <div class="field">
            <label for="configWebHost">Web Host</label>
            <select id="configWebHost">
              <option value="127.0.0.1">127.0.0.1（只服务本机）</option>
              <option value="0.0.0.0">0.0.0.0（服务局域网）</option>
            </select>
          </div>
          <div class="field">
            <label for="configWebPort">Web Port</label>
            <input id="configWebPort" type="number" min="1" max="65535">
          </div>
          <div class="field">
            <label for="configWebWorkers">Web Workers</label>
            <input id="configWebWorkers" type="number" min="1" max="16">
          </div>
        </div>
        <div class="field-grid">
          <label class="field check" for="configOfflineMode">
            <input id="configOfflineMode" type="checkbox">
            <span>离线模式</span>
          </label>
          <label class="field check" for="configWebDaemon">
            <input id="configWebDaemon" type="checkbox">
            <span>后台服务模式</span>
          </label>
        </div>
        <div class="field">
          <label for="configVocabularyCorrections">替换词汇配置</label>
          <textarea id="configVocabularyCorrections" placeholder="每行一条，格式：错误词=正确词"></textarea>
        </div>
        <div class="field">
          <label for="configFillerWords">语气词配置</label>
          <textarea id="configFillerWords" placeholder="每行一个语气词，例如：呃"></textarea>
        </div>
        <div class="field">
          <label for="suggestionInbox">词汇修正建议</label>
          <div id="suggestionInbox" class="suggestion-list"></div>
          <div id="suggestionInboxMeta" class="status">正在读取建议箱...</div>
        </div>
        <div class="controls">
          <button id="reloadConfigBtn">读取配置</button>
          <button id="saveConfigBtn" class="primary">保存配置</button>
        </div>
        <div id="configStatus" class="status">正在准备配置页面...</div>
      </div>
    </section>
  </main>
  <script>
    const backToVoiceBtn = document.getElementById("backToVoiceBtn");
    const reloadConfigBtn = document.getElementById("reloadConfigBtn");
    const saveConfigBtn = document.getElementById("saveConfigBtn");
    const logoutBtn = document.getElementById("logoutBtn");
    const configStatusEl = document.getElementById("configStatus");
    const configDefaultLanguageEl = document.getElementById("configDefaultLanguage");
    const configDeviceEl = document.getElementById("configDevice");
    const configOfflineModeEl = document.getElementById("configOfflineMode");
    const configWebHostEl = document.getElementById("configWebHost");
    const configWebPortEl = document.getElementById("configWebPort");
    const configWebWorkersEl = document.getElementById("configWebWorkers");
    const configWebDaemonEl = document.getElementById("configWebDaemon");
    const configVocabularyCorrectionsEl = document.getElementById("configVocabularyCorrections");
    const configFillerWordsEl = document.getElementById("configFillerWords");
    const suggestionInboxEl = document.getElementById("suggestionInbox");
    const suggestionInboxMetaEl = document.getElementById("suggestionInboxMeta");

    function setConfigStatus(text) {
      configStatusEl.textContent = text;
    }

    function escapeHtml(text) {
      return String(text)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }

    function renderSuggestionInbox(suggestionItems) {
      if (!suggestionItems.length) {
        suggestionInboxEl.innerHTML = '<div class="suggestion-tag">当前还没有词汇修正建议。</div>';
        return;
      }

      suggestionInboxEl.innerHTML = suggestionItems
        .map((item) => {
          const wrongText = escapeHtml(item.wrong_text || "");
          const suggestedText = escapeHtml(item.suggested_text || "");
          const createdAt = escapeHtml(item.created_at || "-");
          const encodedWrongText = encodeURIComponent(item.wrong_text || "");
          const encodedSuggestedText = encodeURIComponent(item.suggested_text || "");
          const encodedCreatedAt = encodeURIComponent(item.created_at || "");
          return `
            <div class="suggestion-item">
              <div class="suggestion-row">
                <span class="suggestion-tag">${createdAt}</span>
              </div>
              <div class="suggestion-text">${wrongText} => ${suggestedText}</div>
              <div class="suggestion-actions">
                <button type="button" data-action="accept" data-wrong="${encodedWrongText}" data-suggested="${encodedSuggestedText}" data-created="${encodedCreatedAt}">采纳</button>
                <button type="button" data-action="delete" data-wrong="${encodedWrongText}" data-suggested="${encodedSuggestedText}" data-created="${encodedCreatedAt}">删除</button>
              </div>
            </div>
          `;
        })
        .join("");
    }

    function applyConfigToForm(config) {
      const runtime = config.runtime || {};
      const web = config.web || {};
      const vocabularyCorrections = config.vocabulary_corrections || {};
      const fillerWords = config.filler_words || [];
      const suggestionInbox = config.suggestion_inbox || {};
      const suggestionItems = suggestionInbox.items || [];
      configDefaultLanguageEl.value = runtime.default_language || "";
      configDeviceEl.value = runtime.device || "";
      configOfflineModeEl.checked = Boolean(runtime.offline_mode);
      configWebHostEl.value = web.host || "";
      configWebPortEl.value = web.port ?? 8765;
      configWebWorkersEl.value = web.workers ?? 1;
      configWebDaemonEl.checked = Boolean(web.daemon);
      configVocabularyCorrectionsEl.value = Object.entries(vocabularyCorrections)
        .map(([wrongText, correctText]) => `${wrongText}=${correctText}`)
        .join("\\n");
      configFillerWordsEl.value = fillerWords.join("\\n");
      renderSuggestionInbox(suggestionItems);
      suggestionInboxMetaEl.textContent = suggestionInbox.path
        ? `建议箱：${suggestionInbox.path}，最近 ${suggestionItems.length} 条`
        : "当前还没有词汇修正建议。";
    }

    async function loadConfig() {
      setConfigStatus("正在读取配置...");
      const response = await fetch("/api/config");
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "读取配置失败");
      }
      applyConfigToForm(payload);
      setConfigStatus(`配置已读取：${payload.config_path}`);
    }

    reloadConfigBtn.addEventListener("click", async () => {
      try {
        await loadConfig();
      } catch (error) {
        setConfigStatus(`读取配置失败: ${error.message}`);
      }
    });

    saveConfigBtn.addEventListener("click", async () => {
      saveConfigBtn.disabled = true;
      setConfigStatus("正在保存配置...");
      try {
        const response = await fetch("/api/config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            offline_mode: configOfflineModeEl.checked,
            model: {
              default_language: configDefaultLanguageEl.value.trim(),
              device: configDeviceEl.value.trim(),
            },
            web: {
              host: configWebHostEl.value.trim(),
              port: Number(configWebPortEl.value || 8765),
              workers: Number(configWebWorkersEl.value || 1),
              daemon: configWebDaemonEl.checked,
            },
            vocabulary_corrections: configVocabularyCorrectionsEl.value,
            filler_words: configFillerWordsEl.value,
          }),
        });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.error || "保存配置失败");
        }
        applyConfigToForm(payload);
        setConfigStatus(`配置已保存：${payload.config_path}。Host / Port / Workers / Daemon 需重启后生效。`);
      } catch (error) {
        setConfigStatus(`保存配置失败: ${error.message}`);
      } finally {
        saveConfigBtn.disabled = false;
      }
    });

    backToVoiceBtn.addEventListener("click", () => {
      window.location.href = "/";
    });

    suggestionInboxEl.addEventListener("click", async (event) => {
      const button = event.target.closest("button[data-action]");
      if (!button) return;

      const action = button.dataset.action;
      const wrongText = decodeURIComponent(button.dataset.wrong || "");
      const suggestedText = decodeURIComponent(button.dataset.suggested || "");
      const createdAt = decodeURIComponent(button.dataset.created || "");
      const endpoint = action === "accept" ? "/api/suggestions/accept" : "/api/suggestions/delete";

      button.disabled = true;
      setConfigStatus(action === "accept" ? "正在采纳建议..." : "正在删除建议...");
      try {
        const response = await fetch(endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            wrong_text: wrongText,
            suggested_text: suggestedText,
            created_at: createdAt,
          }),
        });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.error || "操作失败");
        }
        setConfigStatus(action === "accept" ? "建议已采纳并写入正式配置，正在刷新页面..." : "建议已删除，正在刷新页面...");
        window.location.reload();
      } catch (error) {
        setConfigStatus(`操作失败: ${error.message}`);
      } finally {
        button.disabled = false;
      }
    });

    logoutBtn.addEventListener("click", async () => {
      await fetch("/api/admin/logout", { method: "POST" });
      window.location.href = "/admin";
    });

    loadConfig().catch((error) => {
      setConfigStatus(`读取配置失败: ${error.message}`);
    });
  </script>
</body>
</html>
"""


def decode_wav_bytes(audio_bytes: bytes) -> tuple[Any, int]:
    """从上传的 WAV 字节中读取音频数据与采样率。"""
    with BytesIO(audio_bytes) as audio_buffer:
        audio_data, sample_rate = sf.read(audio_buffer, dtype="float32")
    return audio_data, sample_rate


class WebRecognitionRuntime:
    """网页识别服务运行时。"""

    def __init__(self, project_root: Path, worker_count: int = 1):
        self.project_root = project_root
        self.config, self.config_path, self.used_example_config, self.runtime_root = load_runtime_config(project_root)
        apply_offline_env(self.config)
        setup_logging(self.config, self.runtime_root)
        self.worker_count = max(1, worker_count)
        self.configured_input_rate = self.config["audio"]["input_sample_rate"]
        self.target_sample_rate = self.config["audio"]["target_sample_rate"]
        self.suggestion_store = VocabularySuggestionStore(self.get_suggestions_path())
        self._session_lock_guard = threading.Lock()
        self._session_locks: dict[str, threading.Lock] = {}
        self.admin_session_token = uuid.uuid4().hex
        self.workers = self._build_workers()
        self.supported_languages = self.workers[0].supported_languages
        self.default_temp_audio_path = self.workers[0].temp_audio_path
        self._worker_queue: queue.SimpleQueue[WebRecognitionWorker] = queue.SimpleQueue()
        for worker in self.workers:
            self._worker_queue.put(worker)

    def _sanitize_session_id(self, session_id: str | None) -> str:
        raw_session_id = (session_id or "").strip()
        if not raw_session_id:
            return "default"

        cleaned = SESSION_ID_PATTERN.sub("-", raw_session_id).strip("-")
        return cleaned[:64] or "default"

    def _get_session_temp_dir(self, session_id: str | None) -> Path:
        session_key = self._sanitize_session_id(session_id)
        return self.default_temp_audio_path.parent / "web_sessions" / session_key

    def get_session_stream_audio_path(self, session_id: str | None) -> Path:
        session_dir = self._get_session_temp_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        return get_stream_audio_path(session_dir / self.default_temp_audio_path.name)

    def get_suggestions_path(self) -> Path:
        logging_config = self.config.get("logging", {})
        log_file = Path(logging_config.get("file", "logs/voice_input.log"))
        if not log_file.is_absolute():
            log_file = self.runtime_root / log_file
        return log_file.parent / "vocabulary_suggestions.jsonl"

    def get_persisted_config_path(self) -> Path:
        if not self.used_example_config:
            return self.config_path
        return self.runtime_root / "config" / "settings.yaml"

    def _to_display_path(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.runtime_root))
        except ValueError:
            if path.name:
                return path.name
            return "settings.yaml"

    def get_display_config_path(self) -> str:
        return self._to_display_path(self.get_persisted_config_path())

    def verify_admin_password(self, password: str) -> bool:
        return password == ADMIN_PASSWORD

    def get_admin_cookie_value(self) -> str:
        return f"{ADMIN_COOKIE_NAME}={self.admin_session_token}; HttpOnly; Path=/; SameSite=Lax"

    def get_admin_logout_cookie_value(self) -> str:
        return f"{ADMIN_COOKIE_NAME}=; HttpOnly; Path=/; Max-Age=0; SameSite=Lax"

    def is_admin_authenticated(self, cookie_header: str | None) -> bool:
        if not cookie_header:
            return False
        parts = [part.strip() for part in cookie_header.split(";")]
        for part in parts:
            if part == f"{ADMIN_COOKIE_NAME}={self.admin_session_token}":
                return True
        return False

    def get_config_payload(self) -> dict[str, Any]:
        model_config = self.config.get("model", {})
        web_config = self.config.get("web", {})
        recent_suggestions = self.suggestion_store.list_recent(limit=20)
        return {
            "config_path": self.get_display_config_path(),
            "runtime": {
                "default_language": model_config.get("default_language", ""),
                "device": model_config.get("device", ""),
                "offline_mode": bool(self.config.get("offline_mode", False)),
            },
            "web": {
                "host": str(web_config.get("host", "127.0.0.1")),
                "port": int(web_config.get("port", 8765)),
                "workers": max(1, int(web_config.get("workers", 1))),
                "daemon": bool(web_config.get("daemon", False)),
            },
            "filler_words": list(self.config.get("filler_words", [])),
            "vocabulary_corrections": dict(self.config.get("vocabulary_corrections", {})),
            "suggestion_inbox": {
                "path": self._to_display_path(self.suggestion_store.suggestions_path),
                "items": [
                    {
                        "wrong_text": suggestion.wrong_text,
                        "suggested_text": suggestion.suggested_text,
                        "created_at": suggestion.created_at,
                    }
                    for suggestion in recent_suggestions
                ],
            },
        }

    def update_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        model_payload = payload.get("model", {})
        web_payload = payload.get("web", {})

        default_language = str(model_payload.get("default_language", "")).strip()
        if not default_language:
            raise ValueError("default_language 不能为空")

        host = str(web_payload.get("host", "127.0.0.1")).strip() or "127.0.0.1"
        port = int(web_payload.get("port", 8765))
        workers = max(1, int(web_payload.get("workers", 1)))
        filler_words = self._parse_filler_words(payload.get("filler_words", ""))
        vocabulary_corrections = self._parse_vocabulary_corrections(payload.get("vocabulary_corrections", ""))

        self.config["offline_mode"] = bool(payload.get("offline_mode", False))
        self.config.setdefault("model", {})
        self.config["model"]["default_language"] = default_language
        self.config["model"]["device"] = str(model_payload.get("device", "")).strip()
        self.config["filler_words"] = filler_words
        self.config["vocabulary_corrections"] = vocabulary_corrections
        self.config["web"] = {
            "host": host,
            "port": port,
            "workers": workers,
            "daemon": bool(web_payload.get("daemon", False)),
        }

        config_path = self.get_persisted_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as file:
            yaml.safe_dump(self.config, file, allow_unicode=True, sort_keys=False)

        self.config_path = config_path
        self.used_example_config = False
        return self.get_config_payload()

    def _parse_filler_words(self, raw_text: Any) -> list[str]:
        if isinstance(raw_text, list):
            return [str(item).strip() for item in raw_text if str(item).strip()]

        words: list[str] = []
        for raw_line in str(raw_text or "").splitlines():
            word = raw_line.strip()
            if word and word not in words:
                words.append(word)
        return words

    def _parse_vocabulary_corrections(self, raw_text: Any) -> dict[str, str]:
        if isinstance(raw_text, dict):
            return {str(key).strip(): str(value).strip() for key, value in raw_text.items() if str(key).strip()}

        text = str(raw_text or "")
        corrections: dict[str, str] = {}
        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            if "=" not in line:
                raise ValueError(f"替换词汇第 {line_number} 行格式错误，应为 错误词=正确词")
            wrong_text, correct_text = line.split("=", 1)
            wrong_text = wrong_text.strip()
            correct_text = correct_text.strip()
            if not wrong_text or not correct_text:
                raise ValueError(f"替换词汇第 {line_number} 行不能为空")
            corrections[wrong_text] = correct_text
        return corrections

    def _build_workers(self) -> list[WebRecognitionWorker]:
        workers: list[WebRecognitionWorker] = []
        for worker_index in range(self.worker_count):
            _, processor, asr_engine, temp_audio_path, supported_languages = build_runtime(
                self.config,
                self.runtime_root,
            )
            preload_model_or_exit(
                asr_engine.preload,
                logger,
                failure_details=build_preload_failure_details(
                    offline_mode=self.config.get("offline_mode", False),
                    model_path=asr_engine.model_path,
                    vad_model_path=asr_engine.vad_model_path,
                    use_vad=asr_engine.use_vad,
                    last_error=asr_engine.last_error,
                ),
            )
            workers.append(
                WebRecognitionWorker(
                    worker_id=worker_index,
                    processor=processor,
                    asr_engine=asr_engine,
                    temp_audio_path=temp_audio_path,
                    supported_languages=supported_languages,
                )
            )
        return workers

    def _get_session_lock(self, session_id: str | None) -> threading.Lock:
        session_key = self._sanitize_session_id(session_id)
        with self._session_lock_guard:
            if session_key not in self._session_locks:
                self._session_locks[session_key] = threading.Lock()
            return self._session_locks[session_key]

    @contextmanager
    def _checkout_worker(self):
        worker = self._worker_queue.get()
        try:
            yield worker
        finally:
            self._worker_queue.put(worker)

    def _build_processor_for_sample_rate(self, input_sample_rate: int, default_processor: AudioProcessor) -> AudioProcessor:
        if input_sample_rate == self.configured_input_rate:
            return default_processor
        return AudioProcessor(
            input_sample_rate=input_sample_rate,
            target_sample_rate=self.target_sample_rate,
        )

    def transcribe_wav_bytes(
        self,
        audio_bytes: bytes,
        language: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        audio_data, sample_rate = decode_wav_bytes(audio_bytes)
        if audio_data is None or len(audio_data) == 0:
            raise ValueError("上传的音频为空")

        language = language or self.config["model"]["default_language"]
        temp_dir = self.runtime_root / self.config["temp"]["audio_dir"]
        temp_dir.mkdir(parents=True, exist_ok=True)

        session_key = self._sanitize_session_id(session_id)
        session_lock = self._get_session_lock(session_id)
        with session_lock:
            with self._checkout_worker() as worker:
                processor = self._build_processor_for_sample_rate(sample_rate, worker.processor)
                with NamedTemporaryFile(
                    prefix=f"web_{session_key}_",
                    suffix=".wav",
                    dir=temp_dir,
                    delete=False,
                ) as temp_file:
                    temp_audio_path = Path(temp_file.name)

                try:
                    start_time = time.perf_counter()
                    text = transcribe_recording_serialized(
                        audio_data,
                        processor=processor,
                        asr_engine=worker.asr_engine,
                        temp_audio_path=temp_audio_path,
                        language=language,
                        inference_lock=threading.Lock(),
                    )
                    duration_seconds = time.perf_counter() - start_time
                    return {
                        "text": text or "",
                        "language": language,
                        "duration_seconds": round(duration_seconds, 2),
                        "char_count": len((text or "").replace("\n", "")),
                        "worker_id": worker.worker_id,
                    }
                finally:
                    temp_audio_path.unlink(missing_ok=True)

    def preview_wav_bytes(
        self,
        audio_bytes: bytes,
        language: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """识别当前录音中的预览音频。"""
        audio_data, sample_rate = decode_wav_bytes(audio_bytes)
        if audio_data is None or len(audio_data) == 0:
            raise ValueError("上传的音频为空")

        language = language or self.config["model"]["default_language"]
        session_lock = self._get_session_lock(session_id)
        with session_lock:
            with self._checkout_worker() as worker:
                processor = self._build_processor_for_sample_rate(sample_rate, worker.processor)
                processed = processor.process(audio_data)
                stream_audio_path = self.get_session_stream_audio_path(session_id)
                processor.save_wav(processed, str(stream_audio_path))
                text = transcribe_stream_audio_path(
                    stream_audio_path,
                    asr_engine=worker.asr_engine,
                    language=language,
                    inference_lock=threading.Lock(),
                )
                return {
                    "text": text or "",
                    "language": language,
                    "char_count": len((text or "").replace("\n", "")),
                    "worker_id": worker.worker_id,
                }

    def record_vocabulary_suggestion(
        self,
        wrong_text: str,
        suggested_text: str,
        note: str = "",
    ) -> dict[str, Any]:
        if not wrong_text.strip():
            raise ValueError("wrong_text 不能为空")
        if not suggested_text.strip():
            raise ValueError("suggested_text 不能为空")

        suggestion = self.suggestion_store.record(
            wrong_text=wrong_text,
            suggested_text=suggested_text,
            note=note,
        )
        return {
            "ok": True,
            "storage_path": self._to_display_path(self.suggestion_store.suggestions_path),
            "suggestion": {
                "wrong_text": suggestion.wrong_text,
                "suggested_text": suggestion.suggested_text,
                "note": suggestion.note,
                "created_at": suggestion.created_at,
            },
        }

    def delete_vocabulary_suggestion(
        self,
        wrong_text: str,
        suggested_text: str,
        created_at: str,
    ) -> dict[str, Any]:
        if not self.suggestion_store.remove(
            wrong_text=wrong_text,
            suggested_text=suggested_text,
            created_at=created_at,
        ):
            raise ValueError("未找到对应建议")
        return self.get_config_payload()

    def accept_vocabulary_suggestion(
        self,
        wrong_text: str,
        suggested_text: str,
        created_at: str,
    ) -> dict[str, Any]:
        wrong_text = wrong_text.strip()
        suggested_text = suggested_text.strip()
        if not wrong_text or not suggested_text:
            raise ValueError("建议内容不能为空")

        self.config.setdefault("vocabulary_corrections", {})
        self.config["vocabulary_corrections"][wrong_text] = suggested_text

        config_path = self.get_persisted_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as file:
            yaml.safe_dump(self.config, file, allow_unicode=True, sort_keys=False)

        self.config_path = config_path
        self.used_example_config = False

        if not self.suggestion_store.remove(
            wrong_text=wrong_text,
            suggested_text=suggested_text,
            created_at=created_at,
        ):
            raise ValueError("未找到对应建议")
        return self.get_config_payload()


class VoiceWebRequestHandler(BaseHTTPRequestHandler):
    """本地网页服务请求处理器。"""

    runtime: WebRecognitionRuntime | None = None

    def _require_admin(self) -> bool:
        if self.runtime.is_admin_authenticated(self.headers.get("Cookie")):
            return True
        self._send_json({"error": "需要管理员登录"}, status=HTTPStatus.UNAUTHORIZED)
        return False

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            html = build_web_page_html().encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return

        if parsed.path == "/admin":
            html = build_admin_login_html().encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return

        if parsed.path == "/admin/config":
            if not self.runtime.is_admin_authenticated(self.headers.get("Cookie")):
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", "/admin")
                self.end_headers()
                return
            html = build_admin_config_html().encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return

        if parsed.path == "/api/health":
            self._send_json({"ok": True})
            return

        if parsed.path == "/api/config":
            if not self._require_admin():
                return
            self._send_json(self.runtime.get_config_payload())
            return

        self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/admin/login":
            self._handle_admin_login()
            return
        if parsed.path == "/api/admin/logout":
            self._handle_admin_logout()
            return
        if parsed.path == "/api/suggestions":
            self._handle_suggestion_submission()
            return
        if parsed.path in {"/api/suggestions/accept", "/api/suggestions/delete"}:
            if not self._require_admin():
                return
            self._handle_suggestion_action(parsed.path)
            return
        if parsed.path == "/api/config":
            if not self._require_admin():
                return
            self._handle_config_update()
            return

        if parsed.path not in {"/api/transcribe", "/api/preview"}:
            self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            self._send_json({"error": "音频内容为空"}, status=HTTPStatus.BAD_REQUEST)
            return

        audio_bytes = self.rfile.read(content_length)
        language = self.headers.get("X-Voice-Language") or None
        session_id = self.headers.get("X-Voice-Session") or None

        try:
            if parsed.path == "/api/preview":
                result = self.runtime.preview_wav_bytes(audio_bytes, language=language, session_id=session_id)
            else:
                result = self.runtime.transcribe_wav_bytes(audio_bytes, language=language, session_id=session_id)
        except Exception as exc:
            logger.exception("网页识别失败")
            self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self._send_json(result)

    def _handle_suggestion_submission(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            self._send_json({"error": "提交内容为空"}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json({"error": "提交内容不是有效 JSON"}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            result = self.runtime.record_vocabulary_suggestion(
                wrong_text=str(payload.get("wrong_text", "")),
                suggested_text=str(payload.get("suggested_text", "")),
                note=str(payload.get("note", "")),
            )
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        except Exception as exc:
            logger.exception("保存词汇建议失败")
            self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self._send_json(result, status=HTTPStatus.CREATED)

    def _handle_config_update(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            self._send_json({"error": "配置内容为空"}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json({"error": "配置内容不是有效 JSON"}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            result = self.runtime.update_config(payload)
        except (ValueError, TypeError) as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        except Exception as exc:
            logger.exception("保存网页配置失败")
            self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self._send_json(result)

    def _handle_admin_login(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            self._send_json({"error": "密码不能为空"}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json({"error": "登录内容不是有效 JSON"}, status=HTTPStatus.BAD_REQUEST)
            return

        password = str(payload.get("password", ""))
        if not self.runtime.verify_admin_password(password):
            self._send_json({"error": "管理员密码错误"}, status=HTTPStatus.UNAUTHORIZED)
            return

        self._send_json(
            {"ok": True},
            extra_headers={"Set-Cookie": self.runtime.get_admin_cookie_value()},
        )

    def _handle_admin_logout(self):
        self._send_json(
            {"ok": True},
            extra_headers={"Set-Cookie": self.runtime.get_admin_logout_cookie_value()},
        )

    def _handle_suggestion_action(self, path: str):
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            self._send_json({"error": "建议内容为空"}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json({"error": "建议内容不是有效 JSON"}, status=HTTPStatus.BAD_REQUEST)
            return

        wrong_text = str(payload.get("wrong_text", ""))
        suggested_text = str(payload.get("suggested_text", ""))
        created_at = str(payload.get("created_at", ""))

        try:
            if path.endswith("/accept"):
                result = self.runtime.accept_vocabulary_suggestion(
                    wrong_text=wrong_text,
                    suggested_text=suggested_text,
                    created_at=created_at,
                )
            else:
                result = self.runtime.delete_vocabulary_suggestion(
                    wrong_text=wrong_text,
                    suggested_text=suggested_text,
                    created_at=created_at,
                )
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        except Exception as exc:
            logger.exception("处理词汇建议动作失败")
            self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self._send_json(result)

    def log_message(self, format, *args):
        logger.info("web %s - %s", self.address_string(), format % args)

    def _send_json(
        self,
        payload: dict[str, Any],
        status: HTTPStatus = HTTPStatus.OK,
        extra_headers: dict[str, str] | None = None,
    ):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for header_name, header_value in (extra_headers or {}).items():
            self.send_header(header_name, header_value)
        self.end_headers()
        self.wfile.write(body)


def build_arg_parser() -> argparse.ArgumentParser:
    """构建命令行参数。"""
    parser = argparse.ArgumentParser(description="启动本地网页语音识别服务")
    parser.add_argument("--host", default=None, help="监听地址，默认读取配置或使用 127.0.0.1")
    parser.add_argument("--port", default=None, type=int, help="监听端口，默认读取配置或使用 8765")
    parser.add_argument("--workers", default=None, type=int, help="识别 worker 数量，默认读取配置或使用 1")
    parser.add_argument(
        "--daemon",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="是否以后台服务方式运行，默认读取配置",
    )
    parser.add_argument("--pid-file", default="", help="后台模式 PID 文件路径")
    parser.add_argument("--stdout-file", default="", help="后台模式标准输出日志路径")
    parser.add_argument("--stderr-file", default="", help="后台模式错误日志路径")
    return parser


def main():
    """启动网页识别服务。"""
    args = build_arg_parser().parse_args()
    config, _config_path, _used_example_config, _runtime_root = load_runtime_config(SOURCE_ROOT)
    web_options = resolve_web_server_options(config, args)
    pid_file = resolve_service_path(SOURCE_ROOT, args.pid_file, "logs/voice-web.pid")
    stdout_file = resolve_service_path(SOURCE_ROOT, args.stdout_file, "logs/voice-web.stdout.log")
    stderr_file = resolve_service_path(SOURCE_ROOT, args.stderr_file, "logs/voice-web.stderr.log")

    if web_options.daemon:
        print("voice web 正在切换到后台服务模式...")
        daemonize_process(
            pid_file=pid_file,
            stdout_file=stdout_file,
            stderr_file=stderr_file,
        )

    runtime = WebRecognitionRuntime(SOURCE_ROOT, worker_count=web_options.workers)
    VoiceWebRequestHandler.runtime = runtime
    server = ThreadingHTTPServer((web_options.host, web_options.port), VoiceWebRequestHandler)
    logger.info("网页语音服务启动: http://%s:%s (workers=%s)", web_options.host, web_options.port, runtime.worker_count)
    print(f"voice web 已启动: http://{web_options.host}:{web_options.port} (workers={runtime.worker_count})")
    if web_options.daemon:
        print(f"后台 PID 文件: {pid_file}")
        print(f"后台输出日志: {stdout_file}")
        print(f"后台错误日志: {stderr_file}")
    if web_options.host == "0.0.0.0":
        lan_addresses = get_lan_addresses()
        if lan_addresses:
            for address in lan_addresses:
                print(f"局域网可访问: http://{address}:{web_options.port}")
        else:
            print("局域网可访问地址未自动识别，请手动查询本机 IP。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止 voice web ...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
