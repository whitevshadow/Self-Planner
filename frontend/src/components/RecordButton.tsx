"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { uploadMeeting } from "@/lib/api";

type RecordState = "idle" | "recording" | "uploading" | "error";
type AudioSource = "mic+system" | "mic-only";
type Step = "idle" | "step1-mic" | "step2-display" | "recording";

interface Props {
  onUploaded: () => void;
}

export default function RecordButton({ onUploaded }: Props) {
  const [state, setState] = useState<RecordState>("idle");
  const [step, setStep] = useState<Step>("idle");
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [audioSource, setAudioSource] = useState<AudioSource | null>(null);
  const [systemAudioWarn, setSystemAudioWarn] = useState<string | null>(null);

  const mediaRecorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);

  useEffect(() => {
    return () => {
      stopTimer();
      cleanupStreams();
    };
  }, []);

  function stopTimer() {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }

  function cleanupStreams() {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    audioCtxRef.current?.close().catch(() => {});
    audioCtxRef.current = null;
  }

  function formatTime(s: number) {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
  }

  function getMimeType(): string {
    const candidates = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/ogg;codecs=opus",
      "audio/ogg",
      "audio/mp4",
    ];
    for (const mime of candidates) {
      if (MediaRecorder.isTypeSupported(mime)) return mime;
    }
    return "";
  }

  function mimeToExt(mime: string): string {
    if (mime.startsWith("audio/webm")) return ".webm";
    if (mime.startsWith("audio/ogg")) return ".ogg";
    if (mime.startsWith("audio/mp4")) return ".m4a";
    return ".webm";
  }

  async function tryGetSystemAudio(): Promise<MediaStream | null> {
    if (!navigator.mediaDevices?.getDisplayMedia) return null;
    try {
      let displayStream: MediaStream | null = null;
      try {
        displayStream = await navigator.mediaDevices.getDisplayMedia({ audio: true, video: false });
      } catch {
        displayStream = await navigator.mediaDevices.getDisplayMedia({ audio: true, video: true });
      }
      displayStream.getVideoTracks().forEach((t) => t.stop());
      const audioTracks = displayStream.getAudioTracks();
      if (audioTracks.length === 0) {
        displayStream.getTracks().forEach((t) => t.stop());
        return null;
      }
      return displayStream;
    } catch {
      return null;
    }
  }

  function mixStreams(
    micStream: MediaStream,
    systemStream: MediaStream | null
  ): { mixed: MediaStream; ctx: AudioContext | null } {
    if (!systemStream) return { mixed: micStream, ctx: null };
    const ctx = new AudioContext();
    const dest = ctx.createMediaStreamDestination();
    ctx.createMediaStreamSource(micStream).connect(dest);
    ctx.createMediaStreamSource(systemStream).connect(dest);
    return { mixed: dest.stream, ctx };
  }

  const startRecording = useCallback(async () => {
    setError(null);
    setSystemAudioWarn(null);
    setAudioSource(null);

    try {
      // Step 1 — microphone
      setStep("step1-mic");
      const micStream = await navigator.mediaDevices.getUserMedia({ audio: true });

      // Step 2 — system audio via screen-share picker
      setStep("step2-display");
      const systemStream = await tryGetSystemAudio();

      if (!systemStream) {
        setSystemAudioWarn(
          "System audio not captured — recording mic only. " +
          "Next time: in the picker choose a tab/window and tick \"Share system audio\"."
        );
        setAudioSource("mic-only");
      } else {
        setAudioSource("mic+system");
      }

      // Mix + record
      const { mixed, ctx } = mixStreams(micStream, systemStream);
      audioCtxRef.current = ctx;
      streamRef.current = new MediaStream([
        ...micStream.getTracks(),
        ...(systemStream?.getTracks() ?? []),
      ]);

      const mime = getMimeType();
      const recorder = new MediaRecorder(mixed, mime ? { mimeType: mime } : {});
      mediaRecorder.current = recorder;
      chunks.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunks.current.push(e.data);
      };

      recorder.onstop = async () => {
        stopTimer();
        cleanupStreams();
        setStep("idle");

        const actualMime = recorder.mimeType || mime;
        const blob = new Blob(chunks.current, { type: actualMime });
        const timestamp = new Date()
          .toISOString().slice(0, 19).replace("T", "_").replace(/:/g, "-");
        const file = new File(
          [blob],
          `recording_${timestamp}${mimeToExt(actualMime)}`,
          { type: actualMime }
        );

        setState("uploading");
        try {
          await uploadMeeting(file, title.trim() || `Recording ${timestamp}`);
          setTitle("");
          setSeconds(0);
          setAudioSource(null);
          setSystemAudioWarn(null);
          setState("idle");
          onUploaded();
        } catch (err) {
          setError(err instanceof Error ? err.message : "Upload failed");
          setState("error");
        }
      };

      recorder.start(250);
      setStep("recording");
      setState("recording");
      setSeconds(0);
      timerRef.current = setInterval(() => setSeconds((s) => s + 1), 1000);
    } catch (err) {
      setStep("idle");
      setError(
        err instanceof Error
          ? err.message.toLowerCase().includes("permission") ||
            err.message.toLowerCase().includes("denied")
            ? "Microphone permission denied. Please allow mic access and try again."
            : err.message
          : "Could not access microphone"
      );
      setState("error");
    }
  }, [title, onUploaded]);

  const stopRecording = useCallback(() => {
    mediaRecorder.current?.stop();
  }, []);

  const isIdle = state === "idle" || state === "error";
  const isRecording = state === "recording";
  const isUploading = state === "uploading";

  return (
    <div className="record-card">

      <div className="record-header">
        <span className="record-label">🎙 Record meeting live</span>
        <input
          className="record-title-input"
          type="text"
          placeholder="Title (optional)"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          disabled={!isIdle}
        />
      </div>

      {(step === "step1-mic" || step === "step2-display") && (
        <div className="rec-step-guide">
          <div className="rec-step-row">
            <span className={`rec-step-pill ${step === "step1-mic" ? "active" : "done"}`}>
              {step === "step1-mic" ? "⏳" : "✅"} Step 1
            </span>
            <span className="rec-step-text">
              {step === "step1-mic"
                ? "Allow microphone access in the browser prompt…"
                : "Microphone ready"}
            </span>
          </div>

          <div className="rec-step-row">
            <span className={`rec-step-pill ${step === "step2-display" ? "active" : "pending"}`}>
              {step === "step2-display" ? "⏳" : "2"} Step 2
            </span>
            <span className="rec-step-text">
              {step === "step2-display" ? (
                <>
                  A <strong>screen-share picker</strong> just opened. Pick any tab or window, then:
                  <span className="rec-step-highlight"> ☑ tick "Share system audio"</span>
                </>
              ) : (
                "System audio — waiting…"
              )}
            </span>
          </div>

          {step === "step2-display" && (
            <div className="rec-step-diagram">
              <div className="rec-diagram-box">Pick a tab<br/>or window</div>
              <div className="rec-diagram-arrow">→</div>
              <div className="rec-diagram-box highlight">☑ Share<br/>system audio</div>
              <div className="rec-diagram-arrow">→</div>
              <div className="rec-diagram-box">Click<br/>Share</div>
            </div>
          )}
        </div>
      )}

      <div className="record-controls">
        {isIdle && (
          <>
            <button
              id="start-recording-btn"
              className="btn-record"
              onClick={startRecording}
            >
              <span className="rec-dot" /> Record
            </button>
            <span className="rec-hint">
              Captures <strong>mic + system audio</strong> simultaneously.
              Chrome / Edge only — Firefox / Safari: mic only.
            </span>
          </>
        )}

        {isRecording && (
          <>
            <div className="recording-indicator">
              <span className="rec-dot pulsing" />
              <span className="rec-timer">{formatTime(seconds)}</span>
              <span className="rec-live-label">Recording…</span>
              {audioSource === "mic+system" && (
                <span className="rec-source-badge system">🔊 Mic + System</span>
              )}
              {audioSource === "mic-only" && (
                <span className="rec-source-badge mic">🎙 Mic only</span>
              )}
            </div>
            <button
              id="stop-recording-btn"
              className="btn-stop"
              onClick={stopRecording}
            >
              ⬛ Stop &amp; Upload
            </button>
          </>
        )}

        {isUploading && (
          <div className="record-uploading">
            <span className="spinner" />
            Uploading… processing continues in the background.
          </div>
        )}
      </div>

      {systemAudioWarn && isRecording && (
        <div className="upload-status warn">⚠ {systemAudioWarn}</div>
      )}
      {error && <div className="upload-status error">{error}</div>}
    </div>
  );
}
