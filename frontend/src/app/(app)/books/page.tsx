"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { del, get } from "@/lib/api";
import type { Book, Job } from "@/lib/types";
import { TopBar } from "@/components/nav";
import { Badge, Button, Card, EmptyState, Modal, Progress, Spinner, useToast } from "@/components/ui";
import { UploadModal } from "@/components/upload-modal";

export default function BooksPage() {
  const [books, setBooks] = useState<Book[] | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<Book | null>(null);
  const { toast } = useToast();

  const load = useCallback(async () => {
    setBooks(await get<Book[]>("/books"));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // poll while any book is processing
  useEffect(() => {
    if (!books?.some((b) => b.status === "processing")) return;
    const t = setInterval(load, 2500);
    return () => clearInterval(t);
  }, [books, load]);

  const doDelete = async () => {
    if (!confirmDelete) return;
    try {
      await del(`/books/${confirmDelete.id}`);
      toast("Kitob o'chirildi", "success");
      setConfirmDelete(null);
      load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "O'chirishda xatolik", "error");
    }
  };

  return (
    <>
      <TopBar title="Kitoblarim" />
      <main className="mx-auto max-w-6xl px-4 py-6 lg:px-8">
        <div className="mb-6 flex items-center justify-between">
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Kitoblaringiz shaxsiy — faqat siz ko'rasiz.
          </p>
          <Button onClick={() => setUploadOpen(true)}>+ Kitob yuklash</Button>
        </div>

        {!books ? (
          <div className="flex justify-center py-20"><Spinner className="h-8 w-8 text-brand-500" /></div>
        ) : books.length === 0 ? (
          <EmptyState
            icon={<BookLogo />}
            title="Hali kitob yuklanmagan"
            description="Ingliz tili darsligingizni (PDF) yuklang — AI uni interaktiv mashqlar to'plamiga aylantiradi."
            action={<Button onClick={() => setUploadOpen(true)} size="lg">Birinchi kitobni yuklash</Button>}
          />
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {books.map((b) => (
              <BookCard key={b.id} book={b} onDelete={() => setConfirmDelete(b)} />
            ))}
          </div>
        )}
      </main>

      <UploadModal open={uploadOpen} onClose={() => setUploadOpen(false)} />

      <Modal open={!!confirmDelete} onClose={() => setConfirmDelete(null)} title="Kitobni o'chirish">
        <p className="text-sm text-slate-600 dark:text-slate-300">
          <b>{confirmDelete?.title}</b> va unga tegishli BARCHA ma'lumotlar (mashqlar, javoblar,
          lug'at, natijalar) butunlay o'chiriladi. Bu amalni qaytarib bo'lmaydi.
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setConfirmDelete(null)}>Bekor qilish</Button>
          <Button variant="danger" onClick={doDelete}>Ha, o'chirish</Button>
        </div>
      </Modal>
    </>
  );
}

function BookCard({ book, onDelete }: { book: Book; onDelete: () => void }) {
  const [job, setJob] = useState<Job | null>(null);

  useEffect(() => {
    if (book.status !== "processing") return;
    const t = setInterval(async () => {
      try {
        const j = await get<Job>(`/books/${book.id}/status`);
        setJob(j);
      } catch { /* noop */ }
    }, 1500);
    return () => clearInterval(t);
  }, [book.id, book.status]);

  const processing = book.status === "processing";

  return (
    <Card className={`flex flex-col ${processing ? "opacity-90" : ""}`}>
      <div className="mb-3 flex items-start justify-between gap-2">
        <Link href={book.status === "ready" ? `/books/${book.id}` : "#"} className="flex-1">
          <h3 className="line-clamp-2 font-semibold text-slate-800 hover:text-brand-600 dark:text-slate-100 dark:hover:text-brand-400">
            {book.title}
          </h3>
        </Link>
        {book.status === "ready" && <Badge tone="green">Tayyor</Badge>}
        {processing && <Badge tone="amber">Tahlil...</Badge>}
        {book.status === "failed" && <Badge tone="red">Xatolik</Badge>}
        {book.status === "uploading" && <Badge tone="amber">Yuklash tugallanmagan</Badge>}
      </div>

      {processing && (
        <div className="mb-3">
          <Progress value={job?.progress ?? 5} />
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            {job?.stage_label_uz || "Navbatda..."}
          </p>
        </div>
      )}
      {book.status === "failed" && (
        <p className="mb-3 text-xs text-red-500">
          {job?.error_message || "Tahlil bajarilmadi — 'Qayta tahlil' ni bosing yoki kitobni o'chirib, qayta yuklang."}
        </p>
      )}

      <div className="mt-auto flex items-center justify-between">
        <span className="text-xs text-slate-400">
          {book.page_count > 0 ? `${book.page_count} bet · ` : ""}
          {(book.file_size_bytes / (1024 * 1024)).toFixed(1)} MB
        </span>
        <div className="flex gap-1">
          {book.status === "ready" && (
            <>
              <Link href={`/reader/${book.id}`}>
                <Button size="sm" variant="secondary">O'qish</Button>
              </Link>
              <Link href={`/books/${book.id}`}>
                <Button size="sm" variant="ghost">Tafsilotlar</Button>
              </Link>
            </>
          )}
          <Button size="sm" variant="ghost" onClick={onDelete} aria-label="O'chirish">
            <svg className="h-4 w-4 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8">
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
          </Button>
        </div>
      </div>
    </Card>
  );
}

const BookLogo = () => (
  <svg className="h-12 w-12" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.2">
    <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.247m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.247" />
  </svg>
);
