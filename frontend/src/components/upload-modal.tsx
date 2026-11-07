"use client";
/** Book upload modal: PDF validation, copyright consent, progress + status polling. */
import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiErr, getAccessToken } from "@/lib/api";
import { Button, ErrorBox, Input, Modal, Progress, useToast } from "@/components/ui";
import type { Book, Job } from "@/lib/types";

const MAX_MB = 50;

export function UploadModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [phase, setPhase] = useState<"form" | "uploading" | "processing">("form");
  const [progress, setProgress] = useState(0);
  const [stage, setStage] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();
  const { toast } = useToast();

  const reset = () => {
    setFile(null);
    setTitle("");
    setConsent(false);
    setError("");
    setUploading(false);
    setPhase("form");
    setProgress(0);
    setStage("");
  };

  const close = () => {
    if (phase === "processing" || phase === "uploading") return; // keep polling visible
    reset();
    onClose();
  };

  const poll = async (bookId: string): Promise<Job> => {
    for (let i = 0; i < 240; i++) {
      await new Promise((r) => setTimeout(r, 1500));
      try {
        const job = await api<Job>(`/books/${bookId}/status`);
        setProgress(job.progress);
        setStage(job.stage_label_uz);
        if (job.status === "completed") return job;
        if (job.status === "failed") throw new Error(job.error_message || "Tahlil bajarilmadi");
      } catch (e) {
        if (e instanceof ApiErr) throw e;
      }
    }
    throw new Error("Tahlil juda uzoq davom etmoqda. Keyinroq 'Kitoblarim' bo'limidan tekshiring.");
  };

  const submit = async () => {
    if (!file) return;
    setError("");
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setError("Faqat PDF fayl qabul qilinadi.");
      return;
    }
    if (file.size > MAX_MB * 1024 * 1024) {
      setError(`Fayl hajmi ${MAX_MB} MB dan kichik bo'lishi kerak.`);
      return;
    }
    if (!consent) {
      setError("Iltimos, muallif huquqi tasdig'ini belgilang.");
      return;
    }
    setUploading(true);
    setPhase("uploading");
    const fd = new FormData();
    fd.append("file", file);
    fd.append("title", title);
    fd.append("consent", "true");
    try {
      // manual fetch to track upload progress
      const book = await new Promise<Book>((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open("POST", "/backend/api/v1/books/upload");
        xhr.setRequestHeader("authorization", `Bearer ${getAccessToken()}`);
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) setProgress(Math.round((e.loaded / e.total) * 30)); // upload ~30%
        };
        xhr.onload = () => {
          if (xhr.status === 201) resolve(JSON.parse(xhr.responseText));
          else {
            let msg = `Yuklashda xatolik (${xhr.status})`;
            try {
              msg = JSON.parse(xhr.responseText).error.message_uz || msg;
            } catch { /* noop */ }
            reject(new Error(msg));
          }
        };
        xhr.onerror = () => reject(new Error("Tarmoq xatosi"));
        xhr.send(fd);
      });
      setPhase("processing");
      setStage("AI kitobni tahlil qilmoqda...");
      await poll(book.id);
      toast("Kitob tayyor! 🎉", "success");
      reset();
      onClose();
      router.push(`/books/${book.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Xatolik");
      setPhase("form");
    } finally {
      setUploading(false);
    }
  };

  return (
    <Modal open={open} onClose={close} title="Kitob yuklash" wide>
      {phase === "form" && (
        <div className="space-y-4">
          <div
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]);
            }}
            className="flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed border-slate-300 bg-slate-50 px-6 py-10 text-center transition hover:border-brand-400 hover:bg-brand-50/50 dark:border-slate-600 dark:bg-slate-800/40 dark:hover:border-brand-500">
            <svg className="mb-3 h-10 w-10 text-brand-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5">
              <path strokeLinecap="round" strokeLinejoin="round" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
            </svg>
            {file ? (
              <p className="text-sm font-medium text-slate-700 dark:text-slate-200">{file.name}</p>
            ) : (
              <p className="text-sm text-slate-500 dark:text-slate-400">
                PDF kitobni bu yerga tashlang yoki bosing
              </p>
            )}
            <p className="mt-1 text-xs text-slate-400">Maksimal hajm: {MAX_MB} MB · 300 sahifagacha</p>
            <input ref={inputRef} type="file" accept=".pdf,application/pdf" className="hidden"
              onChange={(e) => setFile(e.target.files?.[0] || null)} />
          </div>
          <Input label="Kitob nomi (ixtiyoriy)" value={title} onChange={(e) => setTitle(e.target.value)}
            placeholder="English Grammar in Use" />
          <label className="flex items-start gap-3 rounded-xl bg-amber-50 p-3 text-xs text-amber-800 dark:bg-amber-900/20 dark:text-amber-300">
            <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-amber-300" />
            <span>
              Tasdiqlayman: ushbu kitobni qayta ishlash va shaxsiy o'quv maqsadida foydalanish
              huquqiga egaman. Fayl <b>faqat men ko'radigan</b> shaxsiy kutubxonamda saqlanadi va
              uchinchi shaxslarga tarqatilmaydi.
            </span>
          </label>
          <ErrorBox message={error} />
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={close}>Bekor qilish</Button>
            <Button onClick={submit} disabled={!file || !consent}>Yuklash va tahlil qilish</Button>
          </div>
        </div>
      )}
      {(phase === "uploading" || phase === "processing") && (
        <div className="flex flex-col items-center gap-5 py-8">
          <svg className="h-14 w-14 animate-pulse text-brand-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.5">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.247m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.247" />
          </svg>
          <div className="text-center">
            <p className="font-semibold text-slate-800 dark:text-slate-100">
              {phase === "uploading" ? "Fayl yuklanmoqda..." : "AI kitobni tahlil qilmoqda"}
            </p>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{stage}</p>
          </div>
          <Progress value={progress} className="w-64" />
          <p className="text-xs text-slate-400">Sahifani yopmang — bu odatda 1-3 daqiqa oladi</p>
        </div>
      )}
    </Modal>
  );
}
